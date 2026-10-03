"""Per-session cache of Analysis Agent results that already computed a
plausible table once, keyed by entry id. Mirrors feature_cache.py exactly,
including what it deliberately does NOT store: only the winning
{"plan_text", "generated_code"} pair, never the result table/chart/
interpretation -- those are always recomputed fresh from a cache-replay of
the code (see analysis_engine.run_analysis), so they reflect the current
data even when the underlying computation itself doesn't need rethinking.

Invalidated automatically if the entry's own calculation basis changes (a
different formula/calculation_intent for the same id) -- see `get`.
"""
from app.services.common import doc_store


def _doc(entry_id: str) -> str:
    return f"ACACHE#{entry_id}"


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) hasn't changed since it was cached.
    None otherwise, so the caller computes fresh."""
    cached = doc_store.get(session_id, _doc(entry["id"]))
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
    doc_store.put(session_id, _doc(entry["id"]), {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "plan_text": plan_text,
        "generated_code": generated_code,
        "chart_recommendation": chart_recommendation,
        "template": template,
        "filters": filters,
    })


def invalidate(session_id: str, entry_id: str) -> None:
    doc_store.delete(session_id, _doc(entry_id))
