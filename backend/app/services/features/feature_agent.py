"""The Feature Agent: turns one feature_repository.json entry into a real
computed column. Every entry -- however it was authored (a structured KPI
Profile spec, a Planner recommendation, a PM's typed request, an AI
suggestion) -- has already been reduced to a plain-English
`calculation_intent` by the time it reaches here (see
feature_repository.py), so this agent has exactly one job regardless of
source: THINK about how to compute it, WRITE the pandas code, and VALIDATE
the result -- three separate OpenRouter calls, never Groq. The generated
code is never trusted at face value: it runs through the same AST-sandboxed
executor as before (ai_code_executor.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd
from openai import OpenAI

from app.config import FEATURE_AGENT_MODEL, OPENROUTER_API_KEY
from app.services.common import ai_code_executor, token_usage

MAX_ATTEMPTS = 3
# A pre-supplied formula (Planner-generated and PM-approved, or a fully
# structured predefined spec) is never rethought -- only its CODE gets
# retried against validation feedback, now with explicit instruction to fix
# the LOGIC (not just the syntax) that the feedback describes -- see
# generate_code(). 3 attempts gives that corrective feedback loop room to
# actually converge instead of stopping right after the first correction.
FIXED_FORMULA_MAX_ATTEMPTS = 3

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


def _call(
    system_prompt: str, user_prompt: str, *, json_mode: bool, temperature: float, call_name: str
) -> str:
    client = _get_client()
    kwargs: dict = {
        "model": FEATURE_AGENT_MODEL,
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
    token_usage.record(call_name, FEATURE_AGENT_MODEL, response)
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


def _columns_block(df: pd.DataFrame) -> str:
    lines = []
    for col in df.columns:
        sample = df[col].dropna().astype(str).head(3).tolist()
        preview = ", ".join(sample) if sample else "(all null)"
        lines.append(f"- {col} ({df[col].dtype}): e.g. {preview}")
    return "\n".join(lines)


def _entry_block(entry: dict) -> str:
    cols_hint = f"\nColumns likely involved (hint, not exhaustive): {', '.join(entry['input_columns'])}" if entry.get("input_columns") else ""
    return (
        f"Feature name: {entry['name']}\n"
        f"Output column name: {entry['output_column']}\n"
        f"Description: {entry.get('description', '')}\n"
        f"Calculation intent: {entry['calculation_intent']}"
        f"{cols_hint}"
        f"{_other_features_block(entry)}"
    )


def _other_features_block(entry: dict) -> str:
    """Other features being created alongside this one. If this feature is
    defined on top of one of them, it must read that column, not repeat its
    calculation."""
    lines = [
        f"- `{f['output_column']}` ({f['name']}): {f.get('description', '')}"
        for f in entry.get("other_features") or []
    ]
    if not lines:
        return ""
    return (
        "\nOTHER FEATURES BEING CREATED ALONGSIDE THIS ONE (computed before it when this feature builds on them -- "
        "then read their column by its exact name instead of repeating their calculation; ignore any that are unrelated):\n"
        + "\n".join(lines)
    )


# --- Call 1: Think ---------------------------------------------------------

_THINK_SYSTEM = """You are the planning step of the Feature Agent for a cold-chain shipment \
analytics tool. You are given one requested feature and the full column \
catalog of the current dataset. Produce a precise, unambiguous, step-by-step \
plan for computing this feature as ONE new pandas column -- exactly one \
value per row of the dataframe `df`.

The plan MUST:
- Name the EXACT column(s) from the catalog it uses. Never invent a column \
name that isn't in the catalog.
- State how nulls / missing values are handled. A row that cannot be scored \
(a required input is missing, e.g. no temperature limits) stays blank; do \
not fill it with 0, which would score it as perfect.
- Check the UNITS of every column used (a name or header like "(Days)" vs \
"Hours") and convert so both sides of a calculation use the same unit. Never \
subtract hours from days.
- A percentage or ratio must stay within 0-100 (or 0-1): clamp it and say so.
- State the output type: numeric, percentage, string, category, boolean, \
datetime, or duration.
- If the calculation naturally produces ONE value for the whole dataset (an \
overall rate/total) or ONE value per group (e.g. an average per lane) \
rather than a genuinely per-row value, say explicitly that the SAME value \
is broadcast to every row in that scope -- and say so as the INTENDED \
result, not a caveat, since a validator will otherwise see identical values \
and assume something is wrong.
- Be specific enough that a pandas engineer could implement it without \
asking a follow-up question.
- If the requested calculation genuinely cannot be computed from the \
available columns, say so plainly in the plan instead of inventing a \
substitute.

