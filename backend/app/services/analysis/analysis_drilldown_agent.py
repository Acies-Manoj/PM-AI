"""LLM proposals for guided drill-downs.

Deterministic code (analysis_drilldown.py) knows HOW to run a level; this
asks the model WHICH level is worth running. The model only returns small
JSON choices -- a column, a metric, a top/bottom N, which values to focus on
-- and every choice is validated against the real data before it is shown,
so it can't invent a column or a value. If the call fails or nothing valid
comes back, the caller falls back to the deterministic default.
"""
from __future__ import annotations

import json
import logging
import re

import numpy as np
import pandas as pd

from app.config import DRILLDOWN_AGENT_MODEL, model_for
from app.services.analysis import analysis_agent, analysis_drilldown as dd
from app.services.analysis.analysis_columns import as_labels
from app.prompts import analysis_drilldown_agent as _prompts

logger = logging.getLogger(__name__)

# The most suggestions a drill-down ever holds, across the first batch and every "suggest more".
TOTAL_CAP = 15
# One batch asks the model for about this many; they are then scored against the data and the best are kept.
MAX_PROPOSALS = 12
# Columns worth drilling into: categorical with a manageable number of values.
_MIN_VALUES, _MAX_VALUES = 2, 200
_MAX_PROPOSAL_DIMENSIONS = 4
# Identifiers and free text make useless X axes (one bar per row).
_NOT_AN_AXIS = re.compile(r"\b(id|serial|number|note|notes|comment|comments|cell|phone|email|e-mail|limit|user|created by)\b", re.IGNORECASE)
_MAX_UNIQUE_SHARE = 0.5
# Numeric columns that are real measurements (worth averaging), not phone numbers or codes.
_MEASUREMENT = re.compile(r"(value|hours|length|deviation|spec|temp|mkt|days|delay|transit)", re.IGNORECASE)

_SYSTEM = _prompts.SYSTEM


def _usable(df: pd.DataFrame, col: str) -> bool:
    """A column that makes a readable X axis: categorical-ish, not a date/time
    (every timestamp would be its own group), not near-unique like an id."""
    series = df[col]
    if pd.api.types.is_datetime64_any_dtype(series) or _NOT_AN_AXIS.search(str(col)):
        return False
    try:
        n = as_labels(series).nunique()
    except Exception:
        return False
    if n > _MAX_UNIQUE_SHARE * max(len(series), 1) and n > 20:
        return False  # nearly one value per row: an identifier, not a category
    if pd.api.types.is_float_dtype(series):
        return _MIN_VALUES <= n <= 20
    return _MIN_VALUES <= n <= _MAX_VALUES


def candidate_dimensions(df: pd.DataFrame, exclude: set[str], feature_columns: list[str] | tuple = ()) -> list[str]:
    """Every column usable as an X axis for the next level: the hierarchy's
    steps first, then the engineered feature columns, then all the rest --
    never one the chain has already pinned."""
    ordered = [c for c in dd.hierarchy(df) if c not in exclude]
    for group in (list(feature_columns), list(df.columns)):
        for col in group:
            if col in exclude or col in ordered or col not in df.columns or not _usable(df, col):
                continue
            ordered.append(col)
    return ordered


def _default_proposal(df: pd.DataFrame, dimension: str, where: list[dict], focus: list[str], children: list[str]) -> list[dict]:
    if not children or not focus:
        return []
    child = children[0]
    scope = where + [dd.focus_condition(dimension, focus)]
    return [{
        "child_dimension": child,
        "child_dimensions": [child],
        "metric_column": None,
        "focus_values": focus,
        "metric": "pct_in_spec" if dd.find_in_spec_column(df) else "count",
        "rank": dd.default_rank_for(df, scope, child),
        "reason": f"The next level down: which {child} values carry most of the {', '.join(focus[:2])} volume.",
        "source": "default",
    }]


