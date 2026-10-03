"""The Analysis Agent: turns one analysis_repository.json entry into a
computed chart. Every entry -- however it was authored (a predefined
analysis spec, a Planner recommendation, a PM's typed request, an AI
suggestion, or a PM-triggered drilldown) -- has already been reduced to a
plain-English `calculation_intent` by the time it reaches here (see
analysis_repository.py), so this agent has one job regardless of source:
THINK about how to aggregate it, WRITE the pandas code, pick a CHART TYPE
for the resulting table (unless one was already chosen), INTERPRET the
chart, and SUGGEST follow-up drilldowns -- all via Amazon Bedrock.
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

from app.config import ANALYSIS_AGENT_MODEL, DRILLDOWN_AGENT_MODEL, model_for
from app.services.analysis import analysis_charts
from app.services.analysis.analysis_charts import ChartRoles
from app.services.analysis.analysis_columns import column_catalog
from app.services.common import ai_code_executor, llm

MAX_ATTEMPTS = 3
# A pre-supplied formula (Planner-generated and PM-approved, or a predefined
# spec that shipped with its own formula) is never rethought -- only its
# CODE gets retried against feedback, same rationale as the Feature Agent.
FIXED_FORMULA_MAX_ATTEMPTS = 3

_ALLOWED_CHART_TYPES = set(analysis_charts.CHART_TYPES)


def call_llm(
    system_prompt: str, user_prompt: str, *, json_mode: bool, temperature: float, call_name: str,
    model: str | None = None, max_tokens: int | None = None,
) -> str:
    """One Bedrock call. The system prompt is passed through Prompt Management by
    `call_name` (in-source text is the fallback). Bedrock has no JSON mode, so the
    prompts themselves demand JSON; `json_mode` just selects the fence-stripping path."""
    model = model or model_for(call_name, ANALYSIS_AGENT_MODEL)
    system = llm.system_prompt(call_name, system_prompt)
    fn = llm.chat_json if json_mode else llm.chat_text
    return fn(system, user_prompt, model=model, temperature=temperature, call_name=call_name, max_tokens=max_tokens)


# Kept importable: other modules use these names.
_strip_code_fence = strip_code_fence = llm.strip_code_fence
strip_json_fence = llm.strip_json_fence


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
- If a REQUIRED FEATURES section is given, those columns are already computed \
in the data (even though the catalog may not list them yet): use them \
directly by their exact column name and do NOT recompute their calculation \
(e.g. use a required count column instead of counting again, use a required \
"in spec" column instead of rebuilding it from raw hour columns).
- State what to group by (if anything) and what metric(s) to aggregate \
(sum, mean, count, min, max, median, distinct count, or share of total).
- State how nulls / missing values are handled.
- Be specific enough that a pandas engineer could implement it without \
asking a follow-up question.
- If the requested analysis genuinely cannot be computed from the available \
columns, say so plainly in the plan instead of inventing a substitute.

Examples:
- Request "% in spec by carrier" -> group by Carrier, metric is the share \
of rows where Status = "In Spec" (a percentage, not a count), no pre-filter \
(filtering to only "In Spec" rows first would make every carrier show 100%).
- Request "average temperature by product, cannot be computed" case: if \
no temperature-like column exists in the catalog, say so plainly instead of \
substituting a different column that merely sounds related.

Respond with ONLY a JSON object, no markdown, no commentary. `steps` is an \
array of short, self-contained instructions, each written as its own \
sentence with no leading number -- the caller numbers them for display:
{"logic": "ONE line spec of the analysis: filter (if any) -> group by -> metric(s) -> sort/limit, using exact column names, e.g. Group by Carrier -> count of Trip ID, % where Is Alarmed = Yes -> sort desc", "steps": ["first step", "second step", "..."], "group_by": ["exact column names, or [] if none"], "metrics": ["short description of each aggregated metric"]}"""


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

Example -- plan says "group by Carrier, compute % of rows where Status = 'In Spec'":
result = (
    df.groupby("Carrier")["Status"].apply(lambda s: (s == "In Spec").mean() * 100)
    .round(2).reset_index(name="% in spec")
)
This groups first, then computes the rate WITHIN each group -- never filter \
`df` down to `Status == "In Spec"` before grouping, which would throw away \
the very rows needed to compute the rate.

- Respond with ONLY the Python code. No markdown fences, no explanation, \
no comments."""


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
CHART_TYPE_GUIDANCE = """Chart types:
- "bar": one category + one metric -- comparisons, rankings.
- "grouped_bar": one category + several metrics of similar scale, or two categories + one metric.
- "combo": one category + two metrics of DIFFERENT scale together -- e.g. a 0-100% rate as bars plus a raw count/volume as a line on a second axis. Use this instead of "grouped_bar" whenever the two metrics wouldn't read sanely on the same axis.
- "line": a time or ordered axis + one or more metrics -- trends.
- "pie": shares of a whole, one category with few (<= 8) values.
- "scatter": two numeric measures against each other.
- "heatmap": two categories + one metric with many combinations.
- "table": nothing above fits, or the result is a few headline numbers.

