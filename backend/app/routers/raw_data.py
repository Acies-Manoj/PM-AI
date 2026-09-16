import pandas as pd
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.schemas import (
    RawDataChannel,
    RawDataFlaggedTrip,
    RawDataFlagsResponse,
    RawDataRcaResponse,
    RawDataSeriesPoint,
    RawDataTrip,
    RawDataTripMeanTemp,
    RawDataTripSeriesResponse,
    RawDataUploadResponse,
    RcaHypothesisModel,
)
from app.services import anomaly_detection
from app.services import raw_data_matrix as parser
from app.services.raw_data_store import RawDataSession, store

router = APIRouter(prefix="/api/raw-data", tags=["raw-data"])


def _get_session_or_404(session_id: str) -> RawDataSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Raw data session not found.")
    return session


async def _read_matrix(file: UploadFile | None) -> parser.MatrixData | None:
    if file is None:
        return None
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail=f"'{file.filename}' is empty.")
    try:
        sheets = parser.list_sheets(raw)
        sheet = parser.guess_sheet(sheets, parser.MATRIX_SHEET_HINTS)
        return parser.parse_matrix(raw, sheet)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read '{file.filename}' as a data point matrix: {exc}") from exc


@router.post("/upload", response_model=RawDataUploadResponse)
async def upload_raw_data(
    aggregated: UploadFile = File(...),
    temperature_matrix: UploadFile | None = File(None),
    light_matrix: UploadFile | None = File(None),
) -> RawDataUploadResponse:
    agg_raw = await aggregated.read()
    if not agg_raw:
        raise HTTPException(status_code=422, detail="Aggregated Data Upload is empty.")

    try:
        sheets = parser.list_sheets(agg_raw)
        agg_sheet = parser.guess_sheet(sheets, parser.AGGREGATED_SHEET_HINTS)
        agg = parser.parse_aggregated(agg_raw, agg_sheet)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not read '{aggregated.filename}' as the aggregated data: {exc}") from exc

    trip_rows = parser.build_trip_rows(agg)
    if not trip_rows:
        raise HTTPException(
            status_code=422,
            detail="No trips in the aggregated data have a Serial Number, Trip ID, and start timestamp all present.",
        )

    temperature = await _read_matrix(temperature_matrix)
    light = await _read_matrix(light_matrix)

    session = store.create(aggregated=agg, trips=trip_rows, temperature=temperature, light=light)

    agg_keys = {(t.serial, t.trip_id) for t in trip_rows}
    temperature_matched = len(agg_keys & set(temperature.columns.keys())) if temperature else None
    light_matched = len(agg_keys & set(light.columns.keys())) if light else None

    return RawDataUploadResponse(
        session_id=session.session_id,
        interval_minutes=session.interval_minutes,
        trips=[
            RawDataTrip(serial=t.serial, trip_id=t.trip_id, label=t.label, start_time=t.start_time.isoformat())
            for t in trip_rows
        ],
        temperature_uploaded=temperature is not None,
        temperature_matched=temperature_matched,
        temperature_total=len(temperature.columns) if temperature else None,
        light_uploaded=light is not None,
        light_matched=light_matched,
        light_total=len(light.columns) if light else None,
    )


def _channel(session: RawDataSession, matrix: parser.MatrixData | None, serial: str, trip_id: int, start_time) -> RawDataChannel | None:
    if matrix is None:
        return None
    series = parser.get_series(matrix, serial, trip_id)
    if not series:
        return None
    points = [
        RawDataSeriesPoint(
            t=(start_time + pd.Timedelta(minutes=session.interval_minutes * i)).isoformat(),
            v=(float(v) if v is not None else None),
        )
        for i, v in enumerate(series)
    ]
    return RawDataChannel(unit=matrix.unit, points=points)


@router.get("/{session_id}/trip", response_model=RawDataTripSeriesResponse)
def get_trip_series(session_id: str, serial: str = Query(...), trip_id: int = Query(...)) -> RawDataTripSeriesResponse:
    session = _get_session_or_404(session_id)
    trip = next((t for t in session.trips if t.serial == serial and t.trip_id == trip_id), None)
    if trip is None:
        raise HTTPException(status_code=404, detail="That trip was not found in the uploaded aggregated data.")

    return RawDataTripSeriesResponse(
        session_id=session.session_id,
        serial=trip.serial,
        trip_id=trip.trip_id,
        start_time=trip.start_time.isoformat(),
        interval_minutes=session.interval_minutes,
        temperature=_channel(session, session.temperature, serial, trip_id, trip.start_time),
        light=_channel(session, session.light, serial, trip_id, trip.start_time),
    )


# -- Step 1: outlier/threshold screening (see services/anomaly_detection.py) --
# Runs over the SAME aggregated table this session's trips already came
# from; no separate upload or session type needed.


