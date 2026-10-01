"""Planner Agent service: reads metadata.json + column_metadata.json for a session
and calls OpenRouter to produce structured feature/analysis recommendations."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

from app.config import DATA_DIR, OPENROUTER_API_KEY, PLANNER_AGENT_MODEL, model_for
from app.services.analysis import analysis_agent
from app.services.common import token_usage
from app.services.features import feature_agent
from app.services.planner import planner_dependencies

_SESSIONS_DIR = DATA_DIR / "sessions"

_SYSTEM_PROMPT = """\
You are the Planner Agent for a cold-chain shipment analytics tool.
A business user (Program Manager / PM, not a data engineer) provides a client requirement in plain language. You are given:

1. The CLIENT BRIEF.
2. The COLUMN CATALOG: the raw columns available in the dataset.
3. EXISTING DEFINITIONS, in priority order: customer KPIs (customer_kpi.json), the analysis profile (analysis_profile.json), existing features, existing analyses. Each has an id.

Your job is to work out what the client actually asks for and map it onto what ALREADY EXISTS before proposing anything new. Return only what the brief requires: at most 6 analyses and 6 features, and fewer (or none) when the brief needs fewer. Never pad.

--- CORE PRINCIPLE ---
FEATURE = a reusable calculated building block. It answers "what value do we need?"
ANALYSIS = uses building blocks to answer a business question. It answers "what do we do with that value?"
CUSTOMER KPI = the business meaning of a metric (already defined by the customer).
Never mix them.

A FEATURE describes ONLY a calculation: its inputs, its grouping dimensions (if it is an aggregate), and its output. A feature must NEVER contain ranking, sorting, top/bottom-N selection, comparison, chart logic, business interpretation, narrative or conclusions. Those are the Analysis.
  Wrong: feature "Top Carriers for Origins" with ranking and sorting inside it.
  Right: feature "Shipment Count by Origin and Carrier" (count of trips grouped by Origin and Carrier); the analysis ranks carriers within each origin and shows the top ones.

--- DECISION PROCEDURE (follow in order for every request) ---
1. Understand the business intent: the analysis wanted, the KPI/metric involved, the calculations needed.
2. KPI: is the metric already a customer KPI (section 1)? Compare MEANING, definition and inputs, not just the name ("share of shipments within the delivery window" can be the KPI "On-Time Delivery %"). If yes, reuse its definition; never invent a competing definition.
3. ANALYSIS: does an analysis-profile or existing analysis entry (sections 2, 4) already satisfy the request? Compare intent, dimensions, metrics, filters, ranking. If yes, mark it existing and cite its id in "existing_analysis_id".
4. FEATURE: for each calculation the analysis needs, is it an existing feature or a customer KPI's feature (sections 1, 3)? Compare meaning, formula, inputs, grouping dimensions, output. If it matches, reuse it ("action": "reuse_existing", cite "existing_id").
5. NOT EQUIVALENT means not reusable. "Shipment Count by Carrier" is NOT "Shipment Count by Origin and Carrier" (Origin missing); "Average Temperature" is NOT "Average Temperature Deviation from Product Target". For a partial match, set "action": "create_new" and name what is missing in "missing_dimension". Never reuse a partial match as if it were exact. Never rely on names alone.
6. Can the analysis run DIRECTLY from raw columns (e.g. count Trip ID grouped by Carrier)? Then it needs NO feature: "feature_dependencies": [] and do not invent one. A simple one-off aggregation is analysis logic, not a feature.
7. Create a new feature only when the calculation is genuinely derived or complex, is a business-defined KPI, is an intermediate value another step needs, or is likely reused by several analyses.
8. Each needed new feature is its own recommendation of type "feature"; the analysis lists it in "feature_dependencies". If several analyses need the same calculation, propose ONE feature and list it in each.
9. Do not create a feature or analysis merely because the brief's phrasing differs from an existing one.

--- RECOMMENDATION TYPES ---
"analysis": a chart, trend, ranking, grouping, comparison, distribution or breakdown the client wants to see.
"feature": a reusable calculated value that an analysis (or the client explicitly) needs. When it is only needed by an analysis it is labelled REQUIRED FOR ANALYSIS by the system; do NOT use any combined "feature + analysis" type.
"configuration": only when the client states a business rule, threshold or setting (e.g. "use 8C as the maximum"). Not a feature unless a calculated output is also requested.

