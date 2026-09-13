"""Threshold-based excursion screening for cold-chain trip data.

Works against the aggregated (SensiWatch-style) dataframe from an audit session.
No LLM — excursion flagging is a deterministic rule: mean temperature exceeds
the per-product temperature upper limit.
"""
from __future__ import annotations

import pandas as pd

from app.schemas import FlaggedTrip, ScreeningReport

# Default temperature upper limits (°C) by product line.
# Negative limits apply to frozen products — excursion = temp ABOVE the limit.
DEFAULT_LIMITS: dict[str, float] = {
    "Fresh Produce": 7.0,
    "Fruit": 7.0,
    "Vegetable": 7.0,
    "Chilled": 4.0,
    "Dairy": 6.0,
    "Meat": 4.0,
    "Seafood": 4.0,
    "Frozen": -15.0,
    "Ice Cream": -18.0,
}


def _match_limit(product: str, thresholds: dict[str, float]) -> float | None:
    if product in thresholds:
        return thresholds[product]
    pl = product.lower()
    for key, val in thresholds.items():
        if key.lower() in pl or pl in key.lower():
            return val
    return None


def run_threshold_screening(
    session_id: str,
    df: pd.DataFrame,
    custom_thresholds: dict[str, float] | None = None,
) -> ScreeningReport:
    """Detect excursions in an aggregated trip dataframe."""
    thresholds = {**DEFAULT_LIMITS, **(custom_thresholds or {})}

    has_mean = "Mean Value" in df.columns
    has_product = "Product" in df.columns
    has_trip = "Trip ID" in df.columns
    notes: list[str] = []

    if not has_mean:
        notes.append("No 'Mean Value' column — temperature excursion check skipped.")
        return ScreeningReport(
            session_id=session_id,
            total_trips=len(df),
            flagged_count=0,
            flagged_trips=[],
            product_means={},
            screening_notes=notes,
        )

    product_means: dict[str, float] = {}
    if has_product:
        product_means = (
            df.groupby("Product")["Mean Value"]
            .apply(lambda s: round(float(pd.to_numeric(s, errors="coerce").mean()), 2))
            .dropna()
            .to_dict()
        )

    flagged: list[FlaggedTrip] = []
    for _, row in df.iterrows():
        mean_temp = pd.to_numeric(row.get("Mean Value"), errors="coerce")
        if pd.isna(mean_temp):
            continue

        product = str(row.get("Product", "Unknown")) if has_product else "Unknown"
        trip_id = str(row.get("Trip ID", "")) if has_trip else ""
        limit = _match_limit(product, thresholds)

        if limit is None:
            continue

        if float(mean_temp) <= limit:
            continue

        exceedance = round(float(mean_temp) - limit, 2)

        days_above = 0
        for col in df.columns:
            cl = col.lower()
            if "days above" in cl or "above limit" in cl or "excursion day" in cl:
                v = pd.to_numeric(row.get(col), errors="coerce")
                if not pd.isna(v):
                    days_above = int(v)
                    break

        origin = str(row["Origin"]) if "Origin" in df.columns and pd.notna(row.get("Origin")) else None
        dest = str(row["Destination"]) if "Destination" in df.columns and pd.notna(row.get("Destination")) else None

        flagged.append(FlaggedTrip(
            trip_id=trip_id,
            product=product,
            mean_temp=round(float(mean_temp), 2),
            temp_limit=limit,
            exceedance=exceedance,
            segment_days_above=days_above,
            origin=origin,
            destination=dest,
        ))

    if not flagged:
        notes.append("No temperature excursions detected against known product limits.")

    return ScreeningReport(
        session_id=session_id,
        total_trips=len(df),
        flagged_count=len(flagged),
        flagged_trips=sorted(flagged, key=lambda t: -(t.exceedance or 0)),
        product_means=product_means,
        screening_notes=notes,
    )