def _validated(raw: dict, df: pd.DataFrame, children: list[str], allowed_focus: list[str], numeric: list[str]) -> dict | None:
    raw_dims = raw.get("child_dimensions")
    if not isinstance(raw_dims, list) or not raw_dims:
        raw_dims = [raw.get("child_dimension")]
    dims = [d for d in dict.fromkeys(raw_dims) if d in children][:_MAX_PROPOSAL_DIMENSIONS]
    if not dims:
        return None
    focus = [v for v in (raw.get("focus_values") or []) if v in allowed_focus]
    if not focus:
        # The columns and measure are what make the idea; a misspelt or missing
        # starting value falls back to the first real one (the PM ticks values anyway).
        if not allowed_focus:
            return None
        focus = allowed_focus[:1]
    have_spec = dd.find_in_spec_column(df) is not None
    metric = raw.get("metric") if raw.get("metric") in ("count", "pct_in_spec", "mean") else "count"
    metric_column = raw.get("metric_column") if raw.get("metric_column") in numeric else None
    if metric == "mean" and not metric_column:
        metric = "count"
    if metric == "pct_in_spec" and not have_spec:
        metric = "count"
    rank = raw.get("rank") if isinstance(raw.get("rank"), dict) else {}
    by = rank.get("by") if rank.get("by") in ("count", "pct_in_spec") else "count"
    if not have_spec:
        by = "count"
    return {
        "child_dimension": dims[0], "child_dimensions": dims, "focus_values": focus, "metric": metric,
        "metric_column": metric_column if metric == "mean" else None,
        # Every group is shown; the PM can still switch a level to Top/Bottom N afterwards.
        "rank": {"mode": "all", "n": 5, "by": by},
        "reason": str(raw.get("reason") or "").strip(), "source": "ai",
    }


# -- ranking against the data ---------------------------------------------------------------------
# Groups with fewer rows than this are too noisy to judge a difference by.
_MIN_ROWS_TO_TRUST = 5
# A chart reads well up to about this many groups; far past it, it is a wall of bars.
_READABLE_GROUPS, _CROWDED_GROUPS = 15, 40
# Spread (in points of % in spec) that counts as "clearly different groups"; for other measures, the
# coefficient of variation that does.
_FULL_SPREAD_POINTS, _FULL_CV = 15.0, 0.5
# Each earlier pick that already uses one of a proposal's columns multiplies its score by this.
_REPEAT_PENALTY = 0.75


def score_proposal(df: pd.DataFrame, dimension: str, where: list[dict], proposal: dict) -> float:
    """How worth showing a drill-down is, 0 (nothing to see) to about 1, judged on the real data.

    score = readability x coverage x (0.2 + information) x simplicity
      readability  -- 1 for up to 15 groups, less for a crowded chart, 0 for fewer than two groups
      coverage     -- share of the rows sitting in groups big enough to trust
      information  -- how much the groups differ: the spread of their % in spec / mean, or, for a plain
                      count, how concentrated the volume is (a few groups carrying most of it)
      simplicity   -- fewer columns are easier to read"""
    dims = proposal["child_dimensions"]
    try:
        scope = dd._apply(df, where + [dd.focus_condition(dimension, proposal["focus_values"])])
    except Exception:
        return 0.0
    if scope.empty or any(c not in scope.columns for c in dims):
        return 0.0

    keys = pd.DataFrame({f"k{i}": as_labels(scope[c]) for i, c in enumerate(dims)})
    key_cols = list(keys.columns)
    metric, column = proposal.get("metric"), proposal.get("metric_column")
    if metric == "pct_in_spec" and dd.find_in_spec_column(df):
        values = pd.to_numeric(scope[dd.find_in_spec_column(df)], errors="coerce")
    elif metric == "mean" and column in scope.columns:
        values = pd.to_numeric(scope[column], errors="coerce")
    else:
        values = None

    sizes = keys.groupby(key_cols, dropna=False).size()
    groups = len(sizes)
    if groups < 2:
        return 0.0
    readability = 1.0 if groups <= _READABLE_GROUPS else (0.6 if groups <= _CROWDED_GROUPS else 0.3)
    trusted = sizes[sizes >= _MIN_ROWS_TO_TRUST]
    coverage = float(trusted.sum() / sizes.sum())
    if len(trusted) < 2:
        return 0.05 * readability

    if values is None:
        share = trusted / trusted.sum()
        entropy = float(-(share * np.log(share)).sum())
        information = 0.9 * (1.0 - entropy / float(np.log(len(trusted))))  # equal-sized groups: nothing to see
    else:
        frame = keys.assign(v=values.values)
        means = frame.groupby(key_cols, dropna=False)["v"].mean().reindex(trusted.index).dropna()
        if len(means) < 2:
            return 0.05 * readability
        weights = trusted.reindex(means.index).astype(float)
        centre = float((means * weights).sum() / weights.sum())
        spread = float(np.sqrt((weights * (means - centre) ** 2).sum() / weights.sum()))
        if metric == "pct_in_spec":
            points = spread * (100.0 if float(values.max()) <= 1.0 else 1.0)
            information = min(points / _FULL_SPREAD_POINTS, 1.0)
        else:
            information = min((spread / abs(centre) if centre else 0.0) / _FULL_CV, 1.0)

    simplicity = 1.0 / (1.0 + 0.15 * (len(dims) - 1))
    return readability * coverage * (0.2 + information) * simplicity


