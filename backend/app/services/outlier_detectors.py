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

import numpy as np
import pandas as pd

from app.services import anomaly_detection


def _prepare(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (original_df, analysis_df) with aligned 0-based indices.

    original_df – original data reset to integer index (for display).
    analysis_df – normalized + widened copy passed to the detection functions.
    """
    original = df.reset_index(drop=True)
    analysis = anomaly_detection._normalize_columns(original.copy())

    if anomaly_detection.is_long_sensor_format(analysis):
        serial_col = next(
            (c for c in analysis.columns if "serial" in c.lower()),
            analysis.columns[0],
        )
        trip_col = next(
            (c for c in analysis.columns if "trip" in c.lower() and "id" in c.lower()),
            analysis.columns[1],
        )
        analysis = anomaly_detection.widen_by_sensor_type(analysis, serial_col, trip_col)
        analysis = analysis.reset_index(drop=True)

    # Light channel absent in Temperature-only exports; add NaN column so
    # compute_flags can compute flag_8 without a KeyError (flag_8 = all False).
    if anomaly_detection.COL_MAX_LIGHT not in analysis.columns:
        analysis[anomaly_detection.COL_MAX_LIGHT] = np.nan

    return original, analysis


def detect_segment_outliers(df: pd.DataFrame) -> dict:
    original_df, analysis_df = _prepare(df)

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
        }

    outlier_df = anomaly_detection.compute_lane_duration_outliers(analysis_df)
    # outlier_df.index == analysis_df.index == 0..N-1

    origins = analysis_df[ORIG].fillna("(blank)").astype(str)
    destinations = analysis_df[DEST].fillna("(blank)").astype(str)

    lane_groups: dict[tuple[str, str], list[int]] = {}
    for i in analysis_df.index:
        lane = (str(origins.iat[i]), str(destinations.iat[i]))
        lane_groups.setdefault(lane, []).append(i)

    lanes_output: list[dict] = []

    for (orig, dest), idxs in sorted(lane_groups.items()):
        idx_arr = pd.Index(idxs)
        lane_outlier = outlier_df.loc[idx_arr]

        n_trips = len(idxs)
        n_valid = int(pd.to_numeric(analysis_df.loc[idx_arr, DUR], errors="coerce").notna().sum())

        flagged_idx = list(lane_outlier[lane_outlier["duration_outlier"]].index)
        n_outliers = len(flagged_idx)

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

    return {
        "column_found": True,
        "total_trips": len(original_df),
        "flagged_trips": int(outlier_df["duration_outlier"].sum()),
        "columns": [str(c) for c in original_df.columns],
        "lanes": lanes_output,
    }


def detect_temperature_outliers(df: pd.DataFrame) -> dict:
    original_df, analysis_df = _prepare(df)

    MEAN = anomaly_detection.COL_MEAN_TEMP
    LOW = anomaly_detection.COL_LIMIT_LOW_TEMP
    HIGH = anomaly_detection.COL_LIMIT_HIGH_TEMP
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
    too_warm = flags["flag_1_too_warm_avg"]
    too_cold = flags["flag_2_too_cold_avg"]

    products = (
        original_df[PRODUCT].fillna("Unknown").astype(str)
        if PRODUCT in original_df.columns
        else pd.Series(["Unknown"] * len(original_df), dtype=str)
    )

    by_product: list[dict] = []
    for product in sorted(products.unique()):
        mask = products == product
        n_total = int(mask.sum())
        n_warm = int(too_warm[mask].sum())
        n_cold = int(too_cold[mask].sum())
        by_product.append({
            "product": product,
            "total": n_total,
            "too_warm": n_warm,
            "too_cold": n_cold,
            "in_spec": max(0, n_total - n_warm - n_cold),
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
