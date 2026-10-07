"""The Analysis Agent: turns one analysis_repository.json entry into a
computed chart. Every entry -- however it was authored (a predefined
analysis spec, a Planner recommendation, a PM's typed request, an AI
suggestion, or a PM-triggered drilldown) -- has already been reduced to a
plain-English `calculation_intent` by the time it reaches here (see
analysis_repository.py), so this agent has one job regardless of source:
THINK about how to aggregate it, WRITE the pandas code, pick a CHART TYPE
for the resulting table (unless one was already chosen), and INTERPRET the
chart -- all via OpenRouter, never Groq.
The chart itself is drawn from the real table by analysis_charts.py, never
by the LLM. Generated code is never trusted at face value: it runs through
the same AST-sandboxed executor as the Feature Agent (ai_code_executor.py).
Entries that fit a deterministic template skip this agent's code path
entirely (see analysis_engine.py / analysis_templates.py).
"""
from __future__ import annotations

import datetime
import decimal
import json
import math
import re
from dataclasses import dataclass, field

import pandas as pd

from app.config import ANALYSIS_AGENT_MODEL, model_for
from app.services.analysis import analysis_charts
from app.services.analysis.analysis_charts import ChartRoles
from app.services.analysis.analysis_columns import column_catalog
from app.services.common import ai_code_executor, groq_client
from app.prompts import analysis_agent as _prompts

MAX_ATTEMPTS = 3
# A pre-supplied formula (Planner-generated and PM-approved, or a predefined
# spec that shipped with its own formula) is never rethought -- only its
# CODE gets retried against feedback, same rationale as the Feature Agent.
FIXED_FORMULA_MAX_ATTEMPTS = 3

_ALLOWED_CHART_TYPES = set(analysis_charts.CHART_TYPES)
# Upper bound for one OpenRouter call -- the SDK default (10 minutes) would
# leave a Run click hanging far past any useful point. The SDK itself
# retries transient connection/5xx errors.
REQUEST_TIMEOUT_S = 60.0

def call_llm(
    system_prompt: str, user_prompt: str, *, json_mode: bool, temperature: float, call_name: str,
    model: str | None = None, max_tokens: int | None = None,
) -> str:
    model = model or model_for(call_name, ANALYSIS_AGENT_MODEL)
    client = groq_client.get_client().with_options(timeout=REQUEST_TIMEOUT_S, max_retries=2)
    return groq_client.call(
        client, system_prompt, user_prompt,
        model=model, json_mode=json_mode, temperature=temperature, call_name=call_name, max_tokens=max_tokens,
    )


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:python)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def strip_json_fence(text: str) -> str:
    stripped = (text or "").strip()
    match = re.match(r"^```[a-zA-Z]*\s*(.*?)\s*```$", stripped, re.DOTALL)
    return match.group(1).strip() if match else stripped


def describe_columns(df: pd.DataFrame) -> str:
    return column_catalog(df)


def _entry_block(entry: dict) -> str:
    cols_hint = (
        f"\nColumns likely involved (hint, not exhaustive): {', '.join(entry['input_columns'])}"
        if entry.get("input_columns")
        else ""
    )
    return (
        f"Analysis name: {entry['name']}\n"
        f"Description: {entry.get('description', '')}\n"
        f"Calculation intent: {entry['calculation_intent']}"
        f"{cols_hint}"
        f"{_required_features_block(entry)}"
    )


def _required_features_block(entry: dict) -> str:
    """Features this analysis depends on. They are already computed columns:
    the analysis must read them, never rebuild the calculation itself."""
    lines = [
        f"- `{f['output_column']}` ({f.get('name', '')}): {f.get('definition', '')}".rstrip(": ")
        for f in entry.get("required_features") or []
        if f.get("output_column")
    ]
    if not lines:
        return ""
    return (
        "\nREQUIRED FEATURES (already computed as columns of the data -- use these columns directly "
        "and do NOT recompute their calculation inside this analysis):\n" + "\n".join(lines)
    )


def _table_sample_block(table: list[dict], n: int = 8) -> str:
    if not table:
        return "(empty table)"
    return pd.DataFrame(table).head(n).to_string()


# --- Call 1: Think -----------------------------------------------------------

_THINK_SYSTEM = _prompts.THINK_SYSTEM


def plan_text(plan: dict) -> str:
    """Renders a Think result's `steps` array as one numbered paragraph --
    used wherever a single string is needed (LLM prompts, storage, the
    Planner's pre-generated formula). Falls back to a `plan` key for
    anything that hands in the older single-string shape."""
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return plan.get("plan", "")


