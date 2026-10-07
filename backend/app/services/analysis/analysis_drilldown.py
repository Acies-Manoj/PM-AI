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

import re

import pandas as pd

from app.services.analysis import analysis_repository, analysis_templates
from app.services.analysis.analysis_columns import as_labels
from app.services.audit.audit_store import AuditSession

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
    """Default rank for a level: every group ("all"). `n` is only the
    suggested size if the PM switches to Top/Bottom, sized from the data."""
    try:
        subset = _apply(df, where)
    except analysis_templates.TemplateError:
        return {"mode": "all", "n": 3, "by": "count"}
    if dimension not in subset.columns:
        return {"mode": "all", "n": 3, "by": "count"}
    counts = as_labels(subset[dimension]).value_counts()
    return {"mode": "all", "n": default_n(counts), "by": "count"}


def _apply(df: pd.DataFrame, where: list[dict]) -> pd.DataFrame:
    if not where:
        return df
    return analysis_templates._apply_where(df, [analysis_templates.Condition(**w) for w in where])


def focus_condition(dimension: str, values: list[str]) -> dict:
    if len(values) == 1:
        return {"column": dimension, "op": "eq", "value": values[0]}
    return {"column": dimension, "op": "in", "value": list(values)}


# How each aggregation reads in a title or a chart label.
AGG_LABELS = {"mean": "Avg", "sum": "Total", "median": "Median", "max": "Max", "min": "Min"}


def agg_label(metric: str, column: str) -> str:
    """"Avg Mean Value", or "Max of Max Value" when the column already starts with the word."""
    prefix = AGG_LABELS[metric]
    return f"{prefix} of {column}" if column.lower().startswith(prefix.lower()) else f"{prefix} {column}"


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Columns that can be averaged as a drill-down metric: numeric, and not an
    identifier (nearly one distinct value per row). Engineered features included."""
    out = []
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
            continue
        if re.search(r"limit|cell|phone|serial|number|\bid\b", str(col), re.IGNORECASE):  # settings and codes, not measurements
            continue
        values = df[col].dropna()
        if values.empty:
            continue
        # Integer columns that are nearly one-per-row are identifiers (Trip ID,
        # Serial Number); continuous decimals like a % in spec are real measures.
        if pd.api.types.is_integer_dtype(df[col]) and values.nunique() > 0.9 * len(df) and values.nunique() > 50:
            continue
        out.append(col)
    return out[:80]


def build_template(
    dimensions: list[str] | str, metric: str, rank: dict, where: list[dict], df: pd.DataFrame,
    metric_column: str | None = None,
) -> tuple[dict, str]:
    """The spec for one level (1-5 X-axis columns), and the chart it should use.
    The RANK metric is always first (the template sorts on it). Rank mode "all"
    keeps every group, up to the chart cap."""
    dims = [dimensions] if isinstance(dimensions, str) else list(dimensions)
    in_spec = find_in_spec_column(df)
    count_metric = {"agg": "count", "label": "Trips"}
    extra = None
    if in_spec and (metric == "pct_in_spec" or rank.get("by") == "pct_in_spec"):
        extra = {"agg": "mean", "column": in_spec, "label": "% in spec"}
    elif metric in AGG_LABELS and metric_column:
        extra = {"agg": metric, "column": metric_column, "label": agg_label(metric, metric_column)}
    metrics = [count_metric] if extra is None else ([extra, count_metric] if rank.get("by") == "pct_in_spec" else [count_metric, extra])
    mode = rank.get("mode", "all")
    limit = None if mode == "all" else int(rank.get("n", 3))
    common = {
        "metrics": metrics,
        "sort": "asc" if mode == "bottom" else "desc",
        "top_n": limit if limit is not None else (100 if len(dims) == 1 else None),
        "min_rows": MIN_TRIPS_FOR_RATE_RANK if rank.get("by") == "pct_in_spec" else 1,
        "where": where,
    }
    if len(dims) == 1:
        template = {"template_id": "group_aggregate", "group_by": dims[0], **common}
    else:
        template = {"template_id": "multi_group", "dimensions": dims, **common}
    chart = "combo" if len(dims) == 1 and len(metrics) > 1 else ("bar" if len(dims) == 1 else "grouped_bar")
    return analysis_templates.to_dict(analysis_templates.validate(template, df)), chart


def level_name(dimension: str | list[str], rank: dict, focus_label: str, metric: str, metric_column: str | None = None) -> str:
    dims = " x ".join([dimension] if isinstance(dimension, str) else dimension)
    by = "% in spec" if rank.get("by") == "pct_in_spec" else "trips"
    if metric in AGG_LABELS and metric_column:
        extra = f", with {agg_label(metric, metric_column).lower()}"
    elif metric == "pct_in_spec" and rank.get("by") != "pct_in_spec":
        extra = ", with % in spec"
    else:
        extra = ""
    if rank.get("mode", "all") == "all":
        return f"{focus_label}: {dims} by {by}{extra}"
    word = "Top" if rank.get("mode") == "top" else "Bottom"
    return f"{focus_label}: {word} {rank.get('n', 3)} {dims} by {by}{extra}"


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


MAX_SUBTITLE_CHARS = 110
MAX_SUBTITLE_VALUES = 3


def drilldown_subtitle(chain: dict) -> str:
    """Short filter/rank line for a drill-down slide, e.g. 'Table Grapes - Top 3
    Origin by trips' or 'Origins: A, B, C +2 - Top 3 Carrier by trips, with %
    in spec'."""
    values = [str(v) for v in chain.get("focus_values") or []]
    if len(values) > 1:
        shown = ", ".join(values[:MAX_SUBTITLE_VALUES])
        extra = len(values) - MAX_SUBTITLE_VALUES
        focus = f"{chain.get('focus_dimension') or 'Value'}s: {shown}" + (f" +{extra}" if extra > 0 else "")
    else:
        focus = values[0] if values else (chain.get("focus_label") or "")

    rank = chain.get("rank") or {}
    dims = " x ".join(chain.get("dimensions") or [chain.get("dimension") or ""])
    by = "% in spec" if rank.get("by") == "pct_in_spec" else "trips"
    if rank.get("mode", "all") == "all":
        rank_text = f"{dims} by {by}"
    else:
        rank_text = f"{'Bottom' if rank.get('mode') == 'bottom' else 'Top'} {rank.get('n', 3)} {dims} by {by}"
    rank_text = rank_text.replace("  ", " ")
    if chain.get("metric") == "pct_in_spec" and rank.get("by") != "pct_in_spec":
        rank_text += ", with % in spec"
    elif chain.get("metric") in ("mean", "sum", "median", "max", "min") and chain.get("metric_column"):
        rank_text += f", with {agg_label(chain['metric'], chain['metric_column']).lower()}"

    text = f"{focus} - {rank_text}" if focus else rank_text
    if len(text) > MAX_SUBTITLE_CHARS:
        text = text[: MAX_SUBTITLE_CHARS - 1].rstrip() + "…"
    return text


