"""LLM client backed by OpenRouter (OpenAI-compatible API).

Public surface is unchanged — `chat_text` and `chat_json` — so every
existing caller (audit_agent, feature_suggester, etc.) continues to work
without modification.
"""

import re
from openai import OpenAI

from app.config import DEFAULT_MAX_TOKENS, LLM_MODEL, OPENROUTER_API_KEY, model_for
from app.services.common import token_usage

_client: OpenAI | None = None

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add your key from "
                "https://openrouter.ai/keys to backend/.env"
            )
        _client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
    return _client


def chat_text(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    call_name: str = "unnamed_chat_text",
) -> str:
    """Single-shot call returning plain prose."""
    model = model or model_for(call_name, LLM_MODEL)
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    token_usage.record(call_name, model, response)
    return response.choices[0].message.content or ""



def strip_json_fence(text: str) -> str:
    """Models such as Claude often wrap JSON in ```json fences; return the bare JSON."""
    t = (text or "").strip()
    m = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", t, re.DOTALL)
    return m.group(1).strip() if m else t


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.4,
    call_name: str = "unnamed_chat_json",
) -> str:
    """Single-shot call expecting a JSON object response.

    Uses json_object response_format when the model supports it;
    falls back to plain completion if the model rejects the parameter.
    """
    model = model or model_for(call_name, LLM_MODEL)
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception:
        # Some models don't support response_format — retry without it
        response = client.chat.completions.create(
            model=model,
            max_tokens=DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    token_usage.record(call_name, model, response)
    return strip_json_fence(response.choices[0].message.content or "{}")
