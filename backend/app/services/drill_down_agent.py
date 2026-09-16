"""Suggests where to look next, given what's already been computed for this
session -- the row count, the deterministic highlights (see
overall_analysis.py), and the currently-applied pivot tables. Same
never-invent guardrail as overall_analysis_agent.py: Groq only points at
slices of the data ALREADY represented in the highlights/pivots it's shown
(e.g. "the worst-performing group in an existing pivot"), it never proposes
investigating a column or value that isn't already visible to it.
"""
import json

from app.schemas import OverallHighlight, PivotResult
from app.services.groq_client import chat_json

SYSTEM_PROMPT = """You are a program manager suggesting what to look at \
next in a cold-chain shipment report, given the headline numbers and pivot \
tables already computed. Propose up to 4 SHORT, concrete next steps -- each \
one pointing at a specific slice already visible in what you were given \
(e.g. "Drill into Origin=X's July trips -- it's the worst group in the \
Exception Hours by Origin table"), not a generic suggestion like "investigate \
further". Never invent a value, column, or number that isn't already in the \
highlights or pivot rows given.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"suggestions": ["short suggestion 1", "short suggestion 2", ...]}"""


def _context_block(row_count: int, highlights: list[OverallHighlight], pivots: list[PivotResult]) -> str:
    lines = [f"Rows analyzed: {row_count}", "", "Highlights:"]
    lines += [f"- {h.label}: {h.value}" for h in highlights]
    lines.append("")
    lines.append("Pivot tables:")
    for pivot in pivots:
        lines.append(f"- {pivot.name} (grouped by {', '.join(pivot.group_by)}, metrics: {', '.join(pivot.metric_labels)}):")
        for row in pivot.rows[:8]:
            lines.append("    " + " | ".join(f"{k}={v}" for k, v in row.items()))
        if len(pivot.rows) > 8:
            lines.append(f"    ... and {len(pivot.rows) - 8} more row(s)")
    return "\n".join(lines)


def suggest_drill_downs(row_count: int, highlights: list[OverallHighlight], pivots: list[PivotResult]) -> list[str]:
    if not highlights and not pivots:
        return []
    user_prompt = f"{_context_block(row_count, highlights, pivots)}\n\nPropose the next steps now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    suggestions = payload.get("suggestions", [])
    if not isinstance(suggestions, list):
        return []
    return [str(s).strip() for s in suggestions if str(s or "").strip()][:4]
