"""Column metadata of an uploaded dataset: one `COLUMN#<name>` document per column.

Written once at upload (the Planner reads it to know what the data holds). Each document is the
column's full profile (type, role, missing/unique counts, ranges, samples ...) plus its `name` and
`position` (the column's place in the file, because DynamoDB returns documents in name order).
The session's row and column counts live on the session header (`SESSIONS`).
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.audit.column_profiler import profile_dataframe
from app.services.common import doc_store

PREFIX = "COLUMN#"


def doc_name(column: str) -> str:
    return f"{PREFIX}{column}"


def save(session_id: str, df: pd.DataFrame) -> int:
    """Profile every column and store one document each; returns how many were written."""
    profiles = profile_dataframe(df)
    items = [(name, {"name": name, "position": i, **profile}) for i, (name, profile) in enumerate(profiles.items())]
    doc_store.put_many(session_id, {doc_name(name): data for name, data in items})
    return len(items)


def load(session_id: str) -> dict[str, Any] | None:
    """{"row_count", "column_count", "columns": {name: profile}} in file order, or None if the
    session has no column metadata."""
    from app.services.audit.audit_store import store

    docs = doc_store.list_docs(session_id, PREFIX)
    if not docs:
        return None
    ordered = sorted(docs.values(), key=lambda d: d.get("position", 0))
    columns = {d["name"]: {k: v for k, v in d.items() if k not in ("name", "position")} for d in ordered}
    session = store.get(session_id)
    return {
        "session_id": session_id,
        "row_count": getattr(session, "row_count", 0) if session else 0,
        "column_count": len(columns),
        "columns": columns,
    }
