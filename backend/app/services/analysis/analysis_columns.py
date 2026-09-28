"""Column-type helpers shared by the analysis templates and filters.

The audited dataframe often carries numbers and dates as `object` columns
(values read from Excel as text), so dtype alone isn't a reliable signal.
These helpers coerce a column and accept the result only when most of its
non-null values actually converted -- a text column with one stray number
in it is not a numeric column.
"""
from __future__ import annotations

import warnings

import pandas as pd

# Share of non-null values that must convert before a column is treated as
# numeric / date. High enough that free text never qualifies by accident.
_MIN_CONVERTED_SHARE = 0.8


def as_numeric(series: pd.Series) -> pd.Series | None:
    """The column as floats, or None if it isn't really numeric."""
    if pd.api.types.is_bool_dtype(series):
        return None
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    non_null = series.notna().sum()
    if non_null == 0:
        return None
    converted = pd.to_numeric(series, errors="coerce")
    if converted.notna().sum() / non_null < _MIN_CONVERTED_SHARE:
        return None
    return converted.astype(float)


def as_datetime(series: pd.Series) -> pd.Series | None:
    """The column as datetimes, or None if it isn't really a date column.
    Plain numeric columns are never treated as dates (an int column of
    shipment counts would otherwise parse as nanosecond timestamps)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(series):
        return None
    non_null = series.notna().sum()
    if non_null == 0:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        converted = pd.to_datetime(series, errors="coerce", format="mixed")
    if converted.notna().sum() / non_null < _MIN_CONVERTED_SHARE:
        return None
    return converted


def as_labels(series: pd.Series) -> pd.Series:
    """The column as display strings for a chart axis / group key, with
    nulls shown as "(blank)" rather than silently dropped by groupby. Whole-
    number floats (Excel's habit for year or ID columns) lose the ".0"."""
    if pd.api.types.is_float_dtype(series):
        non_null = series.dropna()
        if len(non_null) and (non_null % 1 == 0).all():
            series = series.astype("Int64")
    if pd.api.types.is_datetime64_any_dtype(series):
        labels = series.dt.strftime("%Y-%m-%d")
    else:
        labels = series.astype("string")
    return labels.fillna("(blank)").astype(str)


SAMPLE_VALUES_PER_COLUMN = 3
SAMPLE_VALUE_MAX_CHARS = 200


def sample_preview(series: pd.Series) -> str:
    """A few real values from the column for an LLM prompt. Takes the
    sample BEFORE converting to text so a large column isn't stringified in
    full, and cuts very long values (free-text notes) to keep prompts small."""
    sample = series.dropna().head(SAMPLE_VALUES_PER_COLUMN).astype(str).tolist()
    if not sample:
        return "(all null)"
    cleaned = []
    for value in sample:
        value = " ".join(value.split())
        if len(value) > SAMPLE_VALUE_MAX_CHARS:
            value = value[:SAMPLE_VALUE_MAX_CHARS] + "…"
        cleaned.append(value)
    return ", ".join(cleaned)


def column_catalog(df: pd.DataFrame) -> str:
    """One line per column -- name, dtype, sample values -- for LLM prompts."""
    return "\n".join(f"- {col} ({df[col].dtype}): e.g. {sample_preview(df[col])}" for col in df.columns)
