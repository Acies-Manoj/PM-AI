"""Renders the final HTML or Markdown report from analysis results."""
from __future__ import annotations

import html
from datetime import datetime

from app.schemas import AnalysisStep

_STEP_TITLES = {
    "summary": "Executive Summary",
    "chart_suggestion": "Chart Recommendation",
    "chart_interpretation": "Chart Interpretation",
    "drill_down": "Drill-Down Suggestions",
    "formula_spec": "Analytical Formula",
}

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
body{{font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:40px;background:#f4f6fb;color:#1b2333}}
.wrap{{max-width:860px;margin:0 auto;background:#fff;border-radius:12px;padding:40px;box-shadow:0 4px 24px rgba(21,44,115,.08)}}
h1{{font-size:26px;font-weight:800;color:#152c73;margin:0 0 6px}}
.meta{{font-size:13px;color:#5b6478;margin-bottom:32px}}
.section{{margin-bottom:28px;padding-bottom:24px;border-bottom:1px solid #dde3ef}}
.section:last-child{{border-bottom:none}}
.badge{{display:inline-block;background:#eaf1fb;color:#152c73;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;margin-bottom:8px}}
h2{{font-size:17px;font-weight:700;color:#152c73;margin:0 0 10px}}
.content{{font-size:14px;line-height:1.7;white-space:pre-wrap}}
.metric{{background:#eaf1fb;border-radius:8px;padding:16px 20px;display:inline-block;margin:8px 0}}
.metric-value{{font-size:28px;font-weight:800;color:#152c73}}
.metric-label{{font-size:12px;color:#5b6478;margin-top:2px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th{{background:#eaf1fb;padding:8px 10px;text-align:left;font-weight:700;color:#152c73}}
td{{padding:7px 10px;border-bottom:1px solid #dde3ef}}
.footer{{margin-top:40px;font-size:12px;color:#5b6478;text-align:right}}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <p class="meta">Generated: {date} · Session: {session_id}</p>
  {sections}
  <div class="footer">AI-Assisted Cold Chain Analysis · Carrier</div>
</div>
</body>
</html>"""

_SECTION = """<div class="section">
  <div class="badge">Step {step}</div>
  <h2>{heading}</h2>
  <div class="content">{content}</div>
</div>"""


def _result_html(res: dict) -> str:
    if res.get("type") == "metric":
        return (
            f'<div class="metric">'
            f'<div class="metric-value">{html.escape(str(res.get("value", "")))}</div>'
            f'<div class="metric-label">{html.escape(str(res.get("label", "")))}</div>'
            f"</div>"
        )
    if res.get("type") == "table":
        cols = res.get("columns", [])
        rows = res.get("rows", [])
        th = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        tr = "".join(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
            for row in rows
        )
        return f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>"
    return ""


def build_html(
    session_id: str,
    brief: str,
    steps: list[AnalysisStep],
    validated_results: list[dict],
) -> str:
    secs = f'<div class="section"><h2>Client Brief</h2><div class="content">{html.escape(brief)}</div></div>'
    for s in steps:
        heading = _STEP_TITLES.get(s.step_type, s.step_type.replace("_", " ").title())
        secs += _SECTION.format(step=s.step_number, heading=heading, content=html.escape(s.content))
    for res in validated_results:
        rh = _result_html(res)
        if rh:
            secs += f'<div class="section"><h2>Computed Result</h2>{rh}</div>'
    return _HTML.format(
        title="Cold Chain Analysis Report",
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        session_id=session_id,
        sections=secs,
    )


def build_markdown(
    session_id: str,
    brief: str,
    steps: list[AnalysisStep],
    validated_results: list[dict],
) -> str:
    lines = [
        "# Cold Chain Analysis Report",
        f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} · Session: {session_id}*",
        "",
        "## Client Brief",
        brief,
        "",
    ]
    for s in steps:
        heading = _STEP_TITLES.get(s.step_type, s.step_type.replace("_", " ").title())
        lines += [f"## {heading}", s.content, ""]
    for res in validated_results:
        if res.get("type") == "metric":
            lines += ["## Computed Metric", f"**{res.get('value')}** — {res.get('label', '')}", ""]
    return "\n".join(lines)
