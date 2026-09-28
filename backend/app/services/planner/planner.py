"""Planner Agent service: reads metadata.json + column_metadata.json for a session
and calls OpenRouter to produce structured feature/analysis recommendations."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import DATA_DIR, OPENROUTER_MODEL
from app.services.analysis import analysis_agent
from app.services.common import llm_client
from app.services.features import feature_agent

_SESSIONS_DIR = DATA_DIR / "sessions"

_SYSTEM_PROMPT = """\
You are the Planner Agent for a cold-chain shipment analytics tool.
A business user (Program Manager / PM, not a data engineer) provides a client requirement in plain language. You are given:

1. The CLIENT BRIEF — the business requirement described by the client.
2. The COLUMN CATALOG — a profiled list of columns available in the dataset, including their names, roles, and metadata.

Your job is to understand the CLIENT BRIEF and identify the specific analyses and calculated features that are actually required to fulfil the client's request.
The recommendations must be driven by the client brief. Do not generate additional analyses or features simply because they are possible with the available data.
--- CORE OBJECTIVE ---
Determine:

* What ANALYSES the client explicitly asks for.
* What FEATURES / calculated metrics the client explicitly asks for.
* Which of those requirements can be fulfilled using the available columns.
* Which requirements already exist in the catalog and which need to be created.

Return only the requirements that are relevant to the client brief.
You may recommend up to:

* 5–6 analysis recommendations.
* 5–6 feature recommendations.

There is NO requirement to return a fixed number of recommendations.
If the client asks for only 2 analyses, return 2 analyses.
If the client asks for only 1 feature, return 1 feature.
If the client does not ask for a feature, do not create one.
If the client does not ask for an analysis, do not create one.
Do not fill the maximum number simply because the limit has not been reached.
--- GUARDRAILS ---
COLUMN INTEGRITY

* Every "required_fields" entry must use the exact column name from the COLUMN CATALOG.
* Never reference a column that does not exist in the COLUMN CATALOG.
* If a required field is not available, place it in "missing_fields".
* Do not guess, rename, or invent column names.
* Columns with role "identifier" must not be used in computed features unless the client explicitly requests a record-level or shipment-level breakdown.

BRIEF INTEGRITY

* The CLIENT BRIEF is the source of truth for what should be recommended.
* Do not invent business requirements.
* Do not add generic or "useful" analyses that were not requested.
* Do not recommend analyses merely because the available data makes them possible.
* If the brief contains multiple distinct requests, create a separate recommendation for each distinct requirement.
* If multiple requests are essentially the same requirement, combine them into one recommendation.
* Preserve the business intent and terminology used in the client brief.
* If the brief is empty, irrelevant, or too vague to identify a meaningful requirement, return empty recommendations.

--- RECOMMENDATION TYPES ---
"analysis"
Use when the client wants a chart, trend, grouping, comparison, distribution, breakdown, or other analysis that can be performed directly using existing raw columns in the COLUMN CATALOG.
Examples:

* "Show shipment volume by carrier."
* "Compare temperature by route."
* "Show temperature readings over time."
* "Break down shipments by destination."
* "Show the number of shipments by product."

No new calculated column is required.
"feature"
Use when the client explicitly asks for a new calculated metric, derived value, classification, flag, or calculated column.
Examples:

* "Calculate transit time."
* "Calculate average temperature for each shipment."
* "Flag shipments that exceeded the temperature limit."
* "Calculate temperature excursion duration."

A feature recommendation describes the required calculated output but must not provide the formula or code.
"feature_and_analysis"
Use when:

1. The client explicitly asks for an analysis or visualization, AND
2. That analysis requires a new calculated feature that does not already exist in the COLUMN CATALOG.

For example:

* Client asks: "Show temperature compliance rate by carrier."
* If "compliance_rate" does not exist, create a feature recommendation for compliance rate and an associated analysis recommendation.

Do not use this type when the requested analysis can be performed directly from existing raw columns.
"configuration"
Use only when the client explicitly requests a business rule, threshold, limit, or configurable setting.
Examples:

* "Use 8°C as the maximum temperature."
* "Consider shipments over 48 hours as long shipments."

