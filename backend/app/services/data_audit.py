"""Deterministic, schema-agnostic data-quality checks -- the "does this look
like clean data to a data analyst" pass. Every check is a pure function of
the current working dataframe so the same detection logic can be re-run at
resolve time (after earlier fixes changed row/column counts) instead of
trusting stale row indices computed at audit time.

No LLM involved here on purpose: duplicate/outlier detection has to be
reliable, not a plausible-sounding guess -- see audit_agent.py for the one
place an LLM is used (the narrative summary only).

Column-level checks (empty/high-null/constant columns) are "selective":
each fires as ONE issue carrying every offending column in `selectable_items`
so the user can pick exactly which ones to drop, rather than an all-or-nothing
button. Row-level checks that naturally split by column (outliers, missing
identifiers) instead fire as one issue PER column, namespaced as
"<category>::<column>", so each gets its own independent decision.
"""
import math
import re
import uuid
from typing import Any

import numpy as np
import pandas as pd

from app.schemas import AuditIssue, IssueOption

HIGH_NULL_THRESHOLD_PCT = 50.0
OUTLIER_IQR_MULTIPLIER = 3.0
MEASUREMENT_COL_NAMES = {"Mean Value", "Min Value", "Max Value", "Standard Deviation"}
CORE_IDENTITY_COLS = ["Product", "Origin", "Destination"]
SAMPLE_ROWS = 5
SAMPLE_COLS = 8
NS = "::"  # separator for column-namespaced categories, e.g. "statistical_outliers::Mean Value"


# ---------------------------------------------------------------- helpers --

def _to_jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _sample(df: pd.DataFrame, mask: pd.Series, n: int = SAMPLE_ROWS) -> list[dict[str, Any]]:
    sub = df[mask].head(n)
    cols = list(sub.columns)[:SAMPLE_COLS]
    return [{str(c): _to_jsonable(row[c]) for c in cols} for _, row in sub.iterrows()]


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _is_measurement_col(name: str) -> bool:
    if name in MEASUREMENT_COL_NAMES:
        return True
    if re.search(r"(hours|days)\s*\)?\s*$", name, re.I):
        return True
    if "segment length" in name.lower():
        return True
    return False


def detect_id_column(df: pd.DataFrame) -> str | None:
    if "Trip ID" in df.columns and not df["Trip ID"].isna().all():
        return "Trip ID"
    candidates = [
        c for c in df.columns
        if re.search(r"\bid\b", c, re.I) and not df[c].isna().all()
    ]
    return candidates[0] if candidates else None


def _differentiator_column(df: pd.DataFrame, id_col: str) -> str | None:
    for c in ("Sensor Type", "Segment Start Date Time", "Segment Name", "Actual Departure Time CET"):
        if c in df.columns and c != id_col and not df[c].isna().all():
            return c
    return None


# ---------------------------------------------------------- mask detectors --
# Each returns a boolean row mask (or, for column-level checks, a list of
# column names) computed fresh against whatever dataframe is passed in.

def detect_fully_empty_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if df[c].isna().all()]


def detect_high_null_columns(df: pd.DataFrame, empty_cols: list[str]) -> pd.Series:
    null_pct = (df.isna().mean() * 100).round(1)
    return null_pct[(null_pct >= HIGH_NULL_THRESHOLD_PCT) & (~null_pct.index.isin(empty_cols))].sort_values(
        ascending=False
    )


def detect_constant_columns(df: pd.DataFrame) -> list[str]:
    """Columns with exactly one distinct non-null value -- zero information
    content. Naturally excludes fully-empty columns (those have 0 distinct
    values, not 1)."""
    return [c for c in df.columns if df[c].nunique(dropna=True) == 1]


def detect_exact_duplicates(df: pd.DataFrame) -> pd.Series:
    return df.duplicated(keep="first")


def detect_key_duplicates(df: pd.DataFrame) -> tuple[list[str], pd.Series] | None:
    id_col = detect_id_column(df)
    if not id_col:
        return None
    diff_col = _differentiator_column(df, id_col)
    if not diff_col:
        return None
    key_cols = [id_col, diff_col]
    mask = df.duplicated(subset=key_cols, keep="first")
    return key_cols, mask