Examples:
- Genuine per-row feature: "Transit Time Hours" from Ship Date/Delivery \
Date -> steps say "subtract Ship Date from Delivery Date for each row, \
convert to hours" -- a normal per-row value, no broadcast needed.
- Group-broadcast feature: "Average Transit Time by Carrier" -> steps say \
"compute the mean transit time PER CARRIER, then assign that SAME value to \
every row for that carrier -- this is the intended result, not a \
duplicate-looking bug."

Respond with ONLY a JSON object, no markdown, no commentary. `steps` is an \
array of short, self-contained instructions, each written as its own \
sentence with no leading number -- the caller numbers them for display:
{"formula": "ONE line, the calculation written like a formula using the exact column names, e.g. Transit Hours = (Actual Arrival - Actual Departure) in hours; In Spec Flag = Max Value <= Limit High", "steps": ["first step", "second step", "..."], "columns_used": ["exact column names"], "output_dtype": "numeric | percentage | string | category | boolean | datetime | duration"}"""


def _plan_text(plan: dict) -> str:
    """Renders a Think result's `steps` array as one numbered paragraph --
    used only where a single string is needed (LLM prompts, legacy storage).
    Falls back to a `plan` key for anything that still hands in the older
    single-string shape (e.g. a Planner-generated formula stored before this
    format existed)."""
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(steps))
    return plan.get("plan", "")


def think(entry: dict, columns_block: str, feedback: str | None = None) -> dict:
    feedback_block = f"\n\nA PREVIOUS ATTEMPT FAILED: {feedback}\nRevise the plan so this doesn't happen again." if feedback else ""
    user_prompt = f"{_entry_block(entry)}\n\nCOLUMN CATALOG:\n{columns_block}{feedback_block}\n\nProduce the plan now."
    raw = _call(_THINK_SYSTEM, user_prompt, json_mode=True, temperature=0.2, call_name="feature_agent_think")
    parsed = json.loads(_strip_json_fence(raw))
    # Normalize to a single "plan" string for every downstream consumer
    # (code generation, validation, storage, the Planner's pre-generated
    # formula) -- `steps` stays available for anything that wants the list.
    parsed["plan"] = _plan_text(parsed)
    return parsed


# --- Call 2: Write code -----------------------------------------------------

_CODE_SYSTEM = """You are the code-writing step of the Feature Agent. You are given a \
plan (already decided -- do not second-guess it) for computing one new \
column. A pandas DataFrame is already available as `df`, and `pandas` is \
already available as `pd`.

Write vectorized pandas code (no explicit for/while loops, no function or \
class definitions, no imports) that implements EXACTLY the given plan and \
assigns the final result -- a pandas Series with exactly one value per row \
of `df`, aligned to `df.index` -- to a variable named exactly `result`.

Rules:
- Only reference columns that actually appear in the column list given below.
- Never read or write files, never use eval/exec/open, never import \
anything, never call any to_csv/to_excel/read_csv/etc-style I/O method.
- `result` must be assigned directly from a Series expression (e.g. \
`result = some_series`, or `result = df["x"] - df["y"]`). NEVER index `df` \
with a list, array, or Series of the VALUES you just computed (e.g. \
`df[computed_values]` or `df.loc[:, computed_values]`) -- that treats those \
numbers as column names and always fails with a "Columns not found" error. \
If you need to assign a computed Series as a new column first, use \
`df["some_new_name"] = computed_values` (a plain string literal key), then \
set `result = df["some_new_name"]`.
- If the output is a boolean/flag column, its NAME tells you which \
direction True means -- e.g. a "compliance flag" or "is_in_spec" column \
must be True when the row IS compliant / within limits, never when it's \
out of spec, even if the plan's wording could be read either way. Before \
finalizing a boolean comparison, re-read the output column name and check \
your comparison produces True for the GOOD/matching case it names, not the \
opposite. Getting a flag's direction backwards is the single most common \
mistake here -- double-check it explicitly.
- If the plan describes a value that's the same for every row sharing a \
group (a per-group average, rate, or count), you MUST compute it with \
`.groupby([group_cols])[...].transform(...)` (or an equivalent merge/map \
back to every row of that group) -- never compute it per-row or with a \
row-by-row conditional, which produces different values within what should \
be one identical group value.

Example -- plan says "average Mean Value per Carrier, same value for every \
row of that carrier":
Wrong: `result = df.apply(lambda r: df[df["Carrier"] == r["Carrier"]]["Mean Value"].mean(), axis=1)` (a slow, error-prone row-by-row rebuild of the same lookup)
Right: `result = df.groupby("Carrier")["Mean Value"].transform("mean")`

