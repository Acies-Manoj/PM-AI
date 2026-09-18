"""AI agent that looks at the audited dataframe's columns/dtypes and proposes
new engineered features. Groq only picks WHICH existing columns to combine
and writes the rationale -- it never computes a value itself. Every
suggestion is constrained to one of the three deterministic types
feature_engineering.py can actually execute, and anything referencing a
column that doesn't exist in the current data (a hallucination) is dropped
rather than surfaced, since a broken suggestion is worse than a missing one.
"""
import json
import uuid

import pandas as pd

from app.schemas import FeatureSuggestion
from app.services.groq_client import chat_json
from app.services.llm_context import columns_block as _columns_block

VALID_TYPES = {"duration_hours", "ratio", "extract_month"}

SYSTEM_PROMPT = """You are a data engineer proposing new engineered columns \
for an operational cold-chain shipment dataset, to help a program manager \
build KPIs and reports. You'll be given the current column names, dtypes, \
and a few sample values per column.

Propose up to 5 NEW feature ideas that would be genuinely useful for \
cold-chain reporting (e.g. transit duration, percentage breakdowns of time \
in/out of spec, seasonality). Every suggestion MUST be exactly one of these \
three computable types, and MUST reference only columns that appear in the \
given column list -- never invent a column name:

1. "duration_hours" -- the difference between two datetime-like columns.
   Required fields: start_column, end_column, unit ("hours" or "days").
2. "ratio" -- percentage of a sum of numerator column(s) over a sum of \
denominator column(s). Both must be numeric columns.
   Required fields: numerator_columns (list), denominator_columns (list).
3. "extract_month" -- calendar month extracted from one or more datetime \
columns (first non-null one wins).
   Required fields: source_columns (list).

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"suggestions": [
  {
    "name": "short title, e.g. 'Time in Transit'",
    "description": "one plain-English sentence on why this is useful",
    "output_column": "short column name for the new field",
    "type": "duration_hours | ratio | extract_month",
    ... the required fields for that type ...
  }
]}"""


def _formula_text(spec: dict) -> str:
    t = spec.get("type")
    if t == "duration_hours":
        unit = spec.get("unit", "hours")
        return f"{spec.get('end_column')} minus {spec.get('start_column')}, in {unit}"
    if t == "ratio":
        num = " + ".join(spec.get("numerator_columns") or [])
        den = " + ".join(spec.get("denominator_columns") or [])
        return f"({num}) / ({den}) x 100"
    if t == "extract_month":
        cols = " / ".join(spec.get("source_columns") or [])
        return f"Calendar month of {cols}"
    return t or ""


def _referenced_columns(spec: dict) -> set[str] | None:
    t = spec.get("type")
    if t == "duration_hours":
        cols = {spec.get("start_column"), spec.get("end_column")}
        return cols if all(cols) else None
    if t == "ratio":
        num, den = spec.get("numerator_columns"), spec.get("denominator_columns")
        if not num or not den:
            return None
        return set(num) | set(den)
    if t == "extract_month":
        cols = spec.get("source_columns")
        return set(cols) if cols else None
    return None


def suggest_features(df: pd.DataFrame) -> list[FeatureSuggestion]:
    user_prompt = f"Columns:\n{_columns_block(df)}\n\nPropose the features now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    candidates = payload.get("suggestions", [])
    if not isinstance(candidates, list):
        return []

    available_columns = set(df.columns.astype(str))
    suggestions: list[FeatureSuggestion] = []
    for spec in candidates:
        if not isinstance(spec, dict):
            continue
        if spec.get("type") not in VALID_TYPES:
            continue
        if not spec.get("name") or not spec.get("output_column"):
            continue
        referenced = _referenced_columns(spec)
        if not referenced or not referenced.issubset(available_columns):
            continue

        suggestions.append(FeatureSuggestion(
            id=f"ai_{uuid.uuid4().hex[:8]}",
            name=spec["name"],
            description=spec.get("description", ""),
            output_column=spec["output_column"],
            type=spec["type"],
            formula=_formula_text(spec),
            summary="distribution" if spec["type"] == "extract_month" else "stats",
            start_column=spec.get("start_column"),
            end_column=spec.get("end_column"),
            unit=spec.get("unit"),
            numerator_columns=spec.get("numerator_columns"),
            denominator_columns=spec.get("denominator_columns"),
            source_columns=spec.get("source_columns"),
        ))

    return suggestions
