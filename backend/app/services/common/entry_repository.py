"""Shared persistence/merge mechanics used by the Feature and Analysis
repositories. Both follow the same pattern -- entries derived fresh from a
predefined-spec store and from accepted Planner recommendations, plus a
persisted set of PM/AI-authored entries, re-merged and re-saved on every
read. This module provides the file I/O, merge, and status-update
mechanics; the entry-building logic itself (predefined-spec shapes, the
Planner-entry mapping, AI-suggestion dedup keys, drilldown-only fields) is
specific to each domain and lives in feature_repository.py /
analysis_repository.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import DATA_DIR

_SESSIONS_DIR = DATA_DIR / "sessions"


def session_dir(session_id: str) -> Path:
    d = _SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def repo_path(session_id: str, filename: str) -> Path:
    return session_dir(session_id) / filename


def planner_output_path(session_id: str) -> Path:
    return session_dir(session_id) / "planner_output.json"


def load_persisted(session_id: str, filename: str, persisted_sources: set[str]) -> list[dict]:
    path = repo_path(session_id, filename)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [e for e in data.get("entries", []) if e.get("source") in persisted_sources]


def save(session_id: str, filename: str, entries: list[dict]) -> None:
    repo_path(session_id, filename).write_text(
        json.dumps({"session_id": session_id, "entries": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def merge_and_save(
    session_id: str, filename: str, predefined: list[dict], planner: list[dict], persisted: list[dict],
) -> list[dict]:
    entries = predefined + planner + persisted
    save(session_id, filename, entries)
    return entries


def set_entry_status(
    session_id: str, filename: str, persisted_sources: set[str],
    predefined: list[dict], planner: list[dict], entry_id: str, status: str,
) -> dict | None:
    persisted = load_persisted(session_id, filename, persisted_sources)
    found = None
    for e in persisted:
        if e["id"] == entry_id:
            e["status"] = status
            found = e
            break
    if found is None:
        return None
    merge_and_save(session_id, filename, predefined, planner, persisted)
    return found


def normalize_name(name: str) -> str:
    """Dedup-name normalization shared by analysis_repository and
    analysis_suggester so both dedupe suggested names the same way."""
    return " ".join(name.lower().split())
