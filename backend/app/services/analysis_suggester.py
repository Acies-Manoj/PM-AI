"""AI agent that looks at the audited dataframe's columns/dtypes and
proposes new chart-worthy analyses -- the "ai_suggested" source in the
analysis repository (see analysis_repository.py). It only picks WHICH
columns/aggregations to explore and describes the analysis in plain
English; it never computes a value itself -- the Analysis Agent
(analysis_agent.py) is what actually plans, writes, and executes the code
for whatever gets accepted. Runs on OpenRouter, never Groq. Anything
referencing a column that doesn't exist in the current data (a
hallucination) is dropped rather than surfaced, since a broken suggestion
is worse than a missing one.
"""
import json

import pandas as pd
from openai import OpenAI

from app.config import OPENROUTER_API_KEY, OPENROUTER_MODEL

SYSTEM_PROMPT = """You are a data analyst proposing new chart-worthy analyses for an \
operational cold-chain shipment dataset, to help a program manager spot \
trends and outliers. You'll be given the current column names, dtypes, and \
a few sample values per column.

Propose up to 5 NEW analysis ideas that would be genuinely useful for \
cold-chain reporting (e.g. shipments by carrier, temperature excursions \
over time, top origins by volume, compliance rate by lane). Every \
suggestion MUST reference only columns that appear in the given column \
list -- never invent a column name.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"suggestions": [
  {
    "name": "short title, e.g. 'Shipments by Carrier'",
    "description": "one plain-English sentence on why this is useful",
    "calculation_intent": "a precise, unambiguous plain-English description of exactly what to group/aggregate from the columns below",
    "input_columns": ["exact column name(s) this analysis reads"]
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


def suggest_analyses(df: pd.DataFrame) -> list[dict]:
    """Returns repository-shaped candidate dicts: name, description,
    calculation_intent, input_columns -- ready to hand to
    analysis_repository.add_ai_suggested_entries."""
    client = _client()
    user_prompt = f"Columns:\n{_columns_block(df)}\n\nPropose the analyses now."
    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
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
        if not spec.get("name") or not spec.get("calculation_intent"):
            continue
        input_columns = spec.get("input_columns") or []
        if input_columns and not set(input_columns).issubset(available_columns):
            continue
        suggestions.append({
            "name": spec["name"],
            "description": spec.get("description", ""),
            "calculation_intent": spec["calculation_intent"],
            "input_columns": input_columns,
        })

    return suggestions
