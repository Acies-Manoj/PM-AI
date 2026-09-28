"""Planner Agent service: reads metadata.json + column_metadata.json for a session
and calls OpenRouter to produce structured feature/analysis recommendations."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import DATA_DIR, OPENROUTER_MODEL
from app.prompts import planner as prompts
from app.services.analysis import analysis_agent
from app.services.common import llm_client
from app.services.features import feature_agent

_SESSIONS_DIR = DATA_DIR / "sessions"


def _build_columns_block(col_meta: dict, row_count: int) -> str:
    lines = []
    for name, m in col_meta.items():
        parts: list[str] = [name, m.get("dtype", "?"), m.get("role", "?")]
        missing = m.get("missing", 0)
        pct = f"{missing / row_count * 100:.1f}%" if row_count else "?"
        parts.append(f"missing={missing}({pct})")
        unique = m.get("unique")
        if unique is not None:
            parts.append(f"unique={unique}")
        top_dict = m.get("top_values") or m.get("counts")
        allowed_list = m.get("allowed_values")
        if top_dict and isinstance(top_dict, dict):
            parts.append(f"top={list(top_dict.keys())[:5]}")
        elif allowed_list and isinstance(allowed_list, list):
            parts.append(f"values={allowed_list[:5]}")
        unit = m.get("unit")
        if unit:
            parts.append(f"unit={unit}")
        mn = m.get("min")
        mx = m.get("max")
        if mn is not None and mx is not None:
            parts.append(f"range=[{mn}, {mx}]")
        lines.append(" | ".join(str(p) for p in parts))
    return "\n".join(lines)


def _build_user_prompt(
    final_brief: str,
    columns_block: str,
    catalog_block: str,
    additional_context: str = "",
) -> str:
    extra = f"\n\nADDITIONAL PM REQUEST:\n{additional_context}" if additional_context.strip() else ""
    return (
        f"CLIENT BRIEF (English):\n{final_brief}\n\n"
        f"COLUMN CATALOG:\n{columns_block}\n\n"
        f"EXISTING FEATURES / ANALYSES (empty if none built yet):\n{catalog_block or 'None'}"
        f"{extra}\n\n"
        "---\n"
        "Produce the recommendations now. Return exactly this JSON — no other text:\n\n"
        + prompts.JSON_SCHEMA
    )


def suggest(session_id: str, additional_context: str = "") -> dict:
    """Call the Planner LLM and return the structured recommendations dict."""
    session_dir = _SESSIONS_DIR / session_id

    col_path = session_dir / "column_metadata.json"
    meta_path = session_dir / "metadata.json"

    if not col_path.exists():
        raise FileNotFoundError(f"column_metadata.json not found for session {session_id}")
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found for session {session_id}")

    col_data = json.loads(col_path.read_text(encoding="utf-8"))
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))

    brief_block = meta_data.get("client_brief", {})
    final_brief = (
        brief_block.get("translated_text")
        or brief_block.get("final_text")
        or brief_block.get("raw_text")
        or ""
    ).strip()

    if not final_brief:
        return {"recommendations": []}

    row_count = col_data.get("row_count", 0)
    columns_block = _build_columns_block(col_data.get("columns", {}), row_count)

    # Load existing catalog if available (grows over time as PM creates features)
    catalog_path = session_dir / "catalog.json"
    lines: list[str] = []
    if catalog_path.exists():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            for entry in catalog.get("features", [])[:25]:
                lines.append(f"[feature] {entry.get('name', '')}: {entry.get('description', '')}")
            for entry in catalog.get("analyses", [])[:25]:
                lines.append(f"[analysis] {entry.get('name', '')}: {entry.get('description', '')}")
        except Exception:
            pass

    # Predefined features/analyses already covered by an uploaded Customer
    # KPI Profile / Analysis Profile -- fed in the same way, so the Planner
    # recommends things NOT already covered by those files instead of
    # duplicating them.
    try:
        from app.services.features import feature_repository
        lines.extend(feature_repository.predefined_catalog_lines()[:25])
    except Exception:
        pass
    try:
        from app.services.analysis import analysis_repository
        lines.extend(analysis_repository.predefined_catalog_lines()[:25])
    except Exception:
        pass

    catalog_block = "\n".join(lines)

    user_prompt = _build_user_prompt(final_brief, columns_block, catalog_block, additional_context)

    raw = llm_client.call(
        prompts.SYSTEM_PROMPT, user_prompt,
        model=OPENROUTER_MODEL, json_mode=False, temperature=0.2, call_name="planner_agent",
        max_tokens=4096,
    )

    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[-1] if raw.count("```") >= 2 else raw
        raw = raw.lstrip("json").strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()

    result = json.loads(raw)
    if "recommendations" not in result or not isinstance(result["recommendations"], list):
        result = {"recommendations": []}

    # Guarantee every array field the frontend renders actually exists, even
    # if the model omitted one -- a missing key here would otherwise blank
    # the whole Planner page (see PlannerPage.tsx's RecommendationCard).
    for rec in result["recommendations"]:
        rec.setdefault("name", "Untitled recommendation")
        rec.setdefault("description", "")
        rec.setdefault("reason", "")
        rec.setdefault("required_fields", [])
        rec.setdefault("missing_fields", [])
        rec.setdefault("clarifications_required", [])

    _attach_generated_formulas(result["recommendations"], columns_block)

    # Cache the raw planner output so /save can attach decisions to it
    (session_dir / "planner_suggest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return result


def _think_entry_for(rec: dict) -> dict:
    """Reshapes one flat Planner recommendation into the entry shape
    feature_agent.think() expects. The Planner no longer proposes its own
    output_column/formula (see the current system prompt) -- output_column
    is always derived from the recommendation's name, and the Think step
    works from the recommendation's own plain-English description."""
    output_column = re.sub(r"\W+", "_", rec["name"].strip().lower()).strip("_")
    return {
        "name": rec["name"],
        "output_column": output_column,
        "description": rec.get("description", ""),
        "calculation_intent": rec.get("description", ""),
        "input_columns": rec.get("required_fields", []),
    }


