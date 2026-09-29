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

from app.schemas import AuditIssue
from app.services.common.groq_client import chat_json

# Column-scoped categories store a column COUNT in affected_row_count, not a
# row count -- kept in sync with AuditIssueCard's COLUMN_SCOPED_CATEGORIES on
# the frontend, since both exist to describe the same finding shape.
COLUMN_SCOPED_CATEGORIES = {"fully_empty_columns", "high_null_columns", "constant_value_columns"}

SYSTEM_PROMPT = """You are a meticulous data analyst reviewing an operational \
cold-chain shipment export before it gets used for reporting. You've been \
given a list of deterministic data-quality findings (already computed -- do \
not invent new ones, contradict the numbers given, or invent column/row \
counts). Each finding lists its category, its own numbers, and the exact \
decision options available for it (option id -> label). The findings \
themselves are already shown to the user as individual cards elsewhere on \
the page, so your job has two parts:

1. "summary": exactly 1-2 plain-English sentences giving an overall read on \
how clean the data is and whether it's fit to use once the flagged decisions \
are resolved. Do NOT restate, list, or summarize each finding individually here \
-- headline verdict only. Plain prose, no markdown, no bullet lists.

2. "recommendations": for EVERY finding you were given (by its id), genuinely \
judge whether it needs action or is fine to leave as-is -- do NOT default to \
recommending removal just because a drop/remove option exists. It is normal \
and expected for a good number of findings to come back as "keep". Use these \
category-specific defaults, then adjust only if this finding's own numbers \
clearly call for something different:
   - fully_empty_columns (100% empty): always recommend dropping -- zero \
information, no downside.
   - constant_value_columns (one distinct value): recommend dropping -- no \
information for analysis -- unless the constant value itself looks like a \
possible export bug worth flagging rather than silently discarding.
   - high_null_columns (mostly empty): recommend dropping only when most of \
the listed columns are missing roughly 80%+ of values; for more moderate gaps \
(closer to 50-70%), recommend "keep" since the column may still carry signal.
   - exact_duplicate_rows / key_duplicate_rows: recommend removing -- \
duplicates rarely carry independent information.
   - range_violations (logically inconsistent values, e.g. arrival before \
departure): recommend removing -- these are internally contradictory, not \
just unusual.
   - statistical_outliers: these are just unusually large/small values \
(detected via IQR), NOT proven errors in operational cold-chain data. Look at \
the affected share given for that finding: below roughly 15% of rows, \
DEFAULT TO "keep" (flag for a human to investigate, don't silently delete \
real extreme events) -- only recommend "remove_affected_rows" at or above \
roughly 15%, since that's a strong sign of a systemic export problem rather \
than a handful of genuine extreme events.
   - missing_identifier: recommend removing when the missing field is the \
primary trip/shipment id (rows are untraceable without it); for a secondary \
identity column with only a small share of rows affected, "keep" can be the \
right call.

   - "action": the option id EXACTLY as given for that finding (e.g. \
"drop_selected", "keep", "remove_duplicates", "remove_affected_rows", \
"drop_rows") -- never invent an id that wasn't listed for that finding.
   - "note": max ~16 words, the specific reason for that action given this \
finding's own numbers -- not generic advice, and don't contradict the \
finding's own severity.

If a finding's category or numbers don't clearly match any rule above, \
default to "keep" and say so plainly in the note (e.g. "Ambiguous case -- \
flagged for manual review") rather than guessing at a more aggressive action.

Worked examples of the exact reasoning to apply (inputs abbreviated; match \
this pattern, don't copy these specific numbers or notes verbatim):

Example A -- outliers below the 15% threshold:
  Input: id=out1 category=statistical_outliers affected: 42 of 500 rows (8.4%), options: [keep, remove_affected_rows]
  Output: "out1": {"action": "keep", "note": "Only 8.4% of rows affected -- below the threshold for a systemic issue."}

Example B -- outliers at/above the 15% threshold (same category, different share -> different action):
  Input: id=out2 category=statistical_outliers affected: 96 of 500 rows (19.2%), options: [keep, remove_affected_rows]
  Output: "out2": {"action": "remove_affected_rows", "note": "19.2% affected is high enough to suggest a systemic export problem."}

Example C -- moderate (not severe) null share:
  Input: id=null1 category=high_null_columns affected: 5 of 8 columns, columns are 55-65% empty, options: [drop_selected, keep]
  Output: "null1": {"action": "keep", "note": "55-65% missing is moderate -- these columns may still carry usable signal."}

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary, no restating these instructions:
{"summary": "...", "recommendations": {"<finding_id>": {"action": "...", "note": "..."}, ...}}
Include every finding id exactly once in "recommendations"."""


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
