"""Per-session cache of Feature Agent results that already passed
validation once, keyed by entry id.

Every recompute (e.g. accepting one more AI suggestion re-runs the WHOLE
approved set, not just the new entry -- see feature_engineering.apply_
features) would otherwise call Think/Code/Validate again for every entry,
including ones that already succeeded. Code generation has some sampling
variance, so a feature that validated fine once can occasionally come out
different -- and fail -- on a later recompute for no reason tied to
anything the PM did. Caching the exact winning plan+code the first time an
entry validates makes recomputation idempotent: a proven-correct entry
just replays its own code from then on, instead of being regenerated (and
re-risked) every time.

The cache is invalidated automatically if the entry's own calculation
basis changes (a re-uploaded KPI Profile with a different formula for the
same id, say) -- see `get`.
"""
import json
from pathlib import Path

from app.config import DATA_DIR

_SESSIONS_DIR = DATA_DIR / "sessions"


def _cache_path(session_id: str) -> Path:
    d = _SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "feature_cache.json"


def _load(session_id: str) -> dict:
    path = _cache_path(session_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(session_id: str, cache: dict) -> None:
    _cache_path(session_id).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) and output column haven't changed
    since it was cached. None otherwise, so the caller computes fresh."""
    cached = _load(session_id).get(entry["id"])
    if not cached:
        return None
    basis = entry.get("formula") or entry["calculation_intent"]
    if cached.get("basis") != basis or cached.get("output_column") != entry["output_column"]:
        return None
    return cached


def set(session_id: str, entry: dict, plan_text: str | None, generated_code: str) -> None:
    cache = _load(session_id)
    cache[entry["id"]] = {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "output_column": entry["output_column"],
        "plan_text": plan_text,
        "generated_code": generated_code,
    }
    _save(session_id, cache)


def invalidate(session_id: str, entry_id: str) -> None:
    cache = _load(session_id)
    if entry_id in cache:
        del cache[entry_id]
        _save(session_id, cache)
