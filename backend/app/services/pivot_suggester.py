"""AI agent that looks at the audited + feature-engineered dataframe's
columns/dtypes and proposes candidate pivot tables. Groq only picks WHICH
existing columns to group/aggregate and writes the rationale -- it never
computes a value itself. Every suggestion is constrained to the aggregation
types pivot_engine.py can actually execute, and anything referencing a
column that doesn't exist in the current data (a hallucination) is dropped
rather than surfaced, since a broken suggestion is worse than a missing one.
"""
import json
import uuid

import pandas as pd

from app.schemas import PivotSuggestion
from app.services.groq_client import chat_json
from app.services.llm_context import columns_block as _columns_block
from app.services.pivot_definitions_store import SUPPORTED_AGGS

SYSTEM_PROMPT = """You are a data analyst proposing pivot tables for an \
operational cold-chain shipment dataset, to help a program manager spot \
trends and outliers for a recurring report. You'll be given the current \
column names, dtypes, and a few sample values per column (some columns may \
be engineered fields like "Country of Origin", "Arrival Month", or \
"% In Spec").

Propose up to 5 NEW pivot table ideas that would be genuinely useful for \
cold-chain reporting (e.g. performance by carrier, seasonality by product, \
exception hours by lane). Every suggestion MUST reference only columns that \
appear in the given column list -- never invent a column name -- and every \
metric's "agg" MUST be exactly one of: sum, mean, count, min, max, median, \
distinct_count, pct_of_total.

- "group_by": 1-2 column names to group rows by.
- "metrics": 1-3 objects, each {"column": <name>, "agg": <one of the above>, \
"output_label": <short display label>}. Only pick numeric columns for sum/ \
mean/min/max/median. "count", "distinct_count", and "pct_of_total" work on \
any column and describe row counts/shares, so prefer an identifier-like \
column (e.g. a trip/shipment id) for those.
- "sort_by" (optional): {"metric": <one of this pivot's output_label \
values>, "direction": "asc" or "desc"}.
- "top_n" (optional): integer cap on rows returned.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"suggestions": [
  {
    "name": "short title, e.g. 'Exception Hours by Carrier'",
    "description": "one plain-English sentence on why this is useful",
    "group_by": ["Carrier"],
    "metrics": [{"column": "Trip ID", "agg": "count", "output_label": "Shipments"}],
    "sort_by": {"metric": "Shipments", "direction": "desc"},
    "top_n": 10
  }
]}"""


def _valid_metric(spec: dict, available_columns: set[str]) -> bool:
    return (
        isinstance(spec, dict)
        and spec.get("column") in available_columns
        and spec.get("agg") in SUPPORTED_AGGS
        and bool(spec.get("output_label"))
    )


def suggest_pivots(df: pd.DataFrame) -> list[PivotSuggestion]:
    user_prompt = f"Columns:\n{_columns_block(df)}\n\nPropose the pivot tables now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    candidates = payload.get("suggestions", [])
    if not isinstance(candidates, list):
        return []

    available_columns = set(df.columns.astype(str))
    suggestions: list[PivotSuggestion] = []
    for spec in candidates:
        if not isinstance(spec, dict) or not spec.get("name"):
            continue

        group_by = spec.get("group_by")
        if not isinstance(group_by, list) or not group_by or not set(group_by).issubset(available_columns):
            continue

        metrics = spec.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            continue
        if not all(_valid_metric(m, available_columns) for m in metrics):
            continue

        metric_labels = {m["output_label"] for m in metrics}
        sort_by = spec.get("sort_by")
        if sort_by is not None and (not isinstance(sort_by, dict) or sort_by.get("metric") not in metric_labels):
            sort_by = None

        top_n = spec.get("top_n")
        if not isinstance(top_n, int) or top_n <= 0:
            top_n = None

        suggestions.append(PivotSuggestion(
            id=f"ai_pivot_{uuid.uuid4().hex[:8]}",
            name=spec["name"],
            description=spec.get("description", ""),
            group_by=group_by,
            metrics=metrics,
            filters=[],
            sort_by=sort_by,
            top_n=top_n,
        ))

    return suggestions
