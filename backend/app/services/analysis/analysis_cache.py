"""Per-session cache of Analysis Agent results that already computed a
plausible table once, keyed by entry id. Mirrors feature_cache.py's shape,
including what it deliberately does NOT store: only the winning
{"plan_text", "generated_code"} pair, never the result table/chart/
interpretation -- those are always recomputed fresh from a cache-replay of
the code (see analysis_engine.run_analysis), so they reflect the current
data even when the underlying computation itself doesn't need rethinking.

Invalidated automatically if the entry's own calculation basis changes (a
different formula/calculation_intent for the same id) -- see `get`.
"""
from app.services.common import agent_cache

_FILENAME = "analysis_cache.json"


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) hasn't changed since it was cached.
    None otherwise, so the caller computes fresh."""
    cached = agent_cache.load(session_id, _FILENAME).get(entry["id"])
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
    cache = agent_cache.load(session_id, _FILENAME)
    cache[entry["id"]] = {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "plan_text": plan_text,
        "generated_code": generated_code,
        "chart_recommendation": chart_recommendation,
        "template": template,
        "filters": filters,
    }
    agent_cache.save(session_id, _FILENAME, cache)


def invalidate(session_id: str, entry_id: str) -> None:
    agent_cache.invalidate(session_id, _FILENAME, entry_id)
