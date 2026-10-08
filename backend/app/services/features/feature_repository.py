"""Per-session feature repository: the single place every candidate feature
lands, regardless of which of the four sources proposed it --

  predefined   -- parsed from the uploaded Customer KPI Profile file
  planner      -- Planner Agent recommendations the PM approved
  custom       -- typed directly into the Features page by the PM
  ai_suggested -- proposed by the AI feature-suggestion agent

`predefined` and `planner` are derived, not stored -- they always reflect
whatever is currently in the user's KPI-profile store / that session's
PLAN#<n> documents, so re-uploading a KPI Profile or re-approving planner
recommendations is picked up automatically. `custom` and `ai_suggested`
are the only entries actually persisted, one FEATURE#<id> document each (their
accept/reject state and PM-authored content can't be re-derived from
anywhere else). Every read rebuilds the full merged view.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from app.services.common import doc_store
from app.services.features import feature_definitions_store as defs_store
from app.services.planner import planner_store

_PERSISTED_SOURCES = {"custom", "ai_suggested"}

# One document per persisted feature: FEATURE#<id> (see also feature_cache.py, which keeps the
# final code in the same document under "cache").
DOC_PREFIX = "FEATURE#"
_INTERNAL_KEYS = ("cache", "persisted", "created_at")


# --- describing a structured spec in plain English -----------------------

def _describe_predefined(spec: dict) -> tuple[str, list[str]]:
    """Turns a Customer-KPI-Profile spec (whatever its `type`) into a plain-
    English calculation_intent plus the columns it names -- both just hints
    fed to the Feature Agent's Think step, not executed directly."""
    t = spec.get("type")
    if t == "lookup":
        source = spec.get("source_column", "")
        mapping = spec.get("mapping", {})
        default = spec.get("default_value", "Unknown")
        return (
            f"Look up each row's `{source}` value in this mapping: {mapping}. "
            f"If the value isn't in the mapping, use '{default}'.",
            [source] if source else [],
        )
    if t == "extract_month":
        cols = spec.get("source_columns", [])
        return (
            f"Extract the calendar month name (January-December) from the first "
            f"non-null value among these datetime columns: {', '.join(cols)}.",
            list(cols),
        )
    if t == "ratio":
        num = spec.get("numerator_columns", [])
        den = spec.get("denominator_columns", [])
        return (
            f"Compute (sum of {', '.join(num)}) divided by (sum of {', '.join(den)}), "
            f"times 100, as a percentage. Leave it blank where the denominator is 0.",
            list(num) + list(den),
        )
    if t == "duration_hours":
        start, end = spec.get("start_column", ""), spec.get("end_column", "")
        unit = spec.get("unit", "hours")
        return (
            f"Compute the difference between `{end}` and `{start}` (both datetimes), "
            f"expressed in {unit}.",
            [c for c in (start, end) if c],
        )
    if t == "custom_formula":
        formula = (spec.get("formula") or "").strip()
        cols = re.findall(r"`([^`]+)`", formula)
        return (f"Evaluate this arithmetic formula over the row's columns: {formula}", cols)
    if t == "ai_generated":
        prompt = (spec.get("calculation_prompt") or "").strip()
        return (prompt, [])
    return (spec.get("description", ""), [])


def _predefined_entries(session_id: str) -> list[dict]:
    """Entries derived from the session owner's Customer KPI Profile."""
    _filename, definitions = defs_store.load_for_session(session_id)
    if definitions is None:
        return []
    entries = []
    for spec in definitions:
        intent, cols = _describe_predefined(spec)
        # Every structured type (lookup/ratio/duration_hours/extract_month/
        # custom_formula) is already a fully unambiguous computation -- that
        # IS a formula, just expressed in the KPI Profile's own JSON rather
        # than agent prose, so there's nothing for the Feature Agent to
        # think about. Only "ai_generated" ships as a bare calculation_prompt
        # with no formula yet -- the agent thinks one up at compute time.
        formula = intent if spec.get("type") != "ai_generated" else None
        entries.append({
            "id": f"predefined_{spec['id']}",
            "source": "predefined",
            "status": "approved",
            "name": spec["name"],
            "description": spec.get("description", ""),
            "output_column": spec["output_column"],
            "calculation_intent": intent,
            "input_columns": cols,
            "formula": formula,
        })
    return entries


def predefined_catalog_lines(session_id: str) -> list[str]:
    """Plain-text lines describing every predefined feature -- fed into the
    Planner's "existing catalog" context so it recommends things NOT already
    covered by the uploaded KPI Profile, the same way it already avoids
    re-suggesting its own past recommendations."""
    return [f"[feature] {e['name']}: {e['description']}" for e in _predefined_entries(session_id)]