def _scored_aggregated(session: RawDataSession) -> pd.DataFrame:
    """Runs the anomaly-detection pass and indexes the result by this
    session's own (serial, trip) columns -- whatever they were named in the
    uploaded file -- so a TripRow can be matched back to its scored row.
    Widens a "one row per trip per sensor channel" export (see
    anomaly_detection.is_long_sensor_format) into the one-row-per-trip shape
    the flag rules expect before scoring; a file already in that shape (e.g.
    a Merged_Temperature_Light-style export) is scored as-is."""
    agg = session.aggregated
    source = agg.df
    if anomaly_detection.is_long_sensor_format(source):
        source = anomaly_detection.widen_by_sensor_type(source, agg.serial_col, agg.trip_col)
    scored = anomaly_detection.run_anomaly_detection(source)
    return scored.set_index([agg.serial_col, agg.trip_col], drop=False)


def _trip_row(scored: pd.DataFrame, serial: str, trip_id: int) -> pd.Series | None:
    key = (serial, trip_id)
    if key not in scored.index:
        return None
    row = scored.loc[key]
    if isinstance(row, pd.DataFrame):  # duplicate (serial, trip_id) in the source file -- take the first
        row = row.iloc[0]
    return row


def _run_screening(session: RawDataSession) -> pd.DataFrame:
    try:
        return _scored_aggregated(session)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Could not run outlier/threshold screening on this data: {exc}"
        ) from exc


@router.get("/{session_id}/flags", response_model=RawDataFlagsResponse)
def get_flags(session_id: str) -> RawDataFlagsResponse:
    session = _get_session_or_404(session_id)
    scored = _run_screening(session)

    flagged: list[RawDataFlaggedTrip] = []
    all_trips: list[RawDataTripMeanTemp] = []
    for t in session.trips:
        row = _trip_row(scored, t.serial, t.trip_id)
        if row is None:
            continue
        flag_count = int(row.get("flag_count", 0))
        duration_outlier = bool(row.get("duration_outlier", False))
        is_flagged = flag_count > 0 or duration_outlier

        mean_temp_val = row.get(anomaly_detection.COL_MEAN_TEMP)
        product_val = row.get(anomaly_detection.COL_PRODUCT)
        limit_low_val = row.get(anomaly_detection.COL_LIMIT_LOW_TEMP)
        limit_ideal_val = row.get(anomaly_detection.COL_LIMIT_IDEAL_TEMP)
        limit_high_val = row.get(anomaly_detection.COL_LIMIT_HIGH_TEMP)
        mean_temp = float(mean_temp_val) if pd.notna(mean_temp_val) else None
        product = str(product_val) if pd.notna(product_val) else None

        # Every trip goes into the mean-temp-by-product chart, flagged or not,
        # so the chart shows where the flagged points sit relative to their
        # product's other trips (see anomaly_detection.py's flag_1/flag_2).
        all_trips.append(
            RawDataTripMeanTemp(
                serial=t.serial,
                trip_id=t.trip_id,
                label=t.label,
                start_time=t.start_time.isoformat(),
                product=product,
                mean_temp=mean_temp,
                limit_low=float(limit_low_val) if pd.notna(limit_low_val) else None,
                limit_ideal=float(limit_ideal_val) if pd.notna(limit_ideal_val) else None,
                limit_high=float(limit_high_val) if pd.notna(limit_high_val) else None,
                flagged=is_flagged,
            )
        )

        if not is_flagged:
            continue  # the flagged-trip list only surfaces trips that tripped a rule
        active_flags = [c for c in anomaly_detection.FLAG_COLUMNS if bool(row.get(c, False))]
        flagged.append(
            RawDataFlaggedTrip(
                serial=t.serial,
                trip_id=t.trip_id,
                label=t.label,
                flag_count=flag_count,
                flags=active_flags,
                duration_outlier=duration_outlier,
                mean_temp=mean_temp,
                product=product,
            )
        )

    return RawDataFlagsResponse(
        session_id=session_id, total_trips=len(session.trips), all_trips=all_trips, flagged_trips=flagged
    )


@router.get("/{session_id}/rca", response_model=RawDataRcaResponse)
def get_rca(session_id: str, serial: str = Query(...), trip_id: int = Query(...)) -> RawDataRcaResponse:
    """Root-cause hypotheses for one already-flagged trip (see
    anomaly_detection.generate_rca) -- the deeper option alongside the plain
    temperature/light drill-down on the same click-a-flagged-trip action."""
    session = _get_session_or_404(session_id)
    scored = _run_screening(session)

    row = _trip_row(scored, serial, trip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="That trip was not found in the scored aggregated data.")

    hypotheses = anomaly_detection.generate_rca(row)
    return RawDataRcaResponse(
        session_id=session_id,
        serial=serial,
        trip_id=trip_id,
        hypotheses=[
            RcaHypothesisModel(hypothesis=h.hypothesis, score=h.score, confidence=h.confidence, rationale=h.rationale)
            for h in hypotheses
        ],
    )
