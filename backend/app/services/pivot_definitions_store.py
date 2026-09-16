"""
Holds the pivot-definitions JSON analysis runs against -- whatever was most
recently uploaded to the "Analysis Profile" slot, or this app's own bundled
default (DEFAULT_PROFILE_PATH) if nothing has been uploaded yet, the same
"always there, upload only to override" arrangement as
feature_definitions_store.py. Single-slot, thread-safe -- same scope as
that store.
"""
import json
import logging
import threading

from app.config import RAW_DATA_DIR

logger = logging.getLogger(__name__)

SUPPORTED_AGGS = {"sum", "mean", "count", "min", "max", "median", "distinct_count", "pct_of_total"}
# "in" matches a slicer with multiple values selected, e.g. Origin is one of
# [Agricola Ci.da, Agricola Dino, ...] -- `value` must be a non-empty list for it.
SUPPORTED_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "in"}

DEFAULT_PROFILE_PATH = RAW_DATA_DIR / "analysis_profile_example.json"


class PivotDefinitionsStore:
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
            pivots = validate(payload)
        except Exception:
            logger.exception("Could not load the bundled default Analysis Profile from %s", DEFAULT_PROFILE_PATH)
            return
        self.filename = DEFAULT_PROFILE_PATH.name
        self.definitions = pivots

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
    returns the validated list of pivot specs."""
    if not isinstance(payload, dict) or "pivots" not in payload:
        raise ValueError("Expected a JSON object with a top-level 'pivots' array.")
    pivots = payload["pivots"]
    if not isinstance(pivots, list) or not pivots:
        raise ValueError("'pivots' must be a non-empty array.")

    required_common = {"id", "name", "description", "group_by", "metrics"}

    for i, spec in enumerate(pivots):
        if not isinstance(spec, dict):
            raise ValueError(f"Pivot #{i + 1} is not an object.")
        missing = required_common - set(spec.keys())
        if missing:
            raise ValueError(f"Pivot #{i + 1} ('{spec.get('id', '?')}') is missing: {', '.join(sorted(missing))}.")

        pivot_id = spec["id"]
        group_by = spec["group_by"]
        if not isinstance(group_by, list) or not group_by or not all(isinstance(c, str) for c in group_by):
            raise ValueError(f"Pivot '{pivot_id}': 'group_by' must be a non-empty array of column names.")

        metrics = spec["metrics"]
        if not isinstance(metrics, list) or not metrics:
            raise ValueError(f"Pivot '{pivot_id}': 'metrics' must be a non-empty array.")
        for j, metric in enumerate(metrics):
            if not isinstance(metric, dict):
                raise ValueError(f"Pivot '{pivot_id}', metric #{j + 1} is not an object.")
            metric_missing = {"column", "agg", "output_label"} - set(metric.keys())
            if metric_missing:
                raise ValueError(f"Pivot '{pivot_id}', metric #{j + 1} is missing: {', '.join(sorted(metric_missing))}.")
            if metric["agg"] not in SUPPORTED_AGGS:
                raise ValueError(
                    f"Pivot '{pivot_id}', metric #{j + 1} has unsupported agg '{metric['agg']}'. "
                    f"Supported: {', '.join(sorted(SUPPORTED_AGGS))}."
                )

        filters = spec.get("filters", [])
        if not isinstance(filters, list):
            raise ValueError(f"Pivot '{pivot_id}': 'filters' must be an array if present.")
        for k, f in enumerate(filters):
            if not isinstance(f, dict) or {"column", "op", "value"} - set(f.keys()):
                raise ValueError(f"Pivot '{pivot_id}', filter #{k + 1} must have 'column', 'op', and 'value'.")
            if f["op"] not in SUPPORTED_OPS:
                raise ValueError(
                    f"Pivot '{pivot_id}', filter #{k + 1} has unsupported op '{f['op']}'. "
                    f"Supported: {', '.join(sorted(SUPPORTED_OPS))}."
                )
            if f["op"] == "in" and (not isinstance(f["value"], list) or not f["value"]):
                raise ValueError(f"Pivot '{pivot_id}', filter #{k + 1}: op 'in' requires 'value' to be a non-empty array.")

        sort_by = spec.get("sort_by")
        if sort_by is not None and (not isinstance(sort_by, dict) or "metric" not in sort_by):
            raise ValueError(f"Pivot '{pivot_id}': 'sort_by' must be an object with at least a 'metric' key.")

        top_n = spec.get("top_n")
        if top_n is not None and (not isinstance(top_n, int) or top_n <= 0):
            raise ValueError(f"Pivot '{pivot_id}': 'top_n' must be a positive integer if present.")

        filterable_columns = spec.get("filterable_columns", [])
        if not isinstance(filterable_columns, list) or not all(isinstance(c, str) for c in filterable_columns):
            raise ValueError(f"Pivot '{pivot_id}': 'filterable_columns' must be an array of column names if present.")

    return pivots


store = PivotDefinitionsStore()
