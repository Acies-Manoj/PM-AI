"""The Analysis Agent: turns one analysis_repository.json entry into a
computed chart. Every entry -- however it was authored (a predefined
analysis spec, a Planner recommendation, a PM's typed request, an AI
suggestion, or a PM-triggered drilldown) -- has already been reduced to a
plain-English `calculation_intent` by the time it reaches here (see
analysis_repository.py), so this agent has one job regardless of source:
THINK about how to aggregate it, WRITE the pandas code, pick a CHART TYPE
for the resulting table, WRITE the chart spec, INTERPRET the chart, and
SUGGEST follow-up drilldowns -- all via OpenRouter, never Groq. Generated
code is never trusted at face value: it runs through the same AST-sandboxed
executor as the Feature Agent (ai_code_executor.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd
from openai import OpenAI

from app.config import ANALYSIS_AGENT_MODEL, OPENROUTER_API_KEY
from app.services import ai_code_executor

MAX_ATTEMPTS = 3
# A pre-supplied formula (Planner-generated and PM-approved, or a predefined
# spec that shipped with its own formula) is never rethought -- only its
# CODE gets retried against feedback, same rationale as the Feature Agent.
FIXED_FORMULA_MAX_ATTEMPTS = 3

_ALLOWED_TRACE_TYPES = {"bar", "scatter", "pie", "heatmap", "box"}
_ALLOWED_CHART_TYPES = {"bar", "line", "pie", "scatter", "grouped_bar", "heatmap", "table"}

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Add your key from https://openrouter.ai/keys to backend/.env"
            )
        _client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
    return _client


def _call(system_prompt: str, user_prompt: str, *, json_mode: bool, temperature: float) -> str:
    client = _get_client()
    kwargs: dict = {
        "model": ANALYSIS_AGENT_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if json_mode:
        try:
            response = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception:
            response = client.chat.completions.create(**kwargs)
    else:
        response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:python)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def _strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```", 2)[-1] if stripped.count("```") >= 2 else stripped
        stripped = stripped[4:].strip() if stripped.lower().startswith("json") else stripped
    return stripped


def describe_columns(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)


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
    )


def _table_sample_block(table: list[dict], n: int = 8) -> str:
    if not table:
        return "(empty table)"
    return pd.DataFrame(table).head(n).to_string()


# --- Call 1: Think -----------------------------------------------------------

_THINK_SYSTEM = """You are the planning step of the Analysis Agent for a cold-chain shipment \
analytics tool. You are given one requested analysis and the full column \
catalog of the current dataset. Produce a precise, unambiguous, step-by-step \
plan for computing an AGGREGATED TABLE that a chart can be built from -- \
e.g. a group-by with one or more metrics, a time trend, a ranking, or a \
distribution. This is NOT a per-row calculation like a feature column; the \
output table almost always has FEWER rows than the source data.

The plan MUST:
- Name the EXACT column(s) from the catalog it uses. Never invent a column \
name that isn't in the catalog.
- State what to group by (if anything) and what metric(s) to aggregate \
(sum, mean, count, min, max, median, distinct count, or share of total).
- State how nulls / missing values are handled.
- Be specific enough that a pandas engineer could implement it without \
asking a follow-up question.
- If the requested analysis genuinely cannot be computed from the available \
columns, say so plainly in the plan instead of inventing a substitute.

Respond with ONLY a JSON object, no markdown, no commentary. `steps` is an \
array of short, self-contained instructions, each written as its own \
sentence with no leading number -- the caller numbers them for display:
{"steps": ["first step", "second step", "..."], "group_by": ["exact column names, or [] if none"], "metrics": ["short description of each aggregated metric"]}"""


def _plan_text(plan: dict) -> str:
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
    raw = _call(_THINK_SYSTEM, user_prompt, json_mode=True, temperature=0.2)
    parsed = json.loads(_strip_json_fence(raw))
    parsed["plan"] = _plan_text(parsed)
    return parsed


# --- Call 2: Write code -------------------------------------------------------

_CODE_SYSTEM = """You are the code-writing step of the Analysis Agent. You are given a \
plan (already decided -- do not second-guess it) for computing an \
AGGREGATED table for a chart. A pandas DataFrame is already available as \
`df`, and `pandas` is already available as `pd`.

Write vectorized pandas code (no explicit for/while loops, no function or \
class definitions, no imports) that implements EXACTLY the given plan and \
assigns the final result -- a pandas DataFrame, one row per group/category/ \
time-bucket, with plain column names describing what each column holds -- \
to a variable named exactly `result`.

