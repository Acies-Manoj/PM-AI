"""
Holds the feature-definitions JSON feature engineering runs against --
whatever was most recently uploaded to the "Customer KPI Profile" slot, or
this app's own bundled default (DEFAULT_PROFILE_PATH) if nothing has been
uploaded yet. The default exists so a fresh session can compute features
immediately instead of blocking on a manual upload step; uploading a
profile still overrides it for the rest of the process's lifetime (`set`
below), the same as before. Single-slot, thread-safe -- same scope as the
other in-memory stores in this app (one demo session at a time).
"""
import json
import logging
import threading

from app.config import RAW_DATA_DIR

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"lookup", "extract_month", "ratio", "duration_hours", "custom_formula", "ai_generated"}

DEFAULT_PROFILE_PATH = RAW_DATA_DIR / "customer_kpi_profile_example.json"


class FeatureDefinitionsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.filename: str | None = None
        self.definitions: list[dict] | None = None
        self._load_default()

    def _load_default(self) -> None:
        """Best-effort only: a missing or malformed bundled default just
        means "no default" (the pre-existing behavior), never a startup
        crash -- an uploaded profile always still works either way."""
        if not DEFAULT_PROFILE_PATH.exists():
            return
        try:
            payload = json.loads(DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
            features = validate(payload)
        except Exception:
            logger.exception("Could not load the bundled default Customer KPI Profile from %s", DEFAULT_PROFILE_PATH)
            return
        self.filename = DEFAULT_PROFILE_PATH.name
        self.definitions = features

    def set(self, filename: str, definitions: list[dict]) -> None:
        with self._lock:
            self.filename = filename
            self.definitions = definitions

    def clear(self) -> None:
        with self._lock:
            self.filename = None
            self.definitions = None


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


store = FeatureDefinitionsStore()
