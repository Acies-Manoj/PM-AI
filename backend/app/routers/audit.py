import io
import json
import re
import uuid
from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from app import config
from app.routers.deps import User, get_user, load_owned_session
from app.schemas import AuditIssue, AuditReport, FeatureReport, ResolveRequest, UpdateTripValueRequest
from app.services.audit import data_audit
from app.services.audit.audit_agent import generate_audit_analysis
from app.services.audit.audit_store import AuditSession, store
from app.services.audit import outlier_audit
from app.services.audit.excel_parser import load_spreadsheet
from app.services.common import audit_log, aws_clients, column_meta, selections
from app.services.features import feature_engineering, feature_repository

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


ALLOWED_EXTENSIONS = (".xlsx", ".xlsm", ".xls", ".csv")


def _check_filename(filename: str) -> None:
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}.",
        )


def _check_size(size: int) -> None:
    if size > config.UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is too large (limit {config.UPLOAD_MAX_BYTES // (1024 * 1024)} MB).",
        )


def _sanitize_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return name[:120]


def _create_session_from_bytes(
    raw: bytes, filename: str, source: str, user: User, raw_key: str | None
) -> UploadOnlyResponse:
    """Parse an uploaded spreadsheet, create the session and store its column metadata."""
    _check_filename(filename)
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    _check_size(len(raw))

    try:
        df, _warnings = load_spreadsheet(raw, filename)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session = store.create(source=source, filename=filename, df=df, user_id=user.id, raw_key=raw_key)

    try:
        column_meta.save(session.session_id, df)
    except Exception:
        pass

    audit_log.log_event(
        session.session_id, user.id, "upload",
        {"filename": filename, "source": source, "rows": len(df), "cols": len(df.columns)},
    )
    return UploadOnlyResponse(
        session_id=session.session_id,
        filename=session.filename,
        row_count=len(df),
        column_count=len(df.columns),
        columns=[str(c) for c in df.columns],
    )


@router.post("/upload", response_model=UploadOnlyResponse)
async def upload_for_profiling(
    file: UploadFile = File(...), source: str = Form(...), user: User = Depends(get_user)
) -> UploadOnlyResponse:
    """Upload a file, create a session, and profile its columns.
    Does NOT run the audit agent -- call /{session_id}/run for that.
    (Legacy multipart path, used in local development; deployed clients use
    /upload-url + /upload/complete to send the file straight to S3.)"""
    filename = file.filename or "upload"
    _check_filename(filename)
    raw = await file.read()
    return await run_in_threadpool(_create_session_from_bytes, raw, filename, source, user, None)


class UploadUrlRequest(BaseModel):
    source: str
    filename: str
    size: int | None = None


class UploadCompleteRequest(BaseModel):
    key: str
    source: str
    filename: str


@router.post("/upload-url")
def create_upload_url(body: UploadUrlRequest, user: User = Depends(get_user)):
    """Where the browser should send the file: {"mode": "direct"} (use the multipart
    /upload) locally, or a presigned S3 PUT URL when AWS storage is configured."""
    if not config.USE_AWS_STORAGE:
        return {"mode": "direct"}
    _check_filename(body.filename)
    if body.size is not None:
        _check_size(body.size)
    key = f"uploads/{user.id}/{uuid.uuid4().hex}/{_sanitize_filename(body.filename)}"
    url = aws_clients.s3().generate_presigned_url(
        "put_object",
        Params={"Bucket": config.S3_BUCKET, "Key": key},
        ExpiresIn=config.PRESIGN_EXPIRY_SECONDS,
    )
    return {"mode": "s3", "url": url, "key": key, "expires_in": config.PRESIGN_EXPIRY_SECONDS}


@router.post("/upload/complete", response_model=UploadOnlyResponse)
def complete_upload(body: UploadCompleteRequest, user: User = Depends(get_user)) -> UploadOnlyResponse:
    """Called after the browser PUT the file to S3: read it back and create the session."""
    if not config.USE_AWS_STORAGE:
        raise HTTPException(status_code=400, detail="Direct-to-S3 upload is not enabled.")
    if not body.key.startswith(f"uploads/{user.id}/") or ".." in body.key:
        raise HTTPException(status_code=403, detail="Not allowed to use this upload key.")
    _check_filename(body.filename)

    s3 = aws_clients.s3()
    try:
        head = s3.head_object(Bucket=config.S3_BUCKET, Key=body.key)
    except Exception as exc:  # noqa: BLE001 - botocore ClientError (404) and friends
        raise HTTPException(status_code=404, detail="Uploaded file not found.") from exc
    _check_size(int(head.get("ContentLength", 0)))
    raw = s3.get_object(Bucket=config.S3_BUCKET, Key=body.key)["Body"].read()
    return _create_session_from_bytes(raw, body.filename, body.source, user, body.key)


@router.post("/{session_id}/run", response_model=AuditReport)
def run_audit_agent(session_id: str, user: User = Depends(get_user)) -> AuditReport:
    """Run the audit agent on an already-uploaded session."""
    session = load_owned_session(session_id, user)

    if session.issues:
        return _to_report(session)

    issues = data_audit.run_audit(session.df)
    try:
        summary, recommendations = generate_audit_analysis(
            session.source, session.filename, len(session.df), len(session.df.columns), issues
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Data audit agent (Bedrock) is unavailable: {exc}"
        ) from exc

    for issue in issues:
        action, note = recommendations.get(issue.id, (None, None))
        issue.recommended_action = action
        issue.recommendation = note

    session.issues = issues
    session.summary = summary
    store.save(session)
    audit_log.log_event(session_id, user.id, "audit_run", {"issues": len(issues)})
    return _to_report(session)


@router.get("/{session_id}", response_model=AuditReport)
def get_audit(session_id: str, user: User = Depends(get_user)) -> AuditReport:
    return _to_report(load_owned_session(session_id, user))


@router.get("/{session_id}/log")
def get_session_log(session_id: str, user: User = Depends(get_user)):
    """The audit trail (uploads, decisions, edits, ...) recorded for this session."""
    load_owned_session(session_id, user)
    return audit_log.events_for_session(session_id)


@router.post("/{session_id}/resolve", response_model=AuditReport)
def resolve_issue(session_id: str, body: ResolveRequest, user: User = Depends(get_user)) -> AuditReport:
    session = load_owned_session(session_id, user)
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
        if session.audit_baseline is None:
            # The audited data before any change, without any feature columns
            # (those are recomputed from it, never part of the baseline).
            feature_cols = [f.output_column for f in session.features if f.output_column in pre_mutation_df.columns]
            session.audit_baseline = pre_mutation_df.drop(columns=feature_cols)
        session.audit_events.append({
            "type": "decision", "issue_id": issue.id, "decision_id": body.decision_id,
            "selected_items": list(body.selected_items) if body.selected_items else None,
        })
        session.mutation_stack.append(issue.id)

    issue.status = "resolved"
    issue.resolution = resolution_text

    store.save(session)
    audit_log.log_event(
        session_id, user.id, "decision",
        {"issue_id": issue.id, "decision_id": body.decision_id,
         "selected_items": list(body.selected_items) if body.selected_items else None},
    )
    selections.refresh(session_id, user.id, "audit_decision", session)
    return _to_report(session)


@router.post("/{session_id}/issues/{issue_id}/revert", response_model=AuditReport)
def revert_issue(session_id: str, issue_id: str, user: User = Depends(get_user)) -> AuditReport:
    session = load_owned_session(session_id, user)
    issue = _get_issue_or_404(session, issue_id)
    if issue.status != "resolved":
        raise HTTPException(status_code=400, detail="This issue has not been resolved yet.")

    issue.status = "pending"
    issue.resolution = None

    if issue_id in session.mutation_stack:
        # Any change can be undone, whatever was applied after it: drop its
        # event and rebuild the data from the baseline without it.
        session.mutation_stack.remove(issue_id)
        session.audit_events = [
            e for e in session.audit_events if not (e["type"] == "decision" and e["issue_id"] == issue_id)
        ]
        _rebuild_audit_df(session)
        _reset_downstream(session)

    store.save(session)
    audit_log.log_event(session_id, user.id, "revert", {"issue_id": issue_id})
    return _to_report(session)


def _rebuild_audit_df(session: AuditSession) -> None:
    """Replays the remaining audit decisions (and inline edits), in their
    original order, on the data as it was before the first change."""
    from app.services.audit.outlier_detectors import update_trip_value as apply_trip_value_edit

    df = session.audit_baseline.copy()
    issues = {i.id: i for i in session.issues}
    for event in session.audit_events:
        if event["type"] == "decision":
            issue = issues[event["issue_id"]]
            try:
                df, text = data_audit.apply_decision(df, issue, event["decision_id"], event.get("selected_items"))
            except ValueError:
                continue
            issue.resolution = text  # counts may differ now that an earlier change is gone
        else:
            try:
                df = apply_trip_value_edit(df, event["serial"], event["trip_id"], event["field"], event["value"])
            except ValueError:
                continue  # the trip's rows were removed by a decision that is still applied
    session.df = df
    if not session.mutation_stack:
        # Nothing left to undo; inline edits made since are already in `df`.
        session.audit_baseline = None
        session.audit_events = []


def _reset_downstream(session: AuditSession) -> None:
    """The audited data changed, so features and analyses built on the old data
    are stale: clear them and they recompute when the PM opens those steps."""
    session.pre_feature_df = None
    session.features = []
    session.feature_skipped_notes = []
    session.analysis_results.clear()
    session.overall_analysis = None


@router.get("/{session_id}/download")
def download_cleansed_file(session_id: str, user: User = Depends(get_user)):
    """Streams the session's CURRENT dataframe (post-audit, and post-feature-
    engineering once that's run) as an .xlsx attachment -- always whatever
    session.df is right now, never the original upload."""
    session = load_owned_session(session_id, user)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        session.df.to_excel(writer, index=False, sheet_name="Cleansed Data")
    buffer.seek(0)

    stem = session.filename.rsplit(".", 1)[0] if "." in session.filename else session.filename
    filename = f"{stem}_cleansed.xlsx"
    audit_log.log_event(session_id, user.id, "download", {"kind": "cleansed", "filename": filename})
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/outliers/download")
def download_flagged_outliers(session_id: str, user: User = Depends(get_user)):
    """Streams the CURRENTLY flagged duration + temperature outlier rows as a two-sheet
    .xlsx -- what the PM takes away to correct in SensiWatch before re-uploading."""
    from app.services.audit.outlier_detectors import build_outlier_export

    session = load_owned_session(session_id, user)
    duration_df, temperature_df = build_outlier_export(session.df)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        duration_df.to_excel(writer, index=False, sheet_name="Duration Outliers")
        temperature_df.to_excel(writer, index=False, sheet_name="Temperature Outliers")
    buffer.seek(0)
    audit_log.log_event(session_id, user.id, "download", {"kind": "flagged_outliers"})

    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="flagged_outliers.xlsx"'},
    )


