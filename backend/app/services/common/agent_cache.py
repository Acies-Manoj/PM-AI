"""Shared file I/O for the per-session Feature/Analysis Agent caches.

feature_cache.py and analysis_cache.py each store a small dict keyed by
entry id under a per-session JSON file; this module provides the path/
load/save/invalidate mechanics both use. `get`/`set` stay in each module
since the cached payload shape and what counts as a still-valid "basis"
differ (analysis also caches a chart_recommendation/template/filters, and
doesn't key invalidation on output_column the way features does).
"""
import json
from pathlib import Path

from app.config import DATA_DIR

_SESSIONS_DIR = DATA_DIR / "sessions"


def cache_path(session_id: str, filename: str) -> Path:
    d = _SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


def load(session_id: str, filename: str) -> dict:
    path = cache_path(session_id, filename)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(session_id: str, filename: str, cache: dict) -> None:
    cache_path(session_id, filename).write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def invalidate(session_id: str, filename: str, entry_id: str) -> None:
    cache = load(session_id, filename)
    if entry_id in cache:
        del cache[entry_id]
        save(session_id, filename, cache)