- Respond with ONLY the Python code. No markdown fences, no explanation, \
no comments."""


def generate_code(entry: dict, plan: dict, columns_block: str, feedback: str | None = None) -> str:
    if feedback:
        feedback_block = (
            f"\n\nYOUR PREVIOUS CODE FAILED THIS CHECK: {feedback}\n"
            "If that failure describes WRONG LOGIC (a backwards comparison, an "
            "inconsistent group value, a wrong direction) rather than a syntax/"
            "runtime error, don't just patch the error message away -- re-derive "
            "the comparison/grouping from the plan and the output column's own "
            "name, and fix the actual direction or grouping mistake."
        )
    else:
        feedback_block = ""
    user_prompt = (
        f"Plan to implement:\n{plan['plan']}\n\n"
        f"Output column name: {entry['output_column']}\n\n"
        f"Columns available in `df`:\n{columns_block}{feedback_block}\n\n"
        "Write the code now."
    )
    raw = _call(_CODE_SYSTEM, user_prompt, json_mode=False, temperature=0.1, call_name="feature_agent_write_code")
    return _strip_code_fence(raw)


# --- Call 3: Validate --------------------------------------------------------

_VALIDATE_SYSTEM = """You are the validation step of the Feature Agent. You are given the plan \
that was supposed to be implemented, and a small sample of the actual \
computed output alongside the source columns it was computed from.

Decide whether the computed values are genuinely consistent with the plan \
and look plausible -- not just "not empty", but actually correct: a \
percentage should fall in a sane range (unless the plan says otherwise), a \
duration shouldn't be negative (unless the plan expects that), a lookup \
should show real mapped values rather than raw codes.

IMPORTANT -- if the plan says the result is ONE overall value or ONE value \
PER GROUP broadcast to every row in that scope (an average, sum, count, or \
similar aggregate per group), this is a MECHANICAL check, not a judgment \
call:
1. Recompute the aggregate yourself from the exact source numbers shown for \
that group.
2. Compare your recomputed number to the OUTPUT column's value for that \
group.
3. If they match: valid=true. Full stop -- do not additionally comment on \
whether the source values "differ" or the output looks "constant" or \
"the same across rows". A group aggregate's OUTPUT being identical while \
its SOURCE rows differ is not a symptom of anything -- it is the definition \
of what an aggregate is, on every single correct case you will ever see. \
Noticing that pattern is not a finding.
4. Only if your own recomputed number DISAGREES with the shown output do \
you flag invalid=false, and your reason must state both numbers (yours vs. \
the shown output).

Example: plan says "average Mean Value per Carrier, broadcast to every row \
of that carrier." Sample: DHL rows have Mean Value 4.0 and 4.4, both show \
avg_mean_value_by_carrier 4.2. You recompute (4.0+4.4)/2 = 4.2. That equals \
the shown output -> valid=true, reason "Recomputed DHL's average as 4.2, \
matching the output." Do not add anything about the source values differing \
-- that observation is irrelevant once the numbers match.

For anything the plan describes as a genuinely PER-ROW calculation (no \
grouping at all), rows whose SOURCE values are identical must get identical \
outputs -- these exports often repeat the same trip/segment on several \
rows, so compare each output with the source columns shown beside it before \
calling repetition wrong.