@router.get("/{session_id}/preview")
def preview_data(session_id: str, rows: int = DEFAULT_PREVIEW_ROWS, user: User = Depends(get_user)):
    """Sample of the session's current dataframe for the HITL review view on
    the Features page -- reflects whatever has been resolved/engineered so far."""
    session = load_owned_session(session_id, user)
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
def get_issue_rows(session_id: str, issue_id: str, limit: int = MAX_ISSUE_ROWS, user: User = Depends(get_user)):
    """Every row currently matching this finding, with every column -- unlike
    the issue's own `sample` (capped to a handful of rows/columns for the
    inline card preview), this is the full table for the "view all rows"
    popup. Re-detects fresh against the current dataframe, same as resolve."""
    session = load_owned_session(session_id, user)
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


@router.post("/{session_id}/features", response_model=FeatureReport)
def apply_features(session_id: str, user: User = Depends(get_user)) -> FeatureReport:
    """Computes every APPROVED entry in this session's feature repository
    (predefined + planner-approved + custom + accepted AI suggestions --
    see feature_repository.py) via the Feature Agent. No Customer KPI
    Profile is required: if none was uploaded, predefined simply
    contributes zero entries and the other three sources still run."""
    session = load_owned_session(session_id, user)
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

    store.save(session)
    audit_log.log_event(
        session_id, user.id, "apply_features",
        {
            "features": [f.output_column for f in results], "rows": len(new_df), "cols": len(new_df.columns),
            "requested": [e["name"] for e in entries],
            "validation": {f.output_column: f.validation_note for f in results},
            "skipped": skipped_notes,
        },
    )
    selections.refresh(session_id, user.id, "apply_features", session)
    return _to_feature_report(session)


