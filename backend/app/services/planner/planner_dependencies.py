"""Deterministic layer around the Planner LLM.

The model decides WHAT the brief asks for and whether an existing customer
KPI / analysis profile entry / feature already covers it. This module gives
it the real catalogs (with ids) to choose from, and then checks everything
it claims against those catalogs -- so a reuse can't point at something that
doesn't exist, a duplicate feature under a new name is folded into the
existing one, and every analysis carries an explicit list of the features it
requires. Source priority when something might already exist:

  1. customer KPI profile   2. analysis profile   3. existing features
  4. existing analyses      5. dataset columns    6. new suggestion
"""
from __future__ import annotations

import re

from app.services.analysis import analysis_repository
from app.services.features import feature_definitions_store, feature_repository

_STOPWORDS = {"by", "of", "the", "per", "and", "for", "a", "an", "to", "in", "each"}
# Ranking / presentation words that belong to an Analysis, never a Feature.
_ANALYSIS_ONLY = re.compile(
    r"\b(rank(?:ing|ed)?|sort(?:ing|ed)?|top[\s-]?\d*|bottom[\s-]?\d*|top[\s-]n|compar(?:e|ison|ing)|chart|graph|"
    r"narrative|insight|conclusion|highest|lowest)\b",
    re.IGNORECASE,
)


def slug(name: str) -> str:
    return re.sub(r"\W+", "_", (name or "").strip().lower()).strip("_")


def _tokens(name: str) -> frozenset[str]:
    return frozenset(w for w in re.sub(r"\W+", " ", (name or "").lower()).split() if w not in _STOPWORDS)


# --- Catalogs shown to the model ----------------------------------------------------


def build_context(session_id: str) -> dict:
    """Every existing definition the Planner must check before proposing
    anything new, each with the id it must cite when reusing it."""
    kpis = []
    specs = feature_definitions_store.store.definitions or []
    by_id = {f"predefined_{s['id']}": s for s in specs}
    for entry in feature_repository._predefined_entries():
        spec = by_id.get(entry["id"], {})
        kpis.append({
            "id": entry["id"], "name": entry["name"], "description": entry["description"],
            "output_column": entry["output_column"], "definition": entry["calculation_intent"],
            "type": spec.get("type", ""),
        })
    features = [
        {"id": e["id"], "name": e["name"], "output_column": e["output_column"], "source": e["source"],
         "status": e["status"], "definition": e.get("calculation_intent") or e.get("description", ""),
         "input_columns": e.get("input_columns", [])}
        for e in feature_repository.get_repository(session_id)
        if e["source"] != "predefined"
    ]
    profile = [
        {"id": e["id"], "name": e["name"], "description": e["description"],
         "intent": e["calculation_intent"], "input_columns": e.get("input_columns", []),
         "required_features": e.get("required_features", [])}
        for e in analysis_repository._predefined_entries()
    ]
    analyses = [
        {"id": e["id"], "name": e["name"], "intent": e["calculation_intent"], "status": e["status"]}
        for e in analysis_repository.get_repository(session_id)
        if e["source"] not in ("predefined", "drilldown")
    ]
    return {"customer_kpis": kpis, "features": features, "analysis_profile": profile, "analyses": analyses}


def render_context(ctx: dict) -> str:
    """Compact text form of `build_context` for the prompt."""
    def block(title: str, rows: list[str]) -> str:
        return f"{title}:\n" + ("\n".join(rows) if rows else "(none)")

    kpis = [f'- id={k["id"]} | {k["name"]} | column={k["output_column"]} | {k["definition"]}' for k in ctx["customer_kpis"]]
    feats = [
        f'- id={f["id"]} | {f["name"]} | column={f["output_column"]} | status={f["status"]} | {f["definition"]}'
        f' | inputs={f["input_columns"]}'
        for f in ctx["features"]
    ]
    profile = [
        f'- id={p["id"]} | {p["name"]} | {p["intent"]} | inputs={p["input_columns"]}'
        + (f' | requires_features={p["required_features"]}' if p["required_features"] else "")
        for p in ctx["analysis_profile"]
    ]
    analyses = [f'- id={a["id"]} | {a["name"]} | {a["intent"]} | status={a["status"]}' for a in ctx["analyses"]]
    return "\n\n".join([
        block("1. CUSTOMER KPIs (customer_kpi.json) -- business definitions, reuse before inventing", kpis),
        block("2. ANALYSIS PROFILE (analysis_profile.json) -- existing analysis definitions", profile),
        block("3. EXISTING FEATURES -- reusable calculated columns already in the library", feats),
        block("4. EXISTING ANALYSES", analyses),
    ])


