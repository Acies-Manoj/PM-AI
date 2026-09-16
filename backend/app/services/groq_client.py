"""Thin wrapper around the Groq chat-completions API."""
from groq import Groq

from app.config import GROQ_API_KEY, GROQ_MODEL

_client: Groq | None = None


def get_client() -> Groq:
    global _client
    if _client is None:
        if not GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Paste your key from "
                "https://console.groq.com/keys into backend/.env"
            )
        # Explicit timeout + no retries: the SDK's own defaults (a ~10-minute
        # timeout, 2 retries) mean a rate-limited response's `Retry-After`
        # header gets honored literally -- observed in practice as a single
        # call hanging for 12+ minutes before ever raising, since Groq's
        # 429 body can suggest a wait that long. Every caller in this app
        # (feature_orchestrator, analysis_orchestrator, formula_agent, ...)
        # already catches a raised exception and degrades gracefully (an
        # empty result, a recorded soft-fail in `errors`); none of them are
        # helped by the SDK silently sleeping first; they just need the
        # exception promptly so the rest of the request can still complete.
        _client = Groq(api_key=GROQ_API_KEY, timeout=30.0, max_retries=0)
    return _client


def chat_text(system_prompt: str, user_prompt: str, model: str = GROQ_MODEL, temperature: float = 0.3) -> str:
    """Single-shot call returning plain prose."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


def chat_json(system_prompt: str, user_prompt: str, model: str = GROQ_MODEL, temperature: float = 0.4) -> str:
    """Single-shot call constrained to a JSON object response (Groq's
    OpenAI-compatible json_object mode) -- for callers that need structured
    output rather than prose, e.g. the feature-suggestion agent."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or "{}"