@router.get("/{session_id}/features", response_model=FeatureReport)
def get_features(session_id: str, user: User = Depends(get_user)) -> FeatureReport:
    return _to_feature_report(load_owned_session(session_id, user))


@router.get("/{session_id}/outliers")
def get_outliers(session_id: str, user: User = Depends(get_user)):
    from app.services.audit.outlier_detectors import detect_segment_outliers, detect_temperature_outliers
    session = load_owned_session(session_id, user)
    segment = detect_segment_outliers(session.df)
    temperature = detect_temperature_outliers(session.df)
    outlier_audit.record_detection(session_id, user.id, segment, temperature)
    return {"session_id": session_id, "segment": segment, "temperature": temperature}


class OutlierReviewRequest(BaseModel):
    """A PM closing out one outlier tab: `completed` (reviewed, possibly edited) or `skipped`
    (kept every flagged value as-is). `note` is optional free text."""
    tab: Literal["segment", "temperature"]
    action: Literal["completed", "skipped"]
    note: str | None = None


@router.post("/{session_id}/outliers/review")
def review_outliers(session_id: str, body: OutlierReviewRequest, user: User = Depends(get_user)):
    from app.services.audit.outlier_detectors import detect_segment_outliers, detect_temperature_outliers
    session = load_owned_session(session_id, user)
    segment = detect_segment_outliers(session.df)
    temperature = detect_temperature_outliers(session.df)
    summary = outlier_audit.summarize(segment, temperature)
    outlier_audit.record(session_id, user.id, "review", {
        "tab": body.tab, "decision": body.action, "note": body.note,
        "flagged_remaining": summary[body.tab]["flagged"] if body.tab == "segment"
        else summary["temperature"]["too_warm"] + summary["temperature"]["too_cold"],
        "trips_remaining": summary[body.tab]["trips"],
    })
    return {"ok": True}