Example: metrics are "% in spec" and "shipment count", grouped by Carrier ->
"combo" (not "grouped_bar" -- a 0-100% rate and a count in the hundreds
don't read sanely on one shared axis)."""

_CHART_SYSTEM = (
    "You are the chart-suggestion step of the Analysis Agent. You are given an analysis "
    "and the computation logic that defines its result table -- the table has NOT been "
    "computed yet. From the logic alone (what is grouped, over what, and which metrics), "
    "recommend the single best chart type, plus up to 2 alternatives.\n\n"
    + CHART_TYPE_GUIDANCE
    + '\n\nRespond with ONLY a JSON object, no markdown:\n'
    '{"chart_type": "<type>", "reason": "one short sentence", '
    '"alternatives": [{"chart_type": "<type>", "reason": "one short sentence"}]}'
)
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

_INTERPRET_SYSTEM = """You are the interpretation step of the Analysis Agent. You are given one \
computed analysis table and its chart type. Write a short, plain-English \
interpretation covering the standout value(s), any clear pattern, and why \
it might matter to a program manager. Do NOT invent any number that isn't \
in the table. Write 2-4 plain sentences, no markdown, no bullet lists.

Lead with the standout finding itself, not a description of the chart. \
NEVER start with "This chart shows...", "The chart illustrates...", "The \
data indicates...", or any other restatement of what the reader is already \
looking at -- state the finding directly instead.

Wrong: "This chart shows that DHL has the lowest % in spec among all carriers at 81%."
Right: "DHL has the lowest % in spec among all carriers at 81%, well below FedEx (93%) and UPS (95%)."
The second version states the same fact one clause shorter, with no \
throwaway lead-in."""


def interpret(entry: dict, plan: dict, table_sample: str, chart_type: str) -> str:
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\nChart type: {chart_type}\n\n"
        f"Computed table sample:\n{table_sample}\n\nWrite the interpretation now."
    )
    text = call_llm(_INTERPRET_SYSTEM, user_prompt, json_mode=False, temperature=0.3, call_name="analysis_agent_interpret")
    return text.strip()


# --- Call 5: Suggest drilldowns -----------------------------------------------

_DRILLDOWN_SYSTEM = """You are the drilldown-suggestion step of the Analysis Agent. Given an \
analysis that was just computed and interpreted, propose up to 3 FOLLOW-UP \
analyses a program manager would genuinely want next. They should narrow into \
the standout entity the interpretation named (the worst/best carrier, product, \
origin, month, etc.) OR compare it against the rest -- and each must answer a \
DIFFERENT QUESTION.

The most important rule: the ideas must differ in WHAT THEY MEASURE, not just \
in the x-axis. "Distinct serial numbers by carrier", "... by month" and \
"... by destination" are ONE idea (the same count re-sliced three ways) -- \
never return that. Give each suggestion its own LENS:

- "quality": compliance / temperature-spec performance -- % in spec, time out \
of spec, excursion or alarm rate. Use an engineered quality feature column if \
one is listed below.
- "volume": how many trips, or the share of volume. At most ONE suggestion may \
be a plain volume/count view.
- "trend": the same measure over time (week / month) for the standout.
- "duration": transit time / segment length / delays.
- "temperature": temperature behaviour -- mean, peak, variability or deviation \
from the limits (Mean Value, Max Value, Standard Deviation, Limit columns).
- "outliers": the worst individual shipments or segments (ranked rows), to find \
what actually went wrong.

Every suggestion MUST:
- Use a DIFFERENT lens from the others (three suggestions = three lenses).
- Use a different metric from the others; where sensible also a different \
breakdown column.
- If ENGINEERED FEATURES are listed, at least one suggestion must be built on \
one of them (use its column name exactly).
- Reference only columns that appear in the given column list -- never invent \
a column name.
- NOT group by the column the parent analysis already grouped by (see "Parent \
grouped by" below, when given).
- Count trips as "Trip ID" only when the lens is volume; do not default to \
distinct Serial Numbers.
- Set "suggested_chart_type" to the parent's own chart type ONLY when it reuses \
the same kind of two metrics (a rate plus a volume); otherwise null.

Example -- parent "Trips by Origin for Table Grapes", interpretation names \
"Origin A carries 60% of trips", engineered feature "% In Spec" available. \
Three DIFFERENT ideas:
1. lens quality: "% in spec by Carrier for Origin A" (mean of % In Spec + trip \
count per carrier).
2. lens trend: "Monthly % in spec for Origin A" (mean of % In Spec by month).
3. lens outliers: "10 lowest % in spec shipments from Origin A" (ranked rows \
with carrier, date and % In Spec).

Respond with ONLY a JSON object, no markdown, no commentary:
{"drilldowns": [
  {
    "name": "short title",
    "lens": "quality | volume | trend | duration | temperature | outliers",
    "metric": "the measure in a few words, e.g. mean % In Spec",
    "dimension": "the breakdown column, 'time', or 'none'",
    "description": "one plain-English sentence on what this drilldown would show",
    "calculation_intent": "a precise, unambiguous plain-English description of exactly how to compute this from the columns below, including any filter/scope to the standout entity",
    "suggested_chart_type": "<chart type, or null>"
  }
]}"""

