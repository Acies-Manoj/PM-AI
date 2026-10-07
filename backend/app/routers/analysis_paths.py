"""Drill-down PATHS endpoints: suggest a complete step-by-step drill-down for an
analysis, run it, and let the PM accept or reject it.

A suggested path's levels are ordinary chain levels (see routers/analysis.py), so
charts, insights, filters and slide numbering behave exactly as for a drill-down
the PM builds by hand -- but they are created PENDING: hidden from the Selected
Drill-downs tab and the report until the path is accepted, and discarded if it is
rejected.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from app.routers import analysis as analysis_router
from app.schemas import DrilldownPath, DrilldownPathAccept, DrilldownPathEntry, DrilldownPathStep
from app.services.analysis import (
    analysis_agent,
    analysis_dependencies,
    analysis_designer,
    analysis_drilldown,
    analysis_drilldown_agent,
    analysis_paths,
    analysis_repository,
    analysis_templates,
)
from app.services.audit.audit_store import AuditSession

router = APIRouter(prefix="/api/analysis", tags=["analysis-paths"])
logger = logging.getLogger(__name__)


def _recommend_chart(session: AuditSession, entry: dict) -> dict | None:
    """Validates the level against the data, then asks the existing chart-recommendation
    call which chart suits it, keeping the answer only if the template can draw it.
    None means "keep the default chart" (the call failed or the level does not compute)."""
    try:
        template = entry["template"]
        spec = analysis_templates.validate(template, session.df)
        output = analysis_templates.execute(template, session.df)
        if output.frame.empty:
            return None
        logic = analysis_agent.plan_text({"steps": analysis_templates.explain_steps(spec)})
        chart = analysis_designer.suggest_chart_and_filters(
            entry["name"], entry.get("description") or entry["name"], {"plan": logic},
            analysis_agent.describe_columns(session.df), session.df,
        )["chart"]
        return analysis_designer.reconcile_chart(chart, output.allowed_charts, output.default_chart, [])
    except Exception as exc:
        logger.info("chart recommendation skipped for %s: %s", entry.get("id"), exc)
        return None


def _measure_label(step: dict) -> str:
    if step["measure"] == "pct_in_spec":
        return "% in spec"
    if step["measure"] in analysis_drilldown.AGG_LABELS and step.get("measure_column"):
        return analysis_drilldown.agg_label(step["measure"], step["measure_column"])
    return "Trips"


def _pick_values(table: list[dict], label_col: str, pick: dict) -> tuple[list[str], str]:
    """The values to carry into the next step, from the previous chart's real
    numbers: top/bottom n of its measure. Returns (values, the measure's label)."""
    if not table or label_col not in table[0]:
        return [], ""
    numeric = [
        c for c in table[0]
        if c != label_col and any(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool) for r in table)
    ]
    by = pick.get("by") if pick.get("by") in numeric else (numeric[0] if numeric else None)
    rows = [r for r in table if r.get(label_col) is not None]
    if by:
        rows = [r for r in rows if isinstance(r.get(by), (int, float))]
        rows.sort(key=lambda r: (r[by], str(r[label_col])), reverse=pick.get("mode", "top") == "top")
    seen: list[str] = []
    for r in rows:
        v = str(r[label_col])
        if v not in seen:
            seen.append(v)
        if len(seen) == pick.get("n", 3):
            break
    return seen, by or ""


def _pick_text(dimension: str, pick: dict, by: str, values: list[str]) -> str:
    n = len(values)
    if n == 1 and pick.get("mode", "top") == "top":
        head = f"Best {dimension}"
    else:
        head = f"{'Top' if pick.get('mode', 'top') == 'top' else 'Bottom'} {n} {dimension}"
    return f"{head}{' by ' + by if by else ''}: {', '.join(values)}"


def _normalise(path: dict) -> dict:
    """Paths saved by an earlier version had one chart per step."""
    steps = []
    for st in path["steps"]:
        if "entries" not in st:
            st = {**st, "split": False, "entries": [{
                "entry_id": st["entry_id"], "path": "", "pick_text": st.get("pick_text", ""),
                "picked_values": st.get("picked_values", []), "created": st.get("created", True),
            }]}
        steps.append(st)
    return {**path, "steps": steps}


def _response(session: AuditSession, session_id: str, path: dict) -> DrilldownPath:
    path = _normalise(path)
    steps = []
    ready = True
    for st in path["steps"]:
        entries = []
        for e in st["entries"]:
            definition = analysis_repository.get_entry(session_id, e["entry_id"])
            result = session.analysis_results.get(e["entry_id"])
            if definition is None or result is None or result.run_status != "done":
                ready = False
            entries.append(DrilldownPathEntry(**{**e, "entry": analysis_router._merge_entry(session, definition) if definition else None}))
        steps.append(DrilldownPathStep(**{k: v for k, v in st.items() if k not in ("entries", "entry_id", "pick_text", "picked_values", "created")}, entries=entries))
    return DrilldownPath(**{**path, "steps": steps, "ready": ready})


