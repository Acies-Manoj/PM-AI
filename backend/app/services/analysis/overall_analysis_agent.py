"""Turns the deterministic highlights from overall_analysis.py into a short
executive-summary narrative via Bedrock. This is the only LLM call in the
overall-analysis pipeline -- it never computes a number itself, only
explains the highlights already given, same guardrail as audit_agent.py.
There is no fallback: if Bedrock isn't configured or the call fails, that's a
real error and the caller surfaces it as one.
"""
from app.schemas import OverallHighlight
from app.services.common import llm

SYSTEM_PROMPT = """You are a program manager writing the executive-summary \
paragraph for a recurring cold-chain shipment report. You've been given a \
list of already-computed headline numbers (rows analyzed, feature averages, \
top categories, and best/worst performers from the pivot tables below). Do \
NOT invent any number, name, or trend that isn't in the list given, and do \
NOT restate every bullet -- synthesize the 2-3 most report-worthy points \
into plain prose. Write exactly 2-4 plain-English sentences, no markdown, \
no bullet lists, no restating these instructions.

Example -- given highlights "Total Rows Analyzed: 1,993", "Highest Avg Mean \
Value: Product Grapes (6.8)", "Lowest % in spec: Carrier DHL (81%)", "Most \
common Origin: ZA", write something like: "Across 1,993 shipments, Grapes \
carried the highest average sensor reading (6.8) and DHL trailed the fleet \
on compliance at 81% in spec." -- two of the four points, synthesized, not \
all four restated as separate clauses."""


def _highlights_block(highlights: list[OverallHighlight]) -> str:
    return "\n".join(f"- {h.label}: {h.value}" for h in highlights)


def generate_narrative(row_count: int, highlights: list[OverallHighlight]) -> str:
    block = _highlights_block(highlights)
    user_prompt = f"Rows analyzed: {row_count}\n\n{block}\n\nWrite the executive summary now."
    text = llm.chat_text(
        llm.system_prompt("overall_analysis_agent", SYSTEM_PROMPT), user_prompt, call_name="overall_analysis_agent",
    )
    return text.strip()