@router.get("/{session_id}/outliers/audit")
def get_outlier_audit(session_id: str, user: User = Depends(get_user)):
    """Every recorded outlier detection, edit and review for this session."""
    load_owned_session(session_id, user)
    return outlier_audit.entries(session_id)


@router.patch("/{session_id}/trip-value")
def edit_trip_value(session_id: str, body: UpdateTripValueRequest, user: User = Depends(get_user)):
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
    session = load_owned_session(session_id, user)
    # What the detector says about this trip BEFORE the edit (old value, flag, fence), for the audit trail.
    before = outlier_audit.trip_context(
        body.field, body.serial, body.trip_id,
        detect_segment_outliers(session.df), detect_temperature_outliers(session.df),
    )
    try:
        session.df = apply_trip_value_edit(session.df, body.serial, body.trip_id, body.field, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if session.audit_baseline is not None:
        # Logged so reverting an earlier audit decision replays this edit too.
        session.audit_events.append({
            "type": "edit", "serial": body.serial, "trip_id": body.trip_id, "field": body.field, "value": body.value,
        })

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
    store.save(session)
    audit_log.log_event(
        session_id, user.id, "edit",
        {"serial": body.serial, "trip_id": body.trip_id, "field": body.field, "value": body.value},
    )
    segment = detect_segment_outliers(session.df)
    temperature = detect_temperature_outliers(session.df)
    after = outlier_audit.trip_context(body.field, body.serial, body.trip_id, segment, temperature)
    outlier_audit.record(session_id, user.id, "edit", {
        "field": body.field, "serial": body.serial, "trip_id": body.trip_id,
        "old_value": before.get("value"), "new_value": body.value,
        "was_flagged": before["was_flagged"], "still_flagged": after["was_flagged"],
        "context": {k: v for k, v in before.items() if k not in ("value", "was_flagged")},
    })
    return {"session_id": session_id, "segment": segment, "temperature": temperature}
