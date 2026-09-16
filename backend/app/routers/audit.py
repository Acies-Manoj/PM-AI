import io
import json
import uuid

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import (
    ApplyFeaturesRequest,
    AuditIssue,
    AuditReport,
    ExcludeTripRequest,
    FeatureReport,
    IssueOption,
    ResolveRequest,
    SegmentDaysResponse,
    SegmentDaysRow,
)
from app.services import anomaly_detection, custom_library_store, data_audit, feature_engineering
from app.services import feature_definitions_store as defs_store
from app.services.audit_agent import generate_audit_analysis
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
        revertible_issue_id=session.mutation_stack[-1] if session.mutation_stack else None,
    )


def _get_issue_or_404(session: AuditSession, issue_id: str) -> AuditIssue:
    issue = next((i for i in session.issues if i.id == issue_id), None)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found in this audit session.")
    return issue


def _combined_feature_defs(session: AuditSession) -> list[dict]:
    """Every feature definition that should be computed for this session, in
    the order they're applied: the uploaded Customer KPI Profile, then any
    saved custom KPI the user marked "keep as my regular" (see
    custom_library_store.py), then whatever this session added on top
    (AI-suggested/custom/client-requested -- session.extra_feature_defs).
    Later groups win on an id clash. Anything the user unchecked on the
    Features page (session.excluded_feature_ids) is filtered out last,
    regardless of which group it came from. Mirrors analysis.py's
    _combined_pivot_defs exactly, one layer over features instead of pivots."""
    combined = custom_library_store.merge_definitions(
        list(defs_store.store.definitions or []),
        custom_library_store.store.regular_specs("features"),
        session.extra_feature_defs,
    )
    if not session.excluded_feature_ids:
        return combined
    excluded = set(session.excluded_feature_ids)
    return [d for d in combined if d.get("id") not in excluded]


