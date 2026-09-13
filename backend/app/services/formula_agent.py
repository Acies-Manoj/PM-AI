"""Formula Agent -- translates a natural-language analytical ask into
sandboxable Python via a self-testing ReAct loop: the agent writes code, runs
it against the real dataframe through the sandbox, sees the actual error or
result, and rewrites until it gets a valid answer.

The generated code computes a result dict from the audited + engineered
dataframe. Result must be one of:
  {"type": "metric",     "label": "...", "value": <number|str>}
  {"type": "table",      "columns": [...], "rows": [[...], ...]}
  {"type": "chart_data", "chart_type": "bar|line|scatter", "labels": [...], "values": [...], "title": "..."}
"""
from __future__ import annotations

import pandas as pd

from app.config import MODEL_FORMULA_AGENT
from app.services import sandbox_executor
from app.services.openrouter_client import ToolSpec, run_agent_loop

_SYSTEM = """You are a Python data-engineering expert answering an analytical \
question against a real pandas DataFrame `df` for a cold-chain shipment \
dataset. You have tools to inspect real columns and test-run your code \
against the actual data before submitting.

Your code must assign its answer to a variable `result`, as one of:
- {"type": "metric", "label": "...", "value": <number or string>}
- {"type": "table", "columns": [...], "rows": [[...], ...]}  (max 50 rows)
- {"type": "chart_data", "chart_type": "bar|line|scatter", "labels": [...], "values": [...], "title": "..."}

Rules for the code: only use df, pd, np, math; guard every column access with \
`if 'Col' in df.columns`; no file I/O or network calls; under 25 lines.

Always call test_code with your draft before submit_formula. If test_code \
reports an error, fix the code and test again. Only call submit_formula once \
test_code has confirmed the code runs cleanly."""


def _build_tools(df: pd.DataFrame) -> list[ToolSpec]:
    def preview_column(column_name: str) -> dict:
        if column_name not in df.columns:
            return {"error": f"'{column_name}' is not a column. Available: {list(df.columns)[:30]}"}
        series = df[column_name]
        info: dict = {"dtype": str(series.dtype), "non_null": int(series.notna().sum())}
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().any():
            info.update(
                mean=round(float(numeric.mean()), 3),
                min=round(float(numeric.min()), 3),
                max=round(float(numeric.max()), 3),
            )
        else:
            info["sample_values"] = [str(v) for v in series.dropna().unique()[:8]]
        return info

    def test_code(code: str) -> dict:
        result, error = sandbox_executor.run_formula_code(code, df)
        if error:
            return {"success": False, "error": error}
        return {"success": True, "result_preview": result}

    return [
        ToolSpec(
            name="preview_column",
            description="Inspect a real column's dtype, null count, and stats/sample values.",
            parameters={
                "type": "object",
                "properties": {"column_name": {"type": "string"}},
                "required": ["column_name"],
            },
            handler=preview_column,
        ),
        ToolSpec(
            name="test_code",
            description="Run draft Python against the real dataframe and see the actual result dict or error.",
            parameters={
                "type": "object",
                "properties": {"code": {"type": "string"}},
                "required": ["code"],
            },
            handler=test_code,
        ),
    ]


_FINISH_TOOL = ToolSpec(
    name="submit_formula",
    description="Submit the final, tested code that answers the question.",
    parameters={
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "One sentence describing what this computes."},
            "code": {"type": "string", "description": "The final Python code, already confirmed working via test_code."},
        },
        "required": ["description", "code"],
    },
    handler=lambda **kwargs: kwargs,
)


def generate_formula_code(ask: str, df: pd.DataFrame, context: str) -> tuple[str, str]:
    """Return (description, sandboxable_code) for a self-tested formula."""
    tools = _build_tools(df) + [_FINISH_TOOL]
    columns = ", ".join(str(c) for c in df.columns)
    prompt = f"Available columns: {columns}\n\nContext:\n{context}\n\nQuestion: {ask}"
    trace = run_agent_loop(
        _SYSTEM,
        prompt,
        tools,
        model=MODEL_FORMULA_AGENT,
        finish_tool="submit_formula",
        temperature=0.2,
        max_iterations=6,
    )
    if trace.final_args:
        return trace.final_args.get("description", ask), trace.final_args.get("code", "")
    return ask, ""