Do not add an analysis just because a feature could be charted. "Calculate transit time" alone is a feature only.

--- STATUS ---
"existing": the request is already covered (cite the id in the reason; for analyses also "existing_analysis_id").
"create_new": not covered and needs creating.
"needs_clarification": meaningful but under-specified; list the specific questions in "clarifications_required". Never invent a business rule or threshold.

--- WHEN THE BRIEF DEFINES A METRIC ---
* If the brief DEFINES a calculation, flag or threshold (e.g. "flag a shipment as a major excursion when it is out of spec for more than 12 hours"), each defined step becomes a feature -- a classification such as "Major Excursion Flag" is a feature -- and every analysis about it MUST use that feature.
* Never substitute a different column as a proxy for a defined metric (e.g. do not use "Is Alarmed" for an excursion rate the brief defines from hours out of spec).
* Never drop a threshold or condition the brief states.
* "X by A and by B" means TWO analyses (by A; by B). Only "by A and B together" or "combinations of A and B" is one analysis grouped by both.
* "Scored" shipments are those where the defined feature is not blank: count non-blank feature values, and compute rates over them.
* When you list a feature in an analysis's feature_dependencies, that analysis really is computed from that feature.
* A flag or threshold on a combined value applies to the COMBINED value (e.g. hours out of spec = above-high + below-low, then flag when that total is > 12), never to each part separately.
* Never create a feature just to count shipments or Trip IDs, and never base a count on an unrelated column: counting is analysis logic. The number of "scored" shipments is the count of non-blank values of the defined feature.
* Example: "Show the excursion rate by product and by carrier" -> TWO analyses: "Excursion rate by product" and "Excursion rate by carrier"; "by carrier and destination together" -> ONE analysis grouped by both.

--- GUARDRAILS ---
* Every "required_fields" entry must be an exact COLUMN CATALOG name; unavailable ones go in "missing_fields". Never invent, rename or guess columns, KPI definitions or analysis definitions.
* Columns with role "identifier" must not feed computed features unless the brief asks for a record- or shipment-level breakdown (counting them, e.g. COUNT(Trip ID), is fine).
* The CLIENT BRIEF is the source of truth; do not add requirements it does not state. Distinct requests get separate recommendations; duplicates are merged.
* Do not modify an existing customer KPI or analysis definition to fit the request.
* Do not put ranking, sorting, top-N, comparison, charts or narrative into a feature.
* Do not generate formulas, code, SQL or implementation steps; describe WHAT is required. (Formulas are produced later by a separate step.)
* If the brief is empty, irrelevant or too vague, return {"recommendations": []}.

--- WORKED EXAMPLE ---
CLIENT BRIEF: "Show the top carriers by origin by shipment count and the percentage of shipments in spec. Also show shipment count by carrier."
EXISTING: customer KPI id=predefined_in_spec "% In Spec" (column % In Spec); feature id=planner_2 "Shipment Count by Carrier".
Correct output:
{
  "recommendations": [
    {
      "name": "Top Carriers by Origin",
      "type": "analysis",
      "description": "Within each origin, rank carriers by shipment count and show each carrier's % in spec.",
      "status": "create_new",
      "required_fields": ["Origin", "Carrier", "Trip ID"],
      "missing_fields": [],
      "reason": "No matching analysis exists. Uses the customer KPI '% In Spec' and needs a shipment count per origin and carrier.",
      "clarifications_required": [],
      "existing_analysis_id": null,
      "kpi_dependencies": [{"existing_id": "predefined_in_spec", "name": "% In Spec"}],
      "feature_dependencies": [
        {"feature_name": "Shipment Count by Origin and Carrier", "action": "create_new",
         "reason": "Existing 'Shipment Count by Carrier' has no Origin dimension.", "missing_dimension": "Origin"}
      ]
    },
    {
      "name": "Shipment Count by Origin and Carrier",
      "type": "feature",
      "description": "Number of shipments (count of Trip ID) for each Origin and Carrier combination.",
      "status": "create_new",
      "required_fields": ["Origin", "Carrier", "Trip ID"],
      "missing_fields": [],
      "reason": "Reusable count needed by 'Top Carriers by Origin'. Ranking is done by the analysis, not here.",
      "clarifications_required": []
    },
    {
      "name": "Shipment Count by Carrier",
      "type": "analysis",
      "description": "Number of shipments per carrier.",
      "status": "create_new",
      "required_fields": ["Carrier", "Trip ID"],
      "missing_fields": [],
      "reason": "A plain count grouped by an existing column; no feature is needed.",
      "clarifications_required": [],
      "existing_analysis_id": null,
      "kpi_dependencies": [],
      "feature_dependencies": []
    }
  ]
}
Note: '% In Spec' was reused (not redefined), the existing carrier-only count was NOT reused for the origin+carrier need, no feature was created for the simple carrier count, and the ranking stayed in the analysis.

