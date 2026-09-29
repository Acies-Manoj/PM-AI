"""Guided drill-down chains.

A chain starts at an analysis the PM already ran (level 1) and adds one
level per confirmed drill-down, up to MAX_CHAIN_LEVEL:

  level 1  trips by Product
  level 2  Product = Table Grapes  ->  its top 3 Origins
  level 3  Origin in (top 3)       ->  its top 3 Carriers, with % in spec

Nothing here calls an LLM. A level is a plain `group_aggregate` template
whose `where` carries everything the earlier levels narrowed down to, so it
runs, filters and re-ranks through the ordinary analysis engine.
"""
from __future__ import annotations

import uuid

import pandas as pd

from app.services.analysis import analysis_templates
from app.services.analysis.analysis_columns import as_labels

MAX_CHAIN_LEVEL = 4
# A parent value with at least this many child groups is "wide": worth a drill-down.
WIDE_THRESHOLD = 5
# Ranking by % in spec ignores groups with fewer trips than this (too noisy).
MIN_TRIPS_FOR_RATE_RANK = 5
# Default N: smallest N covering CUMULATIVE_SHARE of the volume, capped here.
DEFAULT_N_CAP = 5
CUMULATIVE_SHARE = 0.7
# Preferred drill order; only columns present in the data are used.
HIERARCHY = ["Product", "Origin", "Carrier"]
# Columns worth offering as chart filters on a drill-down level.
FILTER_CANDIDATES = ["Product", "Origin", "Carrier", "Mode Of Transportation", "Is Alarmed", "Destination"]


def hierarchy(df: pd.DataFrame) -> list[str]:
    return [c for c in HIERARCHY if c in df.columns]


def next_dimension(current: str | None, df: pd.DataFrame) -> str | None:
    levels = hierarchy(df)
    if current in levels:
        i = levels.index(current) + 1
        return levels[i] if i < len(levels) else None
    return None


def find_in_spec_column(df: pd.DataFrame) -> str | None:
    """The engineered '% in spec' column, whatever the feature step named it."""
    for col in df.columns:
        key = str(col).lower().replace("-", " ").replace("_", " ")
        if "in spec" in key or "inspec" in key:
            return col
    return None


def available_metrics(df: pd.DataFrame) -> list[str]:
    return ["count", "pct_in_spec"] if find_in_spec_column(df) else ["count"]


def default_n(counts: pd.Series) -> int:
    """Smallest N covering ~70% of the volume, between 2 and DEFAULT_N_CAP."""
    ordered = counts.sort_values(ascending=False)
    total = float(ordered.sum())
    if total <= 0 or len(ordered) <= 2:
        return max(1, min(len(ordered), 2))
    running = 0.0
    for i, value in enumerate(ordered, start=1):
        running += float(value)
        if running / total >= CUMULATIVE_SHARE:
            return max(2, min(i, DEFAULT_N_CAP))
    return DEFAULT_N_CAP


def root_dimension(entry: dict, result_template: dict | None, result_columns: list[str] | None, df: pd.DataFrame) -> str | None:
    """The dimension a level-1 analysis is grouped by: its template's own
    group-by if it has one, else the first result column that is a real column."""
    template = entry.get("template") or result_template or {}
    for key in ("group_by", "row_dimension"):
        if template.get(key) in df.columns:
            return template[key]
    for col in result_columns or []:
        if col in df.columns:
            return col
    return None


def focus_options(df: pd.DataFrame, dimension: str, child_dimension: str, limit: int = 12) -> list[dict]:
    """Values of `dimension`, biggest first, each with how many distinct
    `child_dimension` values it spans -- 'Table Grapes spans 22 origins'."""
    labels = as_labels(df[dimension])
    children = as_labels(df[child_dimension])
    frame = pd.DataFrame({"v": labels, "c": children})
    grouped = frame.groupby("v", dropna=True).agg(rows=("c", "size"), child_count=("c", "nunique"))
    grouped = grouped.sort_values("rows", ascending=False).head(limit)
    return [
        {"value": str(v), "rows": int(r.rows), "child_count": int(r.child_count), "is_wide": int(r.child_count) >= WIDE_THRESHOLD}
        for v, r in grouped.iterrows()
    ]


