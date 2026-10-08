"""Planner Agent service: reads the BRIEF + COLUMN#<name> documents for a session
and calls Bedrock to produce structured feature/analysis recommendations."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from app.config import PLANNER_AGENT_MODEL, model_for
from app.services.analysis import analysis_agent
from app.services.common import column_meta, doc_store, llm, request_context
from app.services.features import feature_agent
from app.services.planner import planner_dependencies, planner_store

_SYSTEM_PROMPT = None  # the system prompt lives in Amazon Bedrock Prompt Management (planner_agent); default text: backend/prompts/<name>.txt

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
    col_data = column_meta.load(session_id)
    meta_data = doc_store.get(session_id, "BRIEF")

    if col_data is None:
        raise FileNotFoundError(f"COLUMN# (column metadata) not found for session {session_id}")
    if meta_data is None:
        raise FileNotFoundError(f"BRIEF (client brief) not found for session {session_id}")

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

    user_prompt = _build_user_prompt(final_brief, columns_block, catalog_block, additional_context)

    raw = llm.chat_json(
        llm.system_prompt("planner_agent", _SYSTEM_PROMPT),
        user_prompt,
        model=model_for("planner_agent", PLANNER_AGENT_MODEL),
        temperature=0.2,
        call_name="planner_agent",
        max_tokens=4096,
    )
    raw = llm.strip_json_fence(raw)

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

    # One PLAN#<n> document per recommendation, so /save can attach the PM's decision to each.
    # A request for MORE suggestions appends; the first call replaces the list.
    planner_store.save_suggestions(session_id, result["recommendations"], append=bool(additional_context.strip()))

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
        # one wrapped callable PER job: a copied Context can only be entered by one thread at a time
        futures = [pool.submit(request_context.wrap(fn), rec) for fn, rec in jobs]
        for f in futures:
            f.result()
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
