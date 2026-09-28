"""Per-lane segment length outlier detection and per-trip temperature breach detection.

Delegates to anomaly_detection.py (agent-orchestration-flow branch) for the
actual algorithms:
  - compute_lane_duration_outliers: Tukey fence with peer-shrunk fallback
  - compute_flags: 9 trip-level rules; flag_1/flag_2 used for temperature tab

SensiWatch exports use a "long sensor format": one row per (trip, sensor channel),
"Sensor Type" column = "Temperature". widen_by_sensor_type reshapes this to one
row per trip with _Temperature-suffixed columns that compute_flags expects.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from app.services.audit import anomaly_detection


def _find_col(columns: list[str], *needles: str) -> str | None:
    lowered = [c.lower() for c in columns]
    for i, c in enumerate(lowered):
        if all(n in c for n in needles):
            return columns[i]
    return None


def _raw_column(df: pd.DataFrame, normalized_target: str) -> str | None:
    """The df's OWN column name that normalizes (whitespace-collapsed) to
    `normalized_target` -- so a caller can write to it without renaming any
    column on the dataframe that becomes the new session.df."""
    for c in df.columns:
        if re.sub(r"\s+", " ", str(c)).strip() == normalized_target:
            return c
    return None


def _to_trip_id(val) -> int | str | None:
    if val is None or (isinstance(val, float) and np.isnan(val)) or pd.isna(val):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return str(val)


def _prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, str | None, str | None]:
    """Return (original_df, analysis_df, serial_col, trip_col) with aligned
    0-based indices.

    original_df – original data reset to integer index (for display).
    analysis_df – normalized + widened copy passed to the detection functions.
    serial_col/trip_col – the column names (in analysis_df) identifying each
    trip, so callers can build per-trip records; None if not found.
    """
    original = df.reset_index(drop=True)
    analysis = anomaly_detection._normalize_columns(original.copy())

    serial_col = _find_col(list(analysis.columns), "serial")
    trip_col = _find_col(list(analysis.columns), "trip", "id")

    if anomaly_detection.is_long_sensor_format(analysis):
        s_col = serial_col or analysis.columns[0]
        t_col = trip_col or analysis.columns[1]
        analysis = anomaly_detection.widen_by_sensor_type(analysis, s_col, t_col)
        analysis = analysis.reset_index(drop=True)
        serial_col, trip_col = s_col, t_col

    # Light channel absent in Temperature-only exports; add NaN column so
    # compute_flags can compute flag_8 without a KeyError (flag_8 = all False).
    if anomaly_detection.COL_MAX_LIGHT not in analysis.columns:
        analysis[anomaly_detection.COL_MAX_LIGHT] = np.nan

    return original, analysis, serial_col, trip_col


def detect_segment_outliers(df: pd.DataFrame) -> dict:
    original_df, analysis_df, serial_col, trip_col = _prepare(df)

    DUR = anomaly_detection.COL_DURATION
    ORIG = anomaly_detection.COL_ORIGIN
    DEST = anomaly_detection.COL_DESTINATION

    if DUR not in analysis_df.columns:
        return {
            "column_found": False,
            "total_trips": len(original_df),
            "flagged_trips": 0,
            "columns": [str(c) for c in original_df.columns],
            "lanes": [],
            "outlier_rows": [],
        }

    # Reindexed defensively for the same reason as detect_temperature_outliers
    # below: this is expected to already align 1:1 with analysis_df, but a
    # widened long-sensor-format frame is exactly the kind of reshaping that
    # can leave a subtly mismatched index for some real, messy exports.
    outlier_df = anomaly_detection.compute_lane_duration_outliers(analysis_df).reindex(analysis_df.index)
    outlier_df["duration_outlier"] = outlier_df["duration_outlier"].fillna(False)
    outlier_df["duration_outlier_status"] = outlier_df["duration_outlier_status"].fillna("Insufficient History")
    duration = pd.to_numeric(analysis_df[DUR], errors="coerce")

    origins = analysis_df[ORIG].fillna("(blank)").astype(str)
    destinations = analysis_df[DEST].fillna("(blank)").astype(str)

    lane_groups: dict[tuple[str, str], list[int]] = {}
    for i in analysis_df.index:
        lane = (str(origins.iat[i]), str(destinations.iat[i]))
        lane_groups.setdefault(lane, []).append(i)

    lanes_output: list[dict] = []
    lane_flagged_idx: dict[tuple[str, str], list[int]] = {}

    for (orig, dest), idxs in sorted(lane_groups.items()):
        idx_arr = pd.Index(idxs)
        lane_outlier = outlier_df.loc[idx_arr]

        n_trips = len(idxs)
        n_valid = int(pd.to_numeric(analysis_df.loc[idx_arr, DUR], errors="coerce").notna().sum())

        flagged_idx = list(lane_outlier[lane_outlier["duration_outlier"]].index)
        n_outliers = len(flagged_idx)
        lane_flagged_idx[(orig, dest)] = flagged_idx

        # Prefer any non-"Insufficient History" label for the lane badge
        status_series = lane_outlier["duration_outlier_status"]
        non_insuf = status_series[status_series != "Insufficient History"]
        status_label = str(non_insuf.iloc[0]) if len(non_insuf) > 0 else "Insufficient History"

        if "Own-Lane Fence" in status_label:
            status_type = "own_lane"
        elif "Peer-Shrunk" in status_label:
            status_type = "peer_shrunk"
        else:
            status_type = "insufficient"

        lower_fence: float | None = None
        upper_fence: float | None = None
        non_nan_lo = outlier_df.loc[idx_arr, "duration_lower_fence_days"].dropna()
        non_nan_hi = outlier_df.loc[idx_arr, "duration_upper_fence_days"].dropna()
        if len(non_nan_lo) > 0:
            lower_fence = float(non_nan_lo.iloc[0])
        if len(non_nan_hi) > 0:
            upper_fence = float(non_nan_hi.iloc[0])

        # Outlier rows shown with all original (non-widened) columns
        outlier_rows: list[dict] = []
        if flagged_idx:
            outlier_rows = json.loads(
                original_df.iloc[flagged_idx].to_json(orient="records", date_format="iso")
            )

        lanes_output.append({
            "origin": orig,
            "destination": dest,
            "n_trips": n_trips,
            "n_valid": n_valid,
            "n_outliers": n_outliers,
            "status_type": status_type,
            "status_label": status_label,
            "lower_fence": lower_fence,
            "upper_fence": upper_fence,
            "outlier_rows": outlier_rows,
        })

    lanes_output.sort(key=lambda l: (-l["n_outliers"], l["destination"], l["origin"]))

    # Flat, one-row-per-outlier-trip view across every lane (the "outliers
    # themselves, not the fence numbers" table) -- walked in the same
    # lane order as `lanes` above so trips from the same lane stay grouped.
    flat_rows: list[dict] = []
    for lane in lanes_output:
        idxs = lane_flagged_idx.get((lane["origin"], lane["destination"]), [])
        for i in idxs:
            serial_val = analysis_df.at[i, serial_col] if serial_col else None
            trip_val = analysis_df.at[i, trip_col] if trip_col else None
            days = duration.at[i]
            flat_rows.append({
                "serial": str(serial_val) if serial_val is not None and pd.notna(serial_val) else None,
                "trip_id": _to_trip_id(trip_val),
                "origin": lane["origin"],
                "destination": lane["destination"],
                "segment_days": round(float(days), 2) if pd.notna(days) else None,
                "lower_fence_days": lane["lower_fence"],
                "upper_fence_days": lane["upper_fence"],
                "status": lane["status_label"],
            })

    return {
        "column_found": True,
        "total_trips": len(original_df),
        "flagged_trips": int(outlier_df["duration_outlier"].sum()),
        "columns": [str(c) for c in original_df.columns],
        "lanes": lanes_output,
        "outlier_rows": flat_rows,
    }


def detect_temperature_outliers(df: pd.DataFrame) -> dict:
    original_df, analysis_df, serial_col, trip_col = _prepare(df)

    MEAN = anomaly_detection.COL_MEAN_TEMP
    LOW = anomaly_detection.COL_LIMIT_LOW_TEMP
    HIGH = anomaly_detection.COL_LIMIT_HIGH_TEMP
    IDEAL = anomaly_detection.COL_LIMIT_IDEAL_TEMP
    PRODUCT = anomaly_detection.COL_PRODUCT

    cols_found = {
        "mean": MEAN in analysis_df.columns,
        "limit_low": LOW in analysis_df.columns,
        "limit_high": HIGH in analysis_df.columns,
    }
    col_names_found = {
        "mean": MEAN if MEAN in analysis_df.columns else None,
        "limit_low": LOW if LOW in analysis_df.columns else None,
        "limit_high": HIGH if HIGH in analysis_df.columns else None,
    }

    if not all(cols_found.values()):
        return {
            "columns_found": cols_found,
            "col_names_found": col_names_found,
            "total_trips": len(original_df),
            "too_warm_count": 0,
            "too_cold_count": 0,
            "by_product": [],
        }

    flags = anomaly_detection.compute_flags(analysis_df)
    # Reindexed defensively onto analysis_df's own index: compute_flags is
    # expected to already align 1:1 with it, but a widened long-sensor-format
    # frame (see widen_by_sensor_type's outer merge) is exactly the kind of
    # reshaping that can leave a subtly mismatched index for some real,
    # messy exports -- reindexing turns a would-be crash (KeyError from
    # `.at[i]` below) into "treat that trip as not flagged" instead.
    too_warm = flags["flag_1_too_warm_avg"].reindex(analysis_df.index, fill_value=False)
    too_cold = flags["flag_2_too_cold_avg"].reindex(analysis_df.index, fill_value=False)
    flag_count = flags["flag_count"].reindex(analysis_df.index, fill_value=0)

    mean_temp = pd.to_numeric(analysis_df[MEAN], errors="coerce")
    limit_low = pd.to_numeric(analysis_df[LOW], errors="coerce")
    limit_high = pd.to_numeric(analysis_df[HIGH], errors="coerce")
    limit_ideal = (
        pd.to_numeric(analysis_df[IDEAL], errors="coerce")
        if IDEAL in analysis_df.columns
        else pd.Series(np.nan, index=analysis_df.index)
    )

    products = (
        analysis_df[PRODUCT].fillna("Unknown").astype(str)
        if PRODUCT in analysis_df.columns
        else pd.Series(["Unknown"] * len(analysis_df), dtype=str)
    )

    by_product: list[dict] = []
    for product in sorted(products.unique()):
        mask = products == product
        idxs = list(products[mask].index)
        n_total = int(mask.sum())
        n_warm = int(too_warm[mask].sum())
        n_cold = int(too_cold[mask].sum())

        trips: list[dict] = []
        for i in idxs:
            status = "too_warm" if bool(too_warm.at[i]) else "too_cold" if bool(too_cold.at[i]) else "in_spec"
            serial_val = analysis_df.at[i, serial_col] if serial_col else None
            trip_val = analysis_df.at[i, trip_col] if trip_col else None
            mt = mean_temp.at[i]
            trips.append({
                "serial": str(serial_val) if serial_val is not None and pd.notna(serial_val) else None,
                "trip_id": _to_trip_id(trip_val),
                "mean_temp": round(float(mt), 2) if pd.notna(mt) else None,
                "limit_low": round(float(limit_low.at[i]), 2) if pd.notna(limit_low.at[i]) else None,
                "limit_ideal": round(float(limit_ideal.at[i]), 2) if pd.notna(limit_ideal.at[i]) else None,
                "limit_high": round(float(limit_high.at[i]), 2) if pd.notna(limit_high.at[i]) else None,
                "status": status,
                "flag_count": int(flag_count.at[i]),
            })
        trips.sort(key=lambda t: (t["trip_id"] is None, t["trip_id"]))

        by_product.append({
            "product": product,
            "total": n_total,
            "too_warm": n_warm,
            "too_cold": n_cold,
            "in_spec": max(0, n_total - n_warm - n_cold),
            "trips": trips,
        })

    by_product.sort(key=lambda x: -(x["too_warm"] + x["too_cold"]))

    return {
        "columns_found": cols_found,
        "col_names_found": col_names_found,
        "total_trips": len(original_df),
        "too_warm_count": int(too_warm.sum()),
        "too_cold_count": int(too_cold.sum()),
        "by_product": by_product,
    }


def update_trip_value(df: pd.DataFrame, serial: str, trip_id: str, field: str, value: float) -> pd.DataFrame:
    """Writes a PM's inline edit for one trip back into the session's own
    working dataframe, keyed by (serial, trip_id) -- mutates the dataframe's
    OWN column names/rows directly (no normalization/widening persisted),
    since the result becomes the new session.df for every other endpoint too.

    "segment_days" writes every row for that trip (Segment Length (Days) is
    a trip-level attribute, duplicated across a trip's Temperature/Light
    channel rows in the long sensor format). "mean_temp" writes only the
    Temperature-channel row's Mean Value, so a trip's Light-channel reading
    (a different physical quantity, sharing the generic "Mean Value" column
    name before widening) is left alone.
    """
    df = df.copy()
    serial_col = _find_col(list(df.columns), "serial")
    trip_col = _find_col(list(df.columns), "trip", "id")
    if not serial_col or not trip_col:
        raise ValueError("Could not identify Serial Number/Trip ID columns in this dataset.")

    row_mask = (df[serial_col].astype(str) == str(serial)) & (df[trip_col].astype(str) == str(trip_id))
    if not row_mask.any():
        raise ValueError(f"No rows found for serial '{serial}', trip {trip_id}.")

    if field == "segment_days":
        col = _raw_column(df, anomaly_detection.COL_DURATION)
        if not col:
            raise ValueError(f"Column '{anomaly_detection.COL_DURATION}' not found in this dataset.")
        df.loc[row_mask, col] = value
        return df

    if field == "mean_temp":
        sensor_col = _raw_column(df, anomaly_detection.SENSOR_TYPE_COL)
        target_mask = row_mask
        col = None
        if sensor_col is not None:
            sensor_values = set(df.loc[row_mask, sensor_col].dropna().astype(str).str.strip().unique())
            if sensor_values and sensor_values.issubset({"Temperature", "Light"}):
                target_mask = row_mask & (df[sensor_col].astype(str).str.strip() == "Temperature")
                col = _raw_column(df, "Mean Value")
        if col is None:
            col = _raw_column(df, anomaly_detection.COL_MEAN_TEMP)
        if not col:
            raise ValueError("Mean temperature column not found in this dataset.")
        if not target_mask.any():
            raise ValueError(f"No Temperature-channel row found for serial '{serial}', trip {trip_id}.")
        df.loc[target_mask, col] = value
        return df

    raise ValueError(f"Unknown field '{field}'.")
