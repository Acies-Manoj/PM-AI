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
from app.services.common import agent_cache

_FILENAME = "feature_cache.json"


def get(session_id: str, entry: dict) -> dict | None:
    """Returns the cached {"plan_text", "generated_code"} for this entry if
    one exists and the entry's calculation basis (its formula if it has
    one, else its calculation_intent) and output column haven't changed
    since it was cached. None otherwise, so the caller computes fresh."""
    cached = agent_cache.load(session_id, _FILENAME).get(entry["id"])
    if not cached:
        return None
    basis = entry.get("formula") or entry["calculation_intent"]
    if cached.get("basis") != basis or cached.get("output_column") != entry["output_column"]:
        return None
    return cached


def set(session_id: str, entry: dict, plan_text: str | None, generated_code: str) -> None:
    cache = agent_cache.load(session_id, _FILENAME)
    cache[entry["id"]] = {
        "basis": entry.get("formula") or entry["calculation_intent"],
        "output_column": entry["output_column"],
        "plan_text": plan_text,
        "generated_code": generated_code,
    }
    agent_cache.save(session_id, _FILENAME, cache)


def invalidate(session_id: str, entry_id: str) -> None:
    agent_cache.invalidate(session_id, _FILENAME, entry_id)
