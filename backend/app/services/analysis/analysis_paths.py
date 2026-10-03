"""Drill-down PATHS: a complete, step-by-step drill-down for one analysis.

  Product chart -> best product -> all its origins -> top 3 origins -> their
  carriers -> top 2 carriers -> the full path (Country > Origin > Carrier)

One model call designs the path. It is given the analysis, its result, and the
SEMANTIC MODEL of the data (analysis_semantics.py: what every column means, how
columns roll up, which measures and aggregations make sense, typical drill
patterns, known data issues, plus the feature columns created in this session).
It returns only a small JSON plan: which columns, which measure, and which values
to carry forward ("top 3 of the previous chart"). It never writes code, charts or
numbers. Every choice is checked against the real columns before use, and a
rule-based path is the fallback when the model is unavailable. The picked values
are computed from the previous chart's actual result by the executor
(routers/analysis_paths.py), which then sends every chart through the normal
pipeline: template validation, chart recommendation and interpretation.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import pandas as pd

from app.config import DRILLDOWN_AGENT_MODEL, model_for
from app.services.analysis import analysis_agent, analysis_drilldown as dd, analysis_semantics
from app.services.analysis.analysis_columns import as_labels
from app.services.common import doc_store

logger = logging.getLogger(__name__)

MAX_PICK = 6
MAX_STEP_COLUMNS = 3
# The most charts one path may create in total (splitting multiplies them), so it stays quick to run and read.
MAX_PATH_CHARTS = 12
AGGS = ("mean", "sum", "median", "max", "min")

_SYSTEM = (
    "You design a complete DRILL-DOWN PATH for one analysis in a cold-chain shipment analytics tool. "
    "You are given the analysis (what it groups by, and its result) and a SEMANTIC MODEL of the data: what every "
    "column means, the columns you may group by (groupable_columns), the measures you may use (measures, each with "
    "the aggregations that make sense for it), how columns roll up (hierarchies), typical drill_patterns, "
    "measure_guidance and known data_issues. Engineered feature columns are marked engineered_feature.\n\n"
    "Design 2 or 3 further steps that walk from the broad result down to the specific, the way an analyst would, e.g.:\n"
    "  Product chart -> best product -> all its Origins -> top 3 Origins -> their Carriers -> top 2 Carriers -> the full "
    "path (Country of Origin, Origin, Carrier).\n\n"
    "Each step has:\n"
    '- "columns": 1 to 3 columns to break the focus down by (the X axis). Use ONLY columns from groupable_columns.\n'
    '- "pick": which values of the PREVIOUS chart\'s first column to carry into this step: {"mode": "top" or "bottom", '
    '"n": 1 to 6, "by": the previous chart\'s measure column label, or null for its first measure}. The first step picks '
    "from the analysis's own chart (e.g. the best product = top 1).\n"
    '- "split": true = a SEPARATE chart for each picked value (e.g. one carrier chart for each of the top 3 origins); '
    "false = one combined chart. Each branch then continues on its own, so the next step picks its own top values inside "
    "each chart. Use true when you pick 2 to 4 values that each deserve their own view.\n"
    '- "measure": what each bar shows: "count" (trips), "pct_in_spec" (only if in_spec_available), or an aggregation '
    '("mean", "sum", "median", "max" or "min") of one measure column, set in "measure_column". The aggregation MUST be '
    "one of that measure's allowed_aggs.\n"
    '- "title": a short plain-English name for the step. "reason": one sentence on why this is the next best question.\n\n'
    "Rules:\n"
    "- Go from broad to specific. Follow the hierarchies (a parent such as Country of Origin comes before its child Origin, "
    "never the other way round) and prefer a drill_pattern that fits the analysis.\n"
    "- Choose the measure that answers the question, from ALL the measures, including the engineered features: for quality "
    "questions use % in spec, hours out of spec, alarm or excursion flags and temperature statistics; for journey questions "
    "use the duration measures; use plain counts only for volume. Vary the measure across steps when it helps.\n"
    "- Respect data_issues. Never group by a column that is not in groupable_columns.\n"
    "- Do not repeat a column in an earlier step. ONLY the FINAL step may show the whole path by combining the columns "
    "used before it (e.g. Country of Origin, Origin, Carrier): the 'path view' for the values picked so far.\n"
    "- Keep it readable: prefer columns with few distinct values for later steps.\n"
    "- Total charts = the charts of every step added up, and splitting a step that picks 3 values triples every step after it. "
    "Keep the whole path to at most {max_charts} charts.\n"
    "- At most {max_steps} steps. Do not return a path whose columns are in avoid_paths.\n\n"
    'Return ONLY JSON: {"name": "short path name", "rationale": "one or two sentences on why this path", "steps": '
    '[{"title": "...", "columns": ["..."], "pick": {"mode": "top", "n": 3, "by": null}, "measure": "count", '
    '"split": false, "measure_column": null, "reason": "..."}]}'
)


# --- storage -----------------------------------------------------------------------------------------


PATHS_DOC = "PATHS"


def load(session_id: str) -> list[dict]:
    try:
        data = doc_store.get(session_id, PATHS_DOC)
        return data.get("paths", []) if isinstance(data, dict) else []
    except Exception:
        return []


def save(session_id: str, paths: list[dict]) -> None:
    doc_store.put(session_id, PATHS_DOC, {"session_id": session_id, "paths": paths})


def get(session_id: str, path_id: str) -> dict | None:
    return next((p for p in load(session_id) if p["path_id"] == path_id), None)


def upsert(session_id: str, path: dict) -> None:
    def _merge(data):
        paths = [p for p in ((data or {}).get("paths") or []) if p["path_id"] != path["path_id"]]
        paths.append(path)
        return {"session_id": session_id, "paths": paths}

    doc_store.update(session_id, PATHS_DOC, _merge, default={})


def new_path_id() -> str:
    return f"path_{uuid.uuid4().hex[:8]}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- planning -------------------------------------------------------------------------------------------


def _clean_measure(st: dict, aggs: dict[str, list[str]], have_spec: bool) -> tuple[str, str | None]:
    """The step's measure, made valid: an aggregation must be one the column allows."""
    measure = st.get("measure") if isinstance(st.get("measure"), str) else "count"
    column = st.get("measure_column") if st.get("measure_column") in aggs else None
    if measure == "pct_in_spec":
        return ("pct_in_spec", None) if have_spec else ("count", None)
    if measure in AGGS:
        if not column:
            return "count", None
        return (measure if measure in aggs[column] else aggs[column][0]), column
    return "count", None


