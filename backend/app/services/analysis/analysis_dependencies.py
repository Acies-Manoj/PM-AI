"""Feature dependencies of an analysis.

An analysis may REQUIRE features (a reusable calculated column it consumes
rather than recomputes). Each requirement is a reference on the repository
entry -- `{"feature_id", "name", "output_column"}` -- resolved here against
the live feature library and the current data:

  satisfied     the feature is approved and its column is in the data
  not_approved  the feature exists but is pending / rejected
  not_computed  approved, but its column has not been computed yet
  missing       no such feature in the library (e.g. the Planner
                recommendation for it was never accepted)

The analysis may run only when every requirement is satisfied. This is
enforced server-side (routers/analysis.py and analysis_engine.run_analysis),
not just in the UI.
"""
from __future__ import annotations

import json
import re

import pandas as pd

from app.config import DATA_DIR
from app.services.features import feature_repository

_SESSIONS_DIR = DATA_DIR / "sessions"

SATISFIED = "satisfied"
NOT_APPROVED = "not_approved"
NOT_COMPUTED = "not_computed"
MISSING = "missing"

_MESSAGES = {
    NOT_APPROVED: "is not approved yet -- select it to continue",
    NOT_COMPUTED: "is approved but not computed yet -- compute the features first",
    MISSING: "is not in the feature library -- add or accept it to continue",
}


def _slug(name: str) -> str:
    return re.sub(r"\W+", "_", (name or "").strip().lower()).strip("_")


def resolve(session_id: str, entry: dict, df: pd.DataFrame) -> list[dict]:
    """The state of every feature `entry` requires, with the feature's own
    definition so the analysis can be told exactly what it must use."""
    library = feature_repository.get_repository(session_id)
    by_id = {e["id"]: e for e in library}
    by_column = {e["output_column"]: e for e in library}
    by_name = {_slug(e["name"]): e for e in library}
    refs = list(entry.get("required_features") or [])
    # An input column that is really a library feature's output (a profile
    # analysis reading "% In Spec") is an implicit dependency on that feature.
    declared = {r.get("output_column") for r in refs} | {r.get("feature_id") for r in refs}
    for column in entry.get("input_columns") or []:
        feature = by_column.get(column)
        if feature and column not in declared and feature["id"] not in declared:
            refs.append({"feature_id": feature["id"], "name": feature["name"], "output_column": column})
    if not refs:
        return []

    resolved = []
    for ref in refs:
        feature = (
            by_id.get(ref.get("feature_id"))
            or by_column.get(ref.get("output_column") or "")
            or by_name.get(_slug(ref.get("name", "")))
        )
        name = (feature or {}).get("name") or ref.get("name") or ref.get("feature_id") or "feature"
        column = (feature or {}).get("output_column") or ref.get("output_column") or _slug(name)
        if feature is None:
            state = MISSING
        elif feature["status"] != "approved":
            state = NOT_APPROVED
        elif column not in df.columns:
            state = NOT_COMPUTED
        else:
            state = SATISFIED
        resolved.append({
            "feature_id": (feature or {}).get("id") or ref.get("feature_id"),
            "name": name,
            "output_column": column,
            "definition": (feature or {}).get("calculation_intent") or (feature or {}).get("description", ""),
            "state": state,
            "satisfied": state == SATISFIED,
            "message": "" if state == SATISFIED else f"'{name}' {_MESSAGES[state]}.",
        })
    return resolved


def unmet(resolved: list[dict]) -> list[dict]:
    return [r for r in resolved if not r["satisfied"]]


def block_message(resolved: list[dict]) -> str | None:
    """None when the analysis may run, else the reason it may not."""
    missing = unmet(resolved)
    if not missing:
        return None
    return "Select all required features before continuing. " + " ".join(m["message"] for m in missing)


def with_required_features(entry: dict, resolved: list[dict]) -> dict:
    """A copy of `entry` carrying the resolved features (so the agent is told
    to use their columns) and their columns among the required inputs."""
    if not resolved:
        return entry
    columns = list(entry.get("input_columns") or [])
    columns += [r["output_column"] for r in resolved if r["output_column"] not in columns]
    return {**entry, "required_features": resolved, "input_columns": columns}


def available_features(session_id: str, df: pd.DataFrame) -> list[dict]:
    """Approved features whose column is already in the data -- the engineered
    building blocks (e.g. "% In Spec") an analysis or drill-down can use."""
    return [
        {"output_column": e["output_column"], "name": e["name"],
         "definition": e.get("calculation_intent") or e.get("description", "")}
        for e in feature_repository.get_approved_entries(session_id)
        if e["output_column"] in df.columns
    ]


def prepare_entry(session_id: str, entry: dict, df: pd.DataFrame) -> dict:
    """The entry as the engine should see it: required features resolved (and
    their columns required), plus every computed feature the drill-down step
    may build on."""
    prepared = with_required_features(entry, resolve(session_id, entry, df))
    return {**prepared, "available_features": available_features(session_id, df)}


def select_feature(session_id: str, feature_id: str) -> bool:
    """Approves one required feature so the analysis can proceed: flips a
    Planner recommendation to accepted, or a persisted feature to approved.
    Predefined (customer KPI) features are always approved. Returns False when
    the feature can't be selected (unknown id)."""
    if feature_id.startswith("planner_"):
        try:
            index = int(feature_id.split("_", 1)[1])
        except ValueError:
            return False
        path = _SESSIONS_DIR / session_id / "planner_output.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        recs = data.get("recommendations", [])
        if not 0 <= index < len(recs) or recs[index].get("type") not in ("feature", "feature_and_analysis"):
            return False
        recs[index]["pm_decision"] = "accepted"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    if feature_id.startswith("predefined_"):
        return True
    return feature_repository.set_entry_status(session_id, feature_id, "approved") is not None
