"""Shared OpenRouter client + call wrapper used by the code-generating
agents (Feature Agent, Analysis Agent, Planner): client instantiation, a
json_mode-with-fallback call, and fence-stripping helpers. Same pattern as
`groq_client.py`, which serves the narration-only agents (Audit,
suggesters) on the same OpenRouter backend with a different call shape
(single-shot prose/JSON vs. a fixed-model, named, retryable call).
"""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd
from openai import OpenAI

from app.config import OPENROUTER_API_KEY
from app.services.common import token_usage

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@lru_cache(maxsize=None)
def get_client(*, timeout: float | None = None, max_retries: int | None = None) -> OpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add your key from https://openrouter.ai/keys to backend/.env"
        )
    kwargs: dict = {"api_key": OPENROUTER_API_KEY, "base_url": OPENROUTER_BASE_URL}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if max_retries is not None:
        kwargs["max_retries"] = max_retries
    return OpenAI(**kwargs)


def call(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    json_mode: bool,
    temperature: float,
    call_name: str,
    timeout: float | None = None,
    max_retries: int | None = None,
    max_tokens: int | None = None,
) -> str:
    """One chat completion, with a json_mode-unsupported fallback and
    token_usage recording."""
    client = get_client(timeout=timeout, max_retries=max_retries)
    kwargs: dict = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        try:
            response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception:
            response = client.chat.completions.create(**kwargs)
    else:
        response = client.chat.completions.create(**kwargs)
    token_usage.record(call_name, model, response)
    return response.choices[0].message.content or ""


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:python)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```", 2)[-1] if stripped.count("```") >= 2 else stripped
        stripped = stripped[4:].strip() if stripped.lower().startswith("json") else stripped
    return stripped


def column_preview_block(df: pd.DataFrame) -> str:
    """`- col (dtype): e.g. sample1, sample2` per column, for a live
    DataFrame -- shared by the Feature Agent and the feature suggester.
    Not used by the Planner, which profiles columns from stored metadata
    JSON rather than a live df and needs a differently-shaped block."""
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)
