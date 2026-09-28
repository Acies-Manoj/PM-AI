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

from app.config import OPENROUTER_MODEL
from app.prompts import feature_suggester as prompts
from app.services.common import llm_client


def suggest_features(df: pd.DataFrame) -> list[dict]:
    """Returns repository-shaped candidate dicts: name, description,
    output_column, calculation_intent, input_columns -- ready to hand to
    feature_repository.add_ai_suggested_entries."""
    user_prompt = f"Columns:\n{llm_client.column_preview_block(df)}\n\nPropose the features now."
    raw = llm_client.call(
        prompts.SYSTEM_PROMPT, user_prompt,
        model=OPENROUTER_MODEL, json_mode=True, temperature=0.4, call_name="feature_suggester",
    )
    payload = json.loads(llm_client.strip_json_fence(raw))
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
