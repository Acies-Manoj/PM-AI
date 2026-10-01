"""LLM proposals for guided drill-downs.

Deterministic code (analysis_drilldown.py) knows HOW to run a level; this
asks the model WHICH level is worth running. The model only returns small
JSON choices -- a column, a metric, a top/bottom N, which values to focus on
-- and every choice is validated against the real data before it is shown,
so it can't invent a column or a value. If the call fails or nothing valid
comes back, the caller falls back to the deterministic default.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import re

import pandas as pd

from app.config import DRILLDOWN_AGENT_MODEL, model_for
from app.services.analysis import analysis_agent, analysis_drilldown as dd
from app.services.analysis.analysis_columns import as_labels

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 25
# A batch should reach this many (fewer only in "suggest more" mode, or on tiny data).
MIN_PROPOSALS = 20
MIN_PROPOSALS_MORE = 10
# Wanted number of proposals by X-axis column count (1 col = 2-variable chart ... 4 cols = 5-variable chart).
_WANT_BY_COLUMNS = {1: 3, 2: 5, 3: 5, 4: 4}
# Columns worth drilling into: categorical with a manageable number of values.
_MIN_VALUES, _MAX_VALUES = 2, 200
_MAX_PROPOSAL_DIMENSIONS = 4
# Identifiers and free text make useless X axes (one bar per row).
_NOT_AN_AXIS = re.compile(r"\b(id|serial|number|note|notes|comment|comments|cell|phone|email|e-mail|limit|user|created by)\b", re.IGNORECASE)
_MAX_UNIQUE_SHARE = 0.5
# Numeric columns that are real measurements (worth averaging), not phone numbers or codes.
_MEASUREMENT = re.compile(r"(value|hours|length|deviation|spec|temp|mkt|days|delay|transit)", re.IGNORECASE)

_SYSTEM = """You are the drill-down step of a supply-chain analytics assistant. The analyst is looking \\
at a chart grouped by one dimension and wants to drill into the values that matter. Propose 20 to 25 \\
NEXT drill-downs -- a genuinely useful, non-repetitive SET, not just as many as you can invent.

A drill-down = pick which VALUES of the current dimension to focus on, then pick ONE TO FOUR \\
different columns to break them down by (the X axis). Use ALL the columns you are given, including \\
engineered features (computed columns), not just the obvious ones. Show every group -- do not limit to a \\
top or bottom N.

To reach 20-25 REAL ideas (not the same idea restated), vary at least one of these across your \\
proposals: the child_dimension, the metric, the rank direction (top vs bottom), and which focus values \\
you're narrowing into. Cover the different candidate dimensions given below rather than proposing the \\
same one repeatedly. Two proposals are only worth both keeping if they'd actually answer a different \\
question for the analyst -- don't pad the list with near-duplicates just to hit the count.

Rules:
- Each proposal must be a DIFFERENT ANALYSIS (different columns and/or measure). Never repeat the same \\
analysis for another focus value -- the analyst picks which values to apply an analysis to themselves, so \\
focus_values is only the single most interesting value to start from.
- Vary the MEASURE, not just the columns: no more than a third of the proposals may be plain "count". Where \
they exist, use "pct_in_spec" and "mean" of performance columns (Mean Value, Max Value, Min Value, Standard \
Deviation, hours out of spec, engineered features such as % In Spec) to answer quality and performance \
questions. Never average a spec-limit column (Limit Low / Ideal / High) or an identifier.
- Prefer focusing on values that are wide (span many groups) or dominate the volume.
- child_dimensions is a list of 1 to 4 columns and each MUST be one of the listed candidate dimensions.
- Return AT LEAST 20 proposals (up to 25). Fewer than 20 is a failure unless there are genuinely too few columns.
- Mix the CHART SIZES. A chart's variables = its X-axis columns + the measure. Of your 20-25 proposals: \\
about 4 use 1 column (a 2-variable chart), about 7 use 2 columns (a 3-variable chart), about 6 use 3 columns \\
(a 4-variable chart) and about 5 use 4 columns (a 5-variable chart). Pick combinations that answer a real \\
question (e.g. carrier AND destination AND month) and prefer columns with few distinct values for the extra \\
columns so the chart stays readable. Use different columns across proposals; do not build them all from the \\
same three or four columns.
- focus_values MUST be chosen from the listed focus values, exactly as written.
- metric is "count" (trips), "pct_in_spec" (only if available and the analyst cares about quality/compliance), \\
or "mean" of one of the listed numeric_columns (set metric_column to its exact name).
- rank.by is "count" or "pct_in_spec" (only if available) -- it only decides the sort order.
- Do NOT set a top/bottom limit; always use rank.mode "all".
- Each proposal needs a one-sentence reason in plain business language.
- If a list of ideas to avoid is given, none of your proposals may repeat or closely rephrase one of them.