Rules:
- Only reference columns that actually appear in the column list given below.
- Never read or write files, never use eval/exec/open, never import \
anything, never call any to_csv/to_excel/read_csv/etc-style I/O method.
- `result` must end up as a DataFrame with a plain RangeIndex (call \
`.reset_index()` after any groupby before assigning to `result`), so every \
grouping column and every metric appears as its own named column.
- Cap the result at a reasonable number of rows for a chart (e.g. sort and \
`.head(50)` for a ranking) rather than returning every group unsorted.
- Round float columns to 2 decimal places for a clean chart.
- Respond with ONLY the Python code. No markdown fences, no explanation, \
no comments."""


def generate_code(entry: dict, plan: dict, columns_block: str, feedback: str | None = None) -> str:
    if feedback:
        feedback_block = (
            f"\n\nYOUR PREVIOUS CODE FAILED THIS CHECK: {feedback}\n"
            "Fix the actual problem the feedback describes, not just surface-level syntax."
        )
    else:
        feedback_block = ""
    user_prompt = (
        f"Plan to implement:\n{plan['plan']}\n\n"
        f"Columns available in `df`:\n{columns_block}{feedback_block}\n\n"
        "Write the code now."
    )
    raw = _call(_CODE_SYSTEM, user_prompt, json_mode=False, temperature=0.1)
    return _strip_code_fence(raw)


# --- Call 3: Choose chart type ------------------------------------------------

_CHART_TYPE_SYSTEM = """You are the chart-selection step of the Analysis Agent. You are given the \
plan that was implemented and a sample of the actual computed table. Choose \
the single best Plotly chart type for this table.

Guidance:
- "bar": one category column + one metric -- rankings, comparisons.
- "grouped_bar": two category columns + one or two metrics.
- "line": a time/ordered column + one or more metrics -- trends.
- "pie": one category column + one metric, few categories (<=8), shares of a whole.
- "scatter": two numeric metrics, no meaningful category grouping.
- "heatmap": two category columns + one numeric metric, many combinations.
- "table": nothing above fits well (too many dimensions, or purely textual).

Respond with ONLY a JSON object, no markdown, no commentary:
{"chart_type": "bar | grouped_bar | line | pie | scatter | heatmap | table", "reason": "one short sentence"}"""


def choose_chart_type(entry: dict, plan: dict, table_sample: str) -> dict:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\n\n"
        f"Computed table sample:\n{table_sample}\n\nChoose the chart type now."
    )
    raw = _call(_CHART_TYPE_SYSTEM, user_prompt, json_mode=True, temperature=0.1)
    parsed = json.loads(_strip_json_fence(raw))
    if parsed.get("chart_type") not in _ALLOWED_CHART_TYPES:
        parsed["chart_type"] = "table"
    return parsed


# --- Call 4: Generate chart spec ----------------------------------------------

_CHART_SPEC_SYSTEM = """You are the chart-authoring step of the Analysis Agent. You are given a \
computed table sample and the chart type already chosen for it. Produce a \
Plotly.js figure spec -- a JSON object with "data" (a list of Plotly trace \
objects) and "layout" (a Plotly layout object) -- that renders this table as \
that chart type, using the REAL column names and REAL values from the \
sample (not placeholders).

Rules:
- Every trace's "type" must be one of: bar, scatter, pie, heatmap, box.
- A "line" chart type means a scatter trace with "mode": "lines" (or "lines+markers").
- A "grouped_bar" chart type means two or more bar traces sharing the same \
x values, with layout.barmode = "group".
- Keep "layout" minimal: at most title, xaxis.title, yaxis.title, barmode. \
Do not set colors, fonts, or sizing -- the frontend applies its own theme.
- If the chart type is "table", still return your best-effort bar chart of \
the first category + first numeric metric rather than an empty spec.

