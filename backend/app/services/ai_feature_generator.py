"""AI fallback for feature calculations that no existing template (lookup,
extract_month, ratio, duration_hours, custom_formula) can express. Used
only when a feature spec's type is "ai_generated" -- Groq is given the
calculation described in plain English plus the current dataframe's
columns/dtypes/samples, and asked to write a short pandas snippet. The
snippet is never trusted at face value: it's AST-validated and run in a
restricted sandbox (see ai_code_executor.py) before its output is accepted
as a feature column.
"""
import re

import pandas as pd

from app.services.groq_client import chat_text
from app.services.llm_context import columns_block as _columns_block

SYSTEM_PROMPT = """You are a data engineer writing a short Python snippet \
to compute one new column on an operational cold-chain shipment dataset.

A pandas DataFrame is already available as the variable `df`, and the \
`pandas` module is already available as `pd`. Write vectorized pandas code \
(no explicit for/while loops, no function or class definitions, no \
imports) that computes the requested calculation and assigns the final \
result -- a pandas Series with exactly one value per row of `df`, aligned \
to `df.index` -- to a variable named exactly `result`.

Rules:
- Only reference columns that actually appear in the column list given below.
- Never read or write files, never use eval/exec/open, never import \
anything, never call any to_csv/to_excel/read_csv/etc-style I/O method -- \
everything you need is already available as `df` and `pd`.
- If the calculation naturally produces one value per group (e.g. an \
average per lane) rather than one value per row, broadcast it back to \
every row of that group (e.g. with `.transform(...)` or `.map(...)`), \
since `result` must have exactly one value per row.
- Respond with ONLY the Python code. No markdown fences, no explanation, \
no comments."""


def _strip_code_fence(text: str) -> str:
    """Groq is told not to use markdown fences, but strips them
    defensively if it does anyway."""
    stripped = text.strip()
    match = re.match(r"^```(?:python)?\s*\n(.*)\n```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def generate_code(spec: dict, df: pd.DataFrame) -> str:
    """Raises whatever the Groq client raises (e.g. missing API key,
    network error) -- the caller (feature_engineering._apply_ai_generated)
    is responsible for turning that into a skip note rather than a 500."""
    calculation_prompt = (spec.get("calculation_prompt") or "").strip()
    user_prompt = (
        f"Calculation to implement: {calculation_prompt}\n\n"
        f"Output column name: {spec.get('output_column', 'result')}\n\n"
        f"Columns available in `df`:\n{_columns_block(df)}\n\n"
        f"Write the code now."
    )
    raw = chat_text(SYSTEM_PROMPT, user_prompt)
    return _strip_code_fence(raw)
