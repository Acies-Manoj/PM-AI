"""Turns ONE already-computed pivot table into a short plain-language
interpretation via Groq -- the per-chart counterpart to
overall_analysis_agent.py's whole-report narrative. Same guardrail: Groq is
only shown this pivot's own rows and never invents a number, name, or trend
that isn't already in them. There is no fallback: if Groq isn't configured
or the call fails, that's a real error and the caller surfaces it as one.
"""
from app.schemas import PivotResult
from app.services.groq_client import chat_text

SYSTEM_PROMPT = """You are a program manager writing a 1-2 sentence caption \
for one chart in a cold-chain shipment report. You've been given that \
chart's own computed rows (a group-by column, one or more metrics, already \
sorted). Do NOT invent any number, name, or row that isn't in the table \
given, and do NOT just restate the table -- call out the standout row(s) \
(highest/lowest/an outlier gap) and what it likely means operationally. \
Write exactly 1-2 plain-English sentences, no markdown, no bullet lists, no \
restating these instructions."""


def _rows_block(pivot: PivotResult) -> str:
    lines = [f"Chart: {pivot.name} -- grouped by {', '.join(pivot.group_by)}, metrics: {', '.join(pivot.metric_labels)}"]
    for row in pivot.rows[:25]:  # a long tail doesn't change the caption -- keep the prompt small
        lines.append(" | ".join(f"{k}={v}" for k, v in row.items()))
    if len(pivot.rows) > 25:
        lines.append(f"... and {len(pivot.rows) - 25} more row(s)")
    return "\n".join(lines)


def interpret_pivot(pivot: PivotResult) -> str:
    if not pivot.rows:
        return "This chart has no rows to interpret (its filters currently exclude every trip)."
    user_prompt = f"{_rows_block(pivot)}\n\nWrite the caption now."
    return chat_text(SYSTEM_PROMPT, user_prompt).strip()
