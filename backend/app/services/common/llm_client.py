"""Shared OpenRouter client used by every agent in the pipeline: client
instantiation, a json_mode-with-fallback call, fence-stripping helpers,
and prompt-building helpers. Covers two call shapes -- `call()` for the
code-generating agents (Feature Agent, Analysis Agent, Planner), which
need an explicit model/timeout/retries per call, and `chat_text`/
`chat_json` for the narration-only agents (Audit, overall-analysis,
analysis suggester), which just need a single-shot prose or JSON
response with sensible defaults.
"""
from __future__ import annotations

import re
from functools import lru_cache

import pandas as pd
from openai import OpenAI

from app.config import LLM_MODEL, OPENROUTER_API_KEY
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


def chat_text(
    system_prompt: str,
    user_prompt: str,
    model: str = LLM_MODEL,
    temperature: float = 0.3,
    call_name: str = "unnamed_chat_text",
) -> str:
    """Single-shot call returning plain prose -- used by the narration-only
    agents (Audit, overall-analysis narrative)."""
    return call(system_prompt, user_prompt, model=model, json_mode=False, temperature=temperature, call_name=call_name)


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str = LLM_MODEL,
    temperature: float = 0.4,
    call_name: str = "unnamed_chat_json",
) -> str:
    """Single-shot call expecting a JSON object response -- used by the
    narration-only agents (Audit, analysis suggester). Uses json_object
    response_format when the model supports it; falls back to plain
    completion if the model rejects the parameter (see `call`)."""
    return call(system_prompt, user_prompt, model=model, json_mode=True, temperature=temperature, call_name=call_name) or "{}"


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


SAMPLE_VALUES_PER_COLUMN = 3
SAMPLE_VALUE_MAX_CHARS = 200


def _sample_preview(series: pd.Series) -> str:
    """A few real values from the column for an LLM prompt. Takes the
    sample BEFORE converting to text so a large column isn't stringified in
    full, and cuts very long values (free-text notes) to keep prompts small."""
    sample = series.dropna().head(SAMPLE_VALUES_PER_COLUMN).astype(str).tolist()
    if not sample:
        return "(all null)"
    cleaned = []
    for value in sample:
        value = " ".join(value.split())
        if len(value) > SAMPLE_VALUE_MAX_CHARS:
            value = value[:SAMPLE_VALUE_MAX_CHARS] + "…"
        cleaned.append(value)
    return ", ".join(cleaned)


def column_preview_block(df: pd.DataFrame) -> str:
    """`- col (dtype): e.g. sample1, sample2` per column, for a live
    DataFrame -- shared by the Feature Agent, the feature suggester, and
    (via analysis_columns.column_catalog) the Analysis Agent side. Not
    used by the Planner, which profiles columns from stored metadata JSON
    rather than a live df and needs a differently-shaped block."""
    return "\n".join(f"- {col} ({df[col].dtype}): e.g. {_sample_preview(df[col])}" for col in df.columns)


def entry_block(entry: dict, *, label: str, include_output_column: bool = False) -> str:
    """Renders a repository entry (name/description/calculation_intent,
    plus an optional output-column line and an input-columns hint) as the
    plain-English block every agent's Think/chart/template prompt starts
    from. `label` is the entity noun shown before "name:" (e.g. "Feature",
    "Analysis")."""
    lines = [f"{label} name: {entry['name']}"]
    if include_output_column:
        lines.append(f"Output column name: {entry['output_column']}")
    lines.append(f"Description: {entry.get('description', '')}")
    lines.append(f"Calculation intent: {entry['calculation_intent']}")
    cols_hint = (
        f"\nColumns likely involved (hint, not exhaustive): {', '.join(entry['input_columns'])}"
        if entry.get("input_columns")
        else ""
    )
    return "\n".join(lines) + cols_hint


def render_plan_steps(plan: dict) -> str:
    """Renders a Think result's `steps` array as one numbered paragraph --
    used wherever a single string is needed (LLM prompts, storage, the
    Planner's pre-generated formula). Falls back to a `plan` key for
    anything that hands in the older single-string shape."""
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return plan.get("plan", "")
