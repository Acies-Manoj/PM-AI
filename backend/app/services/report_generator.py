"""Report Agent: assembles steps + results into a final HTML or Markdown report."""
from __future__ import annotations

import uuid

from app.schemas import AnalysisStep, ReportOutput
from app.services import report_template_builder as tmpl


def generate_report(
    analysis_id: str,
    session_id: str,
    brief: str,
    steps: list[AnalysisStep],
    validated_results: list[dict],
    fmt: str = "html",
) -> ReportOutput:
    if fmt == "markdown":
        content = tmpl.build_markdown(session_id, brief, steps, validated_results)
    else:
        content = tmpl.build_html(session_id, brief, steps, validated_results)

    return ReportOutput(
        report_id=uuid.uuid4().hex,
        analysis_id=analysis_id,
        title="Cold Chain Analysis Report",
        format=fmt,
        content=content,
    )
