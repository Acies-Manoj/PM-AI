"""Per-user profiles: the "Customer KPI Profile" and "Analysis Profile" JSON a PM uploads.

These used to be process-wide singletons, so one user's upload leaked into every other user's
sessions and was lost on restart. They are now keyed by user id:

  AWS    -- DynamoDB table DDB_PROFILES, partition `user_id`, sort `profile` (KPI / ANALYSIS).
  local  -- data/profiles/<user>/<kind>.json.

A profile is `{"filename": str, "definitions": list[dict]}`.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any

from app.config import DATA_DIR, DDB_PROFILES, USE_AWS_STORAGE
from app.services.common import session_repo
from app.services.common.doc_store import ANY, blob_delete, blob_get, blob_put, dumps

KPI = "KPI"
ANALYSIS = "ANALYSIS"

LOCAL_USER = "local"

_PROFILES_DIR = DATA_DIR / "profiles"
_lock = threading.RLock()
_SAFE = re.compile(r"[^A-Za-z0-9_\-.@]")


def _use_ddb() -> bool:
    return bool(DDB_PROFILES) and USE_AWS_STORAGE


def _local_path(user_id: str, kind: str):
    return _PROFILES_DIR / _SAFE.sub("_", user_id) / f"{kind}.json"


def load(user_id: str, kind: str) -> dict[str, Any] | None:
    """The user's stored profile, or None if they have not uploaded one."""
    if _use_ddb():
        data, _ = blob_get(
            DDB_PROFILES, {"user_id": user_id, "profile": kind}, s3_prefix=f"overflow/profiles/{_SAFE.sub('_', user_id)}/{kind}"
        )
        return data
    path = _local_path(user_id, kind)
    with _lock:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


def save(user_id: str, kind: str, filename: str, definitions: list[dict]) -> None:
    profile = {"filename": filename, "definitions": definitions}
    if _use_ddb():
        # Profiles do not expire with a session: keep them for a year.
        blob_put(
            DDB_PROFILES,
            {"user_id": user_id, "profile": kind},
            profile,
            s3_prefix=f"overflow/profiles/{_SAFE.sub('_', user_id)}/{kind}",
            expected_version=ANY,
            ttl_days=365,
        )
        return
    path = _local_path(user_id, kind)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps(profile), encoding="utf-8")


def clear(user_id: str, kind: str) -> None:
    if _use_ddb():
        blob_delete(DDB_PROFILES, {"user_id": user_id, "profile": kind})
        return
    with _lock:
        _local_path(user_id, kind).unlink(missing_ok=True)


def user_for_session(session_id: str) -> str:
    """The owner of a session (the profile owner for everything done in that session). Falls
    back to the local user for sessions that predate ownership or do not exist."""
    try:
        header, _ = session_repo.load_header(session_id)
    except ValueError:
        return LOCAL_USER
    return (header or {}).get("user_id") or LOCAL_USER


def load_for_session(session_id: str, kind: str) -> dict[str, Any] | None:
    return load(user_for_session(session_id), kind)
