from fastapi import APIRouter, HTTPException

from app.schemas import ScreeningReport, ScreeningRequest, TripTrace
from app.services import anomaly_detection, raw_data
from app.services.audit_store import store as audit_store

router = APIRouter(prefix="/api/screening", tags=["screening"])


@router.post("/run", response_model=ScreeningReport)
def run_screening(body: ScreeningRequest) -> ScreeningReport:
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    report = anomaly_detection.run_threshold_screening(
        session_id=body.session_id,
        df=session.df,
        custom_thresholds=body.custom_thresholds,
    )
    session.screening_report = report
    return report


@router.get("/{session_id}/report", response_model=ScreeningReport)
def get_screening_report(session_id: str) -> ScreeningReport:
    session = audit_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    if session.screening_report is None:
        raise HTTPException(status_code=404, detail="Screening has not been run yet for this session.")
    return session.screening_report


@router.get("/{session_id}/trip/{trip_id}/trace", response_model=TripTrace)
def get_trip_trace(
    session_id: str,
    trip_id: str,
    rawdata_session_id: str | None = None,
) -> TripTrace:
    """Raw temperature + light trace for a flagged trip.

    Uses the ColdStream (rawdata) session when provided, falling back to the
    primary (SensiWatch) session's aggregated data.
    """
    session = audit_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")

    df = session.df
    if rawdata_session_id:
        raw_session = audit_store.get(rawdata_session_id)
        if raw_session:
            df = raw_session.df

    return raw_data.extract_trip_trace(df, trip_id)
