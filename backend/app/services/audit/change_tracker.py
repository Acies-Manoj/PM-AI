"""Compares the ORIGINAL SensiWatch upload with a corrected re-upload and builds a
change log: every trip whose data differs, with all of its columns, plus a tag
saying whether the change was an expected fix of a flagged outlier or something else.

Trips are keyed on (Serial Number, Trip ID), same as the outlier tools. The
"flagged" set is re-derived from the original upload with the same detectors the
Outliers Check step uses, so the tags match what the PM saw on screen."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from app.services.audit.outlier_detectors import _find_col

CATEGORY_COL = "Change Category"
COLUMNS_CHANGED_COL = "Columns Changed"
DETAILS_COL = "Change Details"

TAG_FLAGGED_CORRECTED = "Flagged outlier - corrected"
TAG_FLAGGED_UNCHANGED = "Flagged outlier - not corrected"
TAG_OTHER_CHANGED = "Other trip - changed"
TAG_NEW = "New trip (not in original)"
TAG_REMOVED = "Removed trip (missing from corrected file)"

_CATEGORY_ORDER = [TAG_FLAGGED_CORRECTED, TAG_FLAGGED_UNCHANGED, TAG_OTHER_CHANGED, TAG_NEW, TAG_REMOVED]
_MAX_DETAILS = 10


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.reset_index(drop=True).copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df.loc[:, ~df.columns.duplicated()]


def _norm_id(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    try:
        number = float(text)
        if number.is_integer():
            return str(int(number))
    except ValueError:
        pass
    return text


def _keys(df: pd.DataFrame, serial_col: str, trip_col: str) -> pd.Series:
    return df[serial_col].map(_norm_id) + "|" + df[trip_col].map(_norm_id)


def _differs(a: pd.Series, b: pd.Series) -> pd.Series:
    """Cell-wise inequality that ignores formatting noise: NaN == NaN, numbers
    compare with a tiny tolerance (so 3 == 3.0 == "3"), text compares trimmed."""
    a_null, b_null = a.isna(), b.isna()
    if pd.api.types.is_datetime64_any_dtype(a) and pd.api.types.is_datetime64_any_dtype(b):
        diff = pd.Series(a.to_numpy() != b.to_numpy(), index=a.index)
    else:
        an = pd.to_numeric(a, errors="coerce")
        bn = pd.to_numeric(b, errors="coerce")
        both_num = (an.notna() & bn.notna()).to_numpy()
        num_diff = ~np.isclose(an.fillna(0).to_numpy(float), bn.fillna(0).to_numpy(float), rtol=1e-9, atol=1e-6)
        str_diff = (a.astype(str).str.strip() != b.astype(str).str.strip()).to_numpy()
        diff = pd.Series(np.where(both_num, num_diff, str_diff), index=a.index)
    diff = diff.where(~(a_null & b_null), False)
    diff = diff.where(~(a_null ^ b_null), True)
    return diff.astype(bool)


def flagged_trips_from_outliers(segment: dict, temperature: dict) -> dict[str, str]:
    """{trip key: 'Segment' | 'Temperature' | 'Segment + Temperature'} read off the
    outlier results the Outliers Check step already computed (the dicts returned by
    detect_segment_outliers / detect_temperature_outliers) -- detection is not re-run."""
    kinds: dict[str, set[str]] = {}
    for row in segment.get("outlier_rows", []):
        kinds.setdefault(_norm_id(row["serial"]) + "|" + _norm_id(row["trip_id"]), set()).add("Segment")
    for product in temperature.get("by_product", []):
        for trip in product["trips"]:
            if trip["status"] != "in_spec":
                kinds.setdefault(_norm_id(trip["serial"]) + "|" + _norm_id(trip["trip_id"]), set()).add("Temperature")
    return {k: " + ".join(sorted(v, key=("Segment", "Temperature").index)) for k, v in kinds.items()}


def compute_change_log(
    original_raw: pd.DataFrame, corrected_raw: pd.DataFrame, flagged: dict[str, str]
) -> tuple[pd.DataFrame, dict]:
    """(change_log_df, summary). `flagged` is the stored snapshot of trips flagged at the
    first Outliers Check. Raises ValueError if the trip identifier columns can't be found."""
    o, c = _clean_columns(original_raw), _clean_columns(corrected_raw)

    serial_col = _find_col(list(o.columns), "serial")
    trip_col = _find_col(list(o.columns), "trip", "id")
    if not serial_col or not trip_col or serial_col not in c.columns or trip_col not in c.columns:
        raise ValueError("Could not identify Serial Number/Trip ID columns in both files.")

    o["_k"], c["_k"] = _keys(o, serial_col, trip_col), _keys(c, serial_col, trip_col)
    o["_n"], c["_n"] = o.groupby("_k").cumcount(), c.groupby("_k").cumcount()

    compare_cols = [col for col in o.columns if col in c.columns and col not in ("_k", "_n", serial_col, trip_col)]
    merged = o[["_k", "_n"] + compare_cols].merge(
        c[["_k", "_n"] + compare_cols], on=["_k", "_n"], how="outer", suffixes=("__o", "__c"), indicator=True
    )
    both = merged[merged["_merge"] == "both"]

    changes: dict[str, dict[str, list[str]]] = {}  # key -> column -> ["old -> new", ...]
    for col in compare_cols:
        mask = _differs(both[col + "__o"], both[col + "__c"])
        for key, old, new in zip(both.loc[mask, "_k"], both.loc[mask, col + "__o"], both.loc[mask, col + "__c"]):
            entry = f"{'(blank)' if pd.isna(old) else old} -> {'(blank)' if pd.isna(new) else new}"
            seen = changes.setdefault(key, {}).setdefault(col, [])
            if entry not in seen:
                seen.append(entry)

    o_counts, c_counts = o["_k"].value_counts(), c["_k"].value_counts()
    o_keys, c_keys = set(o_counts.index), set(c_counts.index)
    for key in o_keys & c_keys:
        if o_counts[key] != c_counts[key]:
            changes.setdefault(key, {})["(row count)"] = [f"{o_counts[key]} -> {c_counts[key]} rows"]

    category: dict[str, str] = {}
    for key in o_keys - c_keys:
        category[key] = TAG_REMOVED
    for key in c_keys - o_keys:
        category[key] = TAG_NEW
    for key in o_keys & c_keys:
        if key in flagged:
            category[key] = TAG_FLAGGED_CORRECTED if key in changes else TAG_FLAGGED_UNCHANGED
        elif key in changes:
            category[key] = TAG_OTHER_CHANGED

    def _details(key: str) -> tuple[str, str]:
        cols = changes.get(key, {})
        parts = [f"{col}: {v}" for col, vals in cols.items() for v in vals]
        if len(parts) > _MAX_DETAILS:
            parts = parts[:_MAX_DETAILS] + [f"... +{len(parts) - _MAX_DETAILS} more"]
        return "; ".join(cols), "; ".join(parts)

    kept_c = c[c["_k"].isin([k for k, v in category.items() if v != TAG_REMOVED])]
    kept_o = o[o["_k"].isin([k for k, v in category.items() if v == TAG_REMOVED])]
    log = pd.concat([kept_c, kept_o], ignore_index=True)

    log[CATEGORY_COL] = log["_k"].map(category)
    details = log["_k"].map(_details)
    log[COLUMNS_CHANGED_COL] = details.map(lambda d: d[0])
    log[DETAILS_COL] = details.map(lambda d: d[1])
    log["_order"] = log[CATEGORY_COL].map(_CATEGORY_ORDER.index)
    log = log.sort_values(["_order", "_k", "_n"], kind="stable").drop(columns=["_k", "_n", "_order"]).reset_index(drop=True)

    counts = pd.Series(category).value_counts()
    summary = {
        "trips_in_original": len(o_keys),
        "trips_in_corrected": len(c_keys),
        "flagged_in_original": len(flagged),
        "flagged_corrected": int(counts.get(TAG_FLAGGED_CORRECTED, 0)),
        "flagged_not_corrected": int(counts.get(TAG_FLAGGED_UNCHANGED, 0)),
        "other_trips_changed": int(counts.get(TAG_OTHER_CHANGED, 0)),
        "new_trips": int(counts.get(TAG_NEW, 0)),
        "removed_trips": int(counts.get(TAG_REMOVED, 0)),
        "rows_in_log": len(log),
        "columns_added_in_corrected": [col for col in c.columns if col not in o.columns and col not in ("_k", "_n")],
        "columns_missing_in_corrected": [col for col in o.columns if col not in c.columns and col not in ("_k", "_n")],
    }
    return log, summary
