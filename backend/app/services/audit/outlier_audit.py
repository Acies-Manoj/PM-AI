"""Audit trail for the Segment and Mean Temperature outlier review.

Every outlier-related action is written twice: to the audit log as an `outlier_*` event (so it
shows on the Audit Log page next to everything else) and to the session's `OUTLIER` doc
(one ordered list, so "what happened to the outliers in this session" is one read).

Actions recorded:
  detected  the flagged set changed since the last time it was recorded (counts + trip keys)
  edit      a PM corrected a value: old value, new value, and the flag / fence it had before
  review    a PM finished or skipped a tab ("skipped" = kept every flagged value as-is)
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from app.services.common import audit_log, doc_store

DOC = "OUTLIER"
_MAX_ENTRIES = 2000
_MAX_TRIP_KEYS = 500


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _segment_keys(segment: dict) -> list[dict]:
    return [
        {"serial": r.get("serial"), "trip_id": r.get("trip_id"), "segment_days": r.get("segment_days"),
         "lower_fence": r.get("lower_fence_days"), "upper_fence": r.get("upper_fence_days"), "lane": f"{r.get('origin')} -> {r.get('destination')}"}
        for r in segment.get("outlier_rows", [])
    ]


def _temperature_keys(temperature: dict) -> list[dict]:
    out: list[dict] = []
    for product in temperature.get("by_product", []):
        for t in product.get("trips", []):
            if t.get("status") != "in_spec":
                out.append({"serial": t.get("serial"), "trip_id": t.get("trip_id"), "mean_temp": t.get("mean_temp"),
                            "limit_low": t.get("limit_low"), "limit_high": t.get("limit_high"),
                            "status": t.get("status"), "product": product.get("product")})
    return out


def summarize(segment: dict, temperature: dict) -> dict[str, Any]:
    seg, temp = _segment_keys(segment), _temperature_keys(temperature)
    return {
        "segment": {"column_found": segment.get("column_found", False), "flagged": len(seg),
                    "total_trips": segment.get("total_trips"), "trips": seg[:_MAX_TRIP_KEYS]},
        "temperature": {"columns_found": temperature.get("columns_found"), "too_warm": temperature.get("too_warm_count", 0),
                        "too_cold": temperature.get("too_cold_count", 0), "total_trips": temperature.get("total_trips"),
                        "trips": temp[:_MAX_TRIP_KEYS]},
    }


def trip_context(field: str, serial: str, trip_id: str, segment: dict, temperature: dict) -> dict[str, Any]:
    """What the detector says about one trip right now (call it on the data BEFORE an edit):
    its value, whether it was flagged, and the fence / limits it was judged against."""
    sid, tid = str(serial), str(trip_id)
    if field == "segment_days":
        for r in segment.get("outlier_rows", []):
            if str(r.get("serial")) == sid and str(r.get("trip_id")) == tid:
                return {"was_flagged": True, "value": r.get("segment_days"), "status": r.get("status"),
                        "lower_fence": r.get("lower_fence_days"), "upper_fence": r.get("upper_fence_days"),
                        "lane": f"{r.get('origin')} -> {r.get('destination')}"}
        return {"was_flagged": False, "value": None}
    for product in temperature.get("by_product", []):
        for t in product.get("trips", []):
            if str(t.get("serial")) == sid and str(t.get("trip_id")) == tid:
                return {"was_flagged": t.get("status") != "in_spec", "value": t.get("mean_temp"), "status": t.get("status"),
                        "limit_low": t.get("limit_low"), "limit_high": t.get("limit_high"), "product": product.get("product")}
    return {"was_flagged": False, "value": None}


def _append(session_id: str, entry: dict) -> None:
    def add(current: Any) -> Any:
        entries = list(current or [])
        entries.append(entry)
        return entries[-_MAX_ENTRIES:]

    try:
        doc_store.update(session_id, DOC, add, default=[])
    except Exception as exc:  # noqa: BLE001 - auditing must never break the request
        audit_log.log.warning("outlier audit doc write failed: %s", exc)


def record(session_id: str, user_id: str, action: str, payload: dict[str, Any]) -> None:
    audit_log.log_event(session_id, user_id, f"outlier_{action}", payload)
    _append(session_id, {"ts": _now(), "user_id": user_id, "action": action, **payload})


def record_detection(session_id: str, user_id: str, segment: dict, temperature: dict) -> None:
    """Records the flagged set only when it differs from the last recorded one, so reloading the
    review screen doesn't flood the trail."""
    summary = summarize(segment, temperature)
    keys = sorted(
        [f"s|{t['serial']}|{t['trip_id']}" for t in summary["segment"]["trips"]]
        + [f"t|{t['serial']}|{t['trip_id']}|{t['status']}" for t in summary["temperature"]["trips"]]
    )
    signature = hashlib.sha1("\n".join(keys).encode("utf-8")).hexdigest()
    try:
        existing = doc_store.get(session_id, DOC) or []
    except Exception:  # noqa: BLE001
        existing = []
    last = next((e for e in reversed(existing) if e.get("action") == "detected"), None)
    if last is not None and last.get("signature") == signature:
        return
    audit_log.log_event(session_id, user_id, "outlier_detected", summary)
    _append(session_id, {"ts": _now(), "user_id": user_id, "action": "detected", "signature": signature, **summary})


def entries(session_id: str) -> list[dict]:
    return doc_store.get(session_id, DOC) or []