Respond with ONLY a JSON object, no markdown, no commentary, shaped exactly \
{"data": [...], "layout": {...}}."""


class ChartSpecError(ValueError):
    pass

# Layout keys the frontend actually lets through -- anything else (width,
# height, margin, autosize, domain, ...) is dropped rather than trusted, so
# a model that ignores the "keep layout minimal" instruction can never blow
# a trace's axis range or the chart's own sizing out of proportion. Only
# `title` is kept under xaxis/yaxis -- range/domain/type overrides are
# dropped for the same reason.
_ALLOWED_LAYOUT_KEYS = {"title", "barmode"}
_ALLOWED_AXIS_KEYS = {"title"}
# Traces plotted against x/y (as opposed to pie's labels/values or heatmap's z).
_XY_TRACE_TYPES = {"bar", "scatter", "box"}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _sanitize_layout(layout: dict) -> dict:
    clean: dict = {k: v for k, v in layout.items() if k in _ALLOWED_LAYOUT_KEYS}
    for axis_key in ("xaxis", "yaxis"):
        axis = layout.get(axis_key)
        if isinstance(axis, dict):
            axis_clean = {k: v for k, v in axis.items() if k in _ALLOWED_AXIS_KEYS}
            if axis_clean:
                clean[axis_key] = axis_clean
    return clean


def _validate_trace(trace) -> None:
    if not isinstance(trace, dict) or trace.get("type") not in _ALLOWED_TRACE_TYPES:
        raise ChartSpecError(f"Chart spec has an unsupported trace type: {trace.get('type') if isinstance(trace, dict) else trace!r}.")

    ttype = trace["type"]
    if ttype in _XY_TRACE_TYPES:
        x, y = trace.get("x"), trace.get("y")
        if not isinstance(x, list) or not isinstance(y, list) or not x or not y:
            raise ChartSpecError(f"A '{ttype}' trace needs non-empty 'x' and 'y' lists.")
        if len(x) != len(y):
            raise ChartSpecError(f"A '{ttype}' trace's 'x' and 'y' lists have different lengths ({len(x)} vs {len(y)}).")
        if not all(_is_number(v) for v in y):
            raise ChartSpecError(f"A '{ttype}' trace's 'y' values must all be numbers.")
    elif ttype == "pie":
        labels, values = trace.get("labels"), trace.get("values")
        if not isinstance(labels, list) or not isinstance(values, list) or not labels or not values:
            raise ChartSpecError("A 'pie' trace needs non-empty 'labels' and 'values' lists.")
        if len(labels) != len(values):
            raise ChartSpecError(f"A 'pie' trace's 'labels' and 'values' lists have different lengths ({len(labels)} vs {len(values)}).")
        if not all(_is_number(v) for v in values):
            raise ChartSpecError("A 'pie' trace's 'values' must all be numbers.")
    elif ttype == "heatmap":
        z = trace.get("z")
        if not isinstance(z, list) or not z or not all(isinstance(row, list) and row for row in z):
            raise ChartSpecError("A 'heatmap' trace needs a non-empty 2D 'z' array.")


def _validate_and_sanitize_chart_spec(spec: dict) -> dict:
    if not isinstance(spec, dict) or "data" not in spec or "layout" not in spec:
        raise ChartSpecError("Chart spec must be a JSON object with 'data' and 'layout' keys.")
    if not isinstance(spec["data"], list) or not spec["data"]:
        raise ChartSpecError("Chart spec's 'data' must be a non-empty list of traces.")
    if not isinstance(spec["layout"], dict):
        raise ChartSpecError("Chart spec's 'layout' must be an object.")
    for trace in spec["data"]:
        _validate_trace(trace)
    return {"data": spec["data"], "layout": _sanitize_layout(spec["layout"])}


def generate_chart_spec(entry: dict, plan: dict, chart_type: str, table_sample: str) -> dict:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\n\n"
        f"Chosen chart type: {chart_type}\n\n"
        f"Computed table sample:\n{table_sample}\n\nProduce the chart spec now."
    )
    raw = _call(_CHART_SPEC_SYSTEM, user_prompt, json_mode=True, temperature=0.2)
    spec = json.loads(_strip_json_fence(raw))
    return _validate_and_sanitize_chart_spec(spec)


# --- Call 5: Interpret ---------------------------------------------------------

_INTERPRET_SYSTEM = """You are the interpretation step of the Analysis Agent. You are given one \
computed analysis table and its chart type. Write a short, plain-English \
interpretation of what this chart shows -- the standout value(s), any clear \
pattern, and why it might matter to a program manager. Do NOT invent any \
number that isn't in the table. Write 2-4 plain sentences, no markdown, no \
bullet lists."""


def interpret(entry: dict, plan: dict, table_sample: str, chart_type: str) -> str:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\nChart type: {chart_type}\n\n"
        f"Computed table sample:\n{table_sample}\n\nWrite the interpretation now."
    )
    text = _call(_INTERPRET_SYSTEM, user_prompt, json_mode=False, temperature=0.3)
    return text.strip()


# --- Call 6: Suggest drilldowns -----------------------------------------------

_DRILLDOWN_SYSTEM = """You are the drilldown-suggestion step of the Analysis Agent. Given an \
analysis that was just computed and interpreted, propose up to 3 genuinely \
useful FOLLOW-UP analyses a program manager might want to explore next -- \
e.g. breaking a top-level finding down by another dimension, or zooming \
into the specific group/time-period that stood out. Every suggestion MUST \
reference only columns that appear in the given column list -- never invent \
a column name.

Respond with ONLY a JSON object, no markdown, no commentary:
{"drilldowns": [
  {
    "name": "short title",
    "description": "one plain-English sentence on what this drilldown would show",
    "calculation_intent": "a precise, unambiguous plain-English description of exactly how to compute this from the columns below"
  }
]}"""


