"""Generates rich per-column metadata from a pandas DataFrame.

Everything here is derived purely from the data — no LLM calls.
The result is a dict keyed by column name, suitable for saving as
column_metadata.json and feeding into the Planner prompt.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

# --- role inference -----------------------------------------------------------

_IDENTIFIER_HINTS = re.compile(
    r"\b(id|code|key|number|no\.?|ref|uuid|trip)\b", re.IGNORECASE
)
_FLAG_HINTS = re.compile(
    r"\b(is_|has_|alarmed|flag|status|active|enabled|bool)\b", re.IGNORECASE
)
_THRESHOLD_HINTS = re.compile(
    r"\b(limit|threshold|max|min|target|ideal|spec|tolerance)\b", re.IGNORECASE
)
_UNIT_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(temp|temperature|celsius|°c|mean|value)\b", re.IGNORECASE), "°C"),
    (re.compile(r"\b(humidity|rh|%)\b", re.IGNORECASE), "%"),
    (re.compile(r"\b(weight|kg|gram)\b", re.IGNORECASE), "kg"),
    (re.compile(r"\b(distance|km|mile)\b", re.IGNORECASE), "km"),
    (re.compile(r"\b(duration|hours?|days?|minutes?)\b", re.IGNORECASE), "h"),
]
_TIMEZONE_PATTERN = re.compile(r"\b(CET|UTC|GMT|EST|PST|IST|JST)\b", re.IGNORECASE)


def _infer_role(col: str, series: pd.Series, dtype_label: str) -> str:
    if dtype_label == "datetime":
        return "timestamp"
    if dtype_label == "bool":
        return "flag"
    if _IDENTIFIER_HINTS.search(col):
        return "identifier"
    if _THRESHOLD_HINTS.search(col):
        return "threshold"
    if _FLAG_HINTS.search(col):
        return "flag"
    n_unique = series.nunique()
    n_total = len(series.dropna())
    if dtype_label in ("int64", "float64"):
        if n_unique <= 2:
            return "flag"
        # high-cardinality numeric that looks like an id
        if n_unique / max(n_total, 1) > 0.95 and n_total > 50:
            return "identifier"
        return "measure"
    if dtype_label == "string":
        if n_unique <= 2:
            return "flag"
        if n_unique / max(n_total, 1) > 0.95 and n_total > 50:
            return "identifier"
        return "category"
    return "unknown"


def _dtype_label(series: pd.Series) -> str:
    kind = series.dtype.kind
    if pd.api.types.is_bool_dtype(series):
        return "bool"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if kind in ("i", "u"):
        return "int64"
    if kind == "f":
        return "float64"
    # object / string-like — try to detect if it looks datetime
    if kind == "O":
        sample = series.dropna().head(20)
        try:
            pd.to_datetime(sample, infer_datetime_format=True)
            return "datetime"
        except Exception:
            pass
        return "string"
    return str(series.dtype)


def _detect_timezone(col: str, series: pd.Series) -> str | None:
    m = _TIMEZONE_PATTERN.search(col)
    if m:
        return m.group(0).upper()
    if hasattr(series.dtype, "tz") and series.dtype.tz is not None:
        return str(series.dtype.tz)
    return None


def _detect_unit(col: str) -> str | None:
    for pattern, unit in _UNIT_HINTS:
        if pattern.search(col):
            return unit
    return None


def _safe_example(series: pd.Series, dtype_label: str) -> Any:
    non_null = series.dropna()
    if non_null.empty:
        return None
    val = non_null.iloc[0]
    if dtype_label in ("int64",):
        return int(val)
    if dtype_label == "float64":
        return round(float(val), 4)
    if dtype_label == "datetime":
        return str(val)
    return str(val)


# --- main entry point ---------------------------------------------------------

def profile_dataframe(df: pd.DataFrame) -> dict[str, dict]:
    """Returns a dict keyed by column name with rich per-column metadata."""
    result: dict[str, dict] = {}

    for col in df.columns:
        series = df[col]
        dtype_label = _dtype_label(series)
        missing = int(series.isna().sum())
        n_unique = int(series.nunique())
        role = _infer_role(col, series, dtype_label)

        entry: dict[str, Any] = {
            "dtype": dtype_label,
            "role": role,
            "missing": missing,
            "unique": n_unique,
        }

        # datetime extras
        if dtype_label == "datetime":
            tz = _detect_timezone(col, series)
            if tz:
                entry["timezone"] = tz
            parsed = pd.to_datetime(series, errors="coerce")
            valid = parsed.dropna()
            if not valid.empty:
                entry["min"] = str(valid.min())
                entry["max"] = str(valid.max())
            entry.pop("unique", None)  # not meaningful for timestamps

        # numeric extras
        elif dtype_label in ("int64", "float64"):
            non_null = series.dropna()
            if not non_null.empty:
                entry["min"] = round(float(non_null.min()), 4)
                entry["max"] = round(float(non_null.max()), 4)
                entry["mean"] = round(float(non_null.mean()), 4)
            unit = _detect_unit(col)
            if unit:
                entry["unit"] = unit
            if role not in ("identifier",):
                entry["example"] = _safe_example(series, dtype_label)

        # categorical / flag extras
        elif dtype_label == "string":
            non_null = series.dropna()
            value_counts = non_null.value_counts()

            if role == "flag" or (n_unique <= 10 and not non_null.empty):
                # show all values + counts
                entry["allowed_values"] = list(value_counts.index.astype(str))
                entry["counts"] = {
                    str(k): int(v) for k, v in value_counts.items()
                }
            elif n_unique <= 30:
                # top values only
                top = value_counts.head(5)
                entry["top_values"] = {str(k): int(v) for k, v in top.items()}
            else:
                entry["example"] = _safe_example(series, dtype_label)

        # bool extras
        elif dtype_label == "bool":
            vc = series.value_counts()
            entry["counts"] = {str(k): int(v) for k, v in vc.items()}

        # identifier: just example
        if role == "identifier":
            entry["example"] = _safe_example(series, dtype_label)
            entry.pop("top_values", None)
            entry.pop("counts", None)
            entry.pop("allowed_values", None)

        result[col] = entry

    return result
