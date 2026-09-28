"""Planner Agent service: reads metadata.json + column_metadata.json for a session
and calls OpenRouter to produce structured feature/analysis recommendations."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from app.config import DATA_DIR, OPENROUTER_API_KEY, OPENROUTER_MODEL
from app.services.analysis import analysis_agent
from app.services.common import token_usage
from app.services.features import feature_agent

_SESSIONS_DIR = DATA_DIR / "sessions"

_SYSTEM_PROMPT = """\
You are the Planner Agent for a cold-chain shipment analytics tool. A business user (PM,
not a data engineer) has described what they need in plain language. You are given their
brief (already in English) and a profiled catalog of the dataset's columns.

Your job: read the brief, understand the intent, and produce one recommendation per
DISTINCT thing the brief is asking for — mapped to what can actually be built from
the available columns.

--- GUARDRAILS ---

COLUMN INTEGRITY
- Every "required_fields" entry must use exact column names from the COLUMN CATALOG.
  Inferred or guessed names belong only in "missing_fields".
- Never reference a column not present in the COLUMN CATALOG.
- Do not use columns with role "identifier" in computed features unless the brief
  explicitly asks for record-level breakdown.

BRIEF INTEGRITY
- Do not invent requirements the brief did not ask for.
- If the brief is a single simple ask, return one recommendation — not several.
- If the brief is empty or too vague, return empty "recommendations" — do not fabricate.

RECOMMENDATION TYPES — choose carefully, the type controls which tab the PM sees:

"feature"
  A new calculated column only. No chart. Use when the PM asks for a derived metric
  (e.g. "calculate transit time", "flag overdue shipments") but not a visualisation.

"analysis"
  A chart or breakdown using ONLY columns that already exist in the COLUMN CATALOG
  as raw data — no calculation or new column needed at all.
  Examples: "count shipments by carrier", "show temperature readings over time",
  "list top 10 origins by volume". Use "analysis" liberally — most visualisations
  of raw columns qualify.

"feature_and_analysis"
  Use ONLY when the chart requires a metric that does NOT exist as a raw column
  AND is not already in the catalog. For example, "compliance rate by carrier"
  needs a compliance_rate column that must be computed first.

"configuration"
  A threshold or business rule setting, not a column or chart.

MANDATORY SPLIT — you MUST follow this exactly:
- Exactly 4 recommendations with type "analysis" (charts from raw columns).
- Exactly 4 recommendations with type "feature" or "feature_and_analysis" (new calculated columns).
- Total = 8 recommendations.
- If you cannot think of 4 pure "analysis" charts, choose groupings, trends, or
  distributions of the raw columns — these always qualify as "analysis".

STATUS RULES
- "existing": the catalog already covers this need — cite the catalog entry by name in "reason".
- "create_new": nothing in the catalog covers it.
- "needs_clarification": brief is too vague (missing threshold, ambiguous field) —
  list specific questions in "clarifications_required".

SCOPE
- Do NOT generate formulas, code, SQL, or Excel expressions — describe WHAT, not HOW.

OUTPUT FORMAT
- Return ONLY a valid JSON object. No markdown fences, no prose, no text before or after.
- Any deviation from the schema is a failure.
"""

_JSON_SCHEMA = """{
  "interpreted_requirement": "...",
  "business_objective": "...",
  "recommendations": [
    {
      "type": "feature | analysis | feature_and_analysis | configuration",
      "status": "existing | create_new | needs_clarification",
      "name": "Short human-readable name",
      "description": "One sentence, plain English.",
      "reason": "Why you classified it this way. Cite catalog entry if status is existing.",
      "confidence": 85,
      "feature_definition": {
        "feature_name": "snake_case_name",
        "formula": "Plain-English calculation logic",
        "input_fields": ["exact_column_name_from_catalog"],
        "dimensions": [],
        "filters": [],
        "business_rules": []
      },
      "analysis_definition": {
        "analysis_name": "Title Case Name",
        "objective": "One sentence.",
        "metrics": [],
        "dimensions": [],
        "filters": [],
        "visualization": "bar | line | pie | ranking | scatter | trend | table | heatmap",
        "group_by": [],
        "sort_by": []
      },
      "configuration": null,
      "data_requirements": {
        "required_fields": ["exact column names — must exist in COLUMN CATALOG"],
        "missing_fields": ["anything the brief implies but no column can provide"]
      },
      "validation": {
        "issues": [],
        "warnings": [],
        "clarifications_required": []
      }
    }
  ]
}

