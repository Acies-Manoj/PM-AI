"""Loads an uploaded spreadsheet into a DataFrame without assuming the real
header sits on row 0 -- real exports (confirmed on the Edeka demo file) can
have a title row and/or a blank row before the actual column headers.

If the file is in long format (one row per sensor type per trip, e.g. a
SensiWatch export with separate Temperature and Light rows), it is
automatically pivoted to wide format (one row per trip) before returning."""
import io
import re

import pandas as pd

HEADER_SCAN_ROWS = 5

# Maps sensor type label → column prefix used after pivoting.
# Add entries here to support new sensor types without changing pivot logic.
_SENSOR_PREFIXES: dict[str, str] = {
    "Temperature": "temp",
    "Light": "light",
    "Door": "door",
    "Humidity": "humidity",
    "Shock": "shock",
    "CO2": "co2",
}

# Canonical names for the sensor-type and trip-id columns as they appear
# (after whitespace normalisation) in SensiWatch exports.
_SENSOR_TYPE_COL = "Sensor Type"
_TRIP_ID_CANDIDATES = ("Trip ID", "trip_id", "TripID", "TRIP_ID")


def _detect_header_row(preview: pd.DataFrame) -> int:
    """Picks the row with the most distinct string-valued cells -- a real
    header row is mostly unique column-name strings, while a title row has
    one or two cells and a blank spacer row has none."""
    best_idx = 0
    best_score = -1
    for i in range(min(HEADER_SCAN_ROWS, len(preview))):
        row = preview.iloc[i]
        str_cells = {v for v in row.dropna() if isinstance(v, str) and v.strip()}
        if len(str_cells) > best_score:
            best_score = len(str_cells)
            best_idx = i
    return best_idx


def _pivot_sensor_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Detects long-format sensor data and pivots to wide format.

    Long format: one row per (trip, sensor_type) — e.g. separate Temperature
    and Light rows for the same trip.
    Wide format: one row per trip with prefixed columns — temp_mean_value,
    light_mean_value, etc.

    Returns the (possibly pivoted) dataframe and any informational warnings.
    If the data is already wide (no Sensor Type column, or only one sensor
    type present) it is returned unchanged.
    """
    warnings: list[str] = []

    # ── 1. Find the sensor type column ──────────────────────────────────────
    sensor_col: str | None = None
    for col in df.columns:
        if col.strip().lower() == _SENSOR_TYPE_COL.lower():
            sensor_col = col
            break

    if sensor_col is None:
        return df, warnings  # already wide — nothing to do

    sensor_values = [v for v in df[sensor_col].dropna().unique() if str(v).strip()]
    if len(sensor_values) <= 1:
        # Only one sensor type — effectively wide already; drop the column so
        # downstream code doesn't see it as a categorical to audit.
        return df, warnings

    # ── 2. Find trip ID column ───────────────────────────────────────────────
    trip_id_col: str | None = None
    for candidate in _TRIP_ID_CANDIDATES:
        if candidate in df.columns:
            trip_id_col = candidate
            break

    if trip_id_col is None:
        warnings.append(
            f"Detected long-format sensor data ({', '.join(sensor_values)}) "
            f"but could not find a 'Trip ID' column — sensor-type pivot skipped."
        )
        return df, warnings

    warnings.append(
        f"Detected long-format sensor data: {', '.join(sensor_values)} rows per trip. "
        f"Pivoted to one row per trip with prefixed columns "
        f"(e.g. temp_mean_value, light_mean_value)."
    )

    # ── 3. Classify columns as identity vs measurement ───────────────────────
    # Identity columns have the same value for every row of the same trip.
    # Measurement columns vary across sensor types for the same trip.
    grouped = df.groupby(trip_id_col, sort=False)
    identity_cols: list[str] = []
    measurement_cols: list[str] = []

    for col in df.columns:
        if col in (sensor_col, trip_id_col):
            continue
        try:
            max_unique = grouped[col].nunique(dropna=False).max()
        except Exception:
            max_unique = 1
        if max_unique <= 1:
            identity_cols.append(col)
        else:
            measurement_cols.append(col)

    # ── 4. Build identity frame (one row per trip) ───────────────────────────
    identity_df = grouped[identity_cols].first().reset_index()

    # ── 5. Pivot measurement columns on sensor type ──────────────────────────
    if measurement_cols:
        pivot_df = df.pivot_table(
            index=trip_id_col,
            columns=sensor_col,
            values=measurement_cols,
            aggfunc="first",
        ).reset_index()

        # Flatten MultiIndex columns: ("Mean Value", "Temperature") → "temp_mean_value".
        # After reset_index() the index column appears as ("Trip ID", "") — preserve it as-is.
        flat_cols: list[str] = []
        for col in pivot_df.columns:
            if isinstance(col, tuple):
                measure, sensor = col
                if not sensor:  # index column restored by reset_index, e.g. ("Trip ID", "")
                    flat_cols.append(measure)
                else:
                    prefix = _SENSOR_PREFIXES.get(sensor, sensor.lower().replace(" ", "_"))
                    flat_cols.append(f"{prefix}_{measure.lower().replace(' ', '_')}")
            else:
                flat_cols.append(col)
        pivot_df.columns = flat_cols

        result = identity_df.merge(pivot_df, on=trip_id_col, how="left")
    else:
        result = identity_df

    return result, warnings


def load_spreadsheet(file_bytes: bytes, filename: str) -> tuple[pd.DataFrame, list[str]]:
    """Returns (dataframe, warnings). Raises ValueError on an unreadable file."""
    warnings: list[str] = []
    is_csv = filename.lower().endswith(".csv")

    try:
        if is_csv:
            preview = pd.read_csv(io.BytesIO(file_bytes), header=None, nrows=HEADER_SCAN_ROWS)
        else:
            preview = pd.read_excel(io.BytesIO(file_bytes), header=None, nrows=HEADER_SCAN_ROWS)
    except Exception as exc:
        raise ValueError(f"Could not read '{filename}' as a spreadsheet: {exc}") from exc

    header_row = _detect_header_row(preview)
    if header_row != 0:
        warnings.append(
            f"Detected the real column headers on row {header_row + 1} of the file; "
            f"the row(s) above were treated as a title block and skipped."
        )

    if is_csv:
        df = pd.read_csv(io.BytesIO(file_bytes), header=header_row)
    else:
        df = pd.read_excel(io.BytesIO(file_bytes), header=header_row)

    # Collapse embedded newlines/repeated whitespace from wrapped Excel header
    # cells (e.g. "Segment Length \n(Days)") into a single space.
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

    # Drop fully-unnamed trailing columns that come from stray formatting
    # past the real data range (openpyxl sometimes reports these) -- but
    # only when they're also entirely empty, so we never silently drop real data.
    unnamed_and_empty = [
        c for c in df.columns if str(c).startswith("Unnamed:") and df[c].isna().all()
    ]
    if unnamed_and_empty:
        df = df.drop(columns=unnamed_and_empty)

    if df.empty:
        raise ValueError(f"'{filename}' parsed to zero data rows.")

    # Pivot long-format sensor rows → wide format if needed.
    df, pivot_warnings = _pivot_sensor_rows(df)
    warnings.extend(pivot_warnings)

    return df, warnings
