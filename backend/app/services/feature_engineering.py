"""
Deterministic feature engineering. Feature specs (including any lookup
mappings, e.g. the COO table) come entirely from whatever "Customer KPI
Profile" JSON the user uploaded (see feature_definitions_store.py) -- there
is no bundled backend default definitions file. Adding a new feature of an
already-supported type ("lookup", "extract_month", "ratio") only requires
editing/re-uploading that JSON.

Every feature is computed against the dataframe passed in by the caller,
which is always the CURRENT audited session dataframe (see routers/audit.py)
-- this module never reads the original uploaded file. If a feature's source
column was removed during the audit's HITL review, that feature is skipped
(and reported as skipped) rather than silently recomputed from data the user
already chose to drop.

No LLM involved -- lookup/date-extraction/ratio arithmetic needs to be
reliable, not a plausible-sounding guess.
"""
import pandas as pd

from app.schemas import FeatureResult

TOP_N_DISTRIBUTION = 12


def _numeric_stats(series: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {}
    return {
        "mean": round(float(clean.mean()), 1),
        "median": round(float(clean.median()), 1),
        "min": round(float(clean.min()), 1),
        "max": round(float(clean.max()), 1),
    }


def _distribution(series: pd.Series, top_n: int = TOP_N_DISTRIBUTION) -> dict[str, int]:
    counts = series.dropna().astype(str).value_counts().head(top_n)
    return {str(k): int(v) for k, v in counts.items()}


def _apply_lookup(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    source = spec["source_column"]
    if source not in df.columns:
        return None
    mapping = spec.get("mapping", {})
    default = spec.get("default_value", "Unknown")
    return df[source].map(lambda v: mapping.get(str(v).strip(), default) if pd.notna(v) else None)


def _apply_extract_month(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    candidates = [c for c in spec["source_columns"] if c in df.columns]
    if not candidates:
        return None
    combined = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for c in candidates:
        parsed = pd.to_datetime(df[c], errors="coerce")
        combined = combined.fillna(parsed)
    return combined.dt.month.astype("Int64")


def _apply_ratio(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    # require every denominator column to be present -- a partial sum would
    # silently misrepresent the ratio, which is worse than not computing it
    if set(spec["denominator_columns"]) - set(df.columns):
        return None
    if set(spec["numerator_columns"]) - set(df.columns):
        return None
    numerator = df[spec["numerator_columns"]].sum(axis=1, skipna=False)
    denominator = df[spec["denominator_columns"]].sum(axis=1, skipna=False)
    pct = (numerator / denominator) * 100
    return pct.where(denominator != 0).round(1)


def _apply_excursion_duration(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """Count segments (rows) where the mean temp exceeds the product limit."""
    col = spec.get("mean_column", "Mean Value")
    limit = spec.get("limit")
    if col not in df.columns or limit is None:
        return None
    series = pd.to_numeric(df[col], errors="coerce")
    return (series > float(limit)).astype("Int64")


def _apply_excursion_magnitude(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """How far above the limit the mean temperature is (0 if within spec)."""
    col = spec.get("mean_column", "Mean Value")
    limit = spec.get("limit")
    if col not in df.columns or limit is None:
        return None
    series = pd.to_numeric(df[col], errors="coerce")
    return (series - float(limit)).clip(lower=0).round(2)


def _apply_rate_of_change(df: pd.DataFrame, spec: dict) -> pd.Series | None:
    """Approximate rate of change: (Max Value - Min Value) / (duration or 1)."""
    val_col = spec.get("value_column", "Mean Value")
    if val_col not in df.columns:
        return None
    series = pd.to_numeric(df[val_col], errors="coerce")
    # Use Max - Min as a proxy when no time axis is available
    if "Max Value" in df.columns and "Min Value" in df.columns:
        max_v = pd.to_numeric(df["Max Value"], errors="coerce")
        min_v = pd.to_numeric(df["Min Value"], errors="coerce")
        return (max_v - min_v).round(2)
    return series.diff().abs().round(2)


_APPLIERS = {
    "lookup": _apply_lookup,
    "extract_month": _apply_extract_month,
    "ratio": _apply_ratio,
    "excursion_duration": _apply_excursion_duration,
    "excursion_magnitude": _apply_excursion_magnitude,
    "rate_of_change": _apply_rate_of_change,
}


def apply_features(df: pd.DataFrame, definitions: list[dict]) -> tuple[pd.DataFrame, list[FeatureResult], list[str]]:
    """Returns (df with feature columns appended, computed feature results,
    notes explaining any features that were skipped). `definitions` is
    whatever was uploaded to the Customer KPI Profile slot -- the caller is
    responsible for making sure that actually happened."""
    working = df.copy()
    results: list[FeatureResult] = []
    skipped_notes: list[str] = []

    for spec in definitions:
        applier = _APPLIERS.get(spec["type"])
        if applier is None:
            skipped_notes.append(f"{spec['name']}: unknown feature type '{spec['type']}'.")
            continue

        values = applier(working, spec)
        if values is None:
            skipped_notes.append(
                f"{spec['name']}: skipped -- a required source column isn't present in the "
                f"current data (likely removed during the audit review)."
            )
            continue

        output_col = spec["output_column"]
        working[output_col] = values
        non_null = int(values.notna().sum())
        summary = spec.get("summary", "distribution")

        results.append(FeatureResult(
            id=spec["id"], name=spec["name"], description=spec["description"],
            output_column=output_col, non_null_count=non_null, null_count=len(values) - non_null,
            distribution=_distribution(values) if summary == "distribution" else {},
            stats=_numeric_stats(values) if summary == "stats" else {},
        ))

    return working, results, skipped_notes
