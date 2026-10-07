"""Feature engineering, driven entirely by the Feature Agent (see
feature_agent.py). Every repository entry -- predefined (from the Customer
KPI Profile), planner-approved, custom, or AI-suggested -- goes through the
same think -> write code -> execute -> validate loop, regardless of how it
was authored. There is no deterministic per-type shortcut: correctness and
plausibility come from the agent's own validation step, not from trusting a
structured spec at face value.

Every feature is computed against the dataframe passed in by the caller,
which is always the CURRENT audited session dataframe (see routers/audit.py)
-- this module never reads the original uploaded file. If a feature's source
column was removed during the audit's HITL review, that's caught by the
agent (it can only reference columns actually present) rather than by a
template-level presence check.
"""
import pandas as pd

from app.schemas import FeatureResult
from app.services.common import ai_code_executor
from app.services.features import feature_agent, feature_cache

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


def _is_boolean_like(series: pd.Series) -> bool:
    """A True/False column. It is a category (how many True, how many False), not a number: an "average" of
    0.7 for a yes/no flag means nothing next to a count of each."""
    values = series.dropna()
    if values.empty:
        return False
    if pd.api.types.is_bool_dtype(values):
        return True
    return set(values.astype(str).unique()) <= {"True", "False"}


def _is_numeric_like(series: pd.Series) -> bool:
    if _is_boolean_like(series):
        return False
    return pd.to_numeric(series, errors="coerce").notna().sum() >= max(1, int(series.notna().sum() * 0.8))


def _compute_with_cache(session_id: str, entry: dict, df: pd.DataFrame) -> feature_agent.FeatureComputation:
    """Replays a previously-validated computation for this entry if one's
    cached (see feature_cache.py) -- recomputing the whole approved set on
    every repository change would otherwise re-run Think/Code/Validate for
    entries that already succeeded, and code generation's sampling
    variance means a feature that validated fine once could occasionally
    fail on a later, unrelated recompute. A cache-replay that itself fails
    (e.g. a column it used got dropped since) invalidates the cache and
    falls through to a fresh computation rather than surfacing a stale
    error."""
    cached = feature_cache.get(session_id, entry)
    if cached:
        try:
            values = ai_code_executor.run_generated_code(cached["generated_code"], df)
            return feature_agent.FeatureComputation(
                values=values,
                plan_text=cached["plan_text"],
                generated_code=cached["generated_code"],
                validation_note="Reused a previously validated computation.",
                error=None,
            )
        except Exception:
            feature_cache.invalidate(session_id, entry["id"])

    return feature_agent.compute_feature(entry, df)


def apply_features(session_id: str, df: pd.DataFrame, entries: list[dict]) -> tuple[pd.DataFrame, list[FeatureResult], list[str]]:
    """Returns (df with feature columns appended, computed feature results,
    notes explaining any features that were skipped). `entries` is the
    session's approved feature_repository.json entries (see
    feature_repository.get_approved_entries)."""
    working = df.copy()
    results: list[FeatureResult] = []
    skipped_notes: list[str] = []

    for entry in entries:
        computation = _compute_with_cache(session_id, entry, working)

        if computation.values is None:
            skipped_notes.append(f"{entry['name']}: {computation.error}")
            continue

        feature_cache.set(session_id, entry, computation.plan_text, computation.generated_code)

        output_col = entry["output_column"]
        working[output_col] = computation.values
        non_null = int(computation.values.notna().sum())
        numeric = _is_numeric_like(computation.values)

        results.append(FeatureResult(
            id=entry["id"],
            name=entry["name"],
            description=entry["description"],
            output_column=output_col,
            non_null_count=non_null,
            null_count=len(computation.values) - non_null,
            distribution={} if numeric else _distribution(computation.values),
            stats=_numeric_stats(computation.values) if numeric else {},
            generated_code=computation.generated_code,
            source=entry["source"],
            plan=computation.plan_text,
            validation_note=computation.validation_note,
        ))

    return working, results, skipped_notes
