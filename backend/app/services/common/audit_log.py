"""Append-only log of what users did, per session: uploads, audit decisions, edits, analysis
runs, report downloads and every LLM call (with its token usage).

AWS: one item per event in the DDB_AUDIT table (partition `session_id`, sort `ts_event` =
"<ISO time>#<uuid>"), with a `by-user` GSI (`user_id`, `ts_event`) for "everything this user
did". Local: one JSON line per event in data/audit_log.jsonl.

Logging must never break a request, so every failure is swallowed (and printed).
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import AUDIT_LOG_TTL_DAYS, DATA_DIR, DDB_AUDIT
from app.services.common.doc_store import dumps

log = logging.getLogger(__name__)

LOCAL_LOG_PATH = DATA_DIR / "audit_log.jsonl"
_lock = threading.Lock()

# Session id used for events that belong to no session (e.g. LLM calls made outside a request).
GLOBAL_SESSION = "_global"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def log_event(
    session_id: str | None,
    user_id: str | None,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Record one event. Safe to call from any thread; never raises."""
    try:
        session = session_id or GLOBAL_SESSION
        user = user_id or "unknown"
        ts_event = f"{_now_iso()}#{uuid.uuid4().hex[:8]}"
        body = dumps(payload or {})
        if len(body.encode("utf-8")) > 200_000:
            # DynamoDB items max out at 400 KB. Never cut the JSON text (that would leave
            # unparseable JSON and break reading the log back): keep a small valid preview.
            body = dumps({"truncated": True, "preview": body[:2000]})
        if DDB_AUDIT:
            import time

            from app.services.common import aws_clients

            item = {
                "session_id": {"S": session},
                "ts_event": {"S": ts_event},
                "user_id": {"S": user},
                "event_type": {"S": event_type},
                "payload": {"S": body},
                "ttl": {"N": str(int(time.time()) + 86400 * AUDIT_LOG_TTL_DAYS)},
            }
            aws_clients.dynamodb().put_item(TableName=DDB_AUDIT, Item=item)
        else:
            line = json.dumps(
                {"session_id": session, "ts_event": ts_event, "user_id": user, "event_type": event_type, "payload": json.loads(body)}
            )
            with _lock:
                LOCAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with LOCAL_LOG_PATH.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001 - logging must never break the request
        log.warning("audit log write failed (%s): %s", event_type, exc)


def _decode(item: dict) -> dict:
    return {
        "session_id": item["session_id"]["S"],
        "ts_event": item["ts_event"]["S"],
        "user_id": item.get("user_id", {}).get("S", ""),
        "event_type": item.get("event_type", {}).get("S", ""),
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