def detect_range_violations(df: pd.DataFrame) -> tuple[pd.Series, list[str]]:
    mask = pd.Series(False, index=df.index)
    notes: list[str] = []

    if "Min Value" in df.columns and "Max Value" in df.columns:
        bad = df["Min Value"] > df["Max Value"]
        if bad.any():
            notes.append(f"{int(bad.sum())} row(s) where Min Value exceeds Max Value")
            mask |= bad

    if "Actual Departure Time CET" in df.columns and "Actual Arrival Time CET" in df.columns:
        dep = pd.to_datetime(df["Actual Departure Time CET"], errors="coerce")
        arr = pd.to_datetime(df["Actual Arrival Time CET"], errors="coerce")
        bad = (arr < dep) & dep.notna() & arr.notna()
        if bad.any():
            notes.append(f"{int(bad.sum())} row(s) where the arrival time is before the departure time")
            mask |= bad

    for c in df.columns:
        if re.search(r"(hours|days)\s*\)?\s*$", c, re.I) and pd.api.types.is_numeric_dtype(df[c]):
            bad = df[c] < 0
            if bad.any():
                notes.append(f"{int(bad.sum())} row(s) with a negative value in '{c}'")
                mask |= bad

    return mask, notes


def _measurement_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if _is_measurement_col(c) and pd.api.types.is_numeric_dtype(df[c])]


