"""The "Analysis Profile" a PM uploaded: a JSON list of analysis definitions, stored PER USER
(see services/common/profile_store.py). There is no bundled backend default -- if the user has
not uploaded one, `load*` returns (None, None) and the Analysis page simply shows zero
`predefined` entries (never a hard error).

Deliberately looser than the old pivot-table JSON schema: no group_by/metrics/agg vocabulary,
since the Analysis Agent now derives the aggregation itself from a plain-English
`calculation_intent`.
"""
from app.services.common import profile_store


def save(user_id: str, filename: str, definitions: list[dict]) -> None:
    profile_store.save(user_id, profile_store.ANALYSIS, filename, definitions)


def clear(user_id: str) -> None:
    profile_store.clear(user_id, profile_store.ANALYSIS)


def load(user_id: str) -> tuple[str | None, list[dict] | None]:
    """(filename, definitions) for this user; (None, None) if nothing was uploaded."""
    profile = profile_store.load(user_id, profile_store.ANALYSIS)
    if not profile:
        return None, None
    return profile.get("filename"), profile.get("definitions")


def load_for_session(session_id: str) -> tuple[str | None, list[dict] | None]:
    """Same, for the owner of `session_id` -- what the repositories use, since they only
    know the session."""
    profile = profile_store.load_for_session(session_id, profile_store.ANALYSIS)
    if not profile:
        return None, None
    return profile.get("filename"), profile.get("definitions")


def validate(payload: dict) -> list[dict]:
    """Raises ValueError with a clear message on anything malformed;
    returns the validated list of analysis specs."""
    if not isinstance(payload, dict) or "analyses" not in payload:
        raise ValueError("Expected a JSON object with a top-level 'analyses' array.")
    analyses = payload["analyses"]
    if not isinstance(analyses, list) or not analyses:
        raise ValueError("'analyses' must be a non-empty array.")

    required = {"id", "name", "description", "calculation_intent"}

    for i, spec in enumerate(analyses):
        if not isinstance(spec, dict):
            raise ValueError(f"Analysis #{i + 1} is not an object.")
        missing = required - set(spec.keys())
        if missing:
            raise ValueError(f"Analysis #{i + 1} ('{spec.get('id', '?')}') is missing: {', '.join(sorted(missing))}.")

    return analyses
