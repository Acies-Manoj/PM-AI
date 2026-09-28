"""Trip-level anomaly detection over the aggregated cold-chain export (one row
per trip -- Mean/Min/Max/Std/MKT Value_Temperature, the configured Limit
Low/Ideal/High_Temperature, Value Minutes Above/Below _Temperature, and the
Light-channel equivalents; see Merged_Temperature_Light_2024-2025.xlsx).

Two layers:
  1. `compute_lane_duration_outliers` -- an Origin->Destination "lane"-level
     Tukey-fence outlier check on transit duration, with a peer-group
     shrinkage fallback for thin lanes (<=10 trips) so a 2-trip lane with
     Q1==Q3 can't fence itself to a single point.
  2. `compute_flags` -- the 9 trip-level rules (too warm/cold on average,
     non-conforming transport, high variability, severe heat/cold excursion
     magnitude, MKT confirmation, light-correlated excursion, missing
     product), each described inline below.

`generate_rca` sits on top of both: given one already-flagged trip, it scores
a fixed set of root-cause hypotheses (door-opening, equipment failure,
sensor glitch, mislogged timestamp, compliance gap, ...) against which flags
fired together, and returns the top N ranked by evidence weight.

This is a standalone module -- no FastAPI/pydantic dependency -- so it can be
run directly against the aggregated export:

    python -m app.services.anomaly_detection "path/to/Merged_Temperature_Light.xlsx"
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# -- column names (after _normalize_columns collapses embedded newlines) ----
COL_ORIGIN = "Origin"
COL_DESTINATION = "Destination"
COL_PRODUCT = "Product"
COL_DURATION = "Segment Length (Days)"

COL_MEAN_TEMP = "Mean Value_Temperature"
COL_MIN_TEMP = "Min Value_Temperature"
COL_MAX_TEMP = "Max Value_Temperature"
COL_STD_TEMP = "Standard Deviation_Temperature"
COL_MKT_TEMP = "MKT Statistics Value_Temperature"
COL_LIMIT_LOW_TEMP = "Limit Low_Temperature"
COL_LIMIT_HIGH_TEMP = "Limit High_Temperature"
# Not used by any flag rule below (only Low/High bound the trip-level checks)
# -- kept only so callers can display the full configured range alongside a
# flag, e.g. the Raw Data Explorer's mean-temp-by-product chart.
COL_LIMIT_IDEAL_TEMP = "Limit Ideal_Temperature"
COL_MINUTES_ABOVE_HIGH_TEMP = "Value Minutes Above High_Temperature"
COL_MINUTES_BELOW_LOW_TEMP = "Value Minutes Below Low_Temperature"
COL_MAX_LIGHT = "Max Value_Light"

GROUP_COLS = (COL_ORIGIN, COL_DESTINATION, COL_PRODUCT)
PERCENTILE = 0.95

# Lane duration-outlier thresholds (see compute_lane_duration_outliers).
LANE_DIRECT_MIN_N = 10  # lanes with MORE trips than this use their own fence outright
PEER_GROUP_MIN_N = 10  # peer group must have more trips than this to be usable
IQR_MULTIPLIER = 1.5

FLAG_COLUMNS = [
    "flag_1_too_warm_avg",
    "flag_2_too_cold_avg",
    "flag_3_non_conforming_transport",
    "flag_4_high_variability",
    "flag_5_severe_heat_excursion",
    "flag_6_severe_cold_excursion",
    "flag_7_mkt_confirmation",
    "flag_8_light_correlated_excursion",
    "flag_9_missing_product",
]


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Same rule as backend/app/services/excel_parser.py: collapse embedded
    newlines/repeated whitespace in header cells (e.g. "Segment Length
    \\n(Days)") into a single space, so this module works whether it's fed a
    raw pd.read_excel() frame or one already normalized upstream."""
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df


# -----------------------------------------------------------------------
# 1. Lane-level transit-duration outliers
# -----------------------------------------------------------------------


def _tukey_fence(values: pd.Series) -> tuple[float, float]:
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    return q1 - IQR_MULTIPLIER * iqr, q3 + IQR_MULTIPLIER * iqr


