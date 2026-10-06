"""Synthesizes the Report's own closing-slide bullet points directly from
the selected analyses' own interpretations -- deliberately independent of
overall_analysis_agent.py's KPI-highlights narrative (the Analysis page's
Summary, which never actually reads any interpretation text, and stays
prose since it's a different UI surface). Same single-LLM-call, no-fallback
guardrail as overall_analysis_agent.py: if the call fails, the caller
surfaces that as a real error.

Bullet points, not a prose paragraph, deliberately -- the reference report
this tool was modeled on (see report_generator.py's module docstring) closes
on a bullet-point slide, never a paragraph.
"""
import json

from app.services.common.groq_client import chat_json
from app.prompts import final_summary_agent as _prompts

SYSTEM_PROMPT = _prompts.SYSTEM_PROMPT


def _entries_block(entries: list[dict]) -> str:
    lines = []
    for entry in entries:
        interpretation = entry.get("interpretation")
        if not interpretation:
            continue
        name = entry.get("name") or "Analysis"
        # Drill-down levels are labelled with their slide number and parent so
        # the model reads them as a narrowing of that slide, not a separate topic.
        number = entry.get("slide_number")
        parent = entry.get("parent_slide_number")
        label = f"Slide {number}" if number else ""
        if parent:
            label += f", drill-down of slide {parent}"
            if entry.get("subtitle"):
                label += f" ({entry['subtitle']})"
        lines.append(f"- {f'[{label}] ' if label else ''}{name}: {interpretation}")
    return "\n".join(lines)


def generate_summary(entries: list[dict]) -> list[str]:
    block = _entries_block(entries)
    if not block:
        return ["No analysis interpretations were available to summarize."]
    user_prompt = f"{block}\n\nWrite the final summary now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt, call_name="report_final_summary_agent")
    payload = json.loads(raw)
    bullets = payload.get("bullets")
    if not isinstance(bullets, list) or not bullets:
        raise ValueError("The final summary agent returned no bullets.")
    return [str(b).strip() for b in bullets if str(b).strip()]
