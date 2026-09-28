"""AI agent that looks at the audited dataframe's columns/dtypes and
proposes new engineered features -- the "ai_suggested" source in the
feature repository (see feature_repository.py). It only picks WHICH
columns to combine and describes the calculation in plain English; it never
computes a value itself and isn't limited to any fixed set of calculation
shapes -- the Feature Agent (feature_agent.py) is what actually plans,
writes, executes and validates the code for whatever gets accepted. Runs on
OpenRouter, never Groq. Anything referencing a column that doesn't exist in
the current data (a hallucination) is dropped rather than surfaced, since a
broken suggestion is worse than a missing one.
"""
import json
import re

import pandas as pd
from openai import OpenAI

from app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from app.services.common import token_usage

SYSTEM_PROMPT = """You are a data engineer proposing new engineered columns \
for an operational cold-chain shipment dataset, to help a program manager \
build KPIs and reports. You'll be given the current column names, dtypes, \
and a few sample values per column.

Propose up to 5 NEW feature ideas that would be genuinely useful for \
cold-chain reporting (e.g. transit duration, percentage breakdowns of time \
in/out of spec, seasonality, lane- or carrier-level aggregates). Every \
suggestion MUST reference only columns that appear in the given column \
list -- never invent a column name.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"suggestions": [
  {
    "name": "short title, e.g. 'Time in Transit'",
    "description": "one plain-English sentence on why this is useful",
    "output_column": "short column name for the new field",
    "calculation_intent": "a precise, unambiguous plain-English description of exactly how to compute this from the columns below",
    "input_columns": ["exact column name(s) this calculation reads"]
  }
]}"""


def _client() -> OpenAI:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set. Add your key from https://openrouter.ai/keys to backend/.env")
    return OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")


def _columns_block(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)


def suggest_features(df: pd.DataFrame) -> list[dict]:
    """Returns repository-shaped candidate dicts: name, description,
    output_column, calculation_intent, input_columns -- ready to hand to
    feature_repository.add_ai_suggested_entries."""
    client = _client()
    user_prompt = f"Columns:\n{_columns_block(df)}\n\nPropose the features now."
    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    token_usage.record("feature_suggester", OPENROUTER_MODEL, response)
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    candidates = payload.get("suggestions", [])
    if not isinstance(candidates, list):
        return []

    available_columns = set(df.columns.astype(str))
    suggestions: list[dict] = []
    for spec in candidates:
        if not isinstance(spec, dict):
            continue
        if not spec.get("name") or not spec.get("output_column") or not spec.get("calculation_intent"):
            continue
        input_columns = spec.get("input_columns") or []
        if input_columns and not set(input_columns).issubset(available_columns):
            continue
        output_column = re.sub(r"\W+", "_", spec["output_column"].strip().lower()).strip("_")
        suggestions.append({
            "name": spec["name"],
            "description": spec.get("description", ""),
            "output_column": output_column,
            "calculation_intent": spec["calculation_intent"],
            "input_columns": input_columns,
        })

    return suggestions
