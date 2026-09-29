"""Per-session analysis repository: the single place every candidate
analysis lands, regardless of which of the five sources proposed it --

  predefined -- parsed from the uploaded Analysis Profile file
  planner    -- Planner Agent recommendations the PM approved
  custom     -- typed directly into the Analysis page by the PM
  ai_suggested -- proposed by the AI analysis-suggestion agent
  drilldown  -- created when a PM clicks a suggested follow-up on an
                already-computed analysis (see analysis_agent.suggest_drilldowns)

`predefined` and `planner` are derived, not stored -- they always reflect
whatever is currently in the global Analysis Profile store / that session's
planner_output.json, so re-uploading a profile or re-approving planner
recommendations is picked up automatically. `custom`, `ai_suggested`, and
`drilldown` are the only entries actually persisted to
analysis_repository.json (their accept/reject state and PM-authored/
PM-triggered content can't be re-derived from anywhere else). Every read
rebuilds the full merged view.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.config import DATA_DIR
from app.services.analysis import analysis_definitions_store as defs_store

_SESSIONS_DIR = DATA_DIR / "sessions"

_PERSISTED_SOURCES = {"custom", "ai_suggested", "drilldown"}


def _session_dir(session_id: str) -> Path:
    d = _SESSIONS_DIR / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _repo_path(session_id: str) -> Path:
    return _session_dir(session_id) / "analysis_repository.json"


def _planner_output_path(session_id: str) -> Path:
    return _session_dir(session_id) / "planner_output.json"


def _predefined_entries() -> list[dict]:
    if defs_store.store.definitions is None:
        return []
    entries = []
    for spec in defs_store.store.definitions:
        entries.append({
            "id": f"predefined_{spec['id']}",
            "source": "predefined",
            "status": "approved",
            "name": spec["name"],
            "description": spec.get("description", ""),
            "calculation_intent": spec["calculation_intent"],
            "input_columns": spec.get("input_columns", []),
            # A predefined spec may ship its own pre-authored formula (skips
            # Think entirely); otherwise the Analysis Agent thinks one up at
            # compute time, same convention as feature_repository's
            # "ai_generated" predefined type.
            "formula": spec.get("formula"),
            "parent_id": None,
            # Optional in analysis_profile.json: the features (by id, output
            # column or name) this analysis consumes.
            "required_features": _profile_feature_refs(spec.get("required_features")),
        })
    return entries


def _profile_feature_refs(raw) -> list[dict]:
    """Normalises an analysis-profile `required_features` list -- each item a
    feature id / output column / name string, or a dict with those keys."""
    refs = []
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            key = item.strip()
            refs.append({"feature_id": key if key.startswith("predefined_") else None, "name": key, "output_column": key})
        elif isinstance(item, dict) and (item.get("feature_id") or item.get("name") or item.get("output_column")):
            refs.append({"feature_id": item.get("feature_id"), "name": item.get("name") or item.get("output_column") or "",
                         "output_column": item.get("output_column")})
    return refs


def predefined_catalog_lines() -> list[str]:
    """Plain-text lines describing every predefined analysis -- fed into the
    Planner's "existing catalog" context so it recommends things NOT already
    covered by the uploaded Analysis Profile."""
    return [f"[analysis] {e['name']}: {e['description']}" for e in _predefined_entries()]


def _planner_entries(session_id: str) -> list[dict]:
    path = _planner_output_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    # Imported here: planner_dependencies itself reads this module's predefined entries.
    from app.services.planner import planner_dependencies

    recs = data.get("recommendations", [])
    slug_to_index = {
        planner_dependencies.slug(r.get("name", "")): j
        for j, r in enumerate(recs) if r.get("type") in ("feature", "feature_and_analysis")
    }
    entries = []
    for i, rec in enumerate(recs):
        if rec.get("pm_decision") != "accepted":
            continue
        if rec.get("type") not in ("analysis", "feature_and_analysis"):
            continue
        if rec.get("analysis_source") == "analysis_profile":
            # Already present as a predefined entry with its own configuration.
            continue
        required = []
        for dep in rec.get("feature_dependencies") or []:
            if dep.get("action") == "reuse_existing" and dep.get("existing_id"):
                required.append({"feature_id": dep["existing_id"], "name": dep["feature_name"],
                                 "output_column": dep.get("output_column")})
            elif planner_dependencies.slug(dep.get("feature_name", "")) in slug_to_index:
                j = slug_to_index[planner_dependencies.slug(dep["feature_name"])]
                required.append({"feature_id": f"planner_{j}", "name": recs[j]["name"],
                                 "output_column": planner_dependencies.slug(recs[j]["name"])})
        if rec.get("type") == "feature_and_analysis" and not required:
            # Older output: the combined recommendation's own feature is the dependency.
            required.append({"feature_id": f"planner_{i}", "name": rec.get("name", ""),
                             "output_column": planner_dependencies.slug(rec.get("name", ""))})
        # The Planner's current schema is flat (name/description/required_fields
        # directly on the recommendation) -- see planner.py's system prompt.
        name = rec.get("name") or f"Planner Analysis {i + 1}"
        entries.append({
            "id": f"planner_analysis_{i}",
            "source": "planner",
            "status": "approved",
            "name": name,
            "description": rec.get("description", ""),
            "calculation_intent": rec.get("description", ""),
            "input_columns": rec.get("required_fields", []),
            # Pre-generated by the Analysis Agent's Think step at Planner
            # suggest time (see planner.py) -- the PM saw and approved THIS
            # plan specifically, so it's carried through verbatim.
            "formula": rec.get("generated_analysis_formula"),
            "parent_id": None,
            "required_features": required,
            "kpi_dependencies": rec.get("kpi_dependencies") or [],
        })
    return entries


def _load_persisted(session_id: str) -> list[dict]:
    path = _repo_path(session_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [e for e in data.get("entries", []) if e.get("source") in _PERSISTED_SOURCES]


def _save(session_id: str, entries: list[dict]) -> None:
    _repo_path(session_id).write_text(
        json.dumps({"session_id": session_id, "entries": entries}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_repository(session_id: str) -> list[dict]:
    """The full merged view: freshly-derived predefined + planner entries,
    plus whatever custom/ai_suggested/drilldown entries this session has
    persisted. Also re-saves the merge so the file on disk always reflects
    the latest Analysis Profile / planner decisions. Returns definitions
    only -- run results (table/chart/interpretation) live in-memory on the
    audit session and are merged in by the router."""
    entries = _predefined_entries() + _planner_entries(session_id) + _load_persisted(session_id)
    _save(session_id, entries)
    return entries


def add_custom_entry(
    session_id: str, name: str, description: str, calculation_intent: str, input_columns: list[str], *,
    formula: str | None = None, template: dict | None = None, chart_recommendation: dict | None = None,
    filters: list[dict] | None = None,
) -> dict:
    """Persists a PM-authored analysis. When it was drafted through the
    Analysis Designer it also carries the reviewed computation logic
    (`formula`), an optional deterministic `template`, the chosen chart, and
    its interactive filters -- all already validated by the caller."""
    entry = {
        "id": f"custom_{uuid.uuid4().hex[:8]}",
        "source": "custom",
        "status": "approved",
        "name": name,
        "description": description or calculation_intent,
        "calculation_intent": calculation_intent,
        "input_columns": input_columns,
        "formula": formula,
        "parent_id": None,
        "template": template,
        "chart_recommendation": chart_recommendation,
        "filters": filters or [],
    }
    persisted = _load_persisted(session_id)
    persisted.append(entry)
    entries = _predefined_entries() + _planner_entries(session_id) + persisted
    _save(session_id, entries)
    return entry


def _normalize_name(name: str) -> str:
    """Shared with analysis_suggester so both dedupe names the same way."""
    return " ".join(name.lower().split())


def add_ai_suggested_entries(session_id: str, suggestions: list[dict]) -> list[dict]:
    """Appends new AI-suggested candidates (status=pending), skipping any
    whose name already exists in the repository (case/whitespace-insensitive)
    so re-running suggestions doesn't pile up duplicates."""
    existing = get_repository(session_id)
    existing_names = {_normalize_name(e["name"]) for e in existing}
    persisted = _load_persisted(session_id)

    new_entries = []
    for s in suggestions:
        if _normalize_name(s["name"]) in existing_names:
            continue
        entry = {
            "id": f"ai_{uuid.uuid4().hex[:8]}",
            "source": "ai_suggested",
            "status": "pending",
            "name": s["name"],
            "description": s.get("description", ""),
            "calculation_intent": s["calculation_intent"],
            "input_columns": s.get("input_columns", []),
            "formula": None,
            "parent_id": None,
        }
        persisted.append(entry)
        new_entries.append(entry)
        existing_names.add(_normalize_name(entry["name"]))

    entries = _predefined_entries() + _planner_entries(session_id) + persisted
    _save(session_id, entries)
    return new_entries


