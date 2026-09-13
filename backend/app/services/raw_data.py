"""Parse raw time-series sensor data from ColdStream-style exports.

Extracts per-trip temperature traces and light (door-open) events from
a raw sensor dataframe (the ColdStream upload).
"""
from __future__ import annotations

import pandas as pd

from app.schemas import TripTrace

_ID_CANDIDATES = ["Trip ID", "TripID", "trip_id", "ID", "Shipment ID"]
_TIME_CANDIDATES = ["Timestamp", "DateTime", "Time", "Date Time", "timestamp", "date_time", "Date"]
_TEMP_CANDIDATES = ["Temperature", "Temp", "Value", "Sensor Value", "temperature", "Temp (°C)"]
_LIGHT_CANDIDATES = ["Light", "Light Value", "Door", "Door Open", "light", "door_open", "Light (lux)"]


def _pick(df: pd.DataFrame, candidates: list[str]) -> str | None:
    return next((c for c in candidates if c in df.columns), None)


def extract_trip_trace(df: pd.DataFrame, trip_id: str) -> TripTrace:
    """Return temperature trace and light events for one trip."""
    id_col = _pick(df, _ID_CANDIDATES)
    time_col = _pick(df, _TIME_CANDIDATES)
    temp_col = _pick(df, _TEMP_CANDIDATES)
    light_col = _pick(df, _LIGHT_CANDIDATES)

    trip_df = df[df[id_col].astype(str) == str(trip_id)].copy() if id_col else df.copy()

    if time_col:
        try:
            trip_df = trip_df.sort_values(time_col)
        except Exception:
            pass

    timestamps = trip_df[time_col].astype(str).tolist() if time_col else []

    temperatures: list[float | None] = []
    if temp_col:
        for v in pd.to_numeric(trip_df[temp_col], errors="coerce"):
            temperatures.append(None if pd.isna(v) else float(v))

    light_events: list[str] = []
    if light_col and time_col:
        light_vals = pd.to_numeric(trip_df[light_col], errors="coerce")
        mask = light_vals > 0
        if mask.any():
            light_events = trip_df[mask][time_col].astype(str).tolist()

    return TripTrace(
        trip_id=trip_id,
        timestamps=timestamps,
        temperatures=temperatures,
        light_events=light_events,
    )


def list_trip_ids(df: pd.DataFrame) -> list[str]:
    id_col = _pick(df, _ID_CANDIDATES)
    if id_col is None:
        return []
    return sorted(df[id_col].dropna().astype(str).unique().tolist())
