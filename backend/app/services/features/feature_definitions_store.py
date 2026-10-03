"""
The "Customer KPI Profile" a PM uploaded: a JSON list of feature definitions, stored PER USER
(see services/common/profile_store.py). There is no bundled backend default -- if the user has
not uploaded one, `load*` returns (None, None) and feature engineering simply cannot run yet.
"""
from app.services.common import profile_store

SUPPORTED_TYPES = {"lookup", "extract_month", "ratio", "duration_hours", "custom_formula", "ai_generated"}


def save(user_id: str, filename: str, definitions: list[dict]) -> None:
    profile_store.save(user_id, profile_store.KPI, filename, definitions)


def clear(user_id: str) -> None:
    profile_store.clear(user_id, profile_store.KPI)


def load(user_id: str) -> tuple[str | None, list[dict] | None]:
    """(filename, definitions) for this user; (None, None) if nothing was uploaded."""
    profile = profile_store.load(user_id, profile_store.KPI)
    if not profile:
        return None, None
    return profile.get("filename"), profile.get("definitions")


def load_for_session(session_id: str) -> tuple[str | None, list[dict] | None]:
    """Same, for the owner of `session_id` -- what the repositories and the planner use,
    since they only know the session."""
    profile = profile_store.load_for_session(session_id, profile_store.KPI)
    if not profile:
        return None, None
    return profile.get("filename"), profile.get("definitions")


def validate(payload: dict) -> list[dict]:
    """Raises ValueError with a clear message on anything malformed;
    returns the validated list of feature specs."""
    if not isinstance(payload, dict) or "features" not in payload:
        raise ValueError("Expected a JSON object with a top-level 'features' array.")
    features = payload["features"]
    if not isinstance(features, list) or not features:
        raise ValueError("'features' must be a non-empty array.")

    required_common = {"id", "name", "description", "output_column", "type"}
    required_by_type = {
        "lookup": {"source_column", "mapping"},
        "extract_month": {"source_columns"},
        "ratio": {"numerator_columns", "denominator_columns"},
        "duration_hours": {"start_column", "end_column"},
        "custom_formula": {"formula"},
        "ai_generated": {"calculation_prompt"},
    }

    for i, spec in enumerate(features):
        if not isinstance(spec, dict):
            raise ValueError(f"Feature #{i + 1} is not an object.")
        missing = required_common - set(spec.keys())
        if missing:
            raise ValueError(f"Feature #{i + 1} ('{spec.get('id', '?')}') is missing: {', '.join(sorted(missing))}.")
        ftype = spec["type"]
        if ftype not in SUPPORTED_TYPES:
            raise ValueError(
                f"Feature '{spec['id']}' has unsupported type '{ftype}'. "
                f"Supported types: {', '.join(sorted(SUPPORTED_TYPES))}."
            )
        type_missing = required_by_type[ftype] - set(spec.keys())
        if type_missing:
            raise ValueError(f"Feature '{spec['id']}' (type '{ftype}') is missing: {', '.join(sorted(type_missing))}.")

    return features