def add_drilldown_entry(session_id: str, parent_id: str, drilldown: dict) -> dict:
    """Persists a new entry for a PM-triggered drilldown. Auto-approved --
    the PM's click on "Explore this" IS the approval, there's no separate
    accept step for a drilldown the way there is for an AI suggestion.
    `chart_type_hint`, when set (see analysis_agent.suggest_drilldowns),
    becomes this entry's own `chart_recommendation` -- the same field a
    predefined/planner/custom entry's PM-reviewed chart lives in -- so
    run_analysis (analysis_engine._recommended_chart) picks it up directly
    instead of running an independent chart-suggestion call that could pick
    something different from the parent, breaking visual consistency down a
    drill chain."""
    chart_type_hint = drilldown.get("chart_type_hint")
    entry = {
        "id": f"drilldown_{uuid.uuid4().hex[:8]}",
        "source": "drilldown",
        "status": "approved",
        "name": drilldown["name"],
        "description": drilldown.get("description", ""),
        "calculation_intent": drilldown["calculation_intent"],
        "input_columns": [],
        "formula": None,
        "parent_id": parent_id,
        "chart_recommendation": (
            {"chart_type": chart_type_hint, "reason": "Matches the parent analysis's chart for a consistent drilldown chain.", "alternatives": []}
            if chart_type_hint else None
        ),
    }
    persisted = _load_persisted(session_id)
    persisted.append(entry)
    entries = _predefined_entries() + _planner_entries(session_id) + persisted
    _save(session_id, entries)
    return entry