--- OUTPUT ---
Return ONLY a valid JSON object, no markdown, no other text:
{
  "recommendations": [
    {
      "name": "string",
      "type": "analysis | feature | configuration",
      "description": "string",
      "status": "existing | create_new | needs_clarification",
      "required_fields": ["exact catalog column names"],
      "missing_fields": ["fields not available in the catalog"],
      "reason": "string",
      "clarifications_required": ["specific questions, if needed"],
      "existing_analysis_id": "id from EXISTING DEFINITIONS or null (analyses only)",
      "kpi_dependencies": [{"existing_id": "customer KPI id", "name": "string"}],
      "feature_dependencies": [
        {"feature_name": "string", "action": "reuse_existing | create_new", "existing_id": "id when reusing",
         "reason": "why it is needed", "missing_dimension": "what an existing near-match lacks, if any"}
      ]
    }
  ]
}
"kpi_dependencies", "feature_dependencies" and "existing_analysis_id" apply to analyses only. If nothing is required, return {"recommendations": []}."""

_JSON_SCHEMA = """{
  "recommendations": [
    {
      "name": "string",
      "type": "analysis | feature | configuration",
      "description": "string",
      "status": "existing | create_new | needs_clarification",
      "required_fields": ["exact catalog column names"],
      "missing_fields": ["fields not available in the catalog"],
      "reason": "string",
      "clarifications_required": ["specific questions, if needed"],
      "existing_analysis_id": "string or null",
      "kpi_dependencies": [{"existing_id": "string", "name": "string"}],
      "feature_dependencies": [{"feature_name": "string", "action": "reuse_existing | create_new", "existing_id": "string", "reason": "string", "missing_dimension": "string"}]
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
        f"EXISTING DEFINITIONS (check these before proposing anything new):\n{catalog_block or 'None'}"
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

    # Every existing definition the Planner must check before proposing
    # anything new -- customer KPIs, the analysis profile, existing features
    # and analyses -- with the ids it must cite when it reuses one (see
    # planner_dependencies.py, which also validates those citations).
    context = planner_dependencies.build_context(session_id)
    catalog_block = planner_dependencies.render_context(context)

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
        model=model_for("planner_agent", PLANNER_AGENT_MODEL),
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    token_usage.record("planner_agent", model_for("planner_agent", PLANNER_AGENT_MODEL), response)

    raw = response.choices[0].message.content or ""

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
    result["recommendations"] = [r for r in result["recommendations"] if isinstance(r, dict) and r.get("name")]

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

    # Validate every reuse/dependency claim against the real catalogs, split
    # any combined feature+analysis, and record who needs which feature.
    result["recommendations"] = planner_dependencies.normalize(result["recommendations"], context)
    _flag_empty_columns(result["recommendations"], col_data.get("columns", {}), row_count)
    _attach_generated_formulas(result["recommendations"], columns_block)
    _prune_features(result["recommendations"])
    _sync_feature_columns(result["recommendations"], set(col_data.get("columns", {})))

    # Cache the raw planner output so /save can attach decisions to it
    (session_dir / "planner_suggest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return result


_ANALYSIS_LOGIC = re.compile(
    r"\b(top|bottom|rank(?:ing|ed)?|sort(?:ing|ed)?|highest|lowest|compar(?:e|ison|ing)|chart|graph|narrative|insight)\b",
    re.IGNORECASE,
)


def _prune_features(recommendations: list[dict]) -> None:
    """A feature is a reusable calculation. Drop any feature recommendation that
    has no formula, or whose name or formula is really analysis logic (ranking,
    top/bottom N, sorting, comparison) -- those belong to an analysis. An analysis
    that listed a dropped feature as a new dependency simply stops requiring it."""
    dropped: set[str] = set()
    for rec in list(recommendations):
        if rec.get("type") != "feature":
            continue
        formula = (rec.get("feature_formula_expression") or rec.get("generated_feature_formula") or "").strip()
        if not formula or _ANALYSIS_LOGIC.search(rec.get("name", "")) or _ANALYSIS_LOGIC.search(formula):
            recommendations.remove(rec)
            dropped.add(planner_dependencies.slug(rec["name"]))
    if not dropped:
        return
    for rec in recommendations:
        if rec.get("type") != "analysis":
            continue
        rec["feature_dependencies"] = [
            d for d in rec.get("feature_dependencies") or []
            if not (d.get("action") == "create_new" and planner_dependencies.slug(d.get("feature_name", "")) in dropped)
        ]
        rec["feature_required"] = bool(rec["feature_dependencies"])


EMPTY_COLUMN_SHARE = 0.9


def _flag_empty_columns(recommendations: list[dict], columns: dict, row_count: int) -> None:
    """Warns on a recommendation built on a column that is almost entirely blank
    (it would compute nothing useful, and the Audit drops such columns)."""
    if not row_count:
        return
    for rec in recommendations:
        empty = [
            f"{c} ({columns[c].get('missing', 0) / row_count:.0%} blank)"
            for c in rec.get("required_fields") or []
            if c in columns and columns[c].get("missing", 0) / row_count >= EMPTY_COLUMN_SHARE
        ]
        if empty:
            rec.setdefault("guardrail_warnings", []).append(
                f"Uses almost-empty column(s): {', '.join(empty)}. This will not compute anything useful -- reject it or ask for a different definition."
            )


def _sync_feature_columns(recommendations: list[dict], catalog_columns: set[str]) -> None:
    """A feature's `required_fields` is the model's first guess; its Think step
    then works out the columns the formula actually reads. Show the latter
    (when they are real catalog columns) so the card can't list columns the
    formula never uses, or omit the ones it does."""
    for rec in recommendations:
        if rec.get("type") != "feature":
            continue
        used = [c for c in rec.get("feature_columns_used") or [] if c in catalog_columns]
        if used:
            rec["required_fields"] = used


def _think_entry_for(rec: dict, others: list[dict] | None = None) -> dict:
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
        "other_features": [
            {"name": o["name"], "output_column": planner_dependencies.slug(o["name"]), "description": o.get("description", "")}
            for o in others or []
        ],
    }


def _analysis_think_entry_for(rec: dict, feature_recs: dict[str, dict] | None = None) -> dict:
    """Reshapes one flat Planner recommendation into the entry shape
    analysis_agent.think() expects, including the feature columns the
    analysis must read instead of recomputing."""
    required = []
    for dep in rec.get("feature_dependencies") or []:
        if dep.get("action") == "reuse_existing":
            column, definition = dep.get("output_column"), ""
        else:
            column = planner_dependencies.slug(dep["feature_name"])
            definition = (feature_recs or {}).get(column, {}).get("description", "")
        if column:
            required.append({"name": dep["feature_name"], "output_column": column, "definition": definition})
    return {
        "name": rec["name"],
        "description": rec.get("description", ""),
        "calculation_intent": rec.get("description", ""),
        "input_columns": rec.get("required_fields", []),
        "required_features": required,
    }


def _clean_line(value) -> str | None:
    """A Think step's one-line formula/logic, or None if it's missing or not a string."""
    return value.strip() or None if isinstance(value, str) else None


def _clean_list(value) -> list[str]:
    return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []


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

    feature_by_slug = {planner_dependencies.slug(r["name"]): r for r in recommendations if r.get("type") == "feature"}

    def _run_feature(rec: dict) -> None:
        try:
            siblings = [o for o in feature_targets if o is not rec]
            plan = feature_agent.think(_think_entry_for(rec, siblings), columns_block)
            rec["generated_feature_formula"] = plan.get("plan")
            rec["feature_formula_expression"] = _clean_line(plan.get("formula"))
            rec["feature_columns_used"] = _clean_list(plan.get("columns_used"))
            rec["feature_output_dtype"] = _clean_line(plan.get("output_dtype"))
        except Exception:
            rec["generated_feature_formula"] = None

    def _unused_features(entry: dict, plan: dict) -> list[str]:
        """Required features the plan never mentions (by column or name)."""
        text = f"{plan.get('plan', '')} {plan.get('logic', '')}".lower()
        return [
            f["name"] for f in entry.get("required_features") or []
            if f["output_column"].lower() not in text and f["name"].lower() not in text
        ]

    def _run_analysis(rec: dict) -> None:
        try:
            think_entry = _analysis_think_entry_for(rec, feature_by_slug)
            plan = analysis_agent.think(think_entry, columns_block)
            unused = _unused_features(think_entry, plan)
            if unused:
                # The analysis declares a feature it doesn't use: ask once more, then flag it.
                plan = analysis_agent.think(
                    think_entry, columns_block,
                    feedback=(
                        f"The plan does not use the required feature(s): {', '.join(unused)}. "
                        "Compute the analysis FROM those feature columns (by their exact column names) and do not "
                        "substitute other columns for them."
                    ),
                )
                unused = _unused_features(think_entry, plan)
            if unused:
                rec.setdefault("guardrail_warnings", []).append(
                    f"The plan does not use its required feature(s): {', '.join(unused)}. Reject or re-check this analysis."
                )
            rec["generated_analysis_formula"] = plan.get("plan")
            rec["analysis_logic"] = _clean_line(plan.get("logic"))
            rec["analysis_group_by"] = _clean_list(plan.get("group_by"))
            rec["analysis_metrics"] = _clean_list(plan.get("metrics"))
        except Exception:
            rec["generated_analysis_formula"] = None

    jobs = [(_run_feature, rec) for rec in feature_targets] + [(_run_analysis, rec) for rec in analysis_targets]
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        list(pool.map(lambda job: job[0](job[1]), jobs))
    _order_features_by_dependency(recommendations)
    _inherit_required_for(recommendations)


def _inherit_required_for(recommendations: list[dict]) -> None:
    """A feature that another feature is built on is needed by whatever needs that
    feature, so it is not shown as an orphan ("Needed by: none")."""
    features = [r for r in recommendations if r.get("type") == "feature"]
    columns = {planner_dependencies.slug(r["name"]): r for r in features}
    for _ in range(len(features)):  # repeat so chains of three or more settle
        for rec in features:
            text = f"{rec.get('generated_feature_formula') or ''} {rec.get('feature_formula_expression') or ''}".lower()
            for col, base in columns.items():
                if base is rec or col not in text:
                    continue
                merged = list(dict.fromkeys((base.get("required_for_analysis") or []) + (rec.get("required_for_analysis") or [])))
                base["required_for_analysis"] = merged
                base.setdefault("used_by_features", [])
                if rec["name"] not in base["used_by_features"]:
                    base["used_by_features"].append(rec["name"])


def _order_features_by_dependency(recommendations: list[dict]) -> None:
    """Features are computed in list order and each may read the columns of the
    ones before it, so a feature whose plan reads another new feature's column
    must come after it. Moves only such features; everything else keeps its place."""
    features = [r for r in recommendations if r.get("type") == "feature"]
    columns = {planner_dependencies.slug(r["name"]): r for r in features}

    def reads(rec: dict) -> list[dict]:
        text = f"{rec.get('generated_feature_formula') or ''} {rec.get('feature_formula_expression') or ''}".lower()
        own = planner_dependencies.slug(rec["name"])
        return [o for col, o in columns.items() if col != own and col in text]

    for rec in list(features):
        for needed in reads(rec):
            if recommendations.index(needed) > recommendations.index(rec) and rec not in reads(needed):
                recommendations.remove(needed)
                recommendations.insert(recommendations.index(rec), needed)
