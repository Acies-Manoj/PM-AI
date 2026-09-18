"""Answers one free-text analysis question against the session's current
data (e.g. "average excursion time by supplier", triggered either by the
Insight Agent's own drill-down suggestion or by a user typing a question
directly -- see routers/analysis.py's /ask).

Two paths, tried in order, same "template first, sandbox only if it
genuinely doesn't fit" precedent as feature_request_agent.py:

1. Template: Groq is asked to express the question as a pivot spec (same
   group_by/metrics/filters shape pivot_suggester.py already proposes from
   its own ideas) -- if that's a faithful fit, it's computed by
   pivot_engine.py, the same deterministic groupby/aggregation engine every
   other pivot in this app runs through. No LLM arithmetic involved.
2. Custom Python: only when Groq itself says the question can't be expressed
   that way (a multi-step calculation, a non-tabular answer, ...), it
   instead writes a short pandas snippet computing the answer directly,
   executed through ai_code_executor.run_generated_analysis_code's sandbox
   -- the same AST-allowlist restriction used for ai_generated features,
   just accepting a table/value instead of a per-row column.

Either way the result is written to analysis_store.py before being returned,
so a near-duplicate question later doesn't need to re-run either path.
"""
import json
import re
import uuid
from dataclasses import dataclass, field

import pandas as pd

from app.schemas import PivotResult
from app.services import ai_code_executor, analysis_store, pivot_engine
from app.services.groq_client import chat_json, chat_text
from app.services.llm_context import columns_block as _columns_block
from app.services.pivot_definitions_store import SUPPORTED_AGGS

TEMPLATE_SYSTEM_PROMPT = """You answer ONE specific analysis question about \
an operational cold-chain shipment dataset by expressing it as a pivot \
table, when that genuinely fits. You'll be given the question and the \
current column names, dtypes, and a few sample values per column.

A pivot table has:
- "group_by": 1-2 column names to group rows by.
- "metrics": 1-3 objects, each {"column": <name>, "agg": <one of: sum, \
mean, count, min, max, median, distinct_count, pct_of_total>, "output_label": \
<short display label>}.
- "filters" (optional): [{"column": <name>, "op": "eq"|"neq"|"gt"|"gte"|"lt"|"lte"|"in", "value": <...>}]
- "sort_by" (optional): {"metric": <an output_label above>, "direction": "asc"|"desc"}
- "top_n" (optional): integer cap on rows.

Only reference columns that appear in the given column list -- never invent \
one. If the question is a straightforward group/aggregate/filter/sort like \
this, respond with {"expressible": true, "spec": {...that shape...}}. If it \
genuinely needs something a pivot table can't do (multi-step arithmetic \
across groups, a single number with custom logic, text matching, ...), \
respond with {"expressible": false, "reason": "one short sentence why"}.

Respond with ONLY that JSON object, no markdown, no commentary."""

CUSTOM_SYSTEM_PROMPT = """You are a data analyst answering ONE specific \
question about an operational cold-chain shipment dataset by writing a \
short pandas snippet.

A pandas DataFrame is already available as the variable `df`, and the \
`pandas` module is already available as `pd`. Write vectorized pandas code \
(no explicit for/while loops, no function or class definitions, no \
imports) that computes the answer and assigns it to a variable named \
exactly `result` -- a pandas DataFrame (a small table) or a plain \
dict/number/string (a single computed value), whichever the question calls \
for.

Rules:
- Only reference columns that actually appear in the column list given below.
- Never read or write files, never use eval/exec/open, never import \
anything, never call any to_csv/to_excel/read_csv/etc-style I/O method.
- Respond with ONLY the Python code. No markdown fences, no explanation, \
no comments."""


@dataclass
class FormulaAnswer:
    mode: str  # "template" | "custom_python"
    pivot: PivotResult | None = None
    table: list[dict] | None = None
    value: str | None = None
    explanation: str = ""
    skipped_reason: str | None = None


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:python)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def _valid_metric(spec: dict, available_columns: set[str]) -> bool:
    return (
        isinstance(spec, dict)
        and spec.get("column") in available_columns
        and spec.get("agg") in SUPPORTED_AGGS
        and bool(spec.get("output_label"))
    )


def _try_template(question: str, df: pd.DataFrame) -> FormulaAnswer | None:
    """Returns a FormulaAnswer on a clean template hit, or None if Groq
    itself declined, the draft doesn't validate, or the computed pivot came
    back skipped -- any of which means "fall through to the custom path",
    not an error."""
    user_prompt = f"Question: {question}\n\nColumns:\n{_columns_block(df)}\n\nAnswer now."
    raw = chat_json(TEMPLATE_SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    if not isinstance(payload, dict) or not payload.get("expressible"):
        return None

    spec = payload.get("spec")
    if not isinstance(spec, dict):
        return None

    available_columns = set(df.columns.astype(str))
    group_by = spec.get("group_by")
    if not isinstance(group_by, list) or not group_by or not set(group_by).issubset(available_columns):
        return None
    metrics = spec.get("metrics")
    if not isinstance(metrics, list) or not metrics or not all(_valid_metric(m, available_columns) for m in metrics):
        return None

    full_spec = {
        "id": f"ask_{uuid.uuid4().hex[:8]}",
        "name": question[:60],
        "description": question,
        "group_by": group_by,
        "metrics": metrics,
        "filters": spec.get("filters") or [],
        "sort_by": spec.get("sort_by"),
        "top_n": spec.get("top_n"),
    }
    results, skipped_notes = pivot_engine.apply_pivots(df, [full_spec])
    if skipped_notes or not results:
        return None

    return FormulaAnswer(mode="template", pivot=results[0], explanation="Answered as a pivot table.")


def _run_custom(question: str, df: pd.DataFrame) -> FormulaAnswer:
    user_prompt = f"Question: {question}\n\nColumns:\n{_columns_block(df)}\n\nWrite the code now."
    raw = chat_text(CUSTOM_SYSTEM_PROMPT, user_prompt)
    code = _strip_code_fence(raw)
    result = ai_code_executor.run_generated_analysis_code(code, df)

    if isinstance(result, pd.DataFrame):
        table = json.loads(result.head(500).to_json(orient="records"))
        return FormulaAnswer(mode="custom_python", table=table, explanation="Answered by a generated calculation.")
    return FormulaAnswer(
        mode="custom_python", value=json.dumps(result, default=str), explanation="Answered by a generated calculation."
    )


def answer_question(session_id: str, question: str, df: pd.DataFrame) -> FormulaAnswer:
    """Raises ValueError (never a raw traceback) if neither path could
    produce an answer -- the caller turns that into a 422, same convention
    as the rest of this app's AI agents."""
    question = (question or "").strip()
    if not question:
        raise ValueError("The question is empty.")

    answer: FormulaAnswer | None = None
    try:
        answer = _try_template(question, df)
    except Exception:
        answer = None  # a malformed template attempt just means "try the custom path" too

    if answer is None:
        try:
            answer = _run_custom(question, df)
        except Exception as exc:
            raise ValueError(f"Couldn't compute an answer for that question: {exc}") from exc

    content = (
        answer.pivot.model_dump() if answer.pivot is not None
        else {"table": answer.table} if answer.table is not None
        else {"value": answer.value}
    )
    analysis_store.store.add(session_id, "formula_result", question, {"mode": answer.mode, **content})
    return answer