Null rules:
- "feature_definition": include only if type is "feature" or "feature_and_analysis", else null.
- "analysis_definition": include only if type is "analysis" or "feature_and_analysis", else null.
- "configuration": include only if type is "configuration", else null."""


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
        return {
            "interpreted_requirement": "No brief provided.",
            "business_objective": "Unknown.",
            "recommendations": [],
        }

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

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set. Add it to your .env file."
        )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    user_prompt = _build_user_prompt(final_brief, columns_block, catalog_block, additional_context)

    response = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    token_usage.record("planner_agent", OPENROUTER_MODEL, response)

    raw = response.choices[0].message.content or ""

    # Strip any accidental markdown fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[-1] if raw.count("```") >= 2 else raw
        raw = raw.lstrip("json").strip()
        if raw.endswith("```"):
            raw = raw[: raw.rfind("```")].strip()

    result = json.loads(raw)

    _attach_generated_formulas(result.get("recommendations", []), columns_block)

    # Cache the raw planner output so /save can attach decisions to it
    (session_dir / "planner_suggest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return result


def _think_entry_for(rec: dict) -> dict:
    """Reshapes one Planner recommendation's feature_definition into the
    entry shape feature_agent.think() expects."""
    fd = rec.get("feature_definition") or {}
    output_column = fd.get("feature_name") or re.sub(r"\W+", "_", rec["name"].strip().lower()).strip("_")
    return {
        "name": rec["name"],
        "output_column": output_column,
        "description": rec.get("description", ""),
        "calculation_intent": fd.get("formula") or rec.get("description", ""),
        "input_columns": fd.get("input_fields", []),
    }


def _analysis_think_entry_for(rec: dict) -> dict:
    """Reshapes one Planner recommendation's analysis_definition into the
    entry shape analysis_agent.think() expects."""
    ad = rec.get("analysis_definition") or {}
    return {
        "name": rec["name"],
        "description": rec.get("description", ""),
        "calculation_intent": ad.get("objective") or rec.get("description", ""),
        "input_columns": rec.get("data_requirements", {}).get("required_fields", []),
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
    time) -- it never fails the whole suggest response."""
    feature_targets = [
        rec for rec in recommendations
        if rec.get("type") in ("feature", "feature_and_analysis") and rec.get("feature_definition")
    ]
    analysis_targets = [
        rec for rec in recommendations
        if rec.get("type") in ("analysis", "feature_and_analysis") and rec.get("analysis_definition")
    ]
    if not feature_targets and not analysis_targets:
        return

    def _run_feature(rec: dict) -> None:
        try:
            plan = feature_agent.think(_think_entry_for(rec), columns_block)
            rec["feature_definition"]["generated_formula"] = plan.get("plan")
        except Exception:
            rec["feature_definition"]["generated_formula"] = None

    def _run_analysis(rec: dict) -> None:
        try:
            plan = analysis_agent.think(_analysis_think_entry_for(rec), columns_block)
            rec["analysis_definition"]["generated_formula"] = plan.get("plan")
        except Exception:
            rec["analysis_definition"]["generated_formula"] = None

    jobs = [(_run_feature, rec) for rec in feature_targets] + [(_run_analysis, rec) for rec in analysis_targets]
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        list(pool.map(lambda job: job[0](job[1]), jobs))
