"""Interactive chart filters for an analysis.

A filter is a row-level restriction on the SOURCE data applied before the
analysis computes (so "filter to Carrier = DHL" re-aggregates, rather than
hiding bars on an already-aggregated chart). The designer's chart prompt
proposes which columns are worth filtering on; this module owns everything
deterministic about them:

  - `kind_for`   picks the control from the column's real type (the LLM's
                 opinion on type is never trusted),
  - `options`    lists the values / range the UI should offer, from the
                 current data,
  - `apply`      restricts the dataframe to the PM's selections -- and only
                 on columns this analysis actually declared as filters.
"""
from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel

from app.schemas import AnalysisFilterSelection as FilterSelection
from app.services.analysis.analysis_columns import as_datetime, as_labels, as_numeric

FilterKind = Literal["categorical", "numeric_range", "date_range"]

MAX_FILTERS = 4
# A categorical filter with thousands of values (IDs, free text) isn't a
# usable control, so such columns are never offered as filters.
MAX_CATEGORICAL_VALUES = 200
# Average value length above which a text column is treated as free text.
MAX_CATEGORY_LABEL_CHARS = 60


class FilterDef(BaseModel):
    column: str
    kind: FilterKind
    reason: str = ""


def kind_for(series: pd.Series) -> FilterKind | None:
    """The filter control a column supports, or None if it isn't a useful
    filter (one value only, too many values, or long free text)."""
    distinct = series.nunique(dropna=True)
    if distinct < 2:
        return None
    if as_datetime(series) is not None:
        return "date_range"
    if as_numeric(series) is not None and distinct > 12:
        return "numeric_range"
    if distinct > MAX_CATEGORICAL_VALUES:
        return None
    if as_labels(series).str.len().mean() > MAX_CATEGORY_LABEL_CHARS:
        return None
    return "categorical"


def build_defs(candidates: list[dict], df: pd.DataFrame) -> list[FilterDef]:
    """Turns the LLM's proposed filter columns into validated FilterDefs:
    unknown columns and unusable (high-cardinality) ones are dropped."""
    available = set(df.columns.astype(str))
    defs: list[FilterDef] = []
    seen: set[str] = set()
    for c in candidates:
        column = c.get("column") if isinstance(c, dict) else None
        if not isinstance(column, str) or column not in available or column in seen:
            continue
        kind = kind_for(df[column])
        if kind is None:
            continue
        reason = c.get("reason") if isinstance(c.get("reason"), str) else ""
        defs.append(FilterDef(column=column, kind=kind, reason=reason.strip()))
        seen.add(column)
        if len(defs) == MAX_FILTERS:
            break
    return defs


def options(df: pd.DataFrame, defs: list[dict]) -> list[dict]:
    """Each filter plus what the UI should offer for it, from the current
    data. A filter whose column no longer exists is skipped."""
    out = []
    for d in defs:
        column = d.get("column")
        if column not in df.columns:
            continue
        item = {"column": column, "kind": d.get("kind"), "reason": d.get("reason", ""),
                "values": None, "min": None, "max": None, "start": None, "end": None}
        if d.get("kind") == "categorical":
            item["values"] = as_labels(df[column]).value_counts().head(MAX_CATEGORICAL_VALUES).index.tolist()
        elif d.get("kind") == "numeric_range":
            numeric = as_numeric(df[column])
            if numeric is None or numeric.dropna().empty:
                continue
            item["min"], item["max"] = float(numeric.min()), float(numeric.max())
        elif d.get("kind") == "date_range":
            dates = as_datetime(df[column])
            if dates is None or dates.dropna().empty:
                continue
            item["start"], item["end"] = dates.min().strftime("%Y-%m-%d"), dates.max().strftime("%Y-%m-%d")
        out.append(item)
    return out


def _parse_day(value: str | None) -> pd.Timestamp | None:
    """A YYYY-MM-DD bound from the UI; anything unparseable means no bound."""
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed


def apply(df: pd.DataFrame, defs: list[dict], selections: dict[str, FilterSelection] | None) -> pd.DataFrame:
    """Rows of `df` matching every selection. Selections on columns this
    analysis didn't declare as filters are ignored, not trusted."""
    if not selections:
        return df
    kinds = {d["column"]: d["kind"] for d in defs if d.get("column") in df.columns}
    mask = pd.Series(True, index=df.index)
    for column, sel in selections.items():
        kind = kinds.get(column)
        if kind is None:
            continue
        if kind == "categorical" and sel.values:
            mask &= as_labels(df[column]).isin(set(sel.values))
        elif kind == "numeric_range":
            numeric = as_numeric(df[column])
            if numeric is None:
                continue
            if sel.min is not None:
                mask &= numeric >= sel.min
            if sel.max is not None:
                mask &= numeric <= sel.max
        elif kind == "date_range":
            dates = as_datetime(df[column])
            if dates is None:
                continue
            start, end = _parse_day(sel.start), _parse_day(sel.end)
            if start is not None:
                mask &= dates >= start
            if end is not None:
                # Inclusive of the whole end day.
                mask &= dates < end + pd.Timedelta(days=1)
    return df[mask.fillna(False)]


def active(selections: dict[str, FilterSelection] | None, defs: list[dict]) -> dict[str, dict]:
    """The selections that actually restrict something, as plain dicts --
    what gets echoed back to the UI as `applied_filters`."""
    if not selections:
        return {}
    declared = {d["column"] for d in defs}
    out = {}
    for column, sel in selections.items():
        if column not in declared:
            continue
        data = sel.model_dump(exclude_none=True)
        if data.get("values") == []:
            data.pop("values")
        if data:
            out[column] = data
    return out