Return ONLY JSON:
{"proposals": [{"child_dimensions": ["..."], "focus_values": ["..."], "metric": "count|pct_in_spec|mean", \\
"metric_column": "numeric column, only when metric is mean", \\
"rank": {"mode": "all", "by": "count|pct_in_spec"}, "reason": "..."}]}"""


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


def _counts_by_columns(proposals: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for p in proposals:
        n = len(p["child_dimensions"])
        counts[n] = counts.get(n, 0) + 1
    return counts


def _deficits(proposals: list[dict], total_min: int) -> dict[int, int]:
    """How many more proposals of each column count are wanted: the per-size
    quota first, then enough extras (cycling the sizes) to reach `total_min`."""
    have = _counts_by_columns(proposals)
    need = {size: max(0, want - have.get(size, 0)) for size, want in _WANT_BY_COLUMNS.items()}
    missing = total_min - len(proposals) - sum(need.values())
    for size in itertools.cycle((2, 3, 4, 1)):
        if missing <= 0:
            break
        need[size] += 1
        missing -= 1
    return {k: v for k, v in need.items() if v > 0}


def _synthesize(
    facts: list[dict], children: list[str], have_spec: bool, numeric: list[str], focus: list[str],
    seen: set, needs: dict[int, int], analysis_key,
) -> list[dict]:
    """Deterministic ideas built from the lowest-cardinality columns -- used only
    to fill what the model did not supply, so a batch always reaches its size."""
    # Lowest-cardinality columns first (they make the most readable charts), but never
    # drop the rest: with few usable columns the batch still has to reach its size.
    names = [f["dimension"] for f in sorted(facts, key=lambda f: f["distinct_values"])] or children
    names = names[:10]
    measures = [("count", None)]
    if have_spec:
        measures.append(("pct_in_spec", None))
    measures += [("mean", col) for col in [c for c in numeric if _MEASUREMENT.search(c)][:4]]
    start = focus[0] if focus else "this selection"
    out: list[dict] = []
    n = 0
    for size, need in needs.items():
        if len(names) < size:
            continue
        # A fixed pseudo-random order, so the ideas spread over many columns instead of
        # all starting with the same two.
        combos = sorted(itertools.combinations(names, size), key=lambda c: hashlib.md5("|".join(c).encode()).hexdigest())
        made = 0
        # Each pass gives every combination a different measure, so scarce columns still
        # yield distinct analyses (same columns, another question).
        for combo, shift in ((c, k) for k in range(len(measures)) for c in combos):
            if made == need:
                break
            metric, column = measures[(n + shift) % len(measures)]
            item = {
                "child_dimension": combo[0], "child_dimensions": list(combo), "focus_values": focus[:1], "metric": metric,
                "metric_column": column, "rank": {"mode": "all", "n": 5, "by": "count"},
                "source": "default",
            }
            if analysis_key(item) in seen:
                continue
            joined = ", ".join(combo[:-1]) + (" and " if len(combo) > 1 else "") + combo[-1]
            item["reason"] = {
                "count": f"How {start} shipments spread across {joined}.",
                "pct_in_spec": f"Where {start} stays in spec, across {joined}.",
                "mean": f"How average {column} varies across {joined} for {start}.",
            }[metric]
            seen.add(analysis_key(item))
            out.append(item)
            made += 1
            n += 1
    return out


def propose(
    df: pd.DataFrame, entry: dict, dimension: str, where: list[dict], allowed_focus: list[str],
    result_table: list[dict], interpretation: str | None, avoid: list[dict] | None = None,
    feature_columns: list[str] | tuple = (), pinned: set[str] | None = None,
) -> list[dict]:
    """Up to MAX_PROPOSALS validated proposals for drilling into `entry` in
    ONE call, falling back to one deterministic default when the model is
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
        # No model answer: the batch is built from the data alone below.
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
        if len(proposals) == MAX_PROPOSALS:
            break

    # The model tends to return few and simple ideas. Reach the wanted size and mix
    # of chart sizes: ask once more for exactly what is missing, then fill any
    # remaining gap from the lowest-cardinality columns.
    total_min = MIN_PROPOSALS_MORE if avoid else MIN_PROPOSALS
    need = _deficits(proposals, total_min)
    need = {size: n for size, n in need.items() if size == 1 or len(children) >= size}
    if need and proposals:
        try:
            extra_prompt = json.loads(user)
            extra_prompt["also_needed"] = {
                "instruction": "Return ONLY additional proposals with the column counts below; do not repeat the ones already given.",
                "how_many_by_number_of_columns": {f"{size}_columns": n for size, n in need.items()},
                "already_have": [{"columns": p["child_dimensions"], "metric": p["metric"]} for p in proposals],
            }
            raw = analysis_agent.call_llm(
                _SYSTEM, json.dumps(extra_prompt, default=str), json_mode=True, temperature=0.5,
                call_name="drilldown_agent_more", model=model_for("drilldown_agent_more", DRILLDOWN_AGENT_MODEL), max_tokens=8000,
            )
            more_items = json.loads(analysis_agent.strip_json_fence(raw)).get("proposals", [])
        except Exception as exc:
            logger.info("extra drilldown proposals failed, synthesising: %s", exc)
            more_items = []
        for item in more_items if isinstance(more_items, list) else []:
            ok = _validated(item, df, children, allowed_focus, numeric) if isinstance(item, dict) else None
            if ok and analysis_key(ok) not in seen:
                seen.add(analysis_key(ok))
                proposals.append(ok)
    need = _deficits(proposals, total_min)
    need = {size: n for size, n in need.items() if size == 1 or len(children) >= size}
    if need:
        proposals += _synthesize(
            facts, children, dd.find_in_spec_column(df) is not None, numeric, default_focus or allowed_focus,
            seen, need, analysis_key,
        )
    # Over the cap: drop trailing single-column ideas first.
    while len(proposals) > MAX_PROPOSALS:
        drop = next((i for i in range(len(proposals) - 1, -1, -1) if len(proposals[i]["child_dimensions"]) == 1), None)
        proposals.pop(drop if drop is not None else -1)
    return proposals or (fallback if not avoid else [])