_LENSES = {"quality", "volume", "trend", "duration", "temperature", "outliers"}


def _features_block(entry: dict) -> str:
    lines = [
        f"- `{f['output_column']}` ({f.get('name', '')}): {f.get('definition', '')}".rstrip(": ")
        for f in entry.get("available_features") or []
    ]
    return ("ENGINEERED FEATURES (computed columns you can build on):\n" + "\n".join(lines) + "\n\n") if lines else ""


def _metric_key(text: str) -> str:
    return " ".join(sorted(set(re.sub(r"[^a-z0-9%]+", " ", (text or "").lower()).split())))


def _diverse(candidates: list, avoid: list[str] | None = None, parent_dims: list[str] | None = None) -> list[dict]:
    """Keeps only ideas that ask a different question: one per lens, never the
    same metric twice (same measure re-sliced by another x-axis), and never a
    breakdown by the column the parent already groups by."""
    taken = {_metric_key(n) for n in avoid or []}
    parent = {str(d).strip().lower() for d in parent_dims or []}
    lenses: set[str] = set()
    metrics: set[str] = set()
    kept: list[dict] = []
    for spec in candidates:
        if not isinstance(spec, dict) or not spec.get("name") or not spec.get("calculation_intent"):
            continue
        lens = str(spec.get("lens") or "").strip().lower()
        lens = lens if lens in _LENSES else "volume"
        metric = _metric_key(spec.get("metric") or spec["name"])
        if str(spec.get("dimension") or "").strip().lower() in parent:
            continue
        if lens in lenses or metric in metrics or _metric_key(spec["name"]) in taken:
            continue
        lenses.add(lens)
        metrics.add(metric)
        kept.append({**spec, "lens": lens})
    return kept


def suggest_drilldowns(
    entry: dict, plan: dict, table_sample: str, interpretation: str, columns_block: str,
    parent_chart_type: str | None = None,
    avoid: list[str] | None = None,
) -> list[dict]:
    parent_group_by = plan.get("group_by") or []
    context_lines = []
    if parent_group_by:
        context_lines.append(f"Parent grouped by: {', '.join(parent_group_by)}")
    if parent_chart_type:
        context_lines.append(f"Parent chart type: {parent_chart_type}")
    if avoid:
        # "Suggest more": the PM already has these -- propose different ones.
        context_lines.append(
            "Already suggested (do NOT repeat or rephrase these; use a different lens, metric or standout):\n"
            + "\n".join(f"- {n}" for n in avoid)
        )
    context_block = ("\n" + "\n".join(context_lines) + "\n") if context_lines else ""
    user_prompt = (
        f"Analysis: {entry['name']}\nPlan:\n{plan['plan']}\n{context_block}\n"
        f"Computed table sample:\n{table_sample}\n\nInterpretation:\n{interpretation}\n\n"
        f"{_features_block(entry)}COLUMN CATALOG:\n{columns_block}\n\nPropose the drilldowns now."
    )

    kept: list[dict] = []
    for attempt in range(2):
        prompt = user_prompt
        if attempt:
            prompt += (
                "\n\nYOUR PREVIOUS IDEAS WERE TOO SIMILAR (same measure, different x-axis): "
                + "; ".join(k["name"] for k in kept)
                + ". Return ideas with DIFFERENT lenses and metrics."
            )
        raw = call_llm(
            _DRILLDOWN_SYSTEM, prompt, json_mode=True, temperature=0.5, call_name="analysis_agent_drilldown",
            model=model_for("analysis_agent_drilldown", DRILLDOWN_AGENT_MODEL),
        )
        payload = json.loads(strip_json_fence(raw))
        candidates = payload.get("drilldowns", [])
        kept = _diverse(candidates if isinstance(candidates, list) else [], avoid, parent_group_by)
        if len(kept) >= 2 or len(candidates or []) < 2:
            break

    drilldowns: list[dict] = []
    for spec in kept:
        chart_type_hint = spec.get("suggested_chart_type")
        drilldowns.append({
            "name": spec["name"],
            "description": spec.get("description", ""),
            "calculation_intent": spec["calculation_intent"],
            "chart_type_hint": chart_type_hint if chart_type_hint in _ALLOWED_CHART_TYPES else None,
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
    drilldown_suggestions: list[dict] = field(default_factory=list)
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