def _planner_entries(session_id: str) -> list[dict]:
    try:
        recs = planner_store.load(session_id)
    except Exception:
        return []
    entries = []
    for i, rec in enumerate(recs):
        if rec.get("pm_decision") != "accepted":
            continue
        if rec.get("type") not in ("feature", "feature_and_analysis"):
            continue
        # The Planner's current schema is flat (name/description/required_fields
        # directly on the recommendation) -- see planner.py's system prompt.
        # output_column has no Planner-proposed name to reuse, so it's always
        # derived from the recommendation's own name.
        name = rec.get("name") or f"Planner Feature {i + 1}"
        output_column = re.sub(r"\W+", "_", name.strip().lower()).strip("_")
        entries.append({
            "id": f"planner_{i}",
            "source": "planner",
            "status": "approved",
            "name": name,
            "description": rec.get("description", ""),
            "output_column": output_column,
            "calculation_intent": rec.get("description", ""),
            "input_columns": rec.get("required_fields", []),
            # Pre-generated by the Feature Agent's Think step at Planner
            # suggest time (see planner.py) -- the PM saw and approved THIS
            # plan specifically, so it's carried through verbatim rather
            # than re-thought.
            "formula": rec.get("generated_feature_formula"),
            # Analyses that depend on this feature: the Features page labels it
            # REQUIRED FOR ANALYSIS instead of a combined feature+analysis.
            "required_for_analysis": list(rec.get("required_for_analysis") or (
                [name] if rec.get("type") == "feature_and_analysis" else [])),
        })
    return entries


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _doc(entry_id: str) -> str:
    return f"{DOC_PREFIX}{entry_id}"


def _public(doc: dict) -> dict:
    """The entry as the rest of the app knows it (without the document's bookkeeping keys)."""
    return {k: v for k, v in doc.items() if k not in _INTERNAL_KEYS}


def _load_persisted(session_id: str) -> list[dict]:
    """The custom / AI-suggested features of the session, oldest first."""
    docs = doc_store.list_docs(session_id, DOC_PREFIX)
    rows = [
        d for d in docs.values()
        if isinstance(d, dict) and d.get("persisted") and d.get("source") in _PERSISTED_SOURCES
    ]
    rows.sort(key=lambda d: (d.get("created_at", ""), d.get("id", "")))
    return [_public(d) for d in rows]


def _store(session_id: str, entry: dict) -> None:
    """Write one persisted feature to its own FEATURE#<id> document, keeping the final code
    (`cache`) and creation time the document may already hold."""

    def merge(current):
        current = current if isinstance(current, dict) else {}
        doc = {**entry, "persisted": True, "created_at": current.get("created_at") or _now()}
        if current.get("cache"):
            doc["cache"] = current["cache"]
        return doc

    doc_store.update(session_id, _doc(entry["id"]), merge)


def get_repository(session_id: str) -> list[dict]:
    """The full merged view: freshly-derived predefined + planner entries,
    plus whatever custom/ai_suggested entries this session has persisted.
    Read-only: a document is only written when an entry is added or changes
    status (the derived entries are recomputed on every read)."""
    return _predefined_entries(session_id) + _planner_entries(session_id) + _load_persisted(session_id)


def get_approved_entries(session_id: str) -> list[dict]:
    return [e for e in get_repository(session_id) if e["status"] == "approved"]


def add_custom_entry(
    session_id: str, name: str, description: str, calculation_intent: str, input_columns: list[str],
    formula: str | None = None,
) -> dict:
    """`formula` is the PM-reviewed formula from the Add KPI form's draft
    (see feature_designer.py); None for a request added without review."""
    entry = {
        "id": f"custom_{uuid.uuid4().hex[:8]}",
        "source": "custom",
        "status": "approved",
        "name": name,
        "description": description or calculation_intent,
        "output_column": re.sub(r"\W+", "_", name.strip().lower()).strip("_") or f"custom_{uuid.uuid4().hex[:6]}",
        "calculation_intent": calculation_intent,
        "input_columns": input_columns,
        # The PM-reviewed formula, when the request went through the
        # draft/review step: treated as fixed by the Feature Agent, exactly
        # like a Planner-generated one. None = the agent thinks at compute time.
        "formula": formula,
    }
    _store(session_id, entry)
    return entry


def add_ai_suggested_entries(session_id: str, suggestions: list[dict]) -> list[dict]:
    """Appends new AI-suggested candidates (status=pending), skipping any
    whose output_column already exists in the repository (predefined,
    planner, or a previous suggestion) so re-running suggestions doesn't
    pile up duplicates."""
    existing = get_repository(session_id)
    existing_cols = {e["output_column"] for e in existing}

    new_entries = []
    for s in suggestions:
        if s["output_column"] in existing_cols:
            continue
        entry = {
            "id": f"ai_{uuid.uuid4().hex[:8]}",
            "source": "ai_suggested",
            "status": "pending",
            "name": s["name"],
            "description": s.get("description", ""),
            "output_column": s["output_column"],
            "calculation_intent": s["calculation_intent"],
            "input_columns": s.get("input_columns", []),
            "formula": None,
        }
        _store(session_id, entry)
        new_entries.append(entry)
        existing_cols.add(entry["output_column"])
    return new_entries


def set_entry_status(session_id: str, entry_id: str, status: str) -> dict | None:
    found: dict = {}

    def change(current):
        if not isinstance(current, dict) or not current.get("persisted"):
            return current  # derived features are re-derived, their status can't be changed here
        current["status"] = status
        found["entry"] = _public(current)
        return current

    if doc_store.get(session_id, _doc(entry_id)) is None:
        return None
    doc_store.update(session_id, _doc(entry_id), change)
    return found.get("entry")