def report_ready_entries(
    session: AuditSession,
    session_id: str,
    entry_ids: list[str] | None,
    chart_type_overrides: dict[str, str] | None = None,
    include_stale: bool = False,
) -> list[dict]:
    """Definitions merged with their in-memory run result, limited to ones
    that actually finished successfully and (if entry_ids was given) were
    chosen for inclusion -- returned as a TREE: each root in the PM's chosen
    order (`entry_ids`' own order when given, see ReportPage.tsx's drag
    reorder, else the repository's), each followed depth-first by its
    drill-down levels (siblings in the PM's order among themselves), so slides
    read 1, 2, 2.1, 2.1.1, 2.2, 3. A drill-down can never precede its parent;
    one whose parent isn't included becomes a root (keeping its subtitle). Each entry gains
    `slide_number`, `chain_level`, `parent_slide_number`, `subtitle` (drill-
    downs only) and `stale`. Stale levels (their own or an ancestor's
    filter/rank changed since they were built) are left out unless
    `include_stale` -- the download and summary must never present them."""
    all_defs = analysis_repository.get_repository(session_id)
    definitions = {d["id"]: d for d in all_defs}
    position = {eid: i for i, eid in enumerate(entry_ids)} if entry_ids is not None else {}
    creation = {d["id"]: i for i, d in enumerate(all_defs)}

    def sort_key(eid: str) -> int:
        return position.get(eid, creation[eid])

    def is_stale(entry_id: str) -> bool:
        seen: set[str] = set()
        while entry_id in definitions and entry_id not in seen:
            seen.add(entry_id)
            d = definitions[entry_id]
            if (d.get("chain") or {}).get("stale"):
                return True
            entry_id = d.get("parent_id") if d.get("chain") else None
        return False

    candidates: dict[str, dict] = {}
    for entry_id in (entry_ids if entry_ids is not None else list(definitions.keys())):
        definition = definitions.get(entry_id)
        if definition is None or entry_id in candidates:
            continue
        if definition.get("status") != "approved":
            continue  # a pending or rejected drill-down path level is never in the report
        result = session.analysis_results.get(entry_id)
        if not result or result.run_status != "done":
            continue
        stale = is_stale(entry_id)
        if stale and not include_stale:
            continue
        merged = dict(definition)
        merged.update(result.model_dump())
        merged["stale"] = stale
        if chart_type_overrides and entry_id in chart_type_overrides:
            merged["chart_type"] = chart_type_overrides[entry_id]
        candidates[entry_id] = merged

    # Effective parent: only when the parent is itself included.
    children: dict[str | None, list[str]] = {}
    for entry_id, entry in candidates.items():
        parent = entry.get("parent_id") if entry.get("chain") else None
        children.setdefault(parent if parent in candidates else None, []).append(entry_id)
    for siblings in children.values():
        siblings.sort(key=sort_key)

    ready: list[dict] = []

    def walk(parent_id: str | None, prefix: str, parent_number: str | None) -> None:
        for i, entry_id in enumerate(children.get(parent_id, []), start=1):
            entry = candidates[entry_id]
            number = f"{prefix}.{i}" if prefix else str(i)
            chain = entry.get("chain")
            entry["slide_number"] = number
            entry["chain_level"] = chain["level"] if chain else 1
            entry["parent_slide_number"] = parent_number
            entry["subtitle"] = drilldown_subtitle(chain) if chain else None
            ready.append(entry)
            walk(entry_id, number, number)

    walk(None, "", None)
    return ready
