"""The PM's final selections for a session, saved on the session header (`session.selections`).

Predefined and planner feature/analysis entries are re-derived on every read from the KPI
profile and the planner output, so nothing in storage says "this is the set the PM actually
ended up with". `refresh` snapshots it: planner decisions, the features and analyses that are
selected / rejected (with their formula), what the audit decisions were, how the computed
features and analyses came out (validation note, error, whether code or a template was used,
how many drill-down suggestions exist), and how the outlier review went.

Call `refresh(session_id, user_id, trigger)` after any change that alters the selection (it
reads the persisted state, so call it AFTER the store/doc write). It never raises: a snapshot
failure must not fail the request that triggered it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.common import doc_store

log = logging.getLogger(__name__)

_MAX_HISTORY = 100


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entry_view(e: dict, kind: str) -> dict[str, Any]:
    view = {
        "id": e.get("id"), "name": e.get("name"), "source": e.get("source"), "status": e.get("status"),
        "description": e.get("description"), "formula": e.get("formula"),
        "input_columns": e.get("input_columns") or [],
    }
    if kind == "feature":
        view["output_column"] = e.get("output_column")
        view["calculation_intent"] = e.get("calculation_intent")
    else:
        view["parent_id"] = e.get("parent_id")
        view["has_template"] = bool(e.get("template"))
        view["chart_type"] = (e.get("chart_recommendation") or {}).get("chart_type")
        view["required_features"] = [r.get("name") for r in e.get("required_features") or []]
        if e.get("chain"):
            view["chain"] = e.get("chain")
    return view


def build(session_id: str, user_id: str, session: Any | None = None) -> dict[str, Any]:
    from app.services.analysis import analysis_repository
    from app.services.audit.audit_store import store
    from app.services.features import feature_repository

    session = session or store.get(session_id)

    planner = doc_store.get(session_id, "PLANNER_OUTPUT") or {}
    planner_decisions = [
        {"index": i, "name": r.get("name"), "type": r.get("type"),
         "pm_decision": r.get("pm_decision", "pending"), "pm_notes": r.get("pm_notes", "")}
        for i, r in enumerate(planner.get("recommendations", []))
    ]

    features = feature_repository.get_repository(session_id)
    analyses = analysis_repository.get_repository(session_id)

    snapshot: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "updated_at": _now(),
        "planner_decisions": planner_decisions,
        "features": {
            "selected": [_entry_view(e, "feature") for e in features if e.get("status") == "approved"],
            "rejected": [_entry_view(e, "feature") for e in features if e.get("status") == "rejected"],
            "pending": [e.get("name") for e in features if e.get("status") == "pending"],
        },
        "analyses": {
            "selected": [_entry_view(e, "analysis") for e in analyses if e.get("status") == "approved"],
            "rejected": [_entry_view(e, "analysis") for e in analyses if e.get("status") == "rejected"],
            "pending": [e.get("name") for e in analyses if e.get("status") == "pending"],
        },
    }

    if session is not None:
        snapshot["audit_decisions"] = [
            {"issue_id": i.id, "status": i.status, "resolution": i.resolution}
            for i in session.issues if i.status == "resolved"
        ]
        snapshot["feature_results"] = [
            {"id": f.id, "output_column": f.output_column, "validation_note": f.validation_note,
             "has_code": bool(f.generated_code), "has_plan": bool(f.plan)}
            for f in session.features
        ]
        snapshot["feature_skipped"] = list(session.feature_skipped_notes)
        snapshot["analysis_results"] = [
            {"id": r.id, "run_status": r.run_status, "computation_mode": r.computation_mode, "chart_type": r.chart_type,
             "has_code": bool(r.generated_code), "has_template": bool(r.template), "error": r.error,
             "drilldown_suggestions": len(r.drilldown_suggestions),
             "guided_proposals": len(r.guided_proposals)}
            for r in session.analysis_results.values()
        ]

    outlier = doc_store.get(session_id, "OUTLIER_AUDIT") or []
    snapshot["outlier_review"] = {
        "edits": sum(1 for e in outlier if e.get("action") == "edit"),
        "reviews": [{"tab": e.get("tab"), "decision": e.get("decision"), "ts": e.get("ts")}
                    for e in outlier if e.get("action") == "review"],
    }
    return snapshot


def refresh(session_id: str, user_id: str, trigger: str = "", session: Any | None = None) -> None:
    """Rebuild the snapshot and save it on the session header (the Sessions table item)."""
    try:
        from app.services.audit.audit_store import store

        session = session or store.get(session_id)
        if session is None:
            return
        snapshot = build(session_id, user_id, session)
        history = list((session.selections or {}).get("history", []))
        history.append({
            "ts": snapshot["updated_at"], "trigger": trigger,
            "features_selected": len(snapshot["features"]["selected"]),
            "analyses_selected": len(snapshot["analyses"]["selected"]),
        })
        snapshot["history"] = history[-_MAX_HISTORY:]
        session.selections = snapshot
        store.save(session)
    except Exception as exc:  # noqa: BLE001 - a snapshot failure must not fail the request
        log.warning("selections snapshot failed for %s (%s): %s", session_id, trigger, exc)


def get(session_id: str) -> dict | None:
    from app.services.audit.audit_store import store

    session = store.get(session_id)
    return (session.selections or None) if session else None