Respond with ONLY a JSON object, no markdown, no commentary. Write "reason" \
FIRST, working out any recomputation in it, and only THEN decide "valid" so \
your verdict follows what "reason" actually found rather than the reverse:
{"reason": "one concise sentence showing your check (e.g. a recomputed number vs. the shown output)", "valid": true or false}"""


def validate(entry: dict, plan: dict, sample_block: str) -> dict:
    user_prompt = (
        f"Plan that was implemented:\n{plan['plan']}\n\n"
        f"Feature: {entry['name']} -> column `{entry['output_column']}`\n\n"
        f"Sample of computed output (with the columns it was likely derived from):\n{sample_block}\n\n"
        "Validate now."
    )
    raw = _call(_VALIDATE_SYSTEM, user_prompt, json_mode=True, temperature=0.0, call_name="feature_agent_validate")
    return json.loads(_strip_json_fence(raw))


_COLUMN_REF = re.compile(r"""\[\s*(['"])(.+?)\1\s*\]""")
MAX_SAMPLE_SOURCE_COLUMNS = 6


def _code_columns(code: str | None, df: pd.DataFrame) -> list[str]:
    """Source columns the generated code actually reads (df["X"] / df['X']
    style references that name a real column)."""
    if not code:
        return []
    return [m.group(2) for m in _COLUMN_REF.finditer(code) if m.group(2) in df.columns]


def _sample_block(df: pd.DataFrame, entry: dict, values: pd.Series, n: int = 8, code: str | None = None) -> str:
    # The validator must see the inputs next to each output: without them,
    # repeated outputs from repeated source rows (duplicate trips/segments
    # are common in these exports) look like a broken per-row calculation.
    # `input_columns` is only a PM/LLM hint and is often empty, so the
    # columns the code really reads are always included.
    hinted = [c for c in entry.get("input_columns", []) if c in df.columns]
    cols = list(dict.fromkeys(hinted + _code_columns(code, df)))[:MAX_SAMPLE_SOURCE_COLUMNS]
    cols = [c for c in cols if c != entry["output_column"]]
    preview = df[cols].copy() if cols else pd.DataFrame(index=df.index)
    preview[entry["output_column"]] = values
    return preview.head(n).to_string()


@dataclass
class FeatureComputation:
    values: pd.Series | None
    plan_text: str | None
    generated_code: str | None
    validation_note: str | None
    error: str | None


def compute_feature(entry: dict, df: pd.DataFrame) -> FeatureComputation:
    """Runs the Feature Agent for one repository entry.

    If `entry["formula"]` is already set -- pre-generated by the Planner at
    suggest time and approved by the PM, or a fully structured predefined
    spec -- that plan is treated as fixed: only code generation is retried
    against it, and it is never rethought. Otherwise this runs the full
    think -> write code -> execute -> validate loop, retrying with feedback
    (regenerating code against the same plan first, then rethinking the plan
    itself as a last resort) up to MAX_ATTEMPTS times."""
    columns_block = _columns_block(df)
    if entry.get("formula"):
        return _compute_with_fixed_plan(entry, df, columns_block)
    return _compute_with_generated_plan(entry, df, columns_block)


def _compute_with_fixed_plan(entry: dict, df: pd.DataFrame, columns_block: str) -> FeatureComputation:
    plan = {"plan": entry["formula"]}
    last_feedback: str | None = None

    for attempt in range(1, FIXED_FORMULA_MAX_ATTEMPTS + 1):
        try:
            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            values = ai_code_executor.run_generated_code(code, df)
            sample = _sample_block(df, entry, values, code=code)
            verdict = validate(entry, plan, sample)

            if verdict.get("valid"):
                return FeatureComputation(
                    values=values,
                    plan_text=plan["plan"],
                    generated_code=code,
                    validation_note=verdict.get("reason"),
                    error=None,
                )
            last_feedback = verdict.get("reason") or "Validation failed for an unspecified reason."
        except Exception as exc:
            last_feedback = str(exc)

    # The approved plan's WORDING was never the problem here -- every retry
    # kept making the same CODE-level mistake against it (e.g. a backwards
    # compliance flag, a per-group value computed as if it were per-row) and
    # validation correctly kept rejecting it. Since this path only ever
    # retries code against the unchanged plan, a systematic code mistake like
    # that can never self-correct. As a last resort, fall through to a fresh
    # Think -- carrying the validator's own feedback forward -- rather than
    # permanently failing a feature the data can very likely still support.
    return _compute_with_generated_plan(entry, df, columns_block, seed_feedback=last_feedback)


def _compute_with_generated_plan(entry: dict, df: pd.DataFrame, columns_block: str, seed_feedback: str | None = None) -> FeatureComputation:
    plan: dict | None = None
    last_feedback: str | None = seed_feedback

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if plan is None or attempt == MAX_ATTEMPTS:
                # First attempt, or last-resort rethink after a code-level fix
                # already failed once.
                plan = think(entry, columns_block, feedback=last_feedback)

            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            values = ai_code_executor.run_generated_code(code, df)

            sample = _sample_block(df, entry, values, code=code)
            verdict = validate(entry, plan, sample)

            if verdict.get("valid"):
                return FeatureComputation(
                    values=values,
                    plan_text=plan.get("plan"),
                    generated_code=code,
                    validation_note=verdict.get("reason"),
                    error=None,
                )
            last_feedback = verdict.get("reason") or "Validation failed for an unspecified reason."
        except Exception as exc:
            last_feedback = str(exc)

    prefix = "This feature's approved formula couldn't be implemented correctly, and a fresh plan also failed: " if seed_feedback else ""
    return FeatureComputation(
        values=None,
        plan_text=plan.get("plan") if plan else None,
        generated_code=None,
        validation_note=None,
        error=f"{prefix}{last_feedback}" if last_feedback else "The Feature Agent could not compute this feature.",
    )
