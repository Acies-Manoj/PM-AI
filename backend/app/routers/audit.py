import io
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.config import DATA_DIR
from app.dependencies import get_session_or_404 as _get_session_or_404
from app.schemas import AuditIssue, AuditReport, FeatureReport, ResolveRequest, UpdateTripValueRequest
from app.services.audit import data_audit
from app.services.audit.audit_agent import generate_audit_analysis
from app.services.audit.audit_store import AuditSession, store
from app.services.audit.column_profiler import profile_dataframe
from app.services.audit.excel_parser import load_spreadsheet
from app.services.features import feature_engineering, feature_repository

_SESSIONS_DIR = DATA_DIR / "sessions"

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
        revertible_issue_id=session.mutation_stack[-1] if session.mutation_stack else None,
    )


def _get_issue_or_404(session: AuditSession, issue_id: str) -> AuditIssue:
    issue = next((i for i in session.issues if i.id == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found in this audit session.")
    return issue


def _to_feature_report(session: AuditSession) -> FeatureReport:
    return FeatureReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        features=session.features,
        skipped_notes=session.feature_skipped_notes,
    )


class UploadOnlyResponse(BaseModel):
    session_id: str
    filename: str
    row_count: int
    column_count: int
    columns: list[str]


@router.post("/upload", response_model=UploadOnlyResponse)
async def upload_for_profiling(
    file: UploadFile = File(...), source: str = Form(...)
) -> UploadOnlyResponse:
    """Upload a file, create a session, and profile its columns.
    Does NOT run the audit agent — call /{session_id}/run for that."""
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        df, _warnings = load_spreadsheet(raw, file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = store.create(source=source, filename=file.filename or "upload", df=df)

    try:
        col_meta = profile_dataframe(df)
        session_dir = _SESSIONS_DIR / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        combined = {
            "session_id": session.session_id,
            "filename": session.filename,
            "source": source,
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": col_meta,
        }
        (session_dir / "column_metadata.json").write_text(
            json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass

    return UploadOnlyResponse(
        session_id=session.session_id,
        filename=session.filename,
        row_count=len(df),
        column_count=len(df.columns),
        columns=[str(c) for c in df.columns],
    )


@router.post("/{session_id}/run", response_model=AuditReport)
def run_audit_agent(session_id: str) -> AuditReport:
    """Run the audit agent on an already-uploaded session."""
    session = _get_session_or_404(session_id)

    if session.issues:
        return _to_report(session)

    issues = data_audit.run_audit(session.df)
    try:
        summary, recommendations = generate_audit_analysis(
            session.source, session.filename, len(session.df), len(session.df.columns), issues
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Data audit agent (Groq) is unavailable: {exc}"
        ) from exc

    for issue in issues:
        action, note = recommendations.get(issue.id, (None, None))
        issue.recommended_action = action
        issue.recommendation = note

    session.issues = issues
    session.summary = summary
    return _to_report(session)


@router.get("/{session_id}", response_model=AuditReport)
def get_audit(session_id: str) -> AuditReport:
    return _to_report(_get_session_or_404(session_id))


@router.post("/{session_id}/resolve", response_model=AuditReport)
def resolve_issue(session_id: str, body: ResolveRequest) -> AuditReport:
    session = _get_session_or_404(session_id)
    issue = _get_issue_or_404(session, body.issue_id)
    if issue.status == "resolved":
        raise HTTPException(status_code=400, detail="This issue has already been resolved.")
    if body.decision_id not in {opt.id for opt in issue.options}:
        raise HTTPException(status_code=400, detail=f"'{body.decision_id}' is not a valid decision for this issue.")

    is_mutating = body.decision_id != "keep"
    pre_mutation_df = session.df.copy() if is_mutating else None

    try:
        session.df, resolution_text = data_audit.apply_decision(
            session.df, issue, body.decision_id, body.selected_items
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if is_mutating:
        session.pre_mutation_snapshots[issue.id] = pre_mutation_df
        session.mutation_stack.append(issue.id)

    issue.status = "resolved"
    issue.resolution = resolution_text

    return _to_report(session)


@router.post("/{session_id}/issues/{issue_id}/revert", response_model=AuditReport)
def revert_issue(session_id: str, issue_id: str) -> AuditReport:
    session = _get_session_or_404(session_id)
    issue = _get_issue_or_404(session, issue_id)
    if issue.status != "resolved":
        raise HTTPException(status_code=400, detail="This issue has not been resolved yet.")

    if issue_id in session.pre_mutation_snapshots:
        if not session.mutation_stack or session.mutation_stack[-1] != issue_id:
            raise HTTPException(
                status_code=400,
                detail="This isn't the most recent data change -- revert that one first.",
            )
        session.df = session.pre_mutation_snapshots.pop(issue_id)
        session.mutation_stack.pop()

    issue.status = "pending"
    issue.resolution = None

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


@router.get("/{session_id}/outliers/download")
def download_flagged_outliers(session_id: str):
    """Streams the CURRENTLY flagged duration + temperature outlier rows as a two-sheet
    .xlsx -- what the PM takes away to correct in SensiWatch before re-uploading."""
    from app.services.audit.outlier_detectors import build_outlier_export

    session = _get_session_or_404(session_id)
    duration_df, temperature_df = build_outlier_export(session.df)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        duration_df.to_excel(writer, index=False, sheet_name="Duration Outliers")
        temperature_df.to_excel(writer, index=False, sheet_name="Temperature Outliers")
    buffer.seek(0)

    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="flagged_outliers.xlsx"'},
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


MAX_ISSUE_ROWS = 2000


@router.get("/{session_id}/issues/{issue_id}/rows")
def get_issue_rows(session_id: str, issue_id: str, limit: int = MAX_ISSUE_ROWS):
    """Every row currently matching this finding, with every column -- unlike
    the issue's own `sample` (capped to a handful of rows/columns for the
    inline card preview), this is the full table for the "view all rows"
    popup. Re-detects fresh against the current dataframe, same as resolve."""
    session = _get_session_or_404(session_id)
    issue = _get_issue_or_404(session, issue_id)
    mask = data_audit.detect_mask_for_category(session.df, issue.category)
    matching = session.df[mask]
    n = max(1, min(limit, MAX_ISSUE_ROWS))
    subset = matching.head(n)
    records = json.loads(subset.to_json(orient="records"))
    return {
        "issue_id": issue.id,
        "total_matching": int(mask.sum()),
        "returned": len(records),
        "columns": [str(c) for c in matching.columns],
        "rows": records,
    }


def _write_enriched_column_metadata(session: AuditSession) -> None:
    """Re-profiles the CURRENT session dataframe (post-audit, post-feature)
    and writes it as a new column_metadata_with_features.json alongside the
    original column_metadata.json -- so downstream stages (Analysis,
    Planner re-runs, Report) have a single file describing every column,
    old and newly agent-computed, without needing to reconstruct it
    themselves. Best-effort: a profiling failure shouldn't block the
    feature response the PM is waiting on."""
    try:
        session_dir = _SESSIONS_DIR / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        combined = {
            "session_id": session.session_id,
            "filename": session.filename,
            "source": session.source,
            "row_count": len(session.df),
            "column_count": len(session.df.columns),
            "columns": profile_dataframe(session.df),
            "feature_columns": [f.output_column for f in session.features],
        }
        (session_dir / "column_metadata_with_features.json").write_text(
            json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


@router.post("/{session_id}/features", response_model=FeatureReport)
def apply_features(session_id: str) -> FeatureReport:
    """Computes every APPROVED entry in this session's feature repository
    (predefined + planner-approved + custom + accepted AI suggestions --
    see feature_repository.py) via the Feature Agent. No Customer KPI
    Profile is required: if none was uploaded, predefined simply
    contributes zero entries and the other three sources still run."""
    session = _get_session_or_404(session_id)
    # Always recompute from the pre-feature snapshot (not the possibly
    # already-engineered `session.df`) so accepting another suggestion
    # re-runs the full entry set cleanly instead of layering feature
    # columns on top of feature columns.
    if session.pre_feature_df is None:
        session.pre_feature_df = session.df.copy()

    entries = feature_repository.get_approved_entries(session_id)
    new_df, results, skipped_notes = feature_engineering.apply_features(session_id, session.pre_feature_df, entries)
    session.df = new_df
    session.features = results
    session.feature_skipped_notes = skipped_notes

    _write_enriched_column_metadata(session)

    return _to_feature_report(session)


@router.get("/{session_id}/features", response_model=FeatureReport)
def get_features(session_id: str) -> FeatureReport:
    return _to_feature_report(_get_session_or_404(session_id))


@router.get("/{session_id}/outliers")
def get_outliers(session_id: str):
    from app.services.audit.outlier_detectors import detect_segment_outliers, detect_temperature_outliers
    session = _get_session_or_404(session_id)
    return {
        "session_id": session_id,
        "segment": detect_segment_outliers(session.df),
        "temperature": detect_temperature_outliers(session.df),
    }


@router.patch("/{session_id}/trip-value")
def edit_trip_value(session_id: str, body: UpdateTripValueRequest):
    """A PM's inline correction to one trip's Segment Length (Days) or Mean
    Value_Temperature (see the Segment/Temperature Outlier tabs' editable
    columns) -- writes straight into session.df, then returns freshly
    recomputed outliers so the edited row's flag/fence status updates too.

    Also patches session.pre_feature_df (the snapshot Features re-applies
    its definitions from -- see routers/features.py) when it already exists,
    so an edit made AFTER Features has run once still reaches every later
    step (Features, Analysis, the downloaded cleansed file, the report)
    instead of being silently overwritten the next time features recompute."""
    from app.services.audit.outlier_detectors import detect_segment_outliers, detect_temperature_outliers
    from app.services.audit.outlier_detectors import update_trip_value as apply_trip_value_edit
    session = _get_session_or_404(session_id)
    try:
        session.df = apply_trip_value_edit(session.df, body.serial, body.trip_id, body.field, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if session.pre_feature_df is not None:
        try:
            session.pre_feature_df = apply_trip_value_edit(
                session.pre_feature_df, body.serial, body.trip_id, body.field, body.value
            )
        except ValueError:
            # pre_feature_df is a strict subset/superset relationship with df
            # in the common case, but not guaranteed (e.g. a column an
            # earlier audit decision dropped from df was never in this
            # snapshot to begin with). The primary edit above already
            # succeeded, so don't fail the whole request over this one.
            pass
    return {
        "session_id": session_id,
        "segment": detect_segment_outliers(session.df),
        "temperature": detect_temperature_outliers(session.df),
    }
