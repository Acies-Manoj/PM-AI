"""Insight Agent -- drives the 5-step AI analysis loop.

Each step is a real ReAct agent grounded in the actual audited dataframe: it
can query real groups, stats, and filters through tools before writing its
answer, instead of guessing from a canned text summary. The 5-step sequence
itself is still driven by routers/analysis.py (summary -> chart_suggestion ->
chart_interpretation -> drill_down -> formula_spec) so the frontend's step
contract is unchanged -- what changed is that each step now has to look at
real numbers before it can finish.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.config import MODEL_INSIGHT_AGENT
from app.services.openrouter_client import ToolSpec, run_agent_loop

_BASE_SYSTEM = """You are an expert cold-chain data analyst supporting a logistics \
quality team. You are working through a structured analysis of flagged shipment \
trips and have tools to query the real dataframe -- use them before answering \
so you never invent numbers. Be concise, specific, and data-driven.

Call submit_step_output exactly once when you are ready to answer. Its \
`content` field must be plain prose (2-4 sentences) -- never raw JSON."""

_STEP_INSTRUCTIONS: dict[str, str] = {
    "summary": (
        "Write 2-3 sentences summarising the key patterns in the flagged trips, "
        "using your tools to check real numbers first. Focus on findings relevant "
        "to the client brief. Submit via `content` only."
    ),
    "chart_suggestion": (
        "Decide the single best chart for these flagged trips given the brief. "
        "Submit `content` describing the chart (type, x/y columns, one-sentence "
        "rationale) in plain English, and also set `chart_type` "
        "(bar|line|scatter|table)."
    ),
    "chart_interpretation": (
        "In 2-3 sentences, explain what the previously suggested chart shows and "
        "what it means for the client's specific brief. Submit via `content` only."
    ),
    "drill_down": (
        "Use your tools to find the most interesting real pattern to dig into, "
        "then submit exactly 3 specific follow-up questions in "
        "`drill_down_suggestions`, plus a one-sentence `content` framing them."
    ),
    "formula_spec": (
        "Based on the drill-down ask, write a precise plain-English computational "
        "specification in `content` -- columns involved, grouping, and what the "
        "output represents."
    ),
}

_OPS = {
    "==": lambda s, v: s.astype(str) == str(v),
    "!=": lambda s, v: s.astype(str) != str(v),
    ">": lambda s, v: pd.to_numeric(s, errors="coerce") > float(v),
    ">=": lambda s, v: pd.to_numeric(s, errors="coerce") >= float(v),
    "<": lambda s, v: pd.to_numeric(s, errors="coerce") < float(v),
    "<=": lambda s, v: pd.to_numeric(s, errors="coerce") <= float(v),
}


@dataclass
class StepResult:
    content: str
    chart_type: str | None = None
    drill_down_suggestions: list[str] = field(default_factory=list)


def _build_context(brief: str, flagged_summary: str, prior_steps: list[dict]) -> str:
    parts = [f"Client brief:\n{brief}", f"\nData context:\n{flagged_summary}"]
    for s in prior_steps:
        parts.append(f"\nStep {s['step_number']} ({s['step_type']}):\n{s['content']}")
    return "\n".join(parts)


def _build_tools(df: pd.DataFrame) -> list[ToolSpec]:
    def run_group_analysis(group_by: str, metric: str, agg: str = "mean") -> dict:
        if group_by not in df.columns:
            return {"error": f"'{group_by}' is not a column."}
        if metric not in df.columns:
            return {"error": f"'{metric}' is not a column."}
        if agg not in ("mean", "sum", "count", "min", "max"):
            return {"error": f"Unsupported aggregation '{agg}'."}
        numeric = pd.to_numeric(df[metric], errors="coerce")
        grouped = numeric.groupby(df[group_by]).agg(agg).dropna().sort_values(ascending=False)
        return {str(k): round(float(v), 3) for k, v in grouped.head(10).items()}

    def compute_column_stats(column: str) -> dict:
        if column not in df.columns:
            return {"error": f"'{column}' is not a column."}
        numeric = pd.to_numeric(df[column], errors="coerce").dropna()
        if numeric.empty:
            return {"error": f"'{column}' has no numeric values."}
        return {
            "count": int(numeric.count()),
            "mean": round(float(numeric.mean()), 3),
            "min": round(float(numeric.min()), 3),
            "max": round(float(numeric.max()), 3),
            "std": round(float(numeric.std()), 3),
        }

    def filter_and_count(column: str, operator: str, value: str) -> dict:
        if column not in df.columns:
            return {"error": f"'{column}' is not a column."}
        op = _OPS.get(operator)
        if op is None:
            return {"error": f"Unsupported operator '{operator}'. Use one of {list(_OPS)}."}
        try:
            mask = op(df[column], value)
        except (ValueError, TypeError) as exc:
            return {"error": f"Could not compare '{column}' {operator} '{value}': {exc}"}
        return {"matching_rows": int(mask.sum()), "total_rows": len(df)}

    return [
        ToolSpec(
            name="run_group_analysis",
            description=(
                "Group the real trip data by a column and aggregate a metric "
                "column. Returns the top 10 groups by value."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "group_by": {"type": "string"},
                    "metric": {"type": "string"},
                    "agg": {"type": "string", "enum": ["mean", "sum", "count", "min", "max"]},
                },
                "required": ["group_by", "metric"],
            },
            handler=run_group_analysis,
        ),
        ToolSpec(
            name="compute_column_stats",
            description="Get count/mean/min/max/std for a real numeric column.",
            parameters={
                "type": "object",
                "properties": {"column": {"type": "string"}},
                "required": ["column"],
            },
            handler=compute_column_stats,
        ),
        ToolSpec(
            name="filter_and_count",
            description="Count how many real rows match a simple condition on one column.",
            parameters={
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "operator": {"type": "string", "enum": list(_OPS)},
                    "value": {"type": "string"},
                },
                "required": ["column", "operator", "value"],
            },
            handler=filter_and_count,
        ),
    ]


_FINISH_TOOL = ToolSpec(
    name="submit_step_output",
    description="Submit your finished output for this analysis step.",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Plain-English prose for this step. Never raw JSON."},
            "chart_type": {"type": "string", "enum": ["bar", "line", "scatter", "table"]},
            "drill_down_suggestions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["content"],
    },
    handler=lambda **kwargs: kwargs,
)


def run_step(
    step_type: str,
    brief: str,
    df: pd.DataFrame,
    flagged_summary: str,
    prior_steps: list[dict],
    user_ask: str | None = None,
) -> StepResult:
    context = _build_context(brief, flagged_summary, prior_steps)
    if user_ask and step_type in ("drill_down", "formula_spec"):
        context += f"\n\nUser ask: {user_ask}"
    instruction = _STEP_INSTRUCTIONS.get(step_type, "Continue the analysis.")

    tools = _build_tools(df) + [_FINISH_TOOL]
    trace = run_agent_loop(
        _BASE_SYSTEM,
        f"{context}\n\n{instruction}",
        tools,
        model=MODEL_INSIGHT_AGENT,
        finish_tool="submit_step_output",
        temperature=0.3,
        max_iterations=5,
    )
    if not trace.final_args:
        return StepResult(content=trace.final_text or "The insight agent could not complete this step.")
    return StepResult(
        content=trace.final_args.get("content", ""),
        chart_type=trace.final_args.get("chart_type"),
        drill_down_suggestions=trace.final_args.get("drill_down_suggestions") or [],
    )
