"""Turns the deterministic findings from data_audit.py into a short,
plain-English "data analyst" narrative via an LLM call. This is the only LLM
call in the audit pipeline -- it never decides what the issues are or fixes
anything itself, it just explains what was already found. There is no
fallback: if OpenRouter isn't configured or the call fails, that's a real
error and the caller (routers/audit.py) surfaces it as one -- the audit
agent is required, not optional.
"""
from app.config import MODEL_AUDIT_NARRATOR
from app.schemas import AuditIssue
from app.services.openrouter_client import chat_text

SYSTEM_PROMPT = """You are a meticulous data analyst reviewing an operational \
cold-chain shipment export before it gets used for reporting. You've been \
given a list of deterministic data-quality findings (already computed -- do \
not invent new ones or contradict the numbers given). The findings themselves \
are already shown to the user as individual cards elsewhere on the page, so \
do NOT restate, list, or summarize each one -- your job is a short headline \
verdict only. Write exactly 1-2 plain-English sentences: an overall read on \
how clean the data is and whether it's fit to use once the flagged decisions \
are resolved. Plain prose, no markdown, no bullet lists, no restating these \
instructions."""


def _findings_block(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    lines = [f"Rows: {row_count}", f"Columns: {column_count}", f"Findings: {len(issues)}"]
    if not issues:
        lines.append("No data-quality issues were detected.")
    for issue in issues:
        decision_note = "requires a user decision" if issue.requires_decision else "informational only"
        lines.append(
            f"- [{issue.severity}] {issue.title} ({decision_note}): {issue.description}"
        )
    return "\n".join(lines)


def generate_summary(source: str, filename: str, row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    findings = _findings_block(row_count, column_count, issues)
    user_prompt = f"Source: {source}\nFile: {filename}\n\n{findings}\n\nWrite the summary now."
    text = chat_text(SYSTEM_PROMPT, user_prompt, model=MODEL_AUDIT_NARRATOR)
    return text.strip()