@router.get("/repository/{session_id}/entries/{entry_id}/paths", response_model=list[DrilldownPath])
def list_paths(session_id: str, entry_id: str) -> list[DrilldownPath]:
    """The suggested paths for one analysis (pending and accepted; rejected ones are gone)."""
    session = analysis_router._get_session_or_404(session_id)
    return [
        _response(session, session_id, p)
        for p in analysis_paths.load(session_id)
        if p["root_id"] == entry_id and p["status"] != "rejected"
    ]


@router.post("/repository/{session_id}/entries/{entry_id}/paths/suggest", response_model=DrilldownPath)
def suggest_path(session_id: str, entry_id: str) -> DrilldownPath:
    """Designs a complete drill-down path for this analysis, runs every step and
    returns it pending. Asking again returns a different path."""
    session = analysis_router._get_session_or_404(session_id)
    root = analysis_repository.get_entry(session_id, entry_id)
    result = session.analysis_results.get(entry_id)
    if root is None or result is None or result.run_status != "done":
        raise HTTPException(status_code=409, detail="Run this analysis before suggesting a drill-down path.")
    level = analysis_router._level_of(root)
    max_steps = analysis_drilldown.MAX_CHAIN_LEVEL - level
    if max_steps < 1:
        raise HTTPException(status_code=422, detail=f"Drill-downs stop at level {analysis_drilldown.MAX_CHAIN_LEVEL}.")
    dimension, where = analysis_router._parent_scope(session, root)
    if dimension is None:
        raise HTTPException(status_code=422, detail="This analysis isn't grouped by a single column, so there is nothing to drill into.")

    features = analysis_dependencies.available_features(session_id, session.df)
    usable = analysis_drilldown_agent.candidate_dimensions(
        session.df, analysis_router._pinned(root, dimension, where), [f["output_column"] for f in features],
    )
    previous = [p for p in analysis_paths.load(session_id) if p["root_id"] == entry_id]
    plan = analysis_paths.plan(
        df=session.df, entry=root, root_dim=dimension, where=where, result_table=result.result_table or [],
        interpretation=result.interpretation, usable=usable, features=features,
        numeric=analysis_drilldown.numeric_columns(session.df), max_steps=max_steps,
        avoid=[[c for s in p["steps"] for c in s["columns"]] for p in previous],
    )
    if not plan["steps"]:
        raise HTTPException(status_code=422, detail="Couldn't design a drill-down path from this analysis.")

    # A branch is one chart so far: the level it is, what it grouped by, the filter it carries,
    # its result, and the values followed to reach it. A step that splits turns each branch into
    # one branch per picked value; otherwise each branch just continues.
    # A branch is one chart so far: the level it is, what it grouped by, the filter it carries,
    # its result, and the values followed to reach it. A step that splits turns each branch into
    # one branch per picked value; otherwise each branch just continues.
    branches = [{"parent": root, "dim": dimension, "where": list(where), "result": result, "path": []}]
    path_steps: list[dict] = []
    total = 0
    for spec in plan["steps"]:
        step_level = analysis_router._level_of(branches[0]["parent"]) + 1
        if step_level > analysis_drilldown.MAX_CHAIN_LEVEL:
            break

        # 1. Build this step's levels (sequential: they share one repository file).
        items: list[dict] = []
        for br in branches:
            table = br["result"].result_table or []
            label_col = br["dim"] if table and br["dim"] in table[0] else (br["result"].result_columns or [br["dim"]])[0]
            values, by = _pick_values(table, label_col, spec["pick"])
            if not values:
                continue
            pick_text = _pick_text(br["dim"], spec["pick"], by, values)
            for focus in ([[v] for v in values] if spec.get("split") else [values]):
                if total + len(items) >= analysis_paths.MAX_PATH_CHARTS:
                    break
                try:
                    entry, is_new = analysis_router._create_level(
                        session=session, session_id=session_id, parent=br["parent"], dimension=br["dim"], where=br["where"],
                        children=spec["columns"], metric=spec["measure"], metric_column=spec["measure_column"],
                        rank={"mode": "all", "n": 5, "by": "count"}, level=step_level, values=focus,
                        split=bool(spec.get("split")), status="pending",
                    )
                except HTTPException as exc:
                    logger.info("path step could not be built: %s", exc.detail)
                    continue
                items.append({"br": br, "focus": focus, "entry": entry, "is_new": is_new, "pick_text": pick_text})

        # 2. Chart recommendation (the existing AI call) for every new level, in parallel; the
        #    answers are saved one by one afterwards.
        fresh = [it for it in items if it["is_new"] or it["entry"]["id"] not in session.analysis_results]
        if fresh:
            with ThreadPoolExecutor(max_workers=4) as pool:
                charts = list(pool.map(lambda it: _recommend_chart(session, it["entry"]), fresh))
            for it, chart in zip(fresh, charts):
                if chart:
                    it["entry"] = analysis_repository.update_entry(session_id, it["entry"]["id"], {"chart_recommendation": chart}) or it["entry"]

            # 3. Run each level (its template, then the existing interpretation call), in parallel.
            with ThreadPoolExecutor(max_workers=3) as pool:
                list(pool.map(lambda it: analysis_router._run_entry(session, session_id, it["entry"]), fresh))

        # 4. Keep the levels that computed; the rest are dropped.
        entries: list[dict] = []
        made: list[dict] = []
        for it in items:
            res = session.analysis_results.get(it["entry"]["id"])
            if res is None or res.run_status != "done" or not res.result_table:
                if it["is_new"]:
                    analysis_repository.update_entry(session_id, it["entry"]["id"], {"status": "rejected"})
                continue
            total += 1
            trail = it["br"]["path"] + [", ".join(it["focus"])]
            entries.append({
                "entry_id": it["entry"]["id"], "path": " › ".join(trail), "pick_text": it["pick_text"],
                "picked_values": it["focus"], "created": it["is_new"],
            })
            made.append({"parent": it["entry"], "dim": spec["columns"][0], "where": it["entry"]["chain"]["where"], "result": res, "path": trail})
        if not made:
            break
        path_steps.append({
            "level": step_level, "title": spec["title"], "reason": spec["reason"], "columns": spec["columns"],
            "measure_label": _measure_label(spec), "split": bool(spec.get("split")), "entries": entries,
        })
        branches = made

    if not path_steps:
        raise HTTPException(status_code=422, detail="None of the drill-down steps could be run on this data.")
    path = {
        "path_id": analysis_paths.new_path_id(), "root_id": entry_id, "name": plan["name"], "rationale": plan["rationale"],
        "source": plan["source"], "status": "pending", "created_at": analysis_paths.now(), "steps": path_steps,
    }
    analysis_paths.upsert(session_id, path)
    return _response(session, session_id, path)


