import io
import json

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import AuditReport, FeatureReport, ResolveRequest
from app.services import data_audit, feature_engineering
from app.services import feature_definitions_store as defs_store
from app.services.audit_agent import generate_summary
from app.services.audit_store import AuditSession, store
from app.services.excel_parser import load_spreadsheet

router = APIRouter(prefix="/api/audit", tags=["audit"])

DEFAULT_PREVIEW_ROWS = 20
MAX_PREVIEW_ROWS = 500


def _to_report(session: AuditSession) -> AuditReport:
    pending_decisions = any(i.requires_decision and i.status == "pending" for i in session.issues)
    return AuditReport(
        session_id=session.session_id,
        source=session.source,
        filename=session.filename,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        summary=session.summary,
        issues=session.issues,
        status="pending_review" if pending_decisions else "reviewed",
    )


def _to_feature_report(session: AuditSession) -> FeatureReport:
    return FeatureReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        features=session.features,
        skipped_notes=session.feature_skipped_notes,
    )


def _get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


@router.post("/upload", response_model=AuditReport)
async def upload_for_audit(file: UploadFile = File(...), source: str = Form(...)) -> AuditReport:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        df, parse_warnings = load_spreadsheet(raw, file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    issues = data_audit.run_audit(df)
    try:
        summary = generate_summary(source, file.filename or "upload", len(df), len(df.columns), issues)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data audit agent is unavailable: {exc}") from exc
    if parse_warnings:
        summary = " ".join(parse_warnings) + " " + summary

    session = store.create(source=source, filename=file.filename or "upload", df=df, issues=issues, summary=summary)
    return _to_report(session)


@router.get("/{session_id}", response_model=AuditReport)
def get_audit(session_id: str) -> AuditReport:
    return _to_report(_get_session_or_404(session_id))


@router.post("/{session_id}/resolve", response_model=AuditReport)
def resolve_issue(session_id: str, body: ResolveRequest) -> AuditReport:
    session = _get_session_or_404(session_id)

    issue = next((i for i in session.issues if i.id == body.issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found in this audit session.")
    if issue.status == "resolved":
        raise HTTPException(status_code=400, detail="This issue has already been resolved.")
    if body.decision_id not in {opt.id for opt in issue.options}:
        raise HTTPException(status_code=400, detail=f"'{body.decision_id}' is not a valid decision for this issue.")

    try:
        session.df, resolution_text = data_audit.apply_decision(
            session.df, issue, body.decision_id, body.selected_items
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issue.status = "resolved"
    issue.resolution = resolution_text

    return _to_report(session)


@router.get("/{session_id}/download")
def download_cleansed_file(session_id: str):
    """Streams the session's CURRENT dataframe (post-audit, and post-feature-
    engineering once that's run) as an .xlsx attachment -- always whatever
    session.df is right now, never the original upload."""
    session = _get_session_or_404(session_id)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        session.df.to_excel(writer, index=False, sheet_name="Cleansed Data")
    buffer.seek(0)

    stem = session.filename.rsplit(".", 1)[0] if "." in session.filename else session.filename
    filename = f"{stem}_cleansed.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/preview")
def preview_data(session_id: str, rows: int = DEFAULT_PREVIEW_ROWS):
    """Sample of the session's current dataframe for the HITL review view on
    the Features page -- reflects whatever has been resolved/engineered so far."""
    session = _get_session_or_404(session_id)
    n = max(1, min(rows, MAX_PREVIEW_ROWS))
    sample = session.df.head(n)
    records = json.loads(sample.to_json(orient="records"))
    return {
        "session_id": session.session_id,
        "row_count": len(session.df),
        "preview_row_count": len(records),
        "columns": [str(c) for c in session.df.columns],
        "rows": records,
    }


@router.post("/{session_id}/features", response_model=FeatureReport)
def apply_features(session_id: str) -> FeatureReport:
    session = _get_session_or_404(session_id)
    if defs_store.store.definitions is None:
        raise HTTPException(
            status_code=422,
            detail="No Customer KPI Profile has been uploaded yet -- upload one (with your feature "
                   "definitions) before features can be computed. There is no default.",
        )
    new_df, results, skipped_notes = feature_engineering.apply_features(session.df, defs_store.store.definitions)
    session.df = new_df
    session.features = results
    session.feature_skipped_notes = skipped_notes
    return _to_feature_report(session)


@router.get("/{session_id}/features", response_model=FeatureReport)
def get_features(session_id: str) -> FeatureReport:
    return _to_feature_report(_get_session_or_404(session_id))