def default_rank_for(df: pd.DataFrame, where: list[dict], dimension: str, metric: str = "count") -> dict:
    """Default top-N for a level, sized from the real distribution."""
    try:
        subset = _apply(df, where)
    except analysis_templates.TemplateError:
        return {"mode": "top", "n": 3, "by": "count"}
    if dimension not in subset.columns:
        return {"mode": "top", "n": 3, "by": "count"}
    counts = as_labels(subset[dimension]).value_counts()
    return {"mode": "top", "n": default_n(counts), "by": "count"}


def _apply(df: pd.DataFrame, where: list[dict]) -> pd.DataFrame:
    if not where:
        return df
    return analysis_templates._apply_where(df, [analysis_templates.Condition(**w) for w in where])


def focus_condition(dimension: str, values: list[str]) -> dict:
    if len(values) == 1:
        return {"column": dimension, "op": "eq", "value": values[0]}
    return {"column": dimension, "op": "in", "value": list(values)}


def build_template(dimension: str, metric: str, rank: dict, where: list[dict], df: pd.DataFrame) -> tuple[dict, str]:
    """The group_aggregate spec for one level, and the chart it should use.
    The RANK metric is always first (the template sorts on it); when the PM
    wants % in spec it is shown next to trip count either way."""
    in_spec = find_in_spec_column(df)
    count_metric = {"agg": "count", "label": "Trips"}
    metrics = [count_metric]
    if in_spec and (metric == "pct_in_spec" or rank.get("by") == "pct_in_spec"):
        spec_metric = {"agg": "mean", "column": in_spec, "label": "% in spec"}
        metrics = [spec_metric, count_metric] if rank.get("by") == "pct_in_spec" else [count_metric, spec_metric]
    template = {
        "template_id": "group_aggregate",
        "group_by": dimension,
        "metrics": metrics,
        "sort": "desc" if rank.get("mode", "top") == "top" else "asc",
        "top_n": int(rank.get("n", 3)),
        "min_rows": MIN_TRIPS_FOR_RATE_RANK if rank.get("by") == "pct_in_spec" else 1,
        "where": where,
    }
    chart = "combo" if len(metrics) > 1 else "bar"
    return analysis_templates.to_dict(analysis_templates.validate(template, df)), chart


def level_name(dimension: str, rank: dict, focus_label: str, metric: str) -> str:
    word = "Top" if rank.get("mode", "top") == "top" else "Bottom"
    by = "% in spec" if rank.get("by") == "pct_in_spec" else "trips"
    extra = ", with % in spec" if metric == "pct_in_spec" and rank.get("by") != "pct_in_spec" else ""
    return f"{focus_label}: {word} {rank.get('n', 3)} {dimension} by {by}{extra}"


def chart_filters(df: pd.DataFrame, exclude: set[str]) -> list[dict]:
    """Filter columns for a level's graph: the other dimensions, minus the
    ones already pinned by the drill-down itself."""
    return [
        {"column": c, "reason": "Narrow this drill-down"}
        for c in FILTER_CANDIDATES if c in df.columns and c not in exclude
    ]


def new_chain_id() -> str:
    return f"chain_{uuid.uuid4().hex[:8]}"


def descendants(entries: list[dict], entry_id: str) -> list[dict]:
    """Every entry below `entry_id` in the chain, nearest first."""
    out: list[dict] = []
    frontier = [entry_id]
    while frontier:
        parent = frontier.pop(0)
        for e in entries:
            if e.get("parent_id") == parent and e.get("chain"):
                out.append(e)
                frontier.append(e["id"])
    return out


def chain_numbers(entries: list[dict]) -> dict[str, str]:
    """Report slide numbers per entry id: roots keep their position (1, 2..),
    drill-downs hang under their parent (2.1, 2.2, 2.1.1)."""
    by_parent: dict[str | None, list[dict]] = {}
    for e in entries:
        by_parent.setdefault(e.get("parent_id") if e.get("chain") else None, []).append(e)
    numbers: dict[str, str] = {}

    def walk(parent_id: str | None, prefix: str) -> None:
        for i, e in enumerate(by_parent.get(parent_id, []), start=1):
            label = f"{prefix}.{i}" if prefix else str(i)
            numbers[e["id"]] = label
            walk(e["id"], label)

    walk(None, "")
    return numbers
