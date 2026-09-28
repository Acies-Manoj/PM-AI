"""The Feature Designer: human-in-the-loop review for user-requested
features, BEFORE they are added.

  1. Formula     -- the Feature Agent's Think step turns the PM's plain-
                    English request into a precise, step-by-step formula
                    (skipped when the PM edited the formula and asked to
                    re-check it).
  2. Dry run     -- the Feature Agent writes the code for that formula, runs
                    it in the sandbox against the real data and validates the
                    result, exactly as it would on "Add". The PM sees the
                    formula, a preview of the new column's values, and the
                    validator's verdict.
  3. Save        -- only a draft whose preview matches the current formula
                    can be added. The dry run's validated code is kept on the
                    session (never sent to or accepted from the browser) and
                    seeds the feature cache, so adding it doesn't regenerate
                    the code with different sampling.
"""
from __future__ import annotations

import re
import uuid

import pandas as pd

from app.services.features import feature_agent, feature_cache
from app.services.features.feature_engineering import _distribution, _is_numeric_like, _numeric_stats

PREVIEW_ROWS = 10
# Drafts a session keeps before the oldest is dropped -- a PM abandoning and
# regenerating drafts must not grow session memory without bound.
MAX_DRAFTS_PER_SESSION = 20


def output_column_for(name: str) -> str:
    """Same slug rule feature_repository uses for custom features."""
    return re.sub(r"\W+", "_", name.strip().lower()).strip("_") or f"custom_{uuid.uuid4().hex[:6]}"


def _steps_from_formula(formula: str) -> list[str]:
    return [line.strip().lstrip("0123456789.) ").strip() for line in formula.splitlines() if line.strip()]


def _preview(df: pd.DataFrame, columns: list[str], output_column: str, values: pd.Series) -> tuple[list[str], list[dict]]:
    shown = [c for c in dict.fromkeys(columns) if c in df.columns and c != output_column][:5]
    frame = df[shown].copy() if shown else pd.DataFrame(index=df.index)
    frame[output_column] = values
    frame = frame.head(PREVIEW_ROWS).astype(object)
    frame = frame.where(frame.notna(), None)
    rows = [{k: (v if isinstance(v, (int, float, bool)) or v is None else str(v)) for k, v in row.items()} for row in frame.to_dict(orient="records")]
    return list(frame.columns), rows


def _summary(values: pd.Series) -> dict:
    non_null = int(values.notna().sum())
    numeric = _is_numeric_like(values)
    return {
        "non_null_count": non_null,
        "null_count": len(values) - non_null,
        "stats": _numeric_stats(values) if numeric else {},
        "distribution": {} if numeric else _distribution(values),
    }


def draft_feature(
    sessions_drafts: dict[str, dict], name: str, description: str, input_columns: list[str], df: pd.DataFrame,
    formula: str | None = None,
) -> dict:
    """Builds the draft shown in the Add KPI form. `formula` set means the PM
    edited it: it's used verbatim (no Think) and only dry-run again."""
    output_column = output_column_for(name)
    entry = {
        "name": name, "description": description, "calculation_intent": description,
        "output_column": output_column, "input_columns": input_columns,
    }
    notes: list[str] = []
    columns_block = feature_agent._columns_block(df)

    if formula and formula.strip():
        steps = _steps_from_formula(formula.strip())
        plan_meta: dict = {}
    else:
        plan = feature_agent.think(entry, columns_block)
        steps = plan.get("steps") or _steps_from_formula(plan.get("plan", ""))
        plan_meta = plan
    formula_text = feature_agent._plan_text({"steps": steps})

    # Columns the formula works from: the plan's own list, else any real
    # column the (edited) formula text names. Shown in the preview and to
    # the validator, so outputs are always judged next to their inputs.
    named = [c for c in df.columns if str(c) in formula_text]
    source_columns = list(dict.fromkeys(list(plan_meta.get("columns_used") or []) + named + list(input_columns)))

    # Dry run: exactly what "Add" would do for a fixed formula. If code can't
    # be made to fit the formula, compute_feature falls back to a fresh plan
    # -- in that case the PM is shown the plan that actually worked.
    computation = feature_agent.compute_feature({**entry, "formula": formula_text, "input_columns": source_columns}, df)
    if computation.values is not None and computation.plan_text and computation.plan_text.strip() != formula_text.strip():
        notes.append("The first formula couldn't be implemented correctly, so the agent revised it -- review the steps below.")
        formula_text = computation.plan_text
        steps = _steps_from_formula(formula_text)

    if output_column in df.columns:
        notes.append(f"A column named '{output_column}' already exists and would be replaced -- rename the KPI to keep both.")

    draft = {
        "draft_token": None,
        "name": name,
        "output_column": output_column,
        "formula": formula_text,
        "formula_steps": steps,
        "columns_used": source_columns,
        "output_dtype": plan_meta.get("output_dtype"),
        "status": "ok" if computation.values is not None else "failed",
        "error": computation.error,
        "validation_note": computation.validation_note,
        "preview_columns": [],
        "preview_rows": [],
        "summary": None,
        "notes": notes,
    }
    if computation.values is None:
        return draft

    draft["preview_columns"], draft["preview_rows"] = _preview(df, source_columns, output_column, computation.values)
    draft["summary"] = _summary(computation.values)
    token = uuid.uuid4().hex
    while len(sessions_drafts) >= MAX_DRAFTS_PER_SESSION:
        sessions_drafts.pop(next(iter(sessions_drafts)))
    sessions_drafts[token] = {"formula": formula_text, "plan_text": computation.plan_text, "generated_code": computation.generated_code}
    draft["draft_token"] = token
    return draft


def seed_cache_from_draft(session_id: str, sessions_drafts: dict[str, dict], draft_token: str | None, entry: dict) -> bool:
    """After a reviewed draft is saved: reuse its validated code if the saved
    formula is exactly the one that was dry-run. Returns True if seeded."""
    draft = sessions_drafts.pop(draft_token, None) if draft_token else None
    if not draft or not draft.get("generated_code"):
        return False
    if (entry.get("formula") or "").strip() != draft["formula"].strip():
        return False
    feature_cache.set(session_id, entry, draft["plan_text"], draft["generated_code"])
    return True