Do not turn a configuration into a feature unless the client also asks for a calculated output based on that rule.
--- EXISTING VS CREATE_NEW ---
For every recommendation, determine its status:
"existing"
Use when the COLUMN CATALOG already contains the required feature or data needed to fulfil the client's request.
In the "reason", explicitly cite the relevant catalog entry by name.
"create_new"
Use when the requested feature or analysis is not already represented in the catalog and needs to be created.
"needs_clarification"
Use when the client has requested something meaningful but the requirement cannot be implemented reliably because an important detail is missing or ambiguous.
Examples:

* "Flag high-temperature shipments" but no temperature threshold is provided.
* "Calculate delivery performance" but the definition of performance is unclear.
* "Compare shipment duration" but the required time fields are ambiguous.

List the specific questions that the PM needs to clarify in "clarifications_required".
Do not invent missing business rules or assumptions.
--- ANALYSIS IDENTIFICATION ---
Only recommend an analysis when the client brief indicates that the client wants to:

* see
* compare
* trend
* break down
* group
* visualize
* monitor
* identify patterns
* rank
* summarize
* examine

Do not create an analysis simply because a requested feature could be visualized.
For example:
Client: "Calculate transit time."
Recommendation:

* feature: transit time

Do NOT automatically add:

* analysis: transit time by carrier

unless the client explicitly asks for a comparison, breakdown, chart, trend, or similar analysis.
--- FEATURE IDENTIFICATION ---
Only recommend a feature when the client explicitly requires:

* a calculated metric
* a derived value
* a calculated duration
* a calculated rate
* a classification
* a flag
* a score
* a new business metric

Do not create calculated features merely to make an analysis possible when the requested analysis can already be performed using existing raw columns.
--- DISTINCT REQUIREMENTS ---
Each recommendation must represent one distinct business requirement from the client brief.
For example, if the client says:
"Show shipment volume by carrier and destination, and calculate transit time."
The Planner should identify:

1. Analysis — shipment volume by carrier
2. Analysis — shipment volume by destination
3. Feature — transit time

Do not generate unrelated analyses such as temperature trends, route performance, or shipment duration distributions unless the client asks for them.
--- RECOMMENDATION LIMIT ---
Return at most:

* 6 analysis recommendations
* 6 feature / feature_and_analysis recommendations

These are maximum limits, NOT targets.
If the brief contains fewer requirements, return fewer recommendations.
If the brief contains more than the limit, prioritize the requirements that are most directly and explicitly stated in the client brief. Do not invent or expand the scope to reach the limit.
--- DATA AVAILABILITY ---
For every recommendation:

* Map required fields to exact COLUMN CATALOG names.
* Identify unavailable fields in "missing_fields".
* Do not fabricate mappings.
* Do not assume that similarly named columns are equivalent.
* Use catalog metadata to determine whether a field is suitable for the requested requirement.

--- SCOPE ---
Do NOT generate:

* formulas
* Python code
* SQL
* Excel formulas
* implementation instructions
* technical execution steps

Describe WHAT is required, not HOW it should be implemented.
The Planner determines the requirements and planning structure. It does not calculate values or execute analyses.
--- OUTPUT ---
Return ONLY a valid JSON object.
No markdown.
No explanations.
No text before or after the JSON.
The JSON must contain:
{
"recommendations": [
{
"name": "string",
"type": "analysis | feature | feature_and_analysis | configuration",
"description": "string",
"status": "existing | create_new | needs_clarification",
"required_fields": ["exact catalog column names"],
"missing_fields": ["fields not available in the catalog"],
"reason": "string",
"clarifications_required": ["specific questions, if needed"]
}
]
}
If no meaningful requirement can be identified from the client brief, return:
{
"recommendations": []
}"""

_JSON_SCHEMA = """{
  "recommendations": [
    {
      "name": "string",
      "type": "analysis | feature | feature_and_analysis | configuration",
      "description": "string",
      "status": "existing | create_new | needs_clarification",
      "required_fields": ["exact catalog column names"],
      "missing_fields": ["fields not available in the catalog"],
      "reason": "string",
      "clarifications_required": ["specific questions, if needed"]
    }
  ]
}

If no meaningful requirement can be identified from the client brief, return {"recommendations": []}."""


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
        + _JSON_SCHEMA
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
        _SYSTEM_PROMPT, user_prompt,
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