# --- Checking what the model claimed ------------------------------------------------


def _find_feature(ctx: dict, dep: dict) -> dict | None:
    """The library feature (or customer KPI's feature) a dependency points at:
    by cited id, else by identical output column, else by an equivalent name."""
    pool = ctx["features"] + [
        {"id": k["id"], "name": k["name"], "output_column": k["output_column"], "status": "approved"}
        for k in ctx["customer_kpis"]
    ]
    cited = dep.get("existing_id")
    for f in pool:
        if cited and f["id"] == cited:
            return f
    name = dep.get("feature_name") or ""
    for f in pool:
        if slug(name) == f["output_column"] or slug(name) == slug(f["name"]):
            return f
    tokens = _tokens(name)
    if tokens:
        for f in pool:
            if tokens == _tokens(f["name"]):
                return f
    return None


def _normalize_dependency(dep: dict, ctx: dict) -> dict | None:
    if not isinstance(dep, dict) or not (dep.get("feature_name") or "").strip():
        return None
    name = dep["feature_name"].strip()
    found = _find_feature(ctx, dep)
    action = dep.get("action")
    partial = bool(dep.get("missing_dimension") or dep.get("partial_match"))
    if found and not partial:
        # Claimed reuse of something real, or proposed as new but it IS an
        # existing feature under another name -- either way, never duplicate it.
        reason = dep.get("reason", "") if action == "reuse_existing" else f"Already available as '{found['name']}'."
        return {"feature_name": found["name"], "required": True, "action": "reuse_existing",
                "existing_id": found["id"], "output_column": found["output_column"], "reason": reason}
    out = {"feature_name": name, "required": True, "action": "create_new", "reason": dep.get("reason", "")}
    if partial and found:
        out["reason"] = (out["reason"] + f" (Existing '{found['name']}' lacks: {dep.get('missing_dimension') or 'a required dimension'}.)").strip()
    return out


def _guardrail_warnings(rec: dict) -> list[str]:
    text = f"{rec.get('name', '')} {rec.get('description', '')}"
    hits = sorted({m.group(0).lower() for m in _ANALYSIS_ONLY.finditer(text)})
    return [f"Feature text mentions analysis logic ({', '.join(hits)}); ranking, sorting and comparison belong to the Analysis."] if hits else []


def _split_legacy(rec: dict) -> list[dict]:
    """A `feature_and_analysis` recommendation becomes a feature and an analysis
    that depends on it (older saved output, or a model that still emits it)."""
    if rec.get("type") != "feature_and_analysis":
        return [rec]
    feature = {**rec, "type": "feature", "name": rec["name"]}
    for key in ("generated_analysis_formula", "analysis_logic", "analysis_group_by", "analysis_metrics"):
        feature.pop(key, None)
    analysis = {**rec, "type": "analysis", "feature_dependencies": [{
        "feature_name": rec["name"], "required": True, "action": "create_new",
        "reason": "Derived value required by this analysis.",
    }]}
    for key in ("generated_feature_formula", "feature_formula_expression", "feature_columns_used", "feature_output_dtype"):
        analysis.pop(key, None)
    return [feature, analysis]