def think(entry: dict, columns_block: str, feedback: str | None = None) -> dict:
    feedback_block = (
        f"\n\nA PREVIOUS ATTEMPT FAILED: {feedback}\nRevise the plan so this doesn't happen again."
        if feedback
        else ""
    )
    user_prompt = f"{_entry_block(entry)}\n\nCOLUMN CATALOG:\n{columns_block}{feedback_block}\n\nProduce the plan now."
    raw = call_llm(_THINK_SYSTEM, user_prompt, json_mode=True, temperature=0.2, call_name="analysis_agent_think")
    parsed = json.loads(strip_json_fence(raw))
    parsed["plan"] = plan_text(parsed)
    return parsed


# --- Call 2: Write code -------------------------------------------------------

_CODE_SYSTEM = _prompts.CODE_SYSTEM


def _chart_layout_hint(chart_type: str | None) -> str:
    """Tells the code step how the table will be drawn, so it orders the
    columns the way analysis_charts.infer_roles reads them."""
    if not chart_type or chart_type == "table":
        return ""
    if chart_type == "scatter":
        layout = "the x-axis numeric column first, then the y-axis numeric column, then (optionally) a label column"
    else:
        layout = (
            "the category / time-period column first (as readable text, e.g. '2024-03' for a month, sorted "
            "chronologically), then an optional series column if the chart splits by a second category, then "
            "the metric column(s)"
        )
    return f"\n\nThe table will be drawn as a {chart_type} chart. Put {layout}."


def generate_code(
    entry: dict, plan: dict, columns_block: str, feedback: str | None = None, chart_type: str | None = None
) -> str:
    if feedback:
        feedback_block = (
            f"\n\nYOUR PREVIOUS CODE FAILED THIS CHECK: {feedback}\n"
            "Fix the actual problem the feedback describes, not just surface-level syntax."
        )
    else:
        feedback_block = ""
    user_prompt = (
        f"Plan to implement:\n{plan['plan']}\n\n"
        f"Columns available in `df`:\n{columns_block}{_chart_layout_hint(chart_type)}{feedback_block}\n\n"
        "Write the code now."
    )
    raw = call_llm(_CODE_SYSTEM, user_prompt, json_mode=False, temperature=0.1, call_name="analysis_agent_write_code")
    return _strip_code_fence(raw)


# --- Call 2b: Suggest chart (from the logic, before computing) ----------------

# Shared with analysis_designer.py so the Add Analysis form and every run
# describe the chart types identically.
CHART_TYPE_GUIDANCE = _prompts.CHART_TYPE_GUIDANCE

_CHART_SYSTEM = _prompts.CHART_SYSTEM
MAX_CHART_ALTERNATIVES = 2


def suggest_chart(entry: dict, plan: dict) -> dict:
    """Picks the chart from the computation logic, BEFORE any code is written
    or run, so the code step can shape the table for that chart. Returns
    {"chart_type", "reason", "alternatives"}; an unknown type becomes "table"."""
    user_prompt = f"{_entry_block(entry)}\n\nComputation logic:\n{plan['plan']}\n\nSuggest the chart now."
    raw = call_llm(_CHART_SYSTEM, user_prompt, json_mode=True, temperature=0.1, call_name="analysis_agent_chart_suggestion")
    parsed = json.loads(strip_json_fence(raw))
    chart_type = parsed.get("chart_type") if parsed.get("chart_type") in _ALLOWED_CHART_TYPES else "table"
    alternatives = []
    for alt in parsed.get("alternatives") or []:
        alt_type = alt.get("chart_type") if isinstance(alt, dict) else None
        if alt_type in _ALLOWED_CHART_TYPES and alt_type != chart_type and alt_type not in {a["chart_type"] for a in alternatives}:
            alternatives.append({"chart_type": alt_type, "reason": str(alt.get("reason") or "")})
    return {"chart_type": chart_type, "reason": str(parsed.get("reason") or ""), "alternatives": alternatives[:MAX_CHART_ALTERNATIVES]}


def ensure_chart(entry: dict, plan: dict, options: dict) -> None:
    """Fills options["chart_type"] / ["chart_recommendation"] from the logic
    when no chart was chosen yet. A failed suggestion is not fatal: the run
    continues and finish_computation falls back to a default chart."""
    if options.get("chart_type") in _ALLOWED_CHART_TYPES:
        return
    try:
        recommendation = suggest_chart(entry, plan)
    except Exception:
        return
    options["chart_type"] = recommendation["chart_type"]
    options["chart_recommendation"] = recommendation