def _to_feature_report(session: AuditSession) -> FeatureReport:
    return FeatureReport(
        session_id=session.session_id,
        row_count=len(session.df),
        column_count=len(session.df.columns),
        columns=[str(c) for c in session.df.columns],
        features=session.features,
        skipped_notes=session.feature_skipped_notes,
        excluded_feature_ids=session.excluded_feature_ids,
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
        summary, recommendations = generate_audit_analysis(
            source, file.filename or "upload", len(df), len(df.columns), issues
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Data audit agent (Groq) is unavailable: {exc}") from exc
    for issue in issues:
        action, note = recommendations.get(issue.id, (None, None))
        issue.recommended_action = action
        issue.recommendation = note
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


@router.post("/{session_id}/exclude-trip", response_model=AuditReport)
def exclude_trip(session_id: str, body: ExcludeTripRequest) -> AuditReport:
    """Outlier Screening's "Exclude from analysis": drops every row for this
    trip (matched on Serial Number + Trip ID, so a trip split across sensor
    channels/segments comes out whole) from the audit session's dataframe --
    the same one Features/Analysis/Report read from. Recorded as an
    already-resolved AuditIssue so it appears in Overall Checks/Summary and
    can be undone via the normal revert endpoint (subject to the same
    most-recent-mutation-first rule as any other finding)."""
    session = _get_session_or_404(session_id)
    if "Serial Number" not in session.df.columns or "Trip ID" not in session.df.columns:
        raise HTTPException(
            status_code=422,
            detail="This data has no Serial Number/Trip ID columns to match a trip against.",
        )

    mask = (session.df["Serial Number"] == body.serial) & (session.df["Trip ID"] == body.trip_id)
    n = int(mask.sum())
    if n == 0:
        raise HTTPException(status_code=404, detail="No rows found for that trip -- it may already be excluded.")

    issue_id = uuid.uuid4().hex[:10]
    session.pre_mutation_snapshots[issue_id] = session.df.copy()
    session.df = session.df[~mask].reset_index(drop=True)
    session.mutation_stack.append(issue_id)

    session.issues.append(AuditIssue(
        id=issue_id,
        category=f"outlier_trip::{body.serial}::{body.trip_id}",
        severity="warning",
        title=f"Excluded trip {body.trip_id} ({body.serial})",
        description=(
            f"Excluded from the Outlier Screening tab: {n} row(s) for trip {body.trip_id} "
            f"(serial {body.serial}) removed from the data Features/Analysis/Report read from."
        ),
        affected_row_count=n,
        requires_decision=True,
        options=[IssueOption(id="exclude", label="Exclude from analysis")],
        status="resolved",
        resolution=f"Excluded {n} row(s) for trip {body.trip_id} ({body.serial}).",
    ))

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


@router.post("/{session_id}/features", response_model=FeatureReport)
def apply_features(session_id: str, body: ApplyFeaturesRequest | None = None) -> FeatureReport:
    session = _get_session_or_404(session_id)
    if defs_store.store.definitions is None:
        raise HTTPException(
            status_code=422,
            detail="No Customer KPI Profile is available and the bundled default could not be loaded -- "
                   "upload one (with your feature definitions) before features can be computed.",
        )
    # Always recompute from the pre-feature snapshot (not the possibly
    # already-engineered `session.df`) so accepting another AI suggestion
    # re-runs the full definition set cleanly instead of layering feature
    # columns on top of feature columns.
    if session.pre_feature_df is None:
        session.pre_feature_df = session.df.copy()

    if body is not None and body.excluded_feature_ids is not None:
        session.excluded_feature_ids = list(dict.fromkeys(body.excluded_feature_ids))
    # `extra_features` omitted (None) means "leave the AI/custom/client-
    # requested features already applied for this session alone" -- a bare
    # recompute (e.g. a fresh page load, or a caller that only wants to
    # change excluded_feature_ids) doesn't have to resend the full accepted
    # list to avoid dropping it.
    if body is not None and body.extra_features is not None:
        session.extra_feature_defs = body.extra_features

    new_df, results, skipped_notes = feature_engineering.apply_features(session.pre_feature_df, _combined_feature_defs(session))
    session.df = new_df
    session.features = results
    session.feature_skipped_notes = skipped_notes
    return _to_feature_report(session)


@router.get("/{session_id}/features", response_model=FeatureReport)
def get_features(session_id: str) -> FeatureReport:
    return _to_feature_report(_get_session_or_404(session_id))


@router.get("/{session_id}/segment-days", response_model=SegmentDaysResponse)
def get_segment_days(session_id: str) -> SegmentDaysResponse:
    """The Audit page's "Segment Days" tab: the actual trips whose transit
    duration falls outside their own lane's Tukey fence (see
    anomaly_detection.compute_lane_duration_outliers) -- the outlier
    instances themselves, not just the fence/rule numbers."""
    session = _get_session_or_404(session_id)
    df = session.df
    try:
        outliers = anomaly_detection.compute_lane_duration_outliers(df)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not compute Segment Days for this data: {exc}") from exc

    flagged = outliers[outliers["duration_outlier"]]
    duration = pd.to_numeric(df[anomaly_detection.COL_DURATION], errors="coerce")

    def _opt_str(value: object) -> str | None:
        return str(value) if pd.notna(value) else None

    rows = [
        SegmentDaysRow(
            serial=_opt_str(df.at[idx, "Serial Number"]) if "Serial Number" in df.columns else None,
            trip_id=int(df.at[idx, "Trip ID"]) if "Trip ID" in df.columns and pd.notna(df.at[idx, "Trip ID"]) else None,
            origin=str(df.at[idx, anomaly_detection.COL_ORIGIN]) if pd.notna(df.at[idx, anomaly_detection.COL_ORIGIN]) else "(blank)",
            destination=str(df.at[idx, anomaly_detection.COL_DESTINATION]) if pd.notna(df.at[idx, anomaly_detection.COL_DESTINATION]) else "(blank)",
            segment_days=float(duration.loc[idx]),
            lower_fence_days=float(row["duration_lower_fence_days"]) if pd.notna(row["duration_lower_fence_days"]) else None,
            upper_fence_days=float(row["duration_upper_fence_days"]) if pd.notna(row["duration_upper_fence_days"]) else None,
            status=str(row["duration_outlier_status"]),
        )
        for idx, row in flagged.iterrows()
    ]
    rows.sort(key=lambda r: (r.origin, r.destination))
    return SegmentDaysResponse(session_id=session_id, total_trips=len(df), rows=rows)