def suggest_drilldowns(entry: dict, plan: dict, table_sample: str, interpretation: str, columns_block: str) -> list[dict]:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\n\n"
        f"Computed table sample:\n{table_sample}\n\nInterpretation:\n{interpretation}\n\n"
        f"COLUMN CATALOG:\n{columns_block}\n\nPropose the drilldowns now."
    )
    raw = _call(_DRILLDOWN_SYSTEM, user_prompt, json_mode=True, temperature=0.4)
    payload = json.loads(_strip_json_fence(raw))
    candidates = payload.get("drilldowns", [])
    if not isinstance(candidates, list):
        return []

    drilldowns: list[dict] = []
    for spec in candidates:
        if not isinstance(spec, dict):
            continue
        if not spec.get("name") or not spec.get("calculation_intent"):
            continue
        drilldowns.append({
            "name": spec["name"],
            "description": spec.get("description", ""),
            "calculation_intent": spec["calculation_intent"],
        })
    return drilldowns[:3]


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


@dataclass
class AnalysisComputation:
    plan_text: str | None
    generated_code: str | None
    result_table: list[dict] | None = None
    result_columns: list[str] | None = None
    chart_type: str | None = None
    chart_spec: dict | None = None
    interpretation: str | None = None
    drilldown_suggestions: list[dict] = field(default_factory=list)
    error: str | None = None


def finish_computation(entry: dict, plan: dict, code: str, table: list[dict], columns_block: str) -> AnalysisComputation:
    """Table+code succeeded (and passed the deterministic sanity check) --
    proceed through chart-type -> chart-spec -> interpret -> drilldowns. A
    failure at any of these stages is recorded as `error` but the plan/code
    that DID succeed is still returned, so the cache write isn't lost."""
    result_columns = list(table[0].keys()) if table else []
    computation = AnalysisComputation(
        plan_text=plan["plan"], generated_code=code, result_table=table, result_columns=result_columns,
    )
    try:
        sample = _table_sample_block(table)
        chart_choice = choose_chart_type(entry, plan, sample)
        computation.chart_type = chart_choice.get("chart_type", "table")
        computation.chart_spec = generate_chart_spec(entry, plan, computation.chart_type, sample)
        computation.interpretation = interpret(entry, plan, sample, computation.chart_type)
        computation.drilldown_suggestions = suggest_drilldowns(
            entry, plan, sample, computation.interpretation, columns_block
        )
    except Exception as exc:
        computation.error = f"Computed the table but couldn't finish charting it: {exc}"
    return computation


def compute_analysis(entry: dict, df: pd.DataFrame) -> AnalysisComputation:
    """Runs the Analysis Agent for one repository entry.

    If `entry["formula"]` is already set -- pre-generated by the Planner at
    suggest time and approved by the PM, or a predefined spec that shipped
    with its own formula -- that plan is treated as fixed: only code
    generation is retried against it. Otherwise this runs the full
    think -> write code -> execute loop, retrying with feedback up to
    MAX_ATTEMPTS times."""
    columns_block = describe_columns(df)
    if entry.get("formula"):
        return _compute_with_fixed_plan(entry, df, columns_block)
    return _compute_with_generated_plan(entry, df, columns_block)


def _compute_with_fixed_plan(entry: dict, df: pd.DataFrame, columns_block: str) -> AnalysisComputation:
    plan = {"plan": entry["formula"]}
    last_feedback: str | None = None

    for attempt in range(1, FIXED_FORMULA_MAX_ATTEMPTS + 1):
        try:
            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            table = ai_code_executor.run_generated_table_code(code, df)
            plausible, reason = is_plausible_table(table)
            if plausible:
                return finish_computation(entry, plan, code, table, columns_block)
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
    return _compute_with_generated_plan(entry, df, columns_block, seed_feedback=last_feedback)


def _compute_with_generated_plan(entry: dict, df: pd.DataFrame, columns_block: str, seed_feedback: str | None = None) -> AnalysisComputation:
    plan: dict | None = None
    last_feedback: str | None = seed_feedback

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if plan is None or attempt == MAX_ATTEMPTS:
                plan = think(entry, columns_block, feedback=last_feedback)

            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            table = ai_code_executor.run_generated_table_code(code, df)
            plausible, reason = is_plausible_table(table)
            if plausible:
                return finish_computation(entry, plan, code, table, columns_block)
            last_feedback = reason
        except Exception as exc:
            last_feedback = str(exc)

    prefix = "This analysis's approved formula no longer applied to the current data, and a fresh plan also failed: " if seed_feedback else ""
    return AnalysisComputation(
        plan_text=plan.get("plan") if plan else None, generated_code=None,
        error=f"{prefix}{last_feedback}" if last_feedback else "The Analysis Agent could not compute this analysis.",
    )