def add_chain_entry(
    session_id: str, parent_id: str, *, name: str, description: str, template: dict, chart_type: str,
    filters: list[dict], chain: dict,
) -> dict:
    """Persists one confirmed level of a guided drill-down chain. Its
    deterministic `template` carries the whole narrowed-down scope, so it
    runs without any LLM call."""
    entry = {
        "id": f"drilldown_{uuid.uuid4().hex[:8]}",
        "source": "drilldown",
        "status": "approved",
        "name": name,
        "description": description,
        "calculation_intent": description,
        "input_columns": [],
        "formula": None,
        "parent_id": parent_id,
        "template": template,
        "chart_recommendation": {"chart_type": chart_type, "reason": "Chosen for this drill-down level.", "alternatives": []},
        "filters": filters,
        "chain": chain,
    }
    persisted = _load_persisted(session_id)
    persisted.append(entry)
    _save(session_id, _predefined_entries() + _planner_entries(session_id) + persisted)
    return entry


def update_entry(session_id: str, entry_id: str, fields: dict) -> dict | None:
    """Merges `fields` into one persisted entry (predefined and planner
    entries are derived, so they can't be edited here)."""
    persisted = _load_persisted(session_id)
    found = None
    for e in persisted:
        if e["id"] == entry_id:
            e.update(fields)
            found = e
            break
    if found is None:
        return None
    _save(session_id, _predefined_entries() + _planner_entries(session_id) + persisted)
    return found


def set_entry_status(session_id: str, entry_id: str, status: str) -> dict | None:
    persisted = _load_persisted(session_id)
    found = None
    for e in persisted:
        if e["id"] == entry_id:
            e["status"] = status
            found = e
            break
    if found is None:
        return None
    entries = _predefined_entries() + _planner_entries(session_id) + persisted
    _save(session_id, entries)
    return found


def get_entry(session_id: str, entry_id: str) -> dict | None:
    for e in get_repository(session_id):
        if e["id"] == entry_id:
            return e
    return None
