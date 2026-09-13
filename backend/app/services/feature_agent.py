"""Feature Agent -- suggests cold-chain features and writes sandboxable code
for them.

Two capabilities, both real tool-calling agents grounded in the actual
audited dataframe rather than a bare column list:
1. suggest_features()      — inspects real columns, then proposes features
2. generate_feature_code() — writes code, test-runs it in the sandbox against
                              the real data, and iterates on the actual error
                              before submitting a final answer
"""
from __future__ import annotations

import pandas as pd

from app.config import MODEL_FEATURE_AGENT
from app.schemas import AIFeatureCodeResult, FeatureSuggestion
from app.services import sandbox_executor
from app.services.openrouter_client import ToolSpec, run_agent_loop

_SUGGEST_SYSTEM = """You are a cold-chain data-science expert. You have a tool \
to inspect real columns of the audited dataframe before suggesting anything -- \
use it on a few relevant columns first. Then suggest up to 5 new features that \
would be valuable for cold-chain KPI analysis. Prioritise:
- Excursion duration (time above threshold)
- Excursion magnitude (how far above threshold)
- Rate of temperature change
- % time in spec per trip
- Any brief-specific metrics

Call submit_suggestions exactly once when you are done."""

_CODE_SYSTEM = """You are a Python data-engineering expert writing sandboxed code \
for a cold-chain analysis pipeline. Your code computes a feature from a pandas \
DataFrame `df` and assigns a pd.Series to `result`.

Rules:
- `df` already exists -- never read from disk or network
- Only import: pandas (as pd), numpy (as np), math, re, statistics
- Never call exec, eval, open, or __import__
- `result` must be a pd.Series aligned with df.index
- Guard every column access: `if 'Col' in df.columns`
- Keep it concise -- under 20 lines

Use preview_column to check real column names/dtypes/values before writing \
code. Always call test_code with your draft and read the actual result or \
error -- if it fails, fix the code and test again. Only call submit_feature \
once test_code has confirmed the code runs cleanly."""


def _preview_tool(df: pd.DataFrame) -> ToolSpec:
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

    return ToolSpec(
        name="preview_column",
        description="Inspect a real column's dtype, null count, and stats/sample values.",
        parameters={
            "type": "object",
            "properties": {"column_name": {"type": "string"}},
            "required": ["column_name"],
        },
        handler=preview_column,
    )


def suggest_features(df: pd.DataFrame, brief: str) -> list[FeatureSuggestion]:
    columns = ", ".join(str(c) for c in df.columns)
    prompt = f"Columns: {columns}\n\nBrief:\n{brief}"

    finish = ToolSpec(
        name="submit_suggestions",
        description="Submit the final list of feature suggestions.",
        parameters={
            "type": "object",
            "properties": {
                "suggestions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "description": {"type": "string"},
                            "rationale": {"type": "string"},
                            "feature_type": {
                                "type": "string",
                                "enum": ["excursion_duration", "excursion_magnitude", "rate_of_change", "custom"],
                            },
                        },
                        "required": ["name", "description", "rationale", "feature_type"],
                    },
                }
            },
            "required": ["suggestions"],
        },
        handler=lambda **kwargs: kwargs,
    )

    trace = run_agent_loop(
        _SUGGEST_SYSTEM,
        prompt,
        [_preview_tool(df), finish],
        model=MODEL_FEATURE_AGENT,
        finish_tool="submit_suggestions",
        temperature=0.4,
        max_iterations=5,
    )
    if not trace.final_args:
        return []
    try:
        return [FeatureSuggestion(**s) for s in trace.final_args.get("suggestions", [])]
    except Exception:
        return []


def generate_feature_code(user_request: str, df: pd.DataFrame) -> AIFeatureCodeResult:
    columns = ", ".join(str(c) for c in df.columns)
    prompt = f"Available columns: {columns}\n\nFeature request: {user_request}"

    def test_code(code: str) -> dict:
        series, error = sandbox_executor.run_feature_code(code, df)
        if error:
            return {"success": False, "error": error}
        return {"success": True, "sample_values": [str(v) for v in series.head(5).tolist()]}

    test_tool = ToolSpec(
        name="test_code",
        description="Run draft code against the real dataframe and see the actual result or error.",
        parameters={
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        },
        handler=test_code,
    )
    finish = ToolSpec(
        name="submit_feature",
        description="Submit the final, tested feature code.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "output_column": {"type": "string", "description": "snake_case column name"},
                "code": {"type": "string"},
            },
            "required": ["name", "description", "output_column", "code"],
        },
        handler=lambda **kwargs: kwargs,
    )

    trace = run_agent_loop(
        _CODE_SYSTEM,
        prompt,
        [_preview_tool(df), test_tool, finish],
        model=MODEL_FEATURE_AGENT,
        finish_tool="submit_feature",
        temperature=0.2,
        max_iterations=6,
    )
    if not trace.final_args:
        return AIFeatureCodeResult(
            name="custom_feature",
            description=user_request,
            output_column="custom_feature",
            code="",
            error="Feature agent did not produce a final result.",
        )
    data = trace.final_args
    return AIFeatureCodeResult(
        name=data.get("name", "custom_feature"),
        description=data.get("description", user_request),
        output_column=data.get("output_column", "custom_feature"),
        code=data.get("code", ""),
    )
