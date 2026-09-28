"""Turns the deterministic findings from data_audit.py into (1) a short,
plain-English "data analyst" narrative and (2) a concrete per-finding
recommendation -- including which of the finding's own decision options the
agent thinks the user should pick -- via Groq. This is the only LLM call in
the audit pipeline: it never decides what the issues ARE or fixes anything
itself, it just explains what was already found and advises what to do about
each one. There is no fallback: if Groq isn't configured or the call fails,
that's a real error and the caller (routers/audit.py) surfaces it as one --
the audit agent is required, not optional.
"""
import json

from app.prompts.audit_agent import SYSTEM_PROMPT
from app.schemas import AuditIssue
from app.services.common.groq_client import chat_json

# Column-scoped categories store a column COUNT in affected_row_count, not a
# row count -- kept in sync with AuditIssueCard's COLUMN_SCOPED_CATEGORIES on
# the frontend, since both exist to describe the same finding shape.
COLUMN_SCOPED_CATEGORIES = {"fully_empty_columns", "high_null_columns", "constant_value_columns"}


def _findings_block(row_count: int, column_count: int, issues: list[AuditIssue]) -> str:
    lines = [f"Rows: {row_count}", f"Columns: {column_count}", f"Findings: {len(issues)}"]
    if not issues:
        lines.append("No data-quality issues were detected.")
    for issue in issues:
        decision_note = "requires a user decision" if issue.requires_decision else "informational only"
        options = ", ".join(f"{opt.id}='{opt.label}'" for opt in issue.options)
        base_category = issue.category.split("::")[0]
        if base_category in COLUMN_SCOPED_CATEGORIES:
            scope_note = f"{issue.affected_row_count} of {column_count} columns"
        elif row_count:
            pct = issue.affected_row_count / row_count * 100
            scope_note = f"{issue.affected_row_count} of {row_count} rows ({pct:.1f}%)"
        else:
            scope_note = f"{issue.affected_row_count} rows"
        lines.append(
            f"- id={issue.id} category={base_category} [{issue.severity}] {issue.title} "
            f"({decision_note}), affected: {scope_note}, options: [{options}]: {issue.description}"
        )
    return "\n".join(lines)


def generate_audit_analysis(
    source: str, filename: str, row_count: int, column_count: int, issues: list[AuditIssue]
) -> tuple[str, dict[str, tuple[str | None, str | None]]]:
    """Returns (summary, {issue_id: (recommended_action, note)})."""
    findings = _findings_block(row_count, column_count, issues)
    user_prompt = f"Source: {source}\nFile: {filename}\n\n{findings}\n\nWrite the analysis now."
    raw = chat_json(SYSTEM_PROMPT, user_prompt, call_name="audit_agent")
    payload = json.loads(raw)

    summary = payload.get("summary", "")
    if not isinstance(summary, str):
        summary = ""

    valid_option_ids = {issue.id: {opt.id for opt in issue.options} for issue in issues}
    raw_recs = payload.get("recommendations", {})
    recommendations: dict[str, tuple[str | None, str | None]] = {}
    if isinstance(raw_recs, dict):
        for issue_id, rec in raw_recs.items():
            if issue_id not in valid_option_ids or not isinstance(rec, dict):
                continue
            action = rec.get("action")
            if action not in valid_option_ids[issue_id]:
                action = None
            note = rec.get("note")
            note = note.strip() if isinstance(note, str) and note.strip() else None
            if action or note:
                recommendations[issue_id] = (action, note)

    return summary.strip(), recommendations
