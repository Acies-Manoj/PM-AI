"""LLM client backed by OpenRouter (OpenAI-compatible API).

Public surface is unchanged — `chat_text` and `chat_json` — so every
existing caller (audit_agent, feature_suggester, etc.) continues to work
without modification.
"""
from openai import OpenAI

from app.config import LLM_MODEL, OPENROUTER_API_KEY

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
    model: str = LLM_MODEL,
    temperature: float = 0.3,
) -> str:
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


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str = LLM_MODEL,
    temperature: float = 0.4,
) -> str:
    """Single-shot call expecting a JSON object response.

    Uses json_object response_format when the model supports it;
    falls back to plain completion if the model rejects the parameter.
    """
    client = get_client()
    try:
        response = client.chat.completions.create(
            model=model,
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
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    return response.choices[0].message.content or "{}"
