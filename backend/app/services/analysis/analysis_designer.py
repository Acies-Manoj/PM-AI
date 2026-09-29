"""The Analysis Designer: turns a PM's plain-English request into a fully
specified analysis BEFORE it is saved, so the PM can review exactly what
will be computed and how it will be drawn.

  1. Computation logic -- the Analysis Agent's Think step writes a precise,
     step-by-step plan (skipped when the PM edited the logic by hand and
     asked to re-check it).
  2. Template match   -- an LLM tries to express that logic as one of the
     deterministic templates in analysis_templates.py. The match is
     validated against the real columns and dry-run on the real data; any
     failure means "no template" and the analysis will use code generation.
  3. Chart + filters  -- an LLM recommends the best chart type (plus
     alternatives) for the logic, and which columns are worth offering as
     interactive filters.

Steps 2 and 3 only depend on step 1, so they run in parallel. Everything
the LLMs return is validated here; nothing is trusted as-is. Runs on
OpenRouter via analysis_agent.call_llm.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from app.services.analysis import analysis_agent, analysis_charts, analysis_filters, analysis_templates
from app.services.analysis.analysis_templates import TemplateError

logger = logging.getLogger(__name__)

TEMPLATE_MATCH_ATTEMPTS = 2
PREVIEW_ROWS = 10
MAX_ALTERNATIVES = 2

_TEMPLATE_SYSTEM = f"""You are the template-matching step of an analytics tool for cold-chain \
shipment data. You are given an analysis request, the computation logic already \
written for it, and the dataset's column catalog. Decide whether the logic can be \
computed EXACTLY by one of the deterministic templates below.

Only choose a template when it computes the same result as the logic -- never an \
approximation. Answer "none" when the logic needs something no template expresses: \
a derived or calculated column, a ratio between two different aggregates, \
period-over-period comparison, joins, ranking within groups, multi-step logic, or \
anything else the parameters can't state.

TEMPLATES:
{analysis_templates.catalog_prompt()}

If the computation logic and the request disagree (e.g. the logic filters rows \
before computing a rate, which would make every rate 100%), match what the request \
asks for. Use column names exactly as they appear in the catalog; omit optional \
parameters you don't need.

Example: request is "% in spec by carrier" but the logic's steps say to filter to \
rows where Status = "In Spec" BEFORE computing the rate -- that would make every \
carrier show 100%. Match the REQUEST instead: a rate_by_group template with no \
pre-filter, computing the true % in spec per carrier from all rows.

Respond with ONLY a JSON object, no markdown:
{{"template_id": "<template id, or none>", "params": {{<the complete template spec including "template_id", or {{}} when none>}}, "reason": "one short sentence"}}"""

_CHART_SYSTEM = """You are the chart-recommendation step of an analytics tool for cold-chain \
shipment data. You are given an analysis request and the computation logic that \
defines the result table -- the table has NOT been computed yet. Recommend how to \
visualise that table, and which source columns a program manager would want as \
interactive filters on the chart.

""" + analysis_agent.CHART_TYPE_GUIDANCE + """

Filters: up to 4 columns from the catalog that are useful to slice this analysis \
by -- key business dimensions (carrier, lane, origin, product, customer, status) and \
the main date column. Never propose the metric being measured, IDs, or free-text \
columns.

Example: analysis is "% in spec by Carrier". Good filters: Product, Origin, Month \
(other dimensions to slice the same rate by). Bad filters to reject: "% in spec" \
itself (the metric being measured, not a slicer), "Shipment ID" (a free-text/ID \
column with one value per row, useless as a filter).

