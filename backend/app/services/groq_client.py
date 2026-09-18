"""Thin wrapper around the chat-completions call every agent in this app
goes through -- Groq by default, or OpenRouter (a genuinely separate
account/quota) when OPENROUTER_API_KEY is set. Same OpenAI-compatible
request/response shape either way, so callers (feature_orchestrator,
analysis_orchestrator, formula_agent, ...) importing chat_text/chat_json
from here don't need to know or care which one is active.

OpenRouter takes priority when both keys are set, since that's the one
meant to relieve Groq's rate limit -- a second Groq key would NOT help
(Groq enforces TPM/RPM/TPD at the ORGANIZATION level, confirmed by every
429 this app has hit naming the same org id regardless of which endpoint
triggered it); OpenRouter is a different account, with its own budget.

Talks to both over plain httpx rather than the `groq` package's own SDK --
verified live that constructing groq.Groq(base_url="https://openrouter.ai/api/v1")
builds the objectively correct request URL, but still gets a 404 (an HTML
page, not the API) back from OpenRouter; something else the SDK sends isn't
compatible with it. A raw request with the identical URL/headers/body via
httpx works cleanly (a real 401 JSON body on a bad key), so that's what's
used here for both providers, uniformly -- one fewer thing that can be
subtly provider-specific."""
import json

import httpx

from app.config import GROQ_API_KEY, GROQ_MODEL, OPENROUTER_API_KEY, OPENROUTER_MODEL

_USE_OPENROUTER = bool(OPENROUTER_API_KEY)
_BASE_URL = "https://openrouter.ai/api/v1" if _USE_OPENROUTER else "https://api.groq.com/openai/v1"
_API_KEY = OPENROUTER_API_KEY if _USE_OPENROUTER else GROQ_API_KEY
DEFAULT_MODEL = OPENROUTER_MODEL if _USE_OPENROUTER else GROQ_MODEL

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        if not _API_KEY:
            raise RuntimeError(
                "Neither OPENROUTER_API_KEY nor GROQ_API_KEY is set. Paste one into backend/.env -- "
                "OpenRouter: https://openrouter.ai/keys, Groq: https://console.groq.com/keys"
            )
        # No retries (httpx does none by default -- unlike the groq SDK,
        # which used to retry a 429 while honoring its own suggested wait,
        # observed in practice as a single call hanging 12+ minutes), and an
        # explicit timeout: every caller in this app already catches a
        # raised exception and degrades gracefully (an empty result, a
        # recorded soft-fail); they just need it promptly.
        _client = httpx.Client(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {_API_KEY}", "Content-Type": "application/json"},
            timeout=30.0,
        )
    return _client


def _complete(system_prompt: str, user_prompt: str, model: str, temperature: float, json_mode: bool) -> str:
    body: dict = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = _get_client().post("/chat/completions", json=body)
    if response.status_code >= 400:
        # Same "Error code: N - <body>" shape the groq SDK's own exceptions
        # rendered as -- every caller's f"...: {exc}" error message (shown
        # in the UI's own error panels) stays just as informative as before.
        raise RuntimeError(f"Error code: {response.status_code} - {response.text}")
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    return content or ("{}" if json_mode else "")


def chat_text(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.3) -> str:
    """Single-shot call returning plain prose."""
    return _complete(system_prompt, user_prompt, model, temperature, json_mode=False)


def chat_json(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL, temperature: float = 0.4) -> str:
    """Single-shot call constrained to a JSON object response -- for
    callers that need structured output rather than prose, e.g. the
    feature-suggestion agent.

    `response_format: json_object` makes a broken response rare but not
    impossible (an unescaped quote inside a string value, or similar
    provider-side formatting slip, breaks every caller's own `json.loads`
    with a cryptic "Expecting ',' delimiter" error). Since that's a sampling
    fluke rather than a real failure, resampling the identical prompt once
    almost always produces valid JSON the second time -- cheaper and more
    reliable than every one of this app's ~10 callers reimplementing the
    same retry-on-parse-failure logic themselves. If the retry also comes
    back unparsable, this still returns it as-is so the caller's own
    json.loads raises a real, visible error rather than this silently
    guessing at a repair."""
    raw = _complete(system_prompt, user_prompt, model, temperature, json_mode=True)
    try:
        json.loads(raw)
    except ValueError:
        raw = _complete(system_prompt, user_prompt, model, temperature, json_mode=True)
    return raw