def normalize(recs: list[dict], ctx: dict) -> list[dict]:
    """Turns raw model output into the final recommendation list:
    features and analyses separated, dependencies validated against the real
    catalogs, every needed new feature present, and provenance recorded."""
    flat: list[dict] = []
    for rec in recs:
        flat.extend(_split_legacy(rec))

    kpi_ids = {k["id"]: k for k in ctx["customer_kpis"]}
    profile_ids = {p["id"]: p for p in ctx["analysis_profile"]}
    feature_recs = {slug(r["name"]): r for r in flat if r.get("type") == "feature"}

    for rec in flat:
        rec.setdefault("kpi_dependencies", [])
        rec.setdefault("feature_dependencies", [])
        if rec.get("type") != "analysis":
            rec["feature_required"] = False
            continue

        deps = [d for d in (_normalize_dependency(d, ctx) for d in rec["feature_dependencies"] or []) if d]
        # A brief-level "feature is required" flag with no listed dependency is meaningless.
        rec["feature_dependencies"] = deps
        rec["feature_required"] = bool(deps)

        kpis = []
        for k in rec["kpi_dependencies"] or []:
            found = kpi_ids.get((k or {}).get("existing_id") or (k or {}).get("id"))
            if found:
                kpis.append({"name": found["name"], "source": "customer_kpi.json", "action": "reuse_existing",
                             "existing_id": found["id"], "output_column": found["output_column"]})
        rec["kpi_dependencies"] = kpis
        # The KPI is only the business definition; its predefined feature is the
        # implementation the analysis actually consumes.
        listed = {d["existing_id"] for d in deps if d.get("existing_id")}
        for k in kpis:
            if k["existing_id"] not in listed:
                deps.append({"feature_name": k["name"], "required": True, "action": "reuse_existing",
                             "existing_id": k["existing_id"], "output_column": k["output_column"],
                             "reason": f"Implements the customer KPI '{k['name']}'."})
        rec["feature_dependencies"] = deps
        rec["feature_required"] = bool(deps)

        analysis_id = rec.get("existing_analysis_id")
        if analysis_id in profile_ids:
            rec["status"] = "existing"
            rec["analysis_source"] = "analysis_profile"
            rec["existing_analysis_name"] = profile_ids[analysis_id]["name"]
        else:
            rec.pop("existing_analysis_id", None)
            rec["analysis_source"] = "new"

        # Every create_new dependency must exist as a feature recommendation.
        for dep in deps:
            if dep["action"] != "create_new" or slug(dep["feature_name"]) in feature_recs:
                continue
            stub = {
                "name": dep["feature_name"], "type": "feature", "status": "create_new",
                "description": dep.get("reason") or "Reusable calculation required by an analysis.",
                "required_fields": list(rec.get("required_fields", [])), "missing_fields": [],
                "reason": "Required by an analysis; no existing feature covers it.", "clarifications_required": [],
                "feature_dependencies": [], "kpi_dependencies": [], "feature_required": False,
            }
            feature_recs[slug(stub["name"])] = stub
            flat.append(stub)

    # Feature recommendations: who needs them, and provenance for the PM.
    for rec in flat:
        if rec.get("type") == "feature":
            users = [a["name"] for a in flat if a.get("type") == "analysis"
                     and any(slug(d["feature_name"]) == slug(rec["name"]) and d["action"] == "create_new"
                             for d in a["feature_dependencies"])]
            rec["required_for_analysis"] = users
            rec["guardrail_warnings"] = _guardrail_warnings(rec)
            rec["decision_source"] = "new_feature"
        elif rec.get("type") == "analysis":
            rec["decision_source"] = rec["analysis_source"]
    return flat


def dependency_index(recs: list[dict]) -> dict[int, list[int]]:
    """analysis rec index -> indexes of the feature recs it needs created."""
    by_slug = {slug(r["name"]): i for i, r in enumerate(recs) if r.get("type") in ("feature", "feature_and_analysis")}
    out: dict[int, list[int]] = {}
    for i, rec in enumerate(recs):
        if rec.get("type") not in ("analysis", "feature_and_analysis"):
            continue
        idx = [by_slug[slug(d["feature_name"])] for d in rec.get("feature_dependencies") or []
               if d.get("action") == "create_new" and slug(d["feature_name"]) in by_slug]
        if rec.get("type") == "feature_and_analysis" and not idx:
            idx = [i]
        out[i] = idx
    return out