Respond with ONLY a JSON object, no markdown:
{"chart_type": "<type>", "reason": "one short sentence",
 "alternatives": [{"chart_type": "<type>", "reason": "one short sentence"}],
 "filters": [{"column": "exact column name", "reason": "one short sentence"}]}"""


def _json(raw: str) -> dict:
    try:
        parsed = json.loads(analysis_agent.strip_json_fence(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _request_block(name: str, description: str, plan: dict) -> str:
    return f"Analysis name: {name}\nRequest: {description}\n\nComputation logic:\n{plan['plan']}"


def _plan_from_formula(formula: str) -> dict:
    steps = [line.strip().lstrip("0123456789.) ").strip() for line in formula.splitlines() if line.strip()]
    return {"steps": steps, "group_by": [], "metrics": [], "plan": analysis_agent.plan_text({"steps": steps}) or formula}


def match_template(name: str, description: str, plan: dict, columns_block: str, df: pd.DataFrame) -> dict:
    """{"template": spec dict | None, "output": TemplateOutput | None, "reason": str}.
    A candidate is accepted only if it validates AND runs on the real data;
    one retry feeds the failure back to the model."""
    base_prompt = f"{_request_block(name, description, plan)}\n\nCOLUMN CATALOG:\n{columns_block}"
    feedback = ""
    reason = "No template fits this logic, so the Analysis Agent will generate code for it."
    for _ in range(TEMPLATE_MATCH_ATTEMPTS):
        raw = analysis_agent.call_llm(
            _TEMPLATE_SYSTEM, f"{base_prompt}{feedback}\n\nDecide now.",
            json_mode=True, temperature=0.1, call_name="analysis_designer_template_match",
        )
        payload = _json(raw)
        template_id = payload.get("template_id")
        if not template_id or template_id == "none":
            return {"template": None, "output": None, "reason": payload.get("reason") or reason}
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        params["template_id"] = template_id
        try:
            output = analysis_templates.execute(params, df)
            spec = analysis_templates.validate(params, df)
            return {"template": analysis_templates.to_dict(spec), "output": output, "reason": payload.get("reason") or ""}
        except TemplateError as exc:
            logger.info("template candidate %s rejected: %s", template_id, exc)
            reason = f"Closest template ({template_id}) didn't fit the data: {exc} Code generation will be used."
            feedback = (
                f"\n\nYOUR PREVIOUS ANSWER FAILED: {exc}\n"
                "Fix the parameters, or answer \"none\" if no template can express this logic exactly."
            )
    return {"template": None, "output": None, "reason": reason}


def _valid_chart(value) -> str | None:
    return value if value in analysis_charts.CHART_TYPES else None


def suggest_chart_and_filters(name: str, description: str, plan: dict, columns_block: str, df: pd.DataFrame) -> dict:
    user_prompt = f"{_request_block(name, description, plan)}\n\nCOLUMN CATALOG:\n{columns_block}\n\nRecommend now."
    payload = _json(analysis_agent.call_llm(
        _CHART_SYSTEM, user_prompt, json_mode=True, temperature=0.2, call_name="analysis_designer_chart",
    ))
    chart_type = _valid_chart(payload.get("chart_type")) or "table"
    alternatives = []
    for alt in payload.get("alternatives") or []:
        alt_type = _valid_chart(alt.get("chart_type")) if isinstance(alt, dict) else None
        if alt_type and alt_type != chart_type and alt_type not in {a["chart_type"] for a in alternatives}:
            alternatives.append({"chart_type": alt_type, "reason": str(alt.get("reason") or "")})
    filters = analysis_filters.build_defs(payload.get("filters") or [], df)
    return {
        "chart": {"chart_type": chart_type, "reason": str(payload.get("reason") or ""), "alternatives": alternatives[:MAX_ALTERNATIVES]},
        "filters": [f.model_dump() for f in filters],
    }


def reconcile_chart(chart: dict, allowed: tuple[str, ...], default: str, notes: list[str]) -> dict:
    """A template's table only supports some chart shapes -- keep the
    recommendation if it fits, otherwise switch to the template's default."""
    chart = dict(chart)
    if chart["chart_type"] not in allowed:
        notes.append(f"A {chart['chart_type']} chart doesn't fit this table's shape, so {default} is used instead.")
        chart["alternatives"] = [{"chart_type": chart["chart_type"], "reason": chart["reason"]}] + chart["alternatives"]
        chart["chart_type"], chart["reason"] = default, "Best fit for this template's result table."
    chart["alternatives"] = [a for a in chart["alternatives"] if a["chart_type"] in allowed][:MAX_ALTERNATIVES]
    return chart


