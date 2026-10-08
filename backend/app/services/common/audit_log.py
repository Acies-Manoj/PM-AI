"""Append-only log of what happened in a session: uploads, audit decisions, edits, feature and
analysis changes, report downloads and every LLM call (with its token usage).

One item per event in the DDB_AUDIT table (partition `session_id`, sort `ts_event` =
"<ISO time>#<uuid>"). Every event says WHAT happened (`event_type`), in WHICH area and wizard
step (`category`, `step`), and to WHICH record (`target`, written exactly as that record's
`pmai-docs` sort key, e.g. "FEATURE#coo"). Indexes: `by-user` (`user_id`, `ts_event`) for
"everything this user did", and `by-target` (`target_key`, `ts_event`) for "the history of one
record". Local mode: one JSON line per event in data/audit_log.jsonl.

Callers pass only (session, user, event_type, payload). The category, step, target and summary
come from EVENT_CATALOG below, so every event is classified the same way and existing call sites
need no changes. A caller may still pass `target=` or `result=` to override.

Logging must never break a request, so every failure is swallowed (and printed).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, NamedTuple

from app.config import AUDIT_LOG_TTL_DAYS, DATA_DIR, DDB_AUDIT
from app.services.common.doc_store import dumps

log = logging.getLogger(__name__)

LOCAL_LOG_PATH = DATA_DIR / "audit_log.jsonl"
_lock = threading.Lock()

# Session id used for events that belong to no session (e.g. LLM calls made outside a request).
GLOBAL_SESSION = "_global"

# --------------------------------------------------------------------------------------------
# The wizard's steps (frontend/src/components/StepIndicator.tsx). 0 = not tied to one step.
# --------------------------------------------------------------------------------------------
STEPS: dict[int, str] = {0: "General", 1: "Upload", 2: "Planner", 3: "Audit", 4: "Features", 5: "Analysis", 6: "Report"}


class EventSpec(NamedTuple):
    category: str          # session | planner | audit | outlier | feature | analysis | report | ai
    step: int              # wizard step 1-6 (0 = general)
    target: str | None     # template over the payload, e.g. "FEATURE#{entry_id}"; None = no record
    summary: str | None    # template over the payload; None = the event name


EVENT_CATALOG: dict[str, EventSpec] = {
    # -- step 1: Upload ----------------------------------------------------------------------
    "upload": EventSpec("session", 1, "SESSIONS", "Uploaded {filename} ({rows} rows)"),
    "brief_finalize": EventSpec("session", 1, "BRIEF", "Saved the client brief"),
    # -- step 2: Planner ---------------------------------------------------------------------
    "planner_suggest": EventSpec("planner", 2, None, "Planner proposed recommendations"),
    "planner_save": EventSpec("planner", 2, None, "Saved planner decisions"),
    # -- step 3: Audit -----------------------------------------------------------------------
    "audit_run": EventSpec("audit", 3, "SESSIONS", "Audit found {issues} issues"),
    "decision": EventSpec("audit", 3, "ISSUE#{issue_id}", "Resolved audit issue {issue_id}"),
    "revert": EventSpec("audit", 3, "ISSUE#{issue_id}", "Reverted audit issue {issue_id}"),
    "download": EventSpec("audit", 3, "SESSIONS", "Downloaded {kind}"),
    "edit": EventSpec("outlier", 3, "OUTLIER", "Edited {field} of trip {trip_id}"),
    "outlier_detected": EventSpec("outlier", 3, "OUTLIER", "Outliers flagged"),
    "outlier_edit": EventSpec("outlier", 3, "OUTLIER", "Corrected {field} of trip {trip_id}"),
    "outlier_review": EventSpec("outlier", 3, "OUTLIER", "Reviewed the {tab} outliers"),
    # -- step 4: Features --------------------------------------------------------------------
    "feature_suggested": EventSpec("feature", 4, None, "AI suggested {count} features"),
    "feature_draft": EventSpec("feature", 4, None, "Drafted feature {name}"),
    "feature_custom_added": EventSpec("feature", 4, "FEATURE#{entry_id}", "Added feature {name}"),
    "feature_accepted": EventSpec("feature", 4, "FEATURE#{entry_id}", "Approved feature {name}"),
    "feature_rejected": EventSpec("feature", 4, "FEATURE#{entry_id}", "Rejected feature {name}"),
    "apply_features": EventSpec("feature", 4, None, "Computed {cols} columns"),
    # -- step 5: Analysis --------------------------------------------------------------------
    "analysis_suggested": EventSpec("analysis", 5, None, "AI suggested {count} analyses"),
    "analysis_custom_added": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Added analysis {name}"),
    "analysis_accepted": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Approved analysis {name}"),
    "analysis_rejected": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Rejected analysis {name}"),
    "analysis_run": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Ran analysis {name}"),
    "drilldown_suggested": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Suggested drill-downs for {name}"),
    "drilldown_proposed": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Proposed guided drill-downs for {name}"),
    "drilldown_run": EventSpec("analysis", 5, "ANALYSIS#{entry_id}", "Ran a drill-down of {name}"),
    "drilldown_path_accepted": EventSpec("analysis", 5, "DRILL#{entry_id}#{path_id}", "Accepted drill-down path {path_id}"),
    "drilldown_path_rejected": EventSpec("analysis", 5, "DRILL#{entry_id}#{path_id}", "Rejected drill-down path {path_id}"),
    # -- step 6: Report ----------------------------------------------------------------------
    "report_downloaded": EventSpec("report", 6, "OVERALL", "Downloaded the report"),
}

# Code-generation events: step and target depend on whether a feature or an analysis was built.
_CODE_EVENTS = {"code_attempt", "code_run", "code_fallback"}

# The step an LLM call belongs to, by its call name.
CALL_STEPS: dict[str, int] = {
    "planner_agent": 2,
    "audit_agent": 3,
    "feature_agent_think": 4, "feature_agent_write_code": 4, "feature_agent_validate": 4, "feature_suggester": 4,
    "analysis_agent_think": 5, "analysis_agent_write_code": 5, "analysis_agent_chart_suggestion": 5,
    "analysis_agent_interpret": 5, "analysis_agent_drilldown": 5, "analysis_designer_template_match": 5,
    "analysis_designer_chart": 5, "analysis_suggester": 5, "drilldown_agent": 5, "drilldown_agent_more": 5,
    "drilldown_path": 5, "overall_analysis_agent": 5,
    "report_final_summary_agent": 6,
}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _fill(template: str | None, payload: dict[str, Any]) -> str | None:
    """Fill `{key}` placeholders from the payload; None if the template is empty or a key is missing."""
    if not template:
        return None
    missing = False

    def sub(match: re.Match) -> str:
        nonlocal missing
        value = payload.get(match.group(1))
        if value is None or value == "":
            missing = True
            return ""
        return str(value)

    text = _PLACEHOLDER.sub(sub, template)
    return None if missing else text


def classify(event_type: str, payload: dict[str, Any]) -> tuple[str, int, str | None, str]:
    """(category, step, target, summary) for one event."""
    if event_type == "llm_call":
        call = str(payload.get("call_name") or "")
        return "ai", CALL_STEPS.get(call, 0), payload.get("output_ref") or None, f"LLM call {call}".strip()
    if event_type in _CODE_EVENTS:
        kind = payload.get("kind")
        step = 4 if kind == "feature" else 5 if kind == "analysis" else 0
        prefix = "FEATURE" if kind == "feature" else "ANALYSIS" if kind == "analysis" else None
        entry_id = payload.get("entry_id")
        target = f"{prefix}#{entry_id}" if prefix and entry_id else None
        name = payload.get("entry_name") or entry_id or ""
        return "ai", step, target, f"{event_type.replace('_', ' ')} for {name}".strip()
    spec = EVENT_CATALOG.get(event_type)
    if spec is None:
        return "other", 0, None, event_type.replace("_", " ")
    summary = _fill(spec.summary, payload) or event_type.replace("_", " ")
    return spec.category, spec.step, _fill(spec.target, payload), summary


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _result_of(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "").lower()
    return "failed" if status == "failed" or payload.get("error") else "ok"


def log_event(
    session_id: str | None,
    user_id: str | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    target: str | None = None,
    result: str | None = None,
) -> None:
    """Record one event. Safe to call from any thread; never raises.

    `payload` holds the details. `target` overrides the record the event is about (default: from
    EVENT_CATALOG); `result` overrides "ok"/"failed" (default: "failed" if the payload says so)."""
    try:
        session = session_id or GLOBAL_SESSION
        user = user_id or "unknown"
        details = payload or {}
        category, step, cat_target, summary = classify(event_type, details)
        target = target or cat_target
        result = result or _result_of(details)
        event_id = uuid.uuid4().hex[:8]
        ts_event = f"{_now_iso()}#{event_id}"
        body = dumps(details)
        if len(body.encode("utf-8")) > 200_000:
            # DynamoDB items max out at 400 KB. Never cut the JSON text (that would leave
            # unparseable JSON and break reading the log back): keep a small valid preview.
            body = dumps({"truncated": True, "preview": body[:2000]})
        record: dict[str, Any] = {
            "session_id": session,
            "ts_event": ts_event,
            "event_id": event_id,
            "user_id": user,
            "event_type": event_type,
            "category": category,
            "step": step,
            "step_name": STEPS.get(step, ""),
            "result": result,
            "summary": summary[:300],
        }
        if target:
            record["target"] = target
            record["target_key"] = f"{session}#{target}"
        if DDB_AUDIT:
            import time

            from app.services.common import aws_clients

            item = {k: ({"N": str(v)} if k == "step" else {"S": str(v)}) for k, v in record.items()}
            item["payload"] = {"S": body}
            item["ttl"] = {"N": str(int(time.time()) + 86400 * AUDIT_LOG_TTL_DAYS)}
            aws_clients.dynamodb().put_item(TableName=DDB_AUDIT, Item=item)
        else:
            line = json.dumps({**record, "payload": json.loads(body)})
            with _lock:
                LOCAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with LOCAL_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never break the request
        log.warning("audit log write failed (%s): %s", event_type, exc)


def _decode(item: dict) -> dict:
    def s(name: str) -> str:
        return item.get(name, {}).get("S", "")

    step = int(item.get("step", {}).get("N", "0") or 0)
    return {
        "session_id": item["session_id"]["S"],
        "ts_event": item["ts_event"]["S"],
        "event_id": s("event_id"),
        "user_id": s("user_id"),
        "event_type": s("event_type"),
        "category": s("category"),
        "step": step,
        "step_name": s("step_name") or STEPS.get(step, ""),
        "target": s("target"),
        "result": s("result") or "ok",
        "summary": s("summary"),
        "payload": json.loads(item.get("payload", {}).get("S", "{}")),
    }


def events_for_session(session_id: str, limit: int = 500) -> list[dict]:
    """Newest-last list of events for one session."""
    if DDB_AUDIT:
        from app.services.common import aws_clients

        # Newest first from DynamoDB (so the limit keeps the LATEST events), then flipped back
        # to oldest-first for the caller.
        resp = aws_clients.dynamodb().query(
            TableName=DDB_AUDIT,
            KeyConditionExpression="session_id = :s",
            ExpressionAttributeValues={":s": {"S": session_id}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return list(reversed([_decode(i) for i in resp.get("Items", [])]))
    return [e for e in _read_local() if e["session_id"] == session_id][-limit:]


def events_for_user(user_id: str, limit: int = 500) -> list[dict]:
    """Newest-first list of events for one user, across sessions."""
    if DDB_AUDIT:
        from app.services.common import aws_clients

        resp = aws_clients.dynamodb().query(
            TableName=DDB_AUDIT,
            IndexName="by-user",
            KeyConditionExpression="user_id = :u",
            ExpressionAttributeValues={":u": {"S": user_id}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_decode(i) for i in resp.get("Items", [])]
    return list(reversed([e for e in _read_local() if e["user_id"] == user_id]))[:limit]


def events_for_target(session_id: str, target: str, limit: int = 200) -> list[dict]:
    """Newest-first history of ONE record, e.g. target="FEATURE#coo": who approved, ran and
    changed it, and when."""
    if DDB_AUDIT:
        from app.services.common import aws_clients

        resp = aws_clients.dynamodb().query(
            TableName=DDB_AUDIT,
            IndexName="by-target",
            KeyConditionExpression="target_key = :t",
            ExpressionAttributeValues={":t": {"S": f"{session_id}#{target}"}},
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_decode(i) for i in resp.get("Items", [])]
    found = [e for e in _read_local() if e["session_id"] == session_id and e.get("target") == target]
    return list(reversed(found))[:limit]


def _read_local() -> list[dict]:
    if not LOCAL_LOG_PATH.exists():
        return []
    out: list[dict] = []
    with _lock, LOCAL_LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out
