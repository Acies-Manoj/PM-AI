"""Central, durable registry of every feature the app has created or reused
via the Client Brief / user-request pipeline (see feature_orchestrator.py).

Distinct from custom_library_store.py: that one is about a user's personal
"keep this as my regular KPI" choice (opt-in, scope-based). This one is the
provenance ledger the orchestration pipeline consults BEFORE creating
anything new (duplicate prevention, section 9) and updates after every
successful creation, so `kpi_store.json` on disk always reflects "every
feature this app knows about, and why it was created" -- CLIENT_REQUESTED,
AI_SUGGESTED, or USER_REQUESTED (section 10).

Same file-backed, thread-safe, load-whole/flush-whole pattern as
custom_library_store.py -- the store stays small enough that there's no
need for anything fancier.
"""
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from app.config import KPI_STORE_PATH

# Generic words that shouldn't drive a duplicate match on their own (e.g. two
# unrelated features both mentioning "total" or "shipment").
_STOPWORDS = {
    "the", "a", "an", "of", "for", "to", "and", "or", "in", "on", "is", "was",
    "its", "this", "that", "with", "by", "from", "as", "be", "total", "all",
}

# A feature described with one of these is a COMPARISON against some
# planned/scheduled BASELINE -- a categorically different calculation shape
# from a plain aggregate/duration, even though the two often share most of
# their other vocabulary (both talk about "actual departure/arrival",
# "transit time", etc.). Two candidates where exactly ONE side uses this
# vocabulary are treated as NOT equivalent regardless of their overall token
# overlap -- e.g. "total transit duration" (actual arrival minus actual
# departure) vs "total delay duration" (actual minus PLANNED) share almost
# every other word but are not the same feature. Deliberately narrow: a word
# like "difference" or "deviation" describes any subtraction (including a
# plain duration's own "arrival minus departure") and would defeat the
# guard, so only words specific to a planned/expected BASELINE qualify.
_DELTA_MARKERS = {"planned", "plan", "scheduled", "schedule", "expected", "delay", "delayed", "shortfall"}


def _tokens(*texts: str) -> set[str]:
    words: set[str] = set()
    for text in texts:
        for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
            if len(w) >= 3 and w not in _STOPWORDS:
                words.add(w)
    return words


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# A kpi_store entry's own id doubles as the Features/Analysis pages' bucket
# marker (the same convention feature_suggester.py's "ai_" and AddKpiForm's
# "custom_" ids already used before this store existed) -- so a feature or
# analysis this store creates or reuses shows up in the right section
# (Client-Requested / AI-Suggested / User-Requested) with no separate
# reprefixing step anywhere else. Stable across reuse, since an existing
# entry keeps its original id regardless of which later call reused it.
_SOURCE_ID_PREFIX = {"CLIENT_REQUESTED": "client", "AI_SUGGESTED": "ai", "USER_REQUESTED": "custom"}


class KpiStore:
    def __init__(self, path=KPI_STORE_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._features: list[dict] = []
        self._load()

    # -- disk -----------------------------------------------------------

    def _load(self) -> None:
        """A missing file is the normal first-run state; a corrupt one just
        means an empty registry rather than a startup crash."""
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if isinstance(payload, dict) and isinstance(payload.get("features"), list):
            self._features = [f for f in payload["features"] if isinstance(f, dict)]

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"features": self._features}, indent=2), encoding="utf-8")

    # -- reads ------------------------------------------------------------

    def all(self) -> list[dict]:
        with self._lock:
            return [dict(f) for f in self._features]

    def get(self, kpi_id: str) -> dict | None:
        with self._lock:
            for f in self._features:
                if f.get("id") == kpi_id:
                    return dict(f)
        return None

    def find_equivalent(
        self, feature_name: str, description: str = "", source_columns: list[str] | None = None
    ) -> dict | None:
        """Best-effort duplicate detection (section 9): NOT exact-name-only.
        Scores each existing entry on shared vocabulary between
        (feature_name + description) and the entry's own (name +
        description), with a bonus for overlapping source columns, and
        returns the best match above a threshold. A lightweight, explainable
        heuristic (no embeddings in this codebase) -- good enough for a
        registry this size, and easy to reason about when it's wrong.

        One guard beyond plain overlap: a comparison/delta feature (e.g.
        "total delay duration" -- actual minus PLANNED) can share almost
        every other word with a plain aggregate over the same raw columns
        (e.g. "total transit duration" -- actual arrival minus actual
        departure) and still score just as high on overlap alone. If exactly
        one side's text uses delta vocabulary (_DELTA_MARKERS) and the other
        doesn't, that's treated as a strong signal they're NOT the same
        feature, regardless of score."""
        query_tokens = _tokens(feature_name, description)
        query_cols = set(source_columns or [])
        query_has_delta = bool(query_tokens & _DELTA_MARKERS)
        if not query_tokens:
            return None

        best: tuple[float, dict] | None = None
        with self._lock:
            candidates = list(self._features)
        for entry in candidates:
            entry_tokens = _tokens(entry.get("name", ""), entry.get("description", ""))
            if not entry_tokens:
                continue
            if query_has_delta != bool(entry_tokens & _DELTA_MARKERS):
                continue

            # Overlap coefficient (intersection / smaller set) rather than
            # Jaccard -- a short name like "transit_duration" (2 tokens)
            # shouldn't need to share most of a longer description's
            # vocabulary to count as the same feature.
            overlap = len(query_tokens & entry_tokens) / min(len(query_tokens), len(entry_tokens))

            col_bonus = 0.0
            entry_cols = set(entry.get("source_columns") or [])
            if query_cols and entry_cols:
                col_overlap = len(query_cols & entry_cols) / min(len(query_cols), len(entry_cols))
                col_bonus = 0.25 * col_overlap

            score = overlap + col_bonus
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, entry)
        return dict(best[1]) if best else None

    # -- writes -----------------------------------------------------------

    def upsert(
        self,
        *,
        name: str,
        description: str,
        source: str,
        output_column: str,
        spec_type: str,
        formula: str,
        python_code: str | None,
        data_type: str,
        dependencies: list[str],
        source_columns: list[str],
        spec: dict,
        kpi_id: str | None = None,
    ) -> dict:
        """Creates a new entry, or -- if `kpi_id` names an existing one --
        replaces it with an incremented `version` (a feature re-derived with
        a changed formula/source is still "the same feature", just a new
        version of it, per the KPI Store's own example schema)."""
        with self._lock:
            existing = next((f for f in self._features if f.get("id") == kpi_id), None) if kpi_id else None
            entry_id = kpi_id or f"{_SOURCE_ID_PREFIX.get(source, 'kpi')}_{uuid.uuid4().hex[:10]}"
            # The applied spec's own "id" field is what feature_engineering.py
            # actually runs with and what shows up as the computed result's
            # id -- keep it in lockstep with the registry entry's id so a
            # caller that reads `entry["spec"]` back gets the same bucketing
            # marker as `entry["id"]` itself.
            spec = {**spec, "id": entry_id}
            entry = {
                "id": entry_id,
                "name": name,
                "description": description,
                "source": source,
                "output_column": output_column,
                "type": spec_type,
                "source_columns": source_columns,
                "formula": formula,
                "python_code": python_code,
                "data_type": data_type,
                "dependencies": dependencies,
                "version": (existing.get("version", 0) if existing else 0) + 1,
                "created_at": existing.get("created_at") if existing else _now(),
                "updated_at": _now(),
                "spec": spec,
            }
            self._features = [f for f in self._features if f.get("id") != entry_id]
            self._features.append(entry)
            self._flush()
            return dict(entry)


store = KpiStore()
