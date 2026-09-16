"""Persistent log of what Step 3's agents have already produced for a given
audit session: AI summaries, per-chart interpretations, drill-down
suggestions, and ask-a-question results (see formula_agent.py). Same
file-backed pattern as custom_library_store.py -- the point is that a
result computed once (e.g. "average excursion time by supplier") doesn't
have to be regenerated from scratch the next time someone asks a similar
question about the same session.

Unlike custom_library_store.py this isn't user-curated -- every entry is
written automatically by the router endpoint that produced it. Entries are
plain, JSON-serializable dicts (never a pandas object), keyed by session_id
so one session's entries never leak into another's report.
"""
import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from app.config import ANALYSIS_STORE_PATH

Kind = Literal["summary", "chart_interpretation", "drill_down", "formula_result"]

MAX_ENTRIES_PER_SESSION = 200  # a demo/session-scoped log, not an unbounded audit trail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AnalysisStore:
    """Thread-safe, file-backed. Same "rewrite the whole (small) file on
    every mutation" simplicity as custom_library_store.py."""

    def __init__(self, path=ANALYSIS_STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(payload, dict):
            self._data = {
                session_id: [e for e in entries if isinstance(e, dict)]
                for session_id, entries in payload.items()
                if isinstance(entries, list)
            }

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def add(self, session_id: str, kind: Kind, label: str, content: Any) -> dict:
        entry = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "label": label,
            "content": content,
            "created_at": _now(),
        }
        with self._lock:
            entries = self._data.setdefault(session_id, [])
            entries.append(entry)
            del entries[:-MAX_ENTRIES_PER_SESSION]  # keep only the most recent, oldest-first list
            self._flush()
        return dict(entry)

    def entries(self, session_id: str, kind: Kind | None = None) -> list[dict]:
        with self._lock:
            items = list(self._data.get(session_id, []))
        if kind is not None:
            items = [e for e in items if e.get("kind") == kind]
        return items


store = AnalysisStore()