# --- Chart spec -------------------------------------------------------------
# No LLM call: the figure is built from the real table by
# analysis_charts.build_chart, so no value can be invented or dropped.


# --- Call 4: Interpret ---------------------------------------------------------

_INTERPRET_SYSTEM = _prompts.INTERPRET_SYSTEM


def interpret(entry: dict, plan: dict, table_sample: str, chart_type: str) -> str:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\nChart type: {chart_type}\n\n"
        f"Computed table sample:\n{table_sample}\n\nWrite the interpretation now."
    )
    text = call_llm(_INTERPRET_SYSTEM, user_prompt, json_mode=False, temperature=0.3, call_name="analysis_agent_interpret")
    return text.strip()


# --- Call 5: Suggest drilldowns -----------------------------------------------

# --- Sanity check + orchestration ---------------------------------------------

def is_plausible_table(table: list[dict]) -> tuple[bool, str | None]:
    if not table:
        return False, "The computed table was empty."
    columns = table[0].keys()
    for col in columns:
        values = [row.get(col) for row in table]
        if any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return True, None
    return False, "The computed table has no numeric metric column."


def _json_safe(table: list[dict]) -> list[dict]:
    """Everything in a table must survive JSON: NaN / inf aren't valid (the
    browser's response.json() rejects them) and generated code often returns
    pandas types the response serializer can't write -- a month `Period`,
    timestamps, timedeltas, numpy scalars, Decimals. All become plain
    None / number / string values before a table leaves the agent."""
    def clean(v):
        if v is None or v is pd.NaT:
            return None
        if isinstance(v, (bool, str, int)):
            return v
        if isinstance(v, float):
            return v if math.isfinite(v) else None
        if isinstance(v, pd.Period):
            return str(v)
        if isinstance(v, (datetime.datetime, datetime.date)):  # includes pd.Timestamp
            return v.isoformat()
        if isinstance(v, (datetime.timedelta, pd.Timedelta)):
            return round(v.total_seconds() / 3600, 2)  # hours, matching the data's own duration columns
        if isinstance(v, decimal.Decimal):
            return clean(float(v))
        if hasattr(v, "item"):  # numpy scalar
            try:
                return clean(v.item())
            except (ValueError, TypeError):
                pass
        return str(v)
    return [{k: clean(v) for k, v in row.items()} for row in table]


@dataclass
class AnalysisComputation:
    plan_text: str | None
    generated_code: str | None
    result_table: list[dict] | None = None
    result_columns: list[str] | None = None
    chart_type: str | None = None
    chart_spec: dict | None = None
    interpretation: str | None = None
    error: str | None = None
    # "template" when a deterministic analysis_templates template computed
    # the table, "code" when the Analysis Agent generated pandas code.
    computation_mode: str = "code"
    notes: list[str] = field(default_factory=list)
    # The chart suggested from the computation logic before computing
    # ({"chart_type", "reason", "alternatives"}); None when the chart was
    # already fixed (the PM's choice, or a cached / previous run's).
    chart_recommendation: dict | None = None
    # The analysis_templates spec that computed the table, when one did --
    # set for every source, not just designed entries (see analysis_engine).
    template: dict | None = None
    # Validated filter-column defs ({"column","kind","reason"}) discovered
    # alongside the chart, for EVERY source now -- not just a hand-drafted
    # custom entry (see analysis_engine._design_and_run). None when not yet
    # decided (chart_type was already fixed before this ran).
    filters: list[dict] | None = None