def _set_levels(session_id: str, path: dict, status: str) -> None:
    for st in _normalise(path)["steps"]:
        for e in st["entries"]:
            if e.get("created"):
                analysis_repository.update_entry(session_id, e["entry_id"], {"status": status})


@router.post("/repository/{session_id}/paths/{path_id}/accept", response_model=DrilldownPath)
def accept_path(session_id: str, path_id: str, body: DrilldownPathAccept | None = None) -> DrilldownPath:
    """Accept the levels the PM kept as real drill-downs (listed under Selected Drill-downs, numbered in the
    report). Levels deeper than the deepest kept one are discarded. A level skipped in the middle stays
    calculated, because the next level is built from its results, but is marked so the report leaves it out."""
    session = analysis_router._get_session_or_404(session_id)
    path = analysis_paths.get(session_id, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="That drill-down path doesn't exist.")
    if path["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"This path was already {path['status']}.")

    path = _normalise(path)
    all_levels = [st["level"] for st in path["steps"]]
    keep = set(body.levels) & set(all_levels) if body and body.levels is not None else set(all_levels)
    if not keep:
        raise HTTPException(status_code=422, detail="Keep at least one level of the path.")
    deepest = max(keep)

    # Levels below the deepest kept one are discarded; the path then ends where the PM chose to stop.
    for st in path["steps"]:
        if st["level"] > deepest:
            for e in st["entries"]:
                if e.get("created"):
                    analysis_repository.update_entry(session_id, e["entry_id"], {"status": "rejected"})
    path["steps"] = [st for st in path["steps"] if st["level"] <= deepest]
    path["skipped_levels"] = sorted(lvl for lvl in all_levels if lvl <= deepest and lvl not in keep)

    _set_levels(session_id, path, "approved")
    path["status"] = "accepted"
    analysis_paths.upsert(session_id, path)
    return _response(session, session_id, path)


@router.post("/repository/{session_id}/paths/{path_id}/reject", response_model=DrilldownPath)
def reject_path(session_id: str, path_id: str) -> DrilldownPath:
    """Reject: the path's levels are discarded."""
    session = analysis_router._get_session_or_404(session_id)
    path = analysis_paths.get(session_id, path_id)
    if path is None:
        raise HTTPException(status_code=404, detail="That drill-down path doesn't exist.")
    if path["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"This path was already {path['status']}.")
    _set_levels(session_id, path, "rejected")
    path["status"] = "rejected"
    analysis_paths.upsert(session_id, path)
    return _response(session, session_id, path)