def _clean_steps(raw, usable: list[str], aggs: dict[str, list[str]], have_spec: bool, used: set[str], max_steps: int) -> list[dict]:
    """Keeps only steps that make sense on the real data; stops at the first that does not."""
    raw = raw if isinstance(raw, list) else []
    steps: list[dict] = []
    branches, charts = 1, 0  # how many charts the previous step made, and the running total
    for i, st in enumerate(raw):
        if len(steps) == max_steps or not isinstance(st, dict):
            break
        is_last = i == len(raw) - 1
        columns = [c for c in dict.fromkeys(st.get("columns") or []) if c in usable][:MAX_STEP_COLUMNS + 1]
        if not (is_last and steps):
            # An early step must open up NEW columns; only the final path view may repeat earlier ones.
            columns = [c for c in columns if c not in used][:MAX_STEP_COLUMNS]
        if not columns:
            break
        measure, column = _clean_measure(st, aggs, have_spec)
        pick = st.get("pick") if isinstance(st.get("pick"), dict) else {}
        try:
            n = max(1, min(int(pick.get("n", 3)), MAX_PICK))
        except (TypeError, ValueError):
            n = 3
        split = bool(st.get("split")) and n > 1
        made = branches * (n if split else 1)
        if charts + made > MAX_PATH_CHARTS and split:
            split, made = False, branches  # too many charts: keep this step combined
        if charts + made > MAX_PATH_CHARTS:
            break
        steps.append({
            "title": str(st.get("title") or "").strip() or " × ".join(columns),
            "reason": str(st.get("reason") or "").strip(),
            "columns": columns,
            "measure": measure,
            "measure_column": column,
            "split": split,
            "pick": {"mode": "bottom" if pick.get("mode") == "bottom" else "top", "n": n, "by": pick.get("by") or None},
        })
        branches, charts = made, charts + made
        used |= set(columns)
    return steps


