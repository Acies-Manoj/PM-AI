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

import pandas as pd

from app.config import DRILLDOWN_AGENT_MODEL
from app.services.analysis import analysis_agent, analysis_drilldown as dd
from app.services.analysis.analysis_columns import as_labels

logger = logging.getLogger(__name__)

MAX_PROPOSALS = 15
# Columns worth drilling into: categorical with a manageable number of values.
_MIN_VALUES, _MAX_VALUES = 2, 80

_SYSTEM = """You are the drill-down step of a supply-chain analytics assistant. The analyst is looking \\
at a chart grouped by one dimension and wants to drill into the values that matter. Propose 10 to 15 \\
NEXT drill-downs -- a genuinely useful, non-repetitive SET, not just as many as you can invent.

A drill-down = pick which VALUES of the current dimension to focus on, pick a DIFFERENT dimension to \\
break them down by, and pick how many groups to show (top or bottom N).

To reach 10-15 REAL ideas (not the same idea restated), vary at least one of these across your \\
proposals: the child_dimension, the metric, the rank direction (top vs bottom), and which focus values \\
you're narrowing into. Cover the different candidate dimensions given below rather than proposing the \\
same one repeatedly. Two proposals are only worth both keeping if they'd actually answer a different \\
question for the analyst -- don't pad the list with near-duplicates just to hit the count.

Rules:
- Prefer focusing on values that are wide (span many groups) or dominate the volume.
- child_dimension MUST be one of the listed candidate dimensions.
- focus_values MUST be chosen from the listed focus values, exactly as written.
- metric is "pct_in_spec" only when the analyst cares about quality/compliance/spec AND it is available; \\
otherwise "count".
- rank.by is "count" (busiest groups) or "pct_in_spec" (best/worst quality; only if available).
- rank.mode is "top" or "bottom"; rank.n is 2 to 5, sized to the shape of the data.
- Each proposal needs a one-sentence reason in plain business language.
- If a list of ideas to avoid is given, none of your proposals may repeat or closely rephrase one of them.

Return ONLY JSON:
{"proposals": [{"child_dimension": "...", "focus_values": ["..."], "metric": "count|pct_in_spec", \\
"rank": {"mode": "top|bottom", "n": 3, "by": "count|pct_in_spec"}, "reason": "..."}]}"""


def candidate_dimensions(df: pd.DataFrame, exclude: set[str]) -> list[str]:
    """Columns usable as the next level: the hierarchy's steps first, then any
    other categorical column, never one the chain has already pinned."""
    ordered = [c for c in dd.hierarchy(df) if c not in exclude]
    for col in df.columns:
        if col in exclude or col in ordered:
            continue
        try:
            n = as_labels(df[col]).nunique()
        except Exception:
            continue
        if _MIN_VALUES <= n <= _MAX_VALUES and not pd.api.types.is_float_dtype(df[col]):
            ordered.append(col)
    return ordered


def _default_proposal(df: pd.DataFrame, dimension: str, where: list[dict], focus: list[str], children: list[str]) -> list[dict]:
    if not children or not focus:
        return []
    child = children[0]
    scope = where + [dd.focus_condition(dimension, focus)]
    return [{
        "child_dimension": child,
        "focus_values": focus,
        "metric": "pct_in_spec" if dd.find_in_spec_column(df) else "count",
        "rank": dd.default_rank_for(df, scope, child),
        "reason": f"The next level down: which {child} values carry most of the {', '.join(focus[:2])} volume.",
        "source": "default",
    }]


def _validated(raw: dict, df: pd.DataFrame, children: list[str], allowed_focus: list[str]) -> dict | None:
    child = raw.get("child_dimension")
    if child not in children:
        return None
    focus = [v for v in (raw.get("focus_values") or []) if v in allowed_focus]
    if not focus:
        return None
    metric = raw.get("metric") if raw.get("metric") in ("count", "pct_in_spec") else "count"
    rank = raw.get("rank") if isinstance(raw.get("rank"), dict) else {}
    by = rank.get("by") if rank.get("by") in ("count", "pct_in_spec") else "count"
    have_spec = dd.find_in_spec_column(df) is not None
    if not have_spec:
        metric, by = "count", "count"
    try:
        n = max(1, min(int(rank.get("n", 3)), 10))
    except (TypeError, ValueError):
        n = 3
    return {
        "child_dimension": child, "focus_values": focus, "metric": metric,
        "rank": {"mode": "bottom" if rank.get("mode") == "bottom" else "top", "n": n, "by": by},
        "reason": str(raw.get("reason") or "").strip(), "source": "ai",
    }


def propose(
    df: pd.DataFrame, entry: dict, dimension: str, where: list[dict], allowed_focus: list[str],
    result_table: list[dict], interpretation: str | None, avoid: list[dict] | None = None,
) -> list[dict]:
    """Up to MAX_PROPOSALS validated proposals for drilling into `entry` in
    ONE call, falling back to one deterministic default when the model is
    unavailable or unusable. `avoid` (existing cached proposals, when this is
    a "suggest more" request) is both told to the model and used to hard-
    filter its response, so a repeat can't sneak through even if the model
    ignores the instruction."""
    exclude = {dimension} | {w["column"] for w in where}
    children = candidate_dimensions(df, exclude)
    default_focus = allowed_focus[:1] if not entry.get("chain") else allowed_focus
    fallback = _default_proposal(df, dimension, where, default_focus, children)
    if not children or not allowed_focus:
        return fallback

    avoid_keys = {(a["child_dimension"], tuple(a["focus_values"])) for a in (avoid or [])}

    scope = dd._apply(df, where) if where else df
    facts = []
    for child in children[:10]:
        facts.append({"dimension": child, "distinct_values": int(as_labels(scope[child]).nunique())})
    focus_facts = dd.focus_options(scope, dimension, children[0], limit=15)
    focus_facts = [f for f in focus_facts if f["value"] in allowed_focus] or [{"value": v} for v in allowed_focus[:15]]
    user = json.dumps({
        "analysis": entry.get("name"),
        "current_dimension": dimension,
        "already_filtered_to": [f'{w["column"]} {w["op"]} {w["value"]}' for w in where],
        "focus_values": focus_facts,
        "candidate_dimensions": facts,
        "in_spec_available": dd.find_in_spec_column(df) is not None,
        "chart_sample": result_table[:10],
        "interpretation": interpretation or "",
        "ideas_to_avoid_repeating": [a.get("reason") or a.get("child_dimension") for a in (avoid or [])],
    }, default=str)
    try:
        raw = analysis_agent.call_llm(
            _SYSTEM, user, json_mode=True, temperature=0.4, call_name="drilldown_agent", model=DRILLDOWN_AGENT_MODEL,
        )
        payload = json.loads(analysis_agent.strip_json_fence(raw))
        items = payload.get("proposals", []) if isinstance(payload, dict) else []
    except Exception as exc:
        logger.info("drilldown proposal failed, using the default: %s", exc)
        return fallback

    proposals: list[dict] = []
    seen: set[tuple] = set(avoid_keys)
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        ok = _validated(item, df, children, allowed_focus)
        key = (ok["child_dimension"], tuple(ok["focus_values"])) if ok else None
        if ok and key not in seen:
            seen.add(key)
            proposals.append(ok)
        if len(proposals) == MAX_PROPOSALS:
            break
    return proposals or (fallback if not avoid else [])
