"""Per-session cache of Feature Agent results that already passed
validation once, keyed by entry id. It lives INSIDE the feature's own `FEATURE#<id>` document
(key `cache`), next to the feature's definition, so one read gives the definition, status and
final code. A predefined or planner feature (derived on every read, never persisted by the
repository) gets a document the first time its code is cached: a snapshot of its definition
plus the code.

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
from datetime import datetime, timezone

from app.services.common import doc_store

PREFIX = "FEATURE#"


def _doc(entry_id: str) -> str:
    return f"{PREFIX}{entry_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) and output column haven't changed
    since it was cached. None otherwise, so the caller computes fresh."""
    doc = doc_store.get(session_id, _doc(entry["id"]))
    cached = doc.get("cache") if isinstance(doc, dict) else None
    if not cached:
        return None
    basis = entry.get("formula") or entry["calculation_intent"]
    if cached.get("basis") != basis or cached.get("output_column") != entry["output_column"]:
        return None
    return cached


def set(session_id: str, entry: dict, plan_text: str | None, generated_code: str) -> None:
    cache = {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "output_column": entry["output_column"],
        "plan_text": plan_text,
        "generated_code": generated_code,
        "cached_at": _now(),
    }

    def put_cache(current):
        # A persisted feature already has its document; a derived one gets a definition snapshot.
        doc = current if isinstance(current, dict) else {**entry, "persisted": False, "created_at": _now()}
        doc["cache"] = cache
        return doc

    doc_store.update(session_id, _doc(entry["id"]), put_cache)


def invalidate(session_id: str, entry_id: str) -> None:
    doc = doc_store.get(session_id, _doc(entry_id))
    if not isinstance(doc, dict):
        return
    if doc.get("persisted"):
        doc.pop("cache", None)
        doc_store.put(session_id, _doc(entry_id), doc)
    else:
        doc_store.delete(session_id, _doc(entry_id))  # a snapshot with no code has no purpose