def rank_proposals(df: pd.DataFrame, dimension: str, where: list[dict], proposals: list[dict], limit: int) -> list[dict]:
    """The best `limit` proposals, best first. Greedy: each pick is the highest score after discounting
    proposals that reuse a column already picked, so the list covers different questions instead of five
    variations on one. Proposals with nothing to show (score 0) are dropped."""
    pool = [(score_proposal(df, dimension, where, p), p) for p in proposals]
    pool = [(sc, p) for sc, p in pool if sc > 0]
    chosen: list[dict] = []
    used: dict[str, int] = {}
    while pool and len(chosen) < limit:
        def adjusted(item: tuple[float, dict]) -> float:
            sc, p = item
            return sc * _REPEAT_PENALTY ** max((used.get(c, 0) for c in p["child_dimensions"]), default=0)

        best = max(pool, key=adjusted)
        pool.remove(best)
        chosen.append(best[1])
        for c in best[1]["child_dimensions"]:
            used[c] = used.get(c, 0) + 1
    return chosen


def propose(
    df: pd.DataFrame, entry: dict, dimension: str, where: list[dict], allowed_focus: list[str],
    result_table: list[dict], interpretation: str | None, avoid: list[dict] | None = None,
    feature_columns: list[str] | tuple = (), pinned: set[str] | None = None,
    limit: int = MAX_PROPOSALS,
) -> list[dict]:
    """Up to `limit` validated proposals for drilling into `entry`, ranked best first (see
    rank_proposals), from ONE model call, falling back to one deterministic default when the model is
    unavailable or unusable. `avoid` (existing cached proposals, when this is
    a "suggest more" request) is both told to the model and used to hard-
    filter its response, so a repeat can't sneak through even if the model
    ignores the instruction."""
    exclude = {dimension} | {w["column"] for w in where} | set(pinned or ())
    children = candidate_dimensions(df, exclude, feature_columns)
    numeric = dd.numeric_columns(df)
    default_focus = allowed_focus[:1] if not entry.get("chain") else allowed_focus
    fallback = _default_proposal(df, dimension, where, default_focus, children)
    if not children or not allowed_focus:
        return fallback

    def analysis_key(item: dict) -> tuple:
        return (tuple(item.get("child_dimensions") or [item["child_dimension"]]), item.get("metric"), item.get("metric_column"))

    avoid_keys = {analysis_key(a) for a in (avoid or [])}

    scope = dd._apply(df, where) if where else df
    facts = []
    for child in children[:25]:
        facts.append({"dimension": child, "distinct_values": int(as_labels(scope[child]).nunique()),
                      "engineered_feature": child in set(feature_columns)})
    focus_facts = dd.focus_options(scope, dimension, children[0], limit=15)
    focus_facts = [f for f in focus_facts if f["value"] in allowed_focus] or [{"value": v} for v in allowed_focus[:15]]
    user = json.dumps({
        "analysis": entry.get("name"),
        "current_dimension": dimension,
        "already_filtered_to": [f'{w["column"]} {w["op"]} {w["value"]}' for w in where],
        "focus_values": focus_facts,
        "candidate_dimensions": facts,
        "in_spec_available": dd.find_in_spec_column(df) is not None,
        "numeric_columns": numeric[:25],
        "chart_sample": result_table[:10],
        "interpretation": interpretation or "",
        "ideas_to_avoid_repeating": [a.get("reason") or a.get("child_dimension") for a in (avoid or [])],
    }, default=str)
    try:
        raw = analysis_agent.call_llm(
            _SYSTEM, user, json_mode=True, temperature=0.4, call_name="drilldown_agent", model=model_for("drilldown_agent", DRILLDOWN_AGENT_MODEL),
            max_tokens=12000,
        )
        payload = json.loads(analysis_agent.strip_json_fence(raw))
        items = payload.get("proposals", []) if isinstance(payload, dict) else []
    except Exception as exc:
        # No model answer: the single default proposal below is all there is.
        logger.info("drilldown proposal failed, building from the data: %s", exc)
        items = []

    proposals: list[dict] = []
    seen: set[tuple] = set(avoid_keys)
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ok = _validated(item, df, children, allowed_focus, numeric)
        key = analysis_key(ok) if ok else None
        if ok and key not in seen:
            seen.add(key)
            proposals.append(ok)
        if len(proposals) >= 2 * MAX_PROPOSALS:  # more than enough to rank; stops a runaway reply
            break

    # No padding: if only a few ideas are worth showing, that is what the analyst gets.
    ranked = rank_proposals(df, dimension, where, proposals, limit)
    return ranked or (fallback if not avoid else [])