def _analysis_think_entry_for(rec: dict) -> dict:
    """Reshapes one flat Planner recommendation into the entry shape
    analysis_agent.think() expects."""
    return {
        "name": rec["name"],
        "description": rec.get("description", ""),
        "calculation_intent": rec.get("description", ""),
        "input_columns": rec.get("required_fields", []),
    }


def _attach_generated_formulas(recommendations: list[dict], columns_block: str) -> None:
    """For every feature/feature_and_analysis recommendation, calls the
    Feature Agent's Think step (see feature_agent.py); for every analysis/
    feature_and_analysis recommendation, calls the Analysis Agent's Think
    step (see analysis_agent.py) -- both right now, before the PM ever sees
    them, so the Planner page can show the actual computation/analysis plan
    alongside the description, not just prose, before an accept/reject
    decision is made. Run concurrently since these are independent calls.
    A single Think failure only leaves that one recommendation without a
    formula (the relevant agent will think one up itself later, at compute
    time) -- it never fails the whole suggest response.

    "feature_and_analysis" needs BOTH plans (one to compute the feature, one
    to aggregate it for the chart), so they're stored in two separate flat
    fields rather than nested per-type objects."""
    feature_targets = [rec for rec in recommendations if rec.get("type") in ("feature", "feature_and_analysis")]
    analysis_targets = [rec for rec in recommendations if rec.get("type") in ("analysis", "feature_and_analysis")]
    if not feature_targets and not analysis_targets:
        return

    def _run_feature(rec: dict) -> None:
        try:
            plan = feature_agent.think(_think_entry_for(rec), columns_block)
            rec["generated_feature_formula"] = plan.get("plan")
        except Exception:
            rec["generated_feature_formula"] = None

    def _run_analysis(rec: dict) -> None:
        try:
            plan = analysis_agent.think(_analysis_think_entry_for(rec), columns_block)
            rec["generated_analysis_formula"] = plan.get("plan")
        except Exception:
            rec["generated_analysis_formula"] = None

    jobs = [(_run_feature, rec) for rec in feature_targets] + [(_run_analysis, rec) for rec in analysis_targets]
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        list(pool.map(lambda job: job[0](job[1]), jobs))
