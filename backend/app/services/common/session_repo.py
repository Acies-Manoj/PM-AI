"""Persistence for an audit session: the small header (DynamoDB) and its DataFrames (S3).

  header  -- JSON: owner, filename, issues, features, audit events, which frames exist, ...
             DynamoDB table DDB_SESSIONS (item overflows to S3 if it ever gets big).
  frames  -- the pandas DataFrames (`df`, `pre_feature_df`, `audit_baseline`), one object each
             at s3://<bucket>/frames/<session_id>/<name>.parquet.

Parquet is used because it is compact and fast, but it cannot hold every DataFrame an Excel
upload can produce (mixed int/str columns, non-string column names, ...). When parquet
refuses, the frame is pickled instead and the header records which format was used. The
bucket is private and only the task role writes to it, so unpickling our own objects is safe.

Without AWS configured (local dev) the same API reads and writes data/sessions/<id>/.
"""
from __future__ import annotations

import io
import json
import threading
from typing import Any

import pandas as pd

from app.config import DATA_DIR, DDB_SESSIONS, S3_BUCKET, USE_AWS_STORAGE
from app.services.common.doc_store import (
    ANY,
    VersionConflict,
    blob_get,
    blob_put,
    dumps,
    safe_session_id,
)

_SESSIONS_DIR = DATA_DIR / "sessions"
_local_lock = threading.RLock()


# --------------------------------------------------------------------------- header
def load_header(session_id: str) -> tuple[dict | None, int | None]:
    """(header dict, version) or (None, None) if the session does not exist."""
    sid = safe_session_id(session_id)
    if USE_AWS_STORAGE:
        return blob_get(DDB_SESSIONS, {"session_id": sid}, s3_prefix=f"overflow/{sid}/__session")
    path = _SESSIONS_DIR / sid / "session.json"
    with _local_lock:
        if not path.exists():
            return None, None
        try:
            wrapper = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None, None
    return wrapper["data"], int(wrapper.get("version", 1))


def save_header(session_id: str, header: dict, *, expected_version: Any = ANY) -> int:
    """Write the header; returns the new version. Raises VersionConflict if
    `expected_version` is given and the stored header has moved on."""
    sid = safe_session_id(session_id)
    if USE_AWS_STORAGE:
        return blob_put(
            DDB_SESSIONS,
            {"session_id": sid},
            header,
            s3_prefix=f"overflow/{sid}/__session",
            expected_version=expected_version,
            extra={"user_id": str(header.get("user_id", ""))} if header.get("user_id") else None,
        )
    path = _SESSIONS_DIR / sid / "session.json"
    with _local_lock:
        current = 0
        if path.exists():
            try:
                current = int(json.loads(path.read_text(encoding="utf-8")).get("version", 1))
            except (OSError, json.JSONDecodeError):
                current = 0
        if expected_version is not ANY and expected_version != current:
            raise VersionConflict(f"session {sid} changed since it was read")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dumps({"version": current + 1, "data": header}), encoding="utf-8")
        return current + 1


# --------------------------------------------------------------------------- frames
def _frame_key(session_id: str, name: str, fmt: str) -> str:
    ext = "parquet" if fmt == "parquet" else "pkl"
    return f"frames/{safe_session_id(session_id)}/{name}.{ext}"


def _to_bytes(df: pd.DataFrame) -> tuple[bytes, str]:
    """Serialize to parquet if it round-trips cleanly, else to pickle."""
    try:
        buf = io.BytesIO()
        df.to_parquet(buf, engine="pyarrow")
        return buf.getvalue(), "parquet"
    except Exception:
        buf = io.BytesIO()
        df.to_pickle(buf)
        return buf.getvalue(), "pickle"


def _from_bytes(raw: bytes, fmt: str) -> pd.DataFrame:
    if fmt == "parquet":
        return pd.read_parquet(io.BytesIO(raw), engine="pyarrow")
    return pd.read_pickle(io.BytesIO(raw))


def save_frame(session_id: str, name: str, df: pd.DataFrame) -> dict:
    """Store one DataFrame and return its reference, `{"fmt": ..., "rows": ...}`, which the
    caller keeps in the session header."""
    raw, fmt = _to_bytes(df)
    key = _frame_key(session_id, name, fmt)
    if USE_AWS_STORAGE:
        from app.services.common import aws_clients

        client = aws_clients.s3()
        client.put_object(Bucket=S3_BUCKET, Key=key, Body=raw, ContentType="application/octet-stream")
        # A frame that switched format leaves the other object behind; remove it.
        other = _frame_key(session_id, name, "pickle" if fmt == "parquet" else "parquet")
        client.delete_object(Bucket=S3_BUCKET, Key=other)
    else:
        path = _SESSIONS_DIR / safe_session_id(session_id) / key.split("/", 2)[2]
        with _local_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            other = path.with_suffix(".pkl" if fmt == "parquet" else ".parquet")
            other.unlink(missing_ok=True)
    return {"fmt": fmt, "rows": int(len(df))}


def load_frame(session_id: str, name: str, ref: dict) -> pd.DataFrame:
    fmt = ref.get("fmt", "parquet")
    key = _frame_key(session_id, name, fmt)
    if USE_AWS_STORAGE:
        from app.services.common import aws_clients

        obj = aws_clients.s3().get_object(Bucket=S3_BUCKET, Key=key)
        return _from_bytes(obj["Body"].read(), fmt)
    path = _SESSIONS_DIR / safe_session_id(session_id) / key.split("/", 2)[2]
    with _local_lock:
        return _from_bytes(path.read_bytes(), fmt)


def delete_frame(session_id: str, name: str, ref: dict | None = None) -> None:
    fmts = [ref.get("fmt", "parquet")] if ref else ["parquet", "pickle"]
    for fmt in fmts:
        key = _frame_key(session_id, name, fmt)
        if USE_AWS_STORAGE:
            from app.services.common import aws_clients

            aws_clients.s3().delete_object(Bucket=S3_BUCKET, Key=key)
        else:
            path = _SESSIONS_DIR / safe_session_id(session_id) / key.split("/", 2)[2]
            with _local_lock:
                path.unlink(missing_ok=True)