def draft_analysis(name: str, description: str, df: pd.DataFrame, formula: str | None = None) -> dict:
    """Builds the full draft shown in the Add Analysis form. `formula` set
    means the PM edited the computation logic -- it's used verbatim and only
    the template match / chart / filters are recomputed for it."""
    columns_block = analysis_agent.describe_columns(df)
    if formula and formula.strip():
        plan = _plan_from_formula(formula.strip())
    else:
        entry = {"name": name, "description": description, "calculation_intent": description}
        plan = analysis_agent.think(entry, columns_block)

    with ThreadPoolExecutor(max_workers=2) as pool:
        template_future = pool.submit(match_template, name, description, plan, columns_block, df)
        chart_future = pool.submit(suggest_chart_and_filters, name, description, plan, columns_block, df)
        match, chart_result = template_future.result(), chart_future.result()

    notes: list[str] = []
    chart = chart_result["chart"]
    draft = {
        "name": name,
        "description": description,
        "formula": plan["plan"],
        "formula_steps": plan.get("steps") or [],
        "group_by": plan.get("group_by") or [],
        "metrics": plan.get("metrics") or [],
        "computation_mode": "code",
        "template": None,
        "template_name": None,
        "template_summary": None,
        "template_reason": match["reason"],
        "chart": chart,
        "filters": analysis_filters.options(df, chart_result["filters"]),
        "preview_columns": [],
        "preview_rows": [],
        "preview_chart_spec": None,
        "notes": notes,
    }

    output = match["output"]
    if match["template"] and output is not None:
        spec = analysis_templates.validate(match["template"], df)
        # The template's own explanation replaces the Think step's prose, so
        # the logic the PM reviews is exactly what will run.
        steps = analysis_templates.explain_steps(spec)
        draft["formula"], draft["formula_steps"] = analysis_agent.plan_text({"steps": steps}), steps
        chart = reconcile_chart(chart, output.allowed_charts, output.default_chart, notes)
        rows = analysis_templates.to_records(output.frame)
        built = analysis_charts.build_chart(rows, chart["chart_type"], output.roles)
        notes.extend(built.notes)
        draft.update({
            "computation_mode": "template",
            "template": match["template"],
            "template_name": analysis_templates.CATALOG[spec.template_id].name,
            "template_summary": analysis_templates.describe(spec),
            "chart": chart,
            "preview_columns": list(output.frame.columns),
            "preview_rows": rows[:PREVIEW_ROWS],
            "preview_chart_spec": built.spec,
        })
    return draft


def finalize_custom(
    df: pd.DataFrame, template: dict | None, chart_type: str | None, chart_reason: str,
    chart_alternatives: list[dict], filters: list[dict],
) -> tuple[dict | None, dict | None, list[dict]]:
    """Re-validates what the browser sends back on save -- never trust the
    client's copy of the draft. Returns (template, chart_recommendation,
    filter defs); an invalid template silently degrades to code generation."""
    valid_template = None
    if template:
        try:
            valid_template = analysis_templates.to_dict(analysis_templates.validate(template, df))
        except TemplateError as exc:
            logger.info("dropping client-sent template on save: %s", exc)
    recommendation = None
    if _valid_chart(chart_type):
        alternatives = [
            {"chart_type": a["chart_type"], "reason": str(a.get("reason") or "")}
            for a in chart_alternatives
            if isinstance(a, dict) and _valid_chart(a.get("chart_type")) and a.get("chart_type") != chart_type
        ][:MAX_ALTERNATIVES]
        recommendation = {"chart_type": chart_type, "reason": chart_reason, "alternatives": alternatives}
    defs = [f.model_dump() for f in analysis_filters.build_defs(filters, df)]
    return valid_template, recommendation, defs