def compute_lane_duration_summary(
    df: pd.DataFrame,
    duration_col: str = COL_DURATION,
    origin_col: str = COL_ORIGIN,
    destination_col: str = COL_DESTINATION,
) -> pd.DataFrame:
    """The lane-level reference table itself (Origin, Destination, N, Q1,
    Q3, Lower Fence, Upper Fence) -- the Audit page's "Segment Days" tab.
    One row per (Origin, Destination) lane with at least one usable
    duration value, each lane's own Tukey fence (same formula as
    `compute_lane_duration_outliers`'s "Own-Lane Fence" case) regardless of
    N, since this table is the reference itself rather than a per-trip flag
    -- a thin lane's fence is still worth showing, just wide/uncertain."""
    df = _normalize_columns(df)
    duration = pd.to_numeric(df[duration_col], errors="coerce")
    working = pd.DataFrame({origin_col: df[origin_col], destination_col: df[destination_col], "_duration": duration})

    rows = []
    for (origin, destination), group in working.groupby([origin_col, destination_col], dropna=False):
        values = group["_duration"].dropna()
        n = len(values)
        if n == 0:
            continue
        if n == 1:
            q1 = q3 = lower = upper = float(values.iloc[0])
        else:
            q1, q3 = float(values.quantile(0.25)), float(values.quantile(0.75))
            lower, upper = _tukey_fence(values)
        rows.append({
            "origin": origin,
            "destination": destination,
            "n": n,
            "q1_days": round(q1, 2),
            "q3_days": round(q3, 2),
            "lower_fence_days": round(float(lower), 2),
            "upper_fence_days": round(float(upper), 2),
        })

    columns = ["origin", "destination", "n", "q1_days", "q3_days", "lower_fence_days", "upper_fence_days"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values(["origin", "destination"]).reset_index(drop=True)


def compute_lane_duration_outliers(
    df: pd.DataFrame,
    duration_col: str = COL_DURATION,
    origin_col: str = COL_ORIGIN,
    destination_col: str = COL_DESTINATION,
) -> pd.DataFrame:
    """Per-lane (Origin -> Destination) Tukey fence on `duration_col`.

    - Lanes with > LANE_DIRECT_MIN_N trips: fence computed directly from the
      lane's own Q1/Q3 -- stable enough at this sample size (already the
      case for 45 lanes in 2024-2025 and 8 lanes in Q1-Q2 2026).
    - Thinner lanes: NOT fenced on their own (a 2-trip lane can have
      Q1 == Q3, i.e. IQR == 0, which would flag any non-identical trip).
      Instead borrow a fence from a peer group and shrink toward the lane's
      own quartiles as its own N grows (alpha = min(N / LANE_DIRECT_MIN_N, 1)).

      True "distance-band" peer grouping needs geocoded lane distance, which
      this export doesn't carry -- as a documented proxy, the peer group here
      is every trip sharing the same Destination (a reasonable stand-in: the
      last-mile leg, and often most of the corridor, is shared). Swap
      `_peer_group_mask` for a real distance-band lookup if/when geocoding
      is wired in.
    - If even that peer group has <= PEER_GROUP_MIN_N trips, no fence is
      guessed: the lane is marked "Insufficient History" for manual review.
    """
    duration = pd.to_numeric(df[duration_col], errors="coerce")
    lane = list(zip(df[origin_col].fillna("(blank)"), df[destination_col].fillna("(blank)")))
    lane_series = pd.Series(lane, index=df.index)

    is_outlier = pd.Series(False, index=df.index)
    status = pd.Series("Insufficient History", index=df.index)
    lower_fence = pd.Series(np.nan, index=df.index)
    upper_fence = pd.Series(np.nan, index=df.index)

    for lane_key, idx in lane_series.groupby(lane_series).groups.items():
        values = duration.loc[idx].dropna()
        n = len(values)
        if n == 0:
            continue  # no usable duration at all for this lane -> stays "Insufficient History"

        if n > LANE_DIRECT_MIN_N:
            lower, upper = _tukey_fence(values)
            lane_status = "Own-Lane Fence"
        else:
            destination = lane_key[1]
            peer_values = duration.loc[df[destination_col] == destination].dropna()
            peer_n = len(peer_values)
            if peer_n <= PEER_GROUP_MIN_N:
                continue  # stays "Insufficient History" -- route to manual review, don't guess
            peer_lower, peer_upper = _tukey_fence(peer_values)
            lane_lower, lane_upper = (values.iloc[0], values.iloc[0]) if n == 1 else _tukey_fence(values)
            alpha = min(n / LANE_DIRECT_MIN_N, 1.0)
            lower = alpha * lane_lower + (1 - alpha) * peer_lower
            upper = alpha * lane_upper + (1 - alpha) * peer_upper
            lane_status = f"Peer-Shrunk Fence (own N={n}, peer N={peer_n}, alpha={alpha:.2f})"

        lower_fence.loc[idx] = lower
        upper_fence.loc[idx] = upper
        status.loc[idx] = lane_status
        in_range = duration.loc[idx].between(lower, upper)
        is_outlier.loc[idx] = duration.loc[idx].notna() & ~in_range

    return pd.DataFrame(
        {
            "duration_outlier": is_outlier,
            "duration_outlier_status": status,
            "duration_lower_fence_days": lower_fence,
            "duration_upper_fence_days": upper_fence,
        },
        index=df.index,
    )


# -----------------------------------------------------------------------
# 2. Trip-level flags
# -----------------------------------------------------------------------


def _nonzero_percentile(series: pd.Series, percentile: float) -> float:
    nonzero = series[series > 0]
    return nonzero.quantile(percentile) if len(nonzero) else np.nan


def compute_flags(df: pd.DataFrame, group_cols: tuple[str, ...] = GROUP_COLS, percentile: float = PERCENTILE) -> pd.DataFrame:
    """The 9 trip-level rules. Each is evaluated against the trip's OWN
    configured limits (never a generic product-category range) except the
    four percentile-based ones, which compare within the trip's own
    Origin/Destination/Product group so a naturally-more-variable lane
    doesn't get flagged against a stricter lane's baseline."""
    mean_temp = pd.to_numeric(df[COL_MEAN_TEMP], errors="coerce")
    min_temp = pd.to_numeric(df[COL_MIN_TEMP], errors="coerce")
    max_temp = pd.to_numeric(df[COL_MAX_TEMP], errors="coerce")
    std_temp = pd.to_numeric(df[COL_STD_TEMP], errors="coerce")
    mkt_temp = pd.to_numeric(df[COL_MKT_TEMP], errors="coerce")
    limit_low = pd.to_numeric(df[COL_LIMIT_LOW_TEMP], errors="coerce")
    limit_high = pd.to_numeric(df[COL_LIMIT_HIGH_TEMP], errors="coerce")
    minutes_above_high = pd.to_numeric(df[COL_MINUTES_ABOVE_HIGH_TEMP], errors="coerce")
    minutes_below_low = pd.to_numeric(df[COL_MINUTES_BELOW_LOW_TEMP], errors="coerce")
    max_light = pd.to_numeric(df[COL_MAX_LIGHT], errors="coerce")

    # dropna=False: a trip missing Product (flag 9's own trigger) still gets
    # grouped -- with the other trips also missing Product -- rather than
    # being silently excluded from every percentile-based flag.
    grouped = df.groupby(list(group_cols), dropna=False)

    std_p95 = grouped[COL_STD_TEMP].transform(lambda s: pd.to_numeric(s, errors="coerce").quantile(percentile))
    heat_minutes_p95 = grouped[COL_MINUTES_ABOVE_HIGH_TEMP].transform(
        lambda s: _nonzero_percentile(pd.to_numeric(s, errors="coerce"), percentile)
    )
    cold_minutes_p95 = grouped[COL_MINUTES_BELOW_LOW_TEMP].transform(
        lambda s: _nonzero_percentile(pd.to_numeric(s, errors="coerce"), percentile)
    )
    light_p95 = grouped[COL_MAX_LIGHT].transform(lambda s: pd.to_numeric(s, errors="coerce").quantile(percentile))

    heat_side = min_temp > limit_high
    cold_side = max_temp < limit_low

    flags = pd.DataFrame(index=df.index)
    flags["flag_1_too_warm_avg"] = mean_temp > limit_high
    flags["flag_2_too_cold_avg"] = mean_temp < limit_low
    flags["flag_3_non_conforming_transport"] = heat_side | cold_side
    flags["flag_3_side"] = np.select([heat_side, cold_side], ["heat", "cold"], default=None)
    flags["flag_4_high_variability"] = std_temp > std_p95
    flags["flag_5_severe_heat_excursion"] = minutes_above_high > heat_minutes_p95
    flags["flag_6_severe_cold_excursion"] = minutes_below_low > cold_minutes_p95
    flags["flag_7_mkt_confirmation"] = mkt_temp > limit_high
    flags["flag_8_light_correlated_excursion"] = max_light > light_p95
    flags["flag_9_missing_product"] = df[COL_PRODUCT].isna() | (df[COL_PRODUCT].astype(str).str.strip() == "")

    for col in FLAG_COLUMNS:
        flags[col] = flags[col].fillna(False)

    flags["flag_count"] = flags[FLAG_COLUMNS].sum(axis=1)
    return flags


# -----------------------------------------------------------------------
# 1b. Adapter for the "one row per trip, per sensor channel" export shape
# -----------------------------------------------------------------------
# Some real exports (e.g. a "Tabular Shipment Data" download) carry one row
# per (trip, sensor channel) -- a Temperature row and a separate Light row
# for the same Serial Number/Trip ID, sharing generic column names (Mean
# Value, Limit Low, ...) distinguished only by a "Sensor Type" column --
# rather than the one-row-per-trip, _Temperature/_Light-suffixed shape the
# rest of this module expects (see the module docstring). These two
# functions detect that shape and reshape it into the expected one, so
# `run_anomaly_detection` below can be reused unchanged either way.

SENSOR_TYPE_COL = "Sensor Type"
_TEMPERATURE_METRIC_COLS = [
    "Limit Low", "Limit Ideal", "Limit High", "Mean Value", "Standard Deviation",
    "Min Value", "Max Value", "MKT Statistics Value",
    "Value Minutes Below Low", "Value Minutes Above High",
]
_LIGHT_METRIC_COLS = ["Max Value"]


def is_long_sensor_format(df: pd.DataFrame) -> bool:
    """True if `df` has one row per (trip, sensor channel) -- see
    `widen_by_sensor_type` -- rather than one row per trip."""
    if SENSOR_TYPE_COL not in df.columns:
        return False
    values = set(df[SENSOR_TYPE_COL].dropna().astype(str).str.strip().unique())
    return bool(values) and values.issubset({"Temperature", "Light"})


def widen_by_sensor_type(df: pd.DataFrame, serial_col: str, trip_col: str) -> pd.DataFrame:
    """Pivots a long (trip, sensor channel) table into one row per trip:
    the Temperature channel's metrics suffixed `_Temperature`, the Light
    channel's `_Light`. Trip-level columns that aren't sensor metrics
    (Product, Origin, Destination, Segment Length (Days), ...) are shared
    by both channel rows already -- an outer merge on (serial, trip) plus a
    coalesce handles a trip that's missing one channel's row entirely
    without dropping it."""
    df = _normalize_columns(df)
    sensor = df[SENSOR_TYPE_COL].astype(str).str.strip()

    temp = df[sensor == "Temperature"].rename(
        columns={c: f"{c}_Temperature" for c in _TEMPERATURE_METRIC_COLS if c in df.columns}
    )
    light = df[sensor == "Light"].rename(
        columns={c: f"{c}_Light" for c in _LIGHT_METRIC_COLS if c in df.columns}
    )

    wide = pd.merge(temp, light, on=[serial_col, trip_col], how="outer", suffixes=("", "_light_dup"))
    # Every OTHER shared trip-level column (Product, Origin, ...) now exists
    # under the same name on both sides -- pandas suffixes the right (Light)
    # copy `_light_dup`. Prefer the Temperature row's value, falling back to
    # the Light row's only for a trip with no Temperature row at all.
    for col in list(wide.columns):
        dup = f"{col}_light_dup"
        if dup in wide.columns:
            wide[col] = wide[col].where(wide[col].notna(), wide[dup])
            wide = wide.drop(columns=[dup])
    return wide


def run_anomaly_detection(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizes headers, then runs both layers and returns the input
    frame with the duration-outlier columns and all flag_* columns appended."""
    df = _normalize_columns(df)
    duration = compute_lane_duration_outliers(df)
    flags = compute_flags(df)
    return pd.concat([df, duration, flags], axis=1)


# -----------------------------------------------------------------------
# 3. Root-cause hypothesis layer
# -----------------------------------------------------------------------

THERMAL_FLAG_COLUMNS = [
    "flag_1_too_warm_avg",
    "flag_2_too_cold_avg",
    "flag_3_non_conforming_transport",
    "flag_4_high_variability",
    "flag_5_severe_heat_excursion",
    "flag_6_severe_cold_excursion",
]


@dataclass
class RcaHypothesis:
    hypothesis: str
    score: int
    confidence: str  # "High" | "Medium" | "Low"
    rationale: list[str] = field(default_factory=list)


def _confidence_band(score: int) -> str:
    if score >= 5:
        return "High"
    if score >= 3:
        return "Medium"
    return "Low"


def generate_rca(trip: pd.Series, top_n: int = 5) -> list[RcaHypothesis]:
    """Scores a fixed set of root-cause hypotheses against whichever flags
    fired together on this one trip (a row from run_anomaly_detection's
    output, or any dict-like with the same flag_*/duration_outlier* keys),
    and returns the top `top_n` ranked by evidence weight. Each hypothesis
    accumulates points from every matching rule below; a trip with no signal
    at all still gets the baseline "likely benign variability" hypothesis so
    the caller never sees an empty list."""

    def flagged(col: str) -> bool:
        return bool(trip.get(col, False))

    candidates: dict[str, list[tuple[int, str]]] = defaultdict(list)

    # -- Possible door-opening event -------------------------------------
    if flagged("flag_8_light_correlated_excursion"):
        candidates["Possible door-opening event"].append(
            (3, "Max Value_Light is an outlier vs. this lane/product's peers (Flag 8)")
        )
        if flagged("flag_1_too_warm_avg") or flagged("flag_5_severe_heat_excursion"):
            candidates["Possible door-opening event"].append(
                (2, "The light excursion coincides with a heat excursion -- consistent with a brief warm-up during an opening")
            )
        if flagged("flag_4_high_variability"):
            candidates["Possible door-opening event"].append(
                (1, "Temperature variability is elevated, consistent with a short-lived event rather than sustained failure")
            )

    # -- Refrigeration / equipment failure (heat side) --------------------
    if trip.get("flag_3_side") == "heat":
        candidates["Refrigeration/equipment failure (sustained cooling loss)"].append(
            (3, "Even the coldest reading of the trip (Min Value_Temperature) never returned into range (Flag 3, heat side)")
        )
    if flagged("flag_1_too_warm_avg"):
        candidates["Refrigeration/equipment failure (sustained cooling loss)"].append(
            (2, "Trip average temperature exceeds its own configured high limit (Flag 1)")
        )
    if flagged("flag_5_severe_heat_excursion"):
        candidates["Refrigeration/equipment failure (sustained cooling loss)"].append(
            (2, "Time-weighted heat excursion (Value Minutes Above High) is a severe outlier for this lane/product (Flag 5)")
        )
    if flagged("flag_7_mkt_confirmation"):
        candidates["Refrigeration/equipment failure (sustained cooling loss)"].append(
            (2, "Mean Kinetic Temperature also exceeds the high limit, confirming sustained (not momentary) exposure (Flag 7)")
        )

    # -- Overcooling / setpoint error (cold side) --------------------------
    if trip.get("flag_3_side") == "cold":
        candidates["Overcooling / setpoint error (cold side failure)"].append(
            (3, "Even the warmest reading of the trip (Max Value_Temperature) never returned into range (Flag 3, cold side)")
        )
    if flagged("flag_2_too_cold_avg"):
        candidates["Overcooling / setpoint error (cold side failure)"].append(
            (2, "Trip average temperature is below its own configured low limit (Flag 2)")
        )
    if flagged("flag_6_severe_cold_excursion"):
        candidates["Overcooling / setpoint error (cold side failure)"].append(
            (2, "Time-weighted cold excursion (Value Minutes Below Low) is a severe outlier for this lane/product (Flag 6)")
        )

    # -- Sensor malfunction / erroneous reading ----------------------------
    if trip.get("flag_3_side") == "heat" and not flagged("flag_7_mkt_confirmation"):
        candidates["Sensor malfunction / erroneous reading"].append(
            (2, "Instantaneous extremes claim the trip never returned in range, but the weighted MKT stat disagrees "
                "(Flag 3 without Flag 7) -- a common sensor-noise signature")
        )
    if flagged("flag_4_high_variability") and not flagged("flag_1_too_warm_avg") and not flagged("flag_2_too_cold_avg"):
        candidates["Sensor malfunction / erroneous reading"].append(
            (2, "Variability is an outlier (Flag 4) even though the trip average stays within limits -- consistent with "
                "spiky sensor noise rather than a real thermal event")
        )

    # -- Trip metadata error (mislogged departure/arrival timestamp) ------
    if trip.get("duration_outlier"):
        candidates["Trip metadata error (mislogged departure/arrival timestamp)"].append(
            (3, f"Segment duration is a statistical outlier for its lane ({trip.get('duration_outlier_status', 'flagged')})")
        )
        if not any(flagged(c) for c in THERMAL_FLAG_COLUMNS):
            candidates["Trip metadata error (mislogged departure/arrival timestamp)"].append(
                (2, "No corroborating thermal excursion -- an isolated duration anomaly points to a logistics "
                    "data-entry error rather than a cold-chain event")
            )

    # -- Compliance / metadata gap (non-thermal) ---------------------------
    if flagged("flag_9_missing_product"):
        candidates["Missing metadata (compliance gap, not a thermal event)"].append(
            (3, "Product field is blank (Flag 9) -- a data-completeness issue, unrelated to sensor readings")
        )

    # -- Baseline fallback so the result is never empty --------------------
    candidates["Likely benign variability (no strong root-cause signal)"].append(
        (1, "Low-confidence baseline -- included when no stronger evidence is present")
    )

    results = [
        RcaHypothesis(hypothesis=name, score=sum(w for w, _ in items), confidence=_confidence_band(sum(w for w, _ in items)),
                      rationale=[reason for _, reason in items])
        for name, items in candidates.items()
    ]
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


# -----------------------------------------------------------------------
# CLI: run against a real aggregated export and print a summary
# -----------------------------------------------------------------------

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else str(
        __import__("pathlib").Path.home() / "Downloads" / "Merged_Temperature_Light_2024-2025.xlsx"
    )
    print(f"Loading {path} ...")
    raw = pd.read_excel(path)
    result = run_anomaly_detection(raw)

    print(f"\n{len(result)} trips scored.\n")
    print("Flag counts:")
    for col in FLAG_COLUMNS:
        print(f"  {col}: {int(result[col].sum())}")
    print(f"  duration_outlier: {int(result['duration_outlier'].sum())}")
    print(f"  (Insufficient History lanes: {int((result['duration_outlier_status'] == 'Insufficient History').sum())} trips)")

    result["_total_flags"] = result[FLAG_COLUMNS].sum(axis=1) + result["duration_outlier"].astype(int)
    top_anomalies = result.sort_values("_total_flags", ascending=False).head(5)

    print("\nTop 5 most-flagged trips -- RCA hypotheses:\n")
    for _, trip in top_anomalies.iterrows():
        label = f"Trip {trip.get('Trip ID', '?')} ({trip.get('Serial Number', '?')})"
        print(f"=== {label} -- {int(trip['_total_flags'])} signal(s) ===")
        for h in generate_rca(trip):
            print(f"  [{h.confidence:>6} | score {h.score}] {h.hypothesis}")
            for reason in h.rationale:
                print(f"      - {reason}")
        print()
