"""Analysis engine: decides HOW each repository entry is computed.

Every entry, whatever its source (predefined, planner, custom,
AI-suggested, drilldown), goes through the same order:

  1. Computation logic -- the entry's saved logic, else the Analysis
     Agent's Think step.
  2. Chart suggestion (from the logic, before computing) and template
     match run in parallel. The template match is an LLM proposal that is
     strictly validated and dry-run on the real data (analysis_designer).
  3. Template fits  -> deterministic pandas (analysis_templates.py), no code.
     No template   -> the Analysis Agent writes and sandbox-runs pandas code
                      for that same logic and chart (analysis_agent.py).

The decision (template spec, or code) is cached per entry with its chart,
so a re-run replays it without asking the LLM again. A cached template or
cached code that no longer fits the current data is dropped and the entry
is designed afresh. Custom entries drafted in the Add Analysis form already
carry the PM-reviewed template and chart, so steps 1-2 are skipped for them.

Either way the chart is drawn from the real table by analysis_charts.py.

`filter_analysis` re-computes an already-run entry on a filtered slice of
the data for the chart's interactive filters. It never calls an LLM: it
reuses the template or the cached code, the chart type already chosen, and
the base run's interpretation (see the router).

Every analysis is computed against the dataframe passed in by the caller,
which is always the CURRENT audited (and feature-engineered) session
dataframe -- this module never reads the original uploaded file.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from app.services.analysis import analysis_agent, analysis_cache, analysis_dependencies, analysis_designer, analysis_filters, analysis_templates
from app.services.analysis.analysis_agent import AnalysisComputation
from app.services.analysis.analysis_filters import FilterSelection
from app.services.analysis.analysis_templates import TemplateError
from app.services.common import ai_code_executor

logger = logging.getLogger(__name__)


def _recommended_chart(entry: dict) -> str | None:
    return (entry.get("chart_recommendation") or {}).get("chart_type")


def _run_template(
    entry: dict, df: pd.DataFrame, template: dict, chart_type: str | None, narrate: bool, plan_text: str | None = None,
) -> AnalysisComputation:
    """Computes `entry` with `template` (raises TemplateError if it no longer
    fits `df`). `plan_text` is the logic shown for it -- the template's own
    step list, so what the PM reads is exactly what ran."""
    output = analysis_templates.execute(template, df)
    rows = analysis_templates.to_records(output.frame)
    if chart_type not in output.allowed_charts:
        chart_type = output.default_chart
    spec = analysis_templates.validate(template, df)
    plan = {"plan": plan_text or entry.get("formula") or analysis_templates.describe(spec)}
    # So the drill-down step won't suggest re-grouping by the column this level already uses.
    plan["group_by"] = [c for c in (template.get("group_by"), template.get("row_dimension")) if isinstance(c, str)]
    computation = analysis_agent.finish_computation(
        entry, plan, None, rows,
        chart_type=chart_type, roles=output.roles, narrate=narrate, computation_mode="template",
    )
    computation.template = template
    return computation


def _template_steps(template: dict, df: pd.DataFrame) -> str:
    spec = analysis_templates.validate(template, df)
    return analysis_agent.plan_text({"steps": analysis_templates.explain_steps(spec)})


def _replay_cached(session_id: str, entry: dict, df: pd.DataFrame, cached: dict, chart_type: str | None) -> AnalysisComputation | None:
    """Replays a cached decision -- template or code -- with its cached
    chart. Returns None (and drops the cache) if it no longer fits the data."""
    cached_chart = cached.get("chart_recommendation")
    options = {
        "chart_type": chart_type or (cached_chart or {}).get("chart_type"),
        "chart_recommendation": None if chart_type else cached_chart,
    }
    plan = {"plan": cached.get("plan_text") or entry.get("formula") or entry["calculation_intent"]}
    try:
        if cached.get("template"):
            computation = _run_template(entry, df, cached["template"], options["chart_type"], True, cached.get("plan_text"))
            computation.chart_recommendation = options["chart_recommendation"]
            computation.filters = cached.get("filters")
            return computation

        # A cache written before charts were cached: pick the chart from the
        # cached logic now -- still BEFORE the code runs.
        analysis_agent.ensure_chart(entry, plan, options)
        table = ai_code_executor.run_generated_table_code(cached["generated_code"], df)
        plausible, reason = analysis_agent.is_plausible_table(table)
        if not plausible:
            raise ValueError(reason)
        computation = analysis_agent.finish_computation(
            entry, plan, cached["generated_code"], table, **options,
        )
        computation.filters = cached.get("filters")
        if options["chart_recommendation"] and not cached_chart:
            analysis_cache.set(session_id, entry, cached["plan_text"], cached["generated_code"], options["chart_recommendation"], filters=cached.get("filters"))
        return computation
    except Exception as exc:
        logger.info("cached computation for %s no longer fits the data: %s", entry["id"], exc)
        analysis_cache.invalidate(session_id, entry["id"])
        return None


def _run_generated(
    session_id: str, entry: dict, df: pd.DataFrame, chart_type: str | None,
    chart_recommendation: dict | None = None, logic: str | None = None,
    filters: list[dict] | None = None,
) -> AnalysisComputation:
    """Code generation for `entry`. `logic` set = implement that already-
    decided logic (instead of the entry's own); the cache is still keyed on
    the stored `entry`, so the next run finds it."""
    compute_entry = {**entry, "formula": logic} if logic else entry
    computation = analysis_agent.compute_analysis(compute_entry, df, chart_type=chart_type)
    if computation.chart_recommendation is None:
        computation.chart_recommendation = chart_recommendation
    if computation.filters is None:
        computation.filters = filters
    if computation.generated_code:
        analysis_cache.set(
            session_id, entry, computation.plan_text, computation.generated_code,
            computation.chart_recommendation, filters=computation.filters,
        )
    return computation


def _design_and_run(session_id: str, entry: dict, df: pd.DataFrame, chart_type: str | None) -> AnalysisComputation:
    """Fresh run for an entry with no cached decision: logic -> (chart
    suggestion || template match) -> template, else generated code."""
    columns_block = analysis_agent.describe_columns(df)
    try:
        plan = {"plan": entry["formula"]} if entry.get("formula") else analysis_agent.think(entry, columns_block)
    except Exception as exc:
        # Can't even plan (LLM down / unparseable): the agent's own retrying
        # think -> code loop takes it from here.
        logger.info("planning failed for %s, falling back to the agent loop: %s", entry["id"], exc)
        return _run_generated(session_id, entry, df, chart_type)

    options = {"chart_type": chart_type, "chart_recommendation": None, "filters": None}
    with ThreadPoolExecutor(max_workers=2) as pool:
        # suggest_chart_and_filters (the same call the "Add Custom Analysis"
        # form already uses) picks the chart AND up to 4 filter columns in
        # one LLM call -- so every source gets real filters now, not just a
        # hand-drafted custom entry.
        chart_job = pool.submit(
            analysis_designer.suggest_chart_and_filters,
            entry["name"], entry.get("description") or entry["calculation_intent"], plan, columns_block, df,
        )
        match_job = pool.submit(
            analysis_designer.match_template,
            entry["name"], entry.get("description") or entry["calculation_intent"], plan, columns_block, df,
        )
        chart_result = chart_job.result()
        options["chart_type"] = chart_result["chart"]["chart_type"]
        options["chart_recommendation"] = chart_result["chart"]
        options["filters"] = chart_result["filters"]
        try:
            match = match_job.result()
        except Exception as exc:
            logger.info("template match failed for %s, using code generation: %s", entry["id"], exc)
            match = {"template": None, "output": None, "reason": ""}

    if match["template"] and match["output"] is not None:
        notes: list[str] = []
        recommendation = options["chart_recommendation"]
        if recommendation:
            recommendation = analysis_designer.reconcile_chart(
                recommendation, match["output"].allowed_charts, match["output"].default_chart, notes,
            )
        chart = (recommendation or {}).get("chart_type") or chart_type
        try:
            steps = _template_steps(match["template"], df)
            computation = _run_template(entry, df, match["template"], chart, True, steps)
        except TemplateError as exc:
            logger.info("matched template failed on the full run for %s: %s", entry["id"], exc)
        else:
            computation.chart_recommendation = recommendation
            computation.filters = options["filters"]
            computation.notes[:0] = notes
            analysis_cache.set(session_id, entry, steps, None, recommendation, template=match["template"], filters=options["filters"])
            return computation

    # No template fits: generated code for the SAME logic and chart.
    return _run_generated(
        session_id, entry, df, options["chart_type"], options["chart_recommendation"], logic=plan["plan"],
        filters=options["filters"],
    )


def run_analysis(session_id: str, entry: dict, df: pd.DataFrame) -> AnalysisComputation:
    """Full run for one entry. Order of preference:
      1. the entry's own (PM-reviewed) template,
      2. a cached decision for this entry (template or code, with its chart),
      3. a fresh design: chart + template match from the logic, then the
         template or generated code.
    Interpretation and drilldowns are never cached."""
    required = entry.get("required_features") or []
    if required and "state" not in required[0]:
        required = analysis_dependencies.resolve(session_id, entry, df)
    blocked = analysis_dependencies.block_message(required)
    if blocked:
        return AnalysisComputation(plan_text=None, generated_code=None, error=blocked)
    missing = [c for c in entry.get("input_columns") or [] if c not in df.columns]
    if missing:
        # Retrying (or re-thinking) can't conjure a column the data no longer
        # has -- most often one dropped in the Audit step (a high-null or
        # constant-column decision) or a feature that hasn't been computed.
        listed = ", ".join(f"'{c}'" for c in missing)
        return AnalysisComputation(
            plan_text=None, generated_code=None,
            error=(
                f"Column {listed} isn't in the current data, so this analysis can't run. "
                "If it was dropped in the Audit step, go back and keep it; if it's a feature, "
                "compute that feature first."
            ),
        )
    chart_type = _recommended_chart(entry)
    fallback_note = None
    if entry.get("template"):
        try:
            return _run_template(entry, df, entry["template"], chart_type, narrate=True)
        except TemplateError as exc:
            fallback_note = f"The template no longer fits the current data ({exc}), so code generation was used."

    computation = None
    cached = analysis_cache.get(session_id, entry)
    if cached:
        computation = _replay_cached(session_id, entry, df, cached, chart_type)

    if computation is None:
        if fallback_note or chart_type:
            # A designed entry (it carries the PM's chart) was already checked
            # against the templates in the Add Analysis form, and the PM
            # reviewed that decision -- don't re-match it (or, if its own
            # template stopped fitting, swap in a different one behind their
            # back). Generate code for their logic.
            computation = _run_generated(session_id, entry, df, chart_type)
        else:
            computation = _design_and_run(session_id, entry, df, chart_type)
    if fallback_note:
        computation.notes.insert(0, fallback_note)
    return computation


_NO_DATA = "No data for the selected filters."


def _filter_error(exc: Exception) -> str:
    """An empty result under filters is an expected outcome, not a failure."""
    message = str(exc)
    if "empty" in message.lower() or "no rows" in message.lower():
        return _NO_DATA
    return f"Couldn't apply these filters: {message}"


def filter_analysis(
    session_id: str, entry: dict, df: pd.DataFrame, selections: dict[str, FilterSelection], chart_type: str | None,
) -> AnalysisComputation:
    """Re-computes `entry` on the rows matching `selections`, with no LLM
    call. `chart_type` is the base run's chart so the filtered view looks
    the same. Returns an error computation (never raises) when the filters
    leave no rows or the entry can't be replayed."""
    defs = entry.get("filters") or []
    subset = analysis_filters.apply(df, defs, selections)
    if subset.empty:
        return AnalysisComputation(plan_text=entry.get("formula"), generated_code=None, error=_NO_DATA)

    cached = analysis_cache.get(session_id, entry)
    template = entry.get("template") or (cached or {}).get("template")
    if template:
        plan_text = None if entry.get("template") else (cached or {}).get("plan_text")
        try:
            return _run_template(entry, subset, template, chart_type, False, plan_text)
        except TemplateError as exc:
            return AnalysisComputation(plan_text=entry.get("formula"), generated_code=None, error=_filter_error(exc))

    if not cached or not cached.get("generated_code"):
        return AnalysisComputation(
            plan_text=entry.get("formula"), generated_code=None,
            error="Run this analysis again before filtering it -- its computation isn't cached.",
        )
    try:
        table = ai_code_executor.run_generated_table_code(cached["generated_code"], subset)
    except ValueError as exc:
        return AnalysisComputation(plan_text=cached["plan_text"], generated_code=cached["generated_code"], error=_filter_error(exc))
    plausible, reason = analysis_agent.is_plausible_table(table)
    if not plausible:
        return AnalysisComputation(plan_text=cached["plan_text"], generated_code=cached["generated_code"], error=reason)
    # chart_type must never be None here -- that would make finish_computation ask the LLM.
    return analysis_agent.finish_computation(
        entry, {"plan": cached["plan_text"]}, cached["generated_code"], table, chart_type=chart_type or "bar", narrate=False,
    )
