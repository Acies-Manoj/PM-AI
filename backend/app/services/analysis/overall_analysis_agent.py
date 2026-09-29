"""Turns the deterministic highlights from overall_analysis.py into a short
executive-summary narrative via OpenRouter. This is the only LLM call in
the overall-analysis pipeline -- it never computes a number itself, only
explains the highlights already given, same guardrail as audit_agent.py.
There is no fallback: if OPENROUTER_API_KEY isn't configured or the call
fails, that's a real error and the caller surfaces it as one.
"""
from app.prompts.overall_analysis_agent import SYSTEM_PROMPT
from app.schemas import OverallHighlight
from app.services.common.llm_client import chat_text


def _highlights_block(highlights: list[OverallHighlight]) -> str:
    return "\n".join(f"- {h.label}: {h.value}" for h in highlights)


def generate_narrative(row_count: int, highlights: list[OverallHighlight]) -> str:
    block = _highlights_block(highlights)
    user_prompt = f"Rows analyzed: {row_count}\n\n{block}\n\nWrite the executive summary now."
    text = chat_text(SYSTEM_PROMPT, user_prompt, call_name="overall_analysis_agent")
    return text.strip()