def fallback_plan(root_dim: str, usable: list[str], distinct: dict[str, int], have_spec: bool, max_steps: int) -> dict:
    """A path from the data alone when the model is unavailable: the classic
    Product > Origin > Carrier order where those columns exist, otherwise the
    columns with the fewest values; the last step shows the whole path."""
    order = [c for c in dd.HIERARCHY if c in usable] + sorted(
        (c for c in usable if c not in dd.HIERARCHY), key=lambda c: distinct.get(c, 999)
    )
    order = [c for c in order if c != root_dim]
    measure = "pct_in_spec" if have_spec else "count"
    steps: list[dict] = []
    if order:
        steps.append({"title": f"All {order[0]} for the best {root_dim}", "reason": f"Which {order[0]} values make up the leading {root_dim}.",
                      "columns": [order[0]], "measure": "count", "measure_column": None, "split": False, "pick": {"mode": "top", "n": 1, "by": None}})
    if len(order) > 1:
        steps.append({"title": f"{order[1]} within the top {order[0]} values", "reason": f"Which {order[1]} values serve the biggest {order[0]} values.",
                      "columns": [order[1]], "measure": measure, "measure_column": None, "split": True, "pick": {"mode": "top", "n": 3, "by": None}})
    if len(order) > 1 and max_steps >= 3:
        steps.append({"title": "The full path for the leading values", "reason": "The leading values side by side along the whole path.",
                      "columns": [order[0], order[1]], "measure": measure, "measure_column": None, "split": False, "pick": {"mode": "top", "n": 2, "by": None}})
    return {
        "name": " → ".join([root_dim] + [s["columns"][0] for s in steps[:2]]),
        "rationale": "Built from the columns of your data (no model suggestion available).",
        "steps": steps[:max_steps], "source": "default",
    }


def plan(
    *, df: pd.DataFrame, entry: dict, root_dim: str, where: list[dict], result_table: list[dict], interpretation: str | None,
    usable: list[str], features: list[dict], numeric: list[str], max_steps: int, avoid: list[list[str]] | None = None,
) -> dict:
    """The planned path: {name, rationale, steps[], source}. Never raises.
    `usable` are the columns that may be grouped by; `numeric` the measure columns;
    `features` the created feature columns ({output_column, name, definition})."""
    have_spec = dd.find_in_spec_column(df) is not None
    used0 = {root_dim} | {w["column"] for w in where}
    usable = [c for c in dict.fromkeys(usable) if c in df.columns and c not in used0]
    if not usable or max_steps < 1:
        return {"name": "", "rationale": "", "steps": [], "source": "default"}

    model = analysis_semantics.for_planner(df, usable, numeric, features)
    # The semantic model decides what may be grouped by: documented identifiers, settings,
    # constant, empty and unusable columns are out, whatever the generic eligibility rule said.
    usable = [g["column"] for g in model["groupable_columns"]]
    if not usable:
        return {"name": "", "rationale": "", "steps": [], "source": "default"}
    aggs = analysis_semantics.allowed_aggs(model)
    user = json.dumps({
        "analysis": entry.get("name"),
        "grouped_by": root_dim,
        "already_filtered_to": [f'{w["column"]} {w["op"]} {w["value"]}' for w in where],
        "result_sample": result_table[:12],
        "interpretation": interpretation or "",
        "in_spec_available": have_spec,
        "semantic_model": model,
        "max_steps": max_steps,
        "avoid_paths": avoid or [],
    }, default=str)
    try:
        raw = analysis_agent.call_llm(
            _SYSTEM.replace("{max_steps}", str(max_steps)).replace("{max_charts}", str(MAX_PATH_CHARTS)), user,
            json_mode=True, temperature=0.3, call_name="drilldown_path", model=model_for("drilldown_path", DRILLDOWN_AGENT_MODEL), max_tokens=4000,
        )
        payload = json.loads(analysis_agent.strip_json_fence(raw))
        steps = _clean_steps(payload.get("steps"), usable, aggs, have_spec, set(used0), max_steps)
        if len(steps) >= 2 or (len(steps) == 1 and max_steps == 1):
            return {
                "name": str(payload.get("name") or "").strip() or " → ".join([root_dim] + [s["columns"][0] for s in steps]),
                "rationale": str(payload.get("rationale") or "").strip(), "steps": steps, "source": "ai",
            }
        logger.info("drilldown path from the model was unusable (%d valid steps)", len(steps))
    except Exception as exc:
        logger.info("drilldown path planning failed, using the data's own columns: %s", exc)
    distinct = {c: int(as_labels(df[c]).nunique()) for c in usable}
    return fallback_plan(root_dim, usable, distinct, have_spec, max_steps)
