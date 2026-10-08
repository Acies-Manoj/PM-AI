"""Per-session cache of Analysis Agent results that already computed a
plausible table once, keyed by entry id. Mirrors feature_cache.py exactly,
including what it deliberately does NOT store: only the winning
{"plan_text", "generated_code"} pair, never the result table/chart/
interpretation -- those are always recomputed fresh from a cache-replay of
the code (see analysis_engine.run_analysis), so they reflect the current
data even when the underlying computation itself doesn't need rethinking.

Stored INSIDE the analysis's own `ANALYSIS#<id>` document (key `cache`), next to its definition, so one
read gives the definition, status and final code. A predefined or planner analysis (derived on
every read) gets a document the first time its computation is cached: a definition snapshot
plus the cache.

Invalidated automatically if the entry's own calculation basis changes (a
different formula/calculation_intent for the same id) -- see `get`.
"""
from datetime import datetime, timezone

from app.services.common import doc_store

PREFIX = "ANALYSIS#"


def _doc(entry_id: str) -> str:
    return f"{PREFIX}{entry_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) hasn't changed since it was cached.
    None otherwise, so the caller computes fresh."""
    doc = doc_store.get(session_id, _doc(entry["id"]))
    cached = doc.get("cache") if isinstance(doc, dict) else None
    if not cached:
        return None
    basis = entry.get("formula") or entry["calculation_intent"]
    if cached.get("basis") != basis:
        return None
    return cached


def set(
    session_id: str, entry: dict, plan_text: str | None, generated_code: str | None,
    chart_recommendation: dict | None = None, template: dict | None = None,
    filters: list[dict] | None = None,
) -> None:
    """Caches this entry's computation decision: either `template` (a
    validated analysis_templates spec, with `plan_text` = its steps) or the
    winning `generated_code`. `chart_recommendation` is the chart picked
    from the logic before computing, and `filters` the filter-column defs
    discovered alongside it -- both kept so a replay reuses them without
    asking the LLM again. `entry` must be the entry as stored in the
    repository, since its logic is the cache key (`basis`)."""
    cache = {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "plan_text": plan_text,
        "generated_code": generated_code,
        "chart_recommendation": chart_recommendation,
        "template": template,
        "filters": filters,
        "cached_at": _now(),
    }

    def put_cache(current):
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
        doc_store.delete(session_id, _doc(entry_id))  # a snapshot with no computation has no purpose
