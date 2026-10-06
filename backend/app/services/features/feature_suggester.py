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

`existing_entries` (the repository's current entries) is shown to the model
so it proposes genuinely new ideas, mirroring analysis_suggester.py's same
pattern -- without it, a PM clicking "Suggest more" repeatedly got the same
handful of ideas back every time, since the model never knew they'd already
been proposed. output_column-exact-match dedup still runs afterward in
feature_repository.add_ai_suggested_entries as a second line of defense,
but that only catches an identical slug, not a conceptual repeat under a
different name -- this prompt-level fix is what actually stops those.
"""
import json
import re
from collections.abc import Iterable

import pandas as pd

from app.services.common import groq_client
from app.services.common.groq_client import strip_json_fence
from app.config import DEFAULT_MAX_TOKENS, OPENROUTER_MODEL, model_for
from app.services.common import token_usage
from app.services.planner import planner_dependencies
from app.prompts import feature_suggester as _prompts

MAX_SUGGESTIONS = 5

SYSTEM_PROMPT = _prompts.build_system_prompt(MAX_SUGGESTIONS)


def _columns_block(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)


def _normalize_name(name: str) -> str:
    """Loose dedup key -- case/punctuation-insensitive, so "Time in Transit"
    and "time-in-transit" collide even though their `output_column` slugs
    might not (mirrors analysis_repository._normalize_name's same idea)."""
    return re.sub(r"\W+", " ", name.strip().lower()).strip()


def _existing_block(existing_entries: Iterable[dict]) -> str:
    lines = [
        f"- {e['name']} (column {e.get('output_column', '?')}): {e.get('calculation_intent') or e.get('description') or ''}".rstrip(": ")
        for e in existing_entries
        if e.get("name")
    ]
    return "\n".join(lines) if lines else "(none yet)"


def suggest_features(df: pd.DataFrame, existing_entries: Iterable[dict] = ()) -> list[dict]:
    """Returns repository-shaped candidate dicts: name, description,
    output_column, calculation_intent, input_columns -- ready to hand to
    feature_repository.add_ai_suggested_entries. `existing_entries` are the
    repository's current entries, shown to the model so it proposes
    genuinely new ideas and used to filter out any repeats it still makes."""
    existing_entries = list(existing_entries)
    client = groq_client.get_client()
    user_prompt = (
        f"Columns:\n{_columns_block(df)}\n\n"
        f"Existing features (do not repeat these):\n{_existing_block(existing_entries)}\n\n"
        "Propose the features now."
    )
    response = client.chat.completions.create(
        model=model_for("feature_suggester", OPENROUTER_MODEL),
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    token_usage.record("feature_suggester", model_for("feature_suggester", OPENROUTER_MODEL), response)
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(strip_json_fence(raw))
    candidates = payload.get("suggestions", [])
    if not isinstance(candidates, list):
        return []

    available_columns = set(df.columns.astype(str))
    seen_names = {_normalize_name(e["name"]) for e in existing_entries if e.get("name")}
    suggestions: list[dict] = []
    for spec in candidates:
        if not isinstance(spec, dict):
            continue
        if not spec.get("name") or not spec.get("output_column") or not spec.get("calculation_intent"):
            continue
        if _normalize_name(spec["name"]) in seen_names:
            continue
        if planner_dependencies._guardrail_warnings(spec):
            continue  # ranking / sorting / comparison logic belongs to an analysis
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
        seen_names.add(_normalize_name(spec["name"]))
        if len(suggestions) == MAX_SUGGESTIONS:
            break

    return suggestions