def finish_computation(
    entry: dict, plan: dict, code: str | None, table: list[dict], *,
    chart_type: str | None = None, roles: ChartRoles | None = None, narrate: bool = True,
    computation_mode: str = "code", chart_recommendation: dict | None = None,
) -> AnalysisComputation:
    """The table succeeded (and passed the sanity check) -- draw it as the
    `chart_type` chosen BEFORE computing (see suggest_chart), then interpret
    it. There is no chart choice after the fact: if no chart was chosen (the
    suggestion call failed), a bar chart is used and build_chart degrades it
    to a table if the shape doesn't fit. Guided drill-down proposals are a
    separate, on-demand call (see analysis_drilldown_agent.propose /
    routers/analysis.py's /drilldown/propose) -- not generated here, so a
    fresh run doesn't pay for suggestions the PM may never look at.
    `narrate=False` skips interpretation, which is how a filtered re-run
    stays LLM-free. A failure after the table is recorded as `error` but the
    table/plan/code are still returned, so the cache write isn't lost."""
    table = _json_safe(table)
    computation = AnalysisComputation(
        plan_text=plan["plan"], generated_code=code, result_table=table,
        result_columns=list(table[0].keys()) if table else [], computation_mode=computation_mode,
        chart_recommendation=chart_recommendation,
    )
    sample = _table_sample_block(table)
    try:
        if chart_type not in _ALLOWED_CHART_TYPES:
            computation.notes.append("A chart type couldn't be suggested for this analysis, so a default chart is shown.")
            chart_type = "bar"
        built = analysis_charts.build_chart(table, chart_type, roles)
        computation.chart_type, computation.chart_spec = built.chart_type, built.spec
        computation.notes.extend(built.notes)
    except Exception as exc:
        computation.chart_type = "table"
        computation.error = f"Computed the table but couldn't chart it: {exc}"

    if narrate:
        try:
            computation.interpretation = interpret(entry, plan, sample, computation.chart_type)
        except Exception as exc:
            computation.error = computation.error or f"Computed the table but couldn't interpret it: {exc}"
    return computation


def compute_analysis(entry: dict, df: pd.DataFrame, chart_type: str | None = None, narrate: bool = True) -> AnalysisComputation:
    """Runs the code-generation path for one repository entry.

    If `entry["formula"]` is already set -- pre-generated by the Planner at
    suggest time and approved by the PM, drafted in the Add Analysis form,
    or a predefined spec that shipped with its own formula -- that plan is
    treated as fixed: only code generation is retried against it. Otherwise
    this runs the full think -> write code -> execute loop, retrying with
    feedback up to MAX_ATTEMPTS times. The chart is picked from the logic
    before any code is written (unless `chart_type` is already known) and
    passed to the code step so the table is shaped for it."""
    columns_block = describe_columns(df)
    options = {"chart_type": chart_type, "narrate": narrate, "chart_recommendation": None}
    if entry.get("formula"):
        return _compute_with_fixed_plan(entry, df, columns_block, options)
    return _compute_with_generated_plan(entry, df, columns_block, options)


def _compute_with_fixed_plan(entry: dict, df: pd.DataFrame, columns_block: str, options: dict) -> AnalysisComputation:
    plan = {"plan": entry["formula"]}
    last_feedback: str | None = None
    # The logic is already known, so the chart is picked now -- before any
    # code is written -- and the code is told which chart it's feeding.
    ensure_chart(entry, plan, options)

    for attempt in range(1, FIXED_FORMULA_MAX_ATTEMPTS + 1):
        try:
            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback, chart_type=options["chart_type"])
            table = ai_code_executor.run_generated_table_code(code, df)
            plausible, reason = is_plausible_table(table)
            if plausible:
                return finish_computation(entry, plan, code, table, **options)
            last_feedback = reason
        except Exception as exc:
            last_feedback = str(exc)

    # The approved plan (pre-generated by the Planner, potentially against an
    # earlier column catalog) can no longer be implemented against the
    # CURRENT columns -- e.g. a column it named got dropped by an Audit
    # resolution after the plan was generated. Retrying code-gen alone can
    # never recover from that, since the plan itself is what's stale. As a
    # last resort, fall through to a fresh Think using the current columns,
    # rather than permanently failing on a plan the data has moved past.
    return _compute_with_generated_plan(entry, df, columns_block, options, seed_feedback=last_feedback)


def _compute_with_generated_plan(
    entry: dict, df: pd.DataFrame, columns_block: str, options: dict, seed_feedback: str | None = None
) -> AnalysisComputation:
    plan: dict | None = None
    last_feedback: str | None = seed_feedback

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if plan is None or attempt == MAX_ATTEMPTS:
                plan = think(entry, columns_block, feedback=last_feedback)
                # Chart from the logic, before writing code. Kept across a
                # re-think: the analysis being asked for hasn't changed.
                ensure_chart(entry, plan, options)

            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback, chart_type=options["chart_type"])
            table = ai_code_executor.run_generated_table_code(code, df)
            plausible, reason = is_plausible_table(table)
            if plausible:
                return finish_computation(entry, plan, code, table, **options)
            last_feedback = reason
        except Exception as exc:
            last_feedback = str(exc)

    prefix = "This analysis's approved formula no longer applied to the current data, and a fresh plan also failed: " if seed_feedback else ""
    return AnalysisComputation(
        plan_text=plan.get("plan") if plan else None, generated_code=None,
        error=f"{prefix}{last_feedback}" if last_feedback else "The Analysis Agent could not compute this analysis.",
    )
