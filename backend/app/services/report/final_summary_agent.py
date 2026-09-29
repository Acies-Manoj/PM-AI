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

SYSTEM_PROMPT = """You are a program manager writing the closing summary \
slide for a cold-chain shipment report. You've been given the name and \
already-written interpretation for each analysis included in this report. \
Do NOT invent any number, name, or trend that isn't already stated in one \
of those interpretations, and do NOT just concatenate them one after \
another -- synthesize the most report-worthy points across all of them.

Write 3-5 short bullet points, each one complete self-contained sentence \
(no leading dash or bullet character -- the caller adds that), the way a \
closing summary slide actually reads: one headline fact per bullet, not a \
paragraph split into fragments.

Example -- given interpretations mentioning "DHL lowest at 81% in spec" and \
"Grapes had 3x the excursion rate of any other product":
{"bullets": [
  "DHL is the weakest carrier for temperature compliance at 81% in spec, well below the fleet average.",
  "Grapes see roughly 3x the temperature excursion rate of any other product, making it the highest-risk commodity shipped."
]}

Respond with ONLY a JSON object, no markdown, no commentary:
{"bullets": ["first bullet", "second bullet", "..."]}"""


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
