"""The Feature Agent: turns one feature_repository.json entry into a real
computed column. Every entry -- however it was authored (a structured KPI
Profile spec, a Planner recommendation, a PM's typed request, an AI
suggestion) -- has already been reduced to a plain-English
`calculation_intent` by the time it reaches here (see
feature_repository.py), so this agent has exactly one job regardless of
source: THINK about how to compute it, WRITE the pandas code, and VALIDATE
the result -- three separate Bedrock calls. The generated
code is never trusted at face value: it runs through the same AST-sandboxed
executor as before (ai_code_executor.py).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd

from app.config import DEFAULT_MAX_TOKENS, FEATURE_AGENT_MODEL, model_for
from app.services.common import ai_code_executor, code_run_log, llm

MAX_ATTEMPTS = 3
# A pre-supplied formula (Planner-generated and PM-approved, or a fully
# structured predefined spec) is never rethought -- only its CODE gets
# retried against validation feedback, now with explicit instruction to fix
# the LOGIC (not just the syntax) that the feedback describes -- see
# generate_code(). 3 attempts gives that corrective feedback loop room to
# actually converge instead of stopping right after the first correction.
FIXED_FORMULA_MAX_ATTEMPTS = 3

def _call(
    system_prompt: str, user_prompt: str, *, json_mode: bool, temperature: float, call_name: str
) -> str:
    system = llm.system_prompt(call_name, system_prompt)
    model = model_for(call_name, FEATURE_AGENT_MODEL)
    if json_mode:
        return llm.chat_json(system, user_prompt, model=model, temperature=temperature,
                             call_name=call_name, max_tokens=DEFAULT_MAX_TOKENS)
    return llm.chat_text(system, user_prompt, model=model, temperature=temperature,
                         call_name=call_name, max_tokens=DEFAULT_MAX_TOKENS)


# Kept importable under their old names.
_strip_code_fence = llm.strip_code_fence
_strip_json_fence = llm.strip_json_fence


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

_THINK_SYSTEM = None  # the system prompt lives in Amazon Bedrock Prompt Management (feature_agent_think); default text: backend/prompts/<name>.txt


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

_CODE_SYSTEM = None  # the system prompt lives in Amazon Bedrock Prompt Management (feature_agent_write_code); default text: backend/prompts/<name>.txt


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

_VALIDATE_SYSTEM = None  # the system prompt lives in Amazon Bedrock Prompt Management (feature_agent_validate); default text: backend/prompts/<name>.txt


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
    tally = {"attempts": 0}
    if entry.get("formula"):
        result = _compute_with_fixed_plan(entry, df, columns_block, tally)
    else:
        result = _compute_with_generated_plan(entry, df, columns_block, tally)
    code_run_log.outcome(
        "feature", entry, attempts=tally["attempts"], status="ok" if result.error is None else "failed", error=result.error,
        extra={"used_fixed_formula": bool(entry.get("formula"))},
    )
    return result


def _compute_with_fixed_plan(entry: dict, df: pd.DataFrame, columns_block: str, tally: dict) -> FeatureComputation:
    plan = {"plan": entry["formula"]}
    last_feedback: str | None = None

    for attempt in range(1, FIXED_FORMULA_MAX_ATTEMPTS + 1):
        tally["attempts"] += 1
        stage, code = "generate", None
        try:
            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            stage = "execute"
            values = ai_code_executor.run_generated_code(code, df)
            stage = "validate"
            sample = _sample_block(df, entry, values, code=code)
            verdict = validate(entry, plan, sample)

            if verdict.get("valid"):
                code_run_log.attempt("feature", entry, path="fixed_formula", attempt_no=attempt, status="ok",
                                     code=code, validation=verdict.get("reason"))
                return FeatureComputation(
                    values=values,
                    plan_text=plan["plan"],
                    generated_code=code,
                    validation_note=verdict.get("reason"),
                    error=None,
                )
            last_feedback = verdict.get("reason") or "Validation failed for an unspecified reason."
            code_run_log.attempt("feature", entry, path="fixed_formula", attempt_no=attempt, status="failed",
                                 stage="validate", code=code, validation=last_feedback)
        except Exception as exc:
            last_feedback = str(exc)
            code_run_log.attempt("feature", entry, path="fixed_formula", attempt_no=attempt, status="failed",
                                 stage=stage, code=code, error=last_feedback)

    # The approved plan's WORDING was never the problem here -- every retry
    # kept making the same CODE-level mistake against it (e.g. a backwards
    # compliance flag, a per-group value computed as if it were per-row) and
    # validation correctly kept rejecting it. Since this path only ever
    # retries code against the unchanged plan, a systematic code mistake like
    # that can never self-correct. As a last resort, fall through to a fresh
    # Think -- carrying the validator's own feedback forward -- rather than
    # permanently failing a feature the data can very likely still support.
    return _compute_with_generated_plan(entry, df, columns_block, tally, seed_feedback=last_feedback)


def _compute_with_generated_plan(
    entry: dict, df: pd.DataFrame, columns_block: str, tally: dict, seed_feedback: str | None = None
) -> FeatureComputation:
    plan: dict | None = None
    last_feedback: str | None = seed_feedback

    for attempt in range(1, MAX_ATTEMPTS + 1):
        tally["attempts"] += 1
        stage, code = "think", None
        try:
            if plan is None or attempt == MAX_ATTEMPTS:
                # First attempt, or last-resort rethink after a code-level fix
                # already failed once.
                plan = think(entry, columns_block, feedback=last_feedback)

            stage = "generate"
            code_feedback = last_feedback if attempt > 1 else None
            code = generate_code(entry, plan, columns_block, feedback=code_feedback)
            stage = "execute"
            values = ai_code_executor.run_generated_code(code, df)

            stage = "validate"
            sample = _sample_block(df, entry, values, code=code)
            verdict = validate(entry, plan, sample)

            if verdict.get("valid"):
                code_run_log.attempt("feature", entry, path="generated_plan", attempt_no=attempt, status="ok",
                                     code=code, validation=verdict.get("reason"))
                return FeatureComputation(
                    values=values,
                    plan_text=plan.get("plan"),
                    generated_code=code,
                    validation_note=verdict.get("reason"),
                    error=None,
                )
            last_feedback = verdict.get("reason") or "Validation failed for an unspecified reason."
            code_run_log.attempt("feature", entry, path="generated_plan", attempt_no=attempt, status="failed",
                                 stage="validate", code=code, validation=last_feedback)
        except Exception as exc:
            last_feedback = str(exc)
            code_run_log.attempt("feature", entry, path="generated_plan", attempt_no=attempt, status="failed",
                                 stage=stage, code=code, error=last_feedback)

    prefix = "This feature's approved formula couldn't be implemented correctly, and a fresh plan also failed: " if seed_feedback else ""
    return FeatureComputation(
        values=None,
        plan_text=plan.get("plan") if plan else None,
        generated_code=None,
        validation_note=None,
        error=f"{prefix}{last_feedback}" if last_feedback else "The Feature Agent could not compute this feature.",
    )