def detect_outlier_mask_for_column(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
        return pd.Series(False, index=df.index)
    series = df[col].dropna()
    if series.empty:
        return pd.Series(False, index=df.index)
    q1, q3 = series.quantile(0.25), series.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return pd.Series(False, index=df.index)
    lower, upper = q1 - OUTLIER_IQR_MULTIPLIER * iqr, q3 + OUTLIER_IQR_MULTIPLIER * iqr
    return (df[col] < lower) | (df[col] > upper)


def detect_outlier_columns(df: pd.DataFrame) -> list[tuple[str, int]]:
    """Which measurement columns have outliers, and how many rows each."""
    per_col: list[tuple[str, int]] = []
    for c in _measurement_columns(df):
        mask = detect_outlier_mask_for_column(df, c)
        if mask.any():
            per_col.append((c, int(mask.sum())))
    per_col.sort(key=lambda x: -x[1])
    return per_col


def detect_missing_identifier_columns(df: pd.DataFrame, id_col: str | None) -> list[tuple[str, int]]:
    """Which identifying columns have missing values, and how many rows each."""
    check_cols = ([id_col] if id_col else []) + [c for c in CORE_IDENTITY_COLS if c in df.columns]
    per_col: list[tuple[str, int]] = []
    for c in check_cols:
        n = int(df[c].isna().sum())
        if n > 0:
            per_col.append((c, n))
    return per_col


# ------------------------------------------------------------- run_audit --

def run_audit(df: pd.DataFrame) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    empty_cols = detect_fully_empty_columns(df)
    if empty_cols:
        issues.append(AuditIssue(
            id=_new_id(),
            category="fully_empty_columns",
            severity="warning",
            title="Columns with no data at all",
            description=(
                f"{len(empty_cols)} column(s) contain zero non-null values across all "
                f"{len(df)} rows. These look like unused fields in the export template "
                f"rather than a parsing problem. Pick which ones to drop below."
            ),
            affected_row_count=len(empty_cols),
            selectable_items=empty_cols,
            requires_decision=True,
            options=[
                IssueOption(id="drop_selected", label="Drop selected columns"),
                IssueOption(id="keep", label="Keep all"),
            ],
        ))

    high_null = detect_high_null_columns(df, empty_cols)
    if not high_null.empty:
        cols = list(high_null.index)
        listing = ", ".join(f"{c} ({v:.0f}%)" for c, v in high_null.items())
        issues.append(AuditIssue(
            id=_new_id(),
            category="high_null_columns",
            severity="info",
            title="Columns that are mostly empty",
            description=(
                f"{len(cols)} column(s) are at least {HIGH_NULL_THRESHOLD_PCT:.0f}% missing "
                f"values: {listing}. Not necessarily a problem, but usually not worth keeping "
                f"around for analysis either -- pick which ones to drop below."
            ),
            affected_row_count=len(cols),
            selectable_items=cols,
            requires_decision=True,
            options=[
                IssueOption(id="drop_selected", label="Drop selected columns"),
                IssueOption(id="keep", label="Keep all"),
            ],
        ))

    constant_cols = detect_constant_columns(df)
    if constant_cols:
        samples = {c: df[c].dropna().iloc[0] for c in constant_cols}
        listing = ", ".join(f"{c} = '{v}'" for c, v in samples.items())
        issues.append(AuditIssue(
            id=_new_id(),
            category="constant_value_columns",
            severity="info",
            title="Columns with only one distinct value",
            description=(
                f"{len(constant_cols)} column(s) hold the same single value in every row that "
                f"has data: {listing}. These carry no information for analysis, and an "
                f"unexpectedly uniform value (e.g. a date-like or ID-like field) can also be a "
                f"sign of an export bug -- pick which ones to drop below."
            ),
            affected_row_count=len(constant_cols),
            selectable_items=constant_cols,
            requires_decision=True,
            options=[
                IssueOption(id="drop_selected", label="Drop selected columns"),
                IssueOption(id="keep", label="Keep all"),
            ],
        ))

    exact_dup_mask = detect_exact_duplicates(df)
    if exact_dup_mask.any():
        n = int(exact_dup_mask.sum())
        issues.append(AuditIssue(
            id=_new_id(),
            category="exact_duplicate_rows",
            severity="warning",
            title="Exact duplicate rows",
            description=(
                f"{n} row(s) are byte-for-byte duplicates of another row in the file "
                f"(same values in every column)."
            ),
            affected_row_count=n,
            sample=_sample(df, exact_dup_mask),
            requires_decision=True,
            options=[
                IssueOption(id="remove_duplicates", label="Remove the duplicate rows"),
                IssueOption(id="keep", label="Keep them as-is"),
            ],
        ))

    key_dup = detect_key_duplicates(df)
    if key_dup:
        key_cols, key_mask = key_dup
        if key_mask.any() and not key_mask.equals(exact_dup_mask):
            n = int(key_mask.sum())
            issues.append(AuditIssue(
                id=_new_id(),
                category="key_duplicate_rows",
                severity="warning",
                title="Repeated entries for the same record",
                description=(
                    f"{n} row(s) share the same {' + '.join(key_cols)} as an earlier row "
                    f"but differ elsewhere -- this can happen when a trip or sensor reading "
                    f"gets exported more than once."
                ),
                affected_row_count=n,
                sample=_sample(df, key_mask),
                requires_decision=True,
                options=[
                    IssueOption(id="remove_duplicates", label="Remove the repeated rows"),
                    IssueOption(id="keep", label="Keep them as-is"),
                ],
            ))

    range_mask, range_notes = detect_range_violations(df)
    if range_mask.any():
        n = int(range_mask.sum())
        issues.append(AuditIssue(
            id=_new_id(),
            category="range_violations",
            severity="critical",
            title="Logically inconsistent values",
            description=(
                f"{n} row(s) fail basic sanity checks: " + "; ".join(range_notes) + "."
            ),
            affected_row_count=n,
            sample=_sample(df, range_mask),
            requires_decision=True,
            options=[
                IssueOption(id="remove_affected_rows", label="Remove these rows"),
                IssueOption(id="keep", label="Keep them as-is"),
            ],
        ))

    for col, n in detect_outlier_columns(df):
        mask = detect_outlier_mask_for_column(df, col)
        issues.append(AuditIssue(
            id=_new_id(),
            category=f"statistical_outliers{NS}{col}",
            severity="warning",
            title=f"Statistical outliers in '{col}'",
            description=(
                f"{n} row(s) fall far outside the typical range (beyond "
                f"{OUTLIER_IQR_MULTIPLIER:.0f}x the interquartile range) for '{col}'. Worth a "
                f"second look before these feed into KPI calculations."
            ),
            affected_row_count=n,
            sample=_sample(df, mask),
            requires_decision=True,
            options=[
                IssueOption(id="remove_affected_rows", label="Remove the outlier rows"),
                IssueOption(id="keep", label="Keep them as-is"),
            ],
        ))

    id_col = detect_id_column(df)
    for col, n in detect_missing_identifier_columns(df, id_col):
        mask = df[col].isna()
        issues.append(AuditIssue(
            id=_new_id(),
            category=f"missing_identifier{NS}{col}",
            severity="critical" if col == id_col else "warning",
            title=f"Rows missing '{col}'",
            description=(
                f"{n} row(s) have no value in '{col}'. These rows are hard to trace back to a "
                f"specific trip or product."
            ),
            affected_row_count=n,
            sample=_sample(df, mask),
            requires_decision=True,
            options=[
                IssueOption(id="drop_rows", label="Remove these rows"),
                IssueOption(id="keep", label="Keep them as-is"),
            ],
        ))

    return issues


# ---------------------------------------------------------- apply_decision --

def apply_decision(
    df: pd.DataFrame, issue: AuditIssue, decision_id: str, selected_items: list[str] | None = None
) -> tuple[pd.DataFrame, str]:
    """Re-detects the issue's target rows/columns fresh against the current
    working dataframe and applies the chosen decision. Returns (new_df, resolution_text)."""
    if decision_id == "keep":
        return df, "Kept as-is."

    category = issue.category

    if decision_id == "drop_selected":
        if not selected_items:
            raise ValueError("Select at least one column to drop.")
        if category == "fully_empty_columns":
            valid = set(detect_fully_empty_columns(df))
        elif category == "high_null_columns":
            valid = set(detect_high_null_columns(df, detect_fully_empty_columns(df)).index)
        elif category == "constant_value_columns":
            valid = set(detect_constant_columns(df))
        else:
            raise ValueError(f"Category '{category}' does not support drop_selected.")
        to_drop = [c for c in selected_items if c in valid and c in df.columns]
        if not to_drop:
            return df, "None of the selected columns were found anymore -- nothing changed."
        return df.drop(columns=to_drop), f"Dropped {len(to_drop)} column(s): {', '.join(to_drop)}."

    if category == "exact_duplicate_rows" and decision_id == "remove_duplicates":
        mask = detect_exact_duplicates(df)
        n = int(mask.sum())
        return df[~mask].reset_index(drop=True), f"Removed {n} exact duplicate row(s)."

    if category == "key_duplicate_rows" and decision_id == "remove_duplicates":
        key_dup = detect_key_duplicates(df)
        if not key_dup:
            return df, "No matching duplicate key found anymore -- nothing to remove."
        _, mask = key_dup
        n = int(mask.sum())
        return df[~mask].reset_index(drop=True), f"Removed {n} repeated row(s)."

    if category == "range_violations" and decision_id == "remove_affected_rows":
        mask, _ = detect_range_violations(df)
        n = int(mask.sum())
        return df[~mask].reset_index(drop=True), f"Removed {n} row(s) with inconsistent values."

    if category.startswith(f"statistical_outliers{NS}") and decision_id == "remove_affected_rows":
        col = category.split(NS, 1)[1]
        mask = detect_outlier_mask_for_column(df, col)
        n = int(mask.sum())
        return df[~mask].reset_index(drop=True), f"Removed {n} outlier row(s) from '{col}'."

    if category.startswith(f"missing_identifier{NS}") and decision_id == "drop_rows":
        col = category.split(NS, 1)[1]
        mask = df[col].isna() if col in df.columns else pd.Series(False, index=df.index)
        n = int(mask.sum())
        return df[~mask].reset_index(drop=True), f"Removed {n} row(s) missing '{col}'."

    raise ValueError(f"Unknown decision '{decision_id}' for category '{category}'")
