"""Deterministic analysis templates.

Most analyses a PM asks for are one of a small number of shapes -- "count
by carrier", "monthly trend of X", "excursion rate by lane", "share of
volume by origin". Each shape is a TEMPLATE here: a strictly-validated
parameter model plus a plain pandas implementation. When the designer
(analysis_designer.py) can fit a request's computation logic into one of
these, the analysis runs with no generated code at all -- faster, cheaper,
repeatable, and it can't hallucinate an operation. Anything that doesn't
fit falls through to the Analysis Agent's code-generation path.

Templates never trust their parameters: `validate` checks every referenced
column exists in the current data with a usable type before `execute` runs.

Catalog (id -> what it computes):
  group_aggregate      one dimension, 1-4 metrics            (bar / grouped bar)
  top_n_ranking        top or bottom N groups by one metric  (bar)
  share_of_total       each group's % of the whole           (pie / bar)
  cross_tab            two dimensions x one metric           (heatmap / grouped bar)
  time_trend           metric(s) per day/week/month/...      (line)
  rate_by_group        % of rows meeting a condition, by group (bar)
  rate_over_time       % of rows meeting a condition, per period (line)
  distribution         histogram of one numeric column       (bar)
  numeric_relationship two numeric columns against each other (scatter)
  overall_kpis         headline numbers, no grouping         (table / bar)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from app.services.analysis.analysis_charts import ChartRoles
from app.services.analysis.analysis_columns import as_datetime, as_labels, as_numeric

Agg = Literal["count", "count_distinct", "sum", "mean", "median", "min", "max"]
Op = Literal["gt", "gte", "lt", "lte", "eq", "neq", "in", "not_in", "between", "is_null", "not_null", "contains"]
Frequency = Literal["day", "week", "month", "quarter", "year"]

_NUMERIC_AGGS = {"sum", "mean", "median", "min", "max"}
_AGG_LABELS = {
    "count": "Count", "count_distinct": "Distinct", "sum": "Total", "mean": "Average",
    "median": "Median", "min": "Min", "max": "Max",
}
_PERIOD_CODES = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
_MAX_SCATTER_POINTS = 500


class TemplateError(ValueError):
    """A template spec that can't run against the current data. The message
    is safe to show the PM and to feed back to the LLM as a correction."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _null_means_default(cls, data):
        # LLMs often send "top_n": null / "n": null for "not specified";
        # treat that as the field's default instead of a type error.
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class Metric(_Strict):
    agg: Agg
    column: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _column_required(self):
        if self.agg != "count" and not self.column:
            raise ValueError(f"metric '{self.agg}' needs a column")
        return self

    def output_label(self) -> str:
        if self.label and self.label.strip():
            return self.label.strip()
        if self.agg == "count":
            return "Count" if not self.column else f"Count of {self.column}"
        word = _AGG_LABELS[self.agg]
        # "Max of Max Temp" rather than "Max Max Temp".
        if self.column.lower().startswith(word.lower()):
            return f"{word} of {self.column}"
        return f"{word} {self.column}"


class Condition(_Strict):
    column: str
    op: Op
    value: Any = None

    @model_validator(mode="after")
    def _value_shape(self):
        if self.op in ("is_null", "not_null"):
            return self
        if self.value is None:
            raise ValueError(f"condition '{self.op}' needs a value")
        if self.op == "between" and not (isinstance(self.value, list) and len(self.value) == 2):
            raise ValueError("condition 'between' needs a [low, high] value")
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            self.value = [self.value]
        return self

    def describe(self) -> str:
        words = {
            "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=", "neq": "!=", "in": "in",
            "not_in": "not in", "between": "between", "contains": "contains",
        }
        if self.op == "is_null":
            return f"{self.column} is blank"
        if self.op == "not_null":
            return f"{self.column} is not blank"
        return f"{self.column} {words[self.op]} {self.value}"


class _Base(_Strict):
    # Row pre-filter applied before the template computes -- e.g. "count of
    # excursions by carrier" is group_aggregate with where=[temp > 8].
    where: list[Condition] = Field(default_factory=list, max_length=5)


class GroupAggregate(_Base):
    template_id: Literal["group_aggregate"]
    group_by: str
    metrics: list[Metric] = Field(min_length=1, max_length=4)
    sort: Literal["desc", "asc", "label"] = "desc"
    top_n: int | None = Field(default=None, ge=1, le=100)
    # Groups with fewer rows are dropped -- keeps a bottom-N by a rate from
    # being filled with 1-2 trip groups (used by guided drill-downs).
    min_rows: int = Field(default=1, ge=1)


class TopNRanking(_Base):
    template_id: Literal["top_n_ranking"]
    group_by: str
    metric: Metric
    n: int = Field(default=10, ge=1, le=100)
    direction: Literal["top", "bottom"] = "top"


class ShareOfTotal(_Base):
    template_id: Literal["share_of_total"]
    group_by: str
    metric: Metric
    max_slices: int = Field(default=8, ge=2, le=20)

    @model_validator(mode="after")
    def _additive_metric(self):
        # Shares only make sense for a metric that adds up across groups.
        if self.metric.agg not in ("count", "sum"):
            raise ValueError("share_of_total needs a 'count' or 'sum' metric")
        return self


class CrossTab(_Base):
    template_id: Literal["cross_tab"]
    row_dimension: str
    column_dimension: str
    metric: Metric
    max_categories: int = Field(default=15, ge=2, le=30)


class TimeTrend(_Base):
    template_id: Literal["time_trend"]
    date_column: str
    frequency: Frequency = "month"
    metrics: list[Metric] = Field(min_length=1, max_length=4)
    series_by: str | None = None
    cumulative: bool = False
    max_series: int = Field(default=8, ge=2, le=12)

    @model_validator(mode="after")
    def _one_metric_with_series(self):
        if self.series_by and len(self.metrics) > 1:
            raise ValueError("time_trend with series_by supports exactly one metric")
        return self


class RateByGroup(_Base):
    template_id: Literal["rate_by_group"]
    group_by: str
    condition: Condition
    rate_label: str = "Rate (%)"
    min_rows: int = Field(default=1, ge=1)
    top_n: int | None = Field(default=None, ge=1, le=100)


class RateOverTime(_Base):
    template_id: Literal["rate_over_time"]
    date_column: str
    frequency: Frequency = "month"
    condition: Condition
    rate_label: str = "Rate (%)"


class Distribution(_Base):
    template_id: Literal["distribution"]
    column: str
    bins: int = Field(default=10, ge=3, le=50)


class NumericRelationship(_Base):
    template_id: Literal["numeric_relationship"]
    x_column: str
    y_column: str
    group_by: str | None = None
    agg: Literal["mean", "median", "sum"] = "mean"


class OverallKpis(_Base):
    template_id: Literal["overall_kpis"]
    metrics: list[Metric] = Field(min_length=1, max_length=8)


TemplateSpec = Annotated[
    Union[
        GroupAggregate, TopNRanking, ShareOfTotal, CrossTab, TimeTrend, RateByGroup,
        RateOverTime, Distribution, NumericRelationship, OverallKpis,
    ],
    Field(discriminator="template_id"),
]
_ADAPTER: TypeAdapter = TypeAdapter(TemplateSpec)


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    use_when: str
    example: str
    default_chart: str
    allowed_charts: tuple[str, ...]


# Shown to the template-matching LLM verbatim and to the PM in the UI, so
# every example is a complete, valid spec.
CATALOG: dict[str, TemplateInfo] = {
    "group_aggregate": TemplateInfo(
        "Group & aggregate",
        "One dimension with one to four metrics, e.g. shipment count and average temperature by carrier.",
        '{"template_id": "group_aggregate", "group_by": "Carrier", "metrics": [{"agg": "count"}, {"agg": "mean", "column": "Avg Temp"}], "sort": "desc", "top_n": null}',
        "bar", ("bar", "grouped_bar", "combo", "pie", "line", "table"),
    ),
    "top_n_ranking": TemplateInfo(
        "Top / bottom N ranking",
        "The N highest or lowest groups by one metric, e.g. top 10 origins by shipment volume.",
        '{"template_id": "top_n_ranking", "group_by": "Origin", "metric": {"agg": "count"}, "n": 10, "direction": "top"}',
        "bar", ("bar", "pie", "table"),
    ),
    "share_of_total": TemplateInfo(
        "Share of total",
        "Each group's percentage of the whole (count or sum), e.g. share of shipments by mode.",
        '{"template_id": "share_of_total", "group_by": "Mode", "metric": {"agg": "count"}, "max_slices": 8}',
        "pie", ("pie", "bar", "table"),
    ),
    "cross_tab": TemplateInfo(
        "Cross-tab (two dimensions)",
        "One metric broken down by two dimensions, e.g. shipment count by origin and destination.",
        '{"template_id": "cross_tab", "row_dimension": "Origin", "column_dimension": "Destination", "metric": {"agg": "count"}, "max_categories": 15}',
        "heatmap", ("heatmap", "grouped_bar", "table"),
    ),
    "time_trend": TemplateInfo(
        "Time trend",
        "Metric(s) per day/week/month/quarter/year, optionally one line per category or cumulative.",
        '{"template_id": "time_trend", "date_column": "Ship Date", "frequency": "month", "metrics": [{"agg": "count"}], "series_by": null, "cumulative": false}',
        "line", ("line", "bar", "grouped_bar", "table"),
    ),
    "rate_by_group": TemplateInfo(
        "Rate by group",
        "Percentage of rows meeting a condition per group, e.g. temperature-excursion rate by carrier.",
        '{"template_id": "rate_by_group", "group_by": "Carrier", "condition": {"column": "Max Temp", "op": "gt", "value": 8}, "rate_label": "Excursion rate (%)", "min_rows": 1}',
        "bar", ("bar", "combo", "table"),
    ),
    "rate_over_time": TemplateInfo(
        "Rate over time",
        "Percentage of rows meeting a condition per period, e.g. monthly on-time delivery rate.",
        '{"template_id": "rate_over_time", "date_column": "Ship Date", "frequency": "month", "condition": {"column": "Status", "op": "eq", "value": "On Time"}, "rate_label": "On-time rate (%)"}',
        "line", ("line", "bar", "combo", "table"),
    ),
    "distribution": TemplateInfo(
        "Distribution (histogram)",
        "How the values of one numeric column are spread, e.g. distribution of trip duration.",
        '{"template_id": "distribution", "column": "Trip Duration (hrs)", "bins": 10}',
        "bar", ("bar", "table"),
    ),
    "numeric_relationship": TemplateInfo(
        "Numeric relationship",
        "Two numeric columns plotted against each other, optionally one point per group.",
        '{"template_id": "numeric_relationship", "x_column": "Trip Duration (hrs)", "y_column": "Max Temp", "group_by": null, "agg": "mean"}',
        "scatter", ("scatter", "table"),
    ),
    "overall_kpis": TemplateInfo(
        "Overall KPIs",
        "Headline numbers with no grouping, e.g. total shipments, average temperature, max duration.",
        '{"template_id": "overall_kpis", "metrics": [{"agg": "count", "label": "Total shipments"}, {"agg": "mean", "column": "Avg Temp"}]}',
        "table", ("table", "bar"),
    ),
}

CONDITION_HELP = (
    'Every template also accepts an optional "where": [conditions] row pre-filter. A condition is '
    '{"column", "op", "value"} with op one of gt, gte, lt, lte, eq, neq, in, not_in, between ([low, high]), '
    "contains, is_null, not_null. A metric is {\"agg\", \"column\", \"label\"} with agg one of count "
    "(column optional), count_distinct, sum, mean, median, min, max; label is optional."
)


def catalog_prompt() -> str:
    lines = []
    for template_id, info in CATALOG.items():
        lines.append(f"- {template_id}: {info.use_when}\n  example: {info.example}")
    return "\n".join(lines) + "\n\n" + CONDITION_HELP


@dataclass
class TemplateOutput:
    frame: pd.DataFrame
    roles: ChartRoles
    default_chart: str
    allowed_charts: tuple[str, ...]


# --- Validation -----------------------------------------------------------------


def _metrics_of(spec) -> list[Metric]:
    if hasattr(spec, "metrics"):
        return list(spec.metrics)
    if hasattr(spec, "metric"):
        return [spec.metric]
    return []


def _conditions_of(spec) -> list[Condition]:
    conditions = list(spec.where)
    if hasattr(spec, "condition"):
        conditions.append(spec.condition)
    return conditions


def _dimension_columns(spec) -> list[str]:
    names = ("group_by", "row_dimension", "column_dimension", "series_by")
    return [getattr(spec, n) for n in names if getattr(spec, n, None)]


def _check_condition(cond: Condition, df: pd.DataFrame) -> None:
    if cond.op in ("gt", "gte", "lt", "lte", "between"):
        values = cond.value if cond.op == "between" else [cond.value]
        numeric_col = as_numeric(df[cond.column]) is not None
        date_col = as_datetime(df[cond.column]) is not None
        if not (numeric_col or date_col):
            raise TemplateError(f"Condition '{cond.describe()}' compares '{cond.column}', which is not numeric or a date.")
        if numeric_col and any(pd.isna(pd.to_numeric(pd.Series([v]), errors="coerce")).iloc[0] for v in values):
            raise TemplateError(f"Condition '{cond.describe()}' needs a numeric value for '{cond.column}'.")


def validate(raw_spec: dict, df: pd.DataFrame):
    """Parses and checks a template spec against the CURRENT dataframe.
    Returns the typed spec or raises TemplateError with a readable reason."""
    try:
        spec = _ADAPTER.validate_python(raw_spec)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        raise TemplateError(f"Invalid template parameters ({where}): {first.get('msg')}") from exc

    available = set(df.columns.astype(str))
    referenced = set(_dimension_columns(spec))
    referenced |= {m.column for m in _metrics_of(spec) if m.column}
    referenced |= {c.column for c in _conditions_of(spec)}
    for attr in ("date_column", "column", "x_column", "y_column"):
        if getattr(spec, attr, None):
            referenced.add(getattr(spec, attr))
    missing = sorted(referenced - available)
    if missing:
        raise TemplateError(f"Template references column(s) not in the data: {', '.join(missing)}.")

    for m in _metrics_of(spec):
        if m.agg in _NUMERIC_AGGS and as_numeric(df[m.column]) is None:
            raise TemplateError(f"'{m.agg}' needs a numeric column, but '{m.column}' is not numeric.")
    for attr in ("column", "x_column", "y_column"):
        col = getattr(spec, attr, None)
        if col and as_numeric(df[col]) is None:
            raise TemplateError(f"'{col}' must be numeric for the {spec.template_id} template.")
    date_col = getattr(spec, "date_column", None)
    if date_col and as_datetime(df[date_col]) is None:
        raise TemplateError(f"'{date_col}' is not a date column.")
    for cond in _conditions_of(spec):
        _check_condition(cond, df)
    return spec


def to_dict(spec) -> dict:
    return spec.model_dump(mode="json")


def describe(spec) -> str:
    """One-line human summary of a validated spec, for the UI."""
    info = CATALOG[spec.template_id]
    parts: list[str] = []
    for dim in _dimension_columns(spec):
        parts.append(f"by {dim}")
    if getattr(spec, "date_column", None):
        parts.append(f"per {spec.frequency} of {spec.date_column}")
    metrics = [m.output_label() for m in _metrics_of(spec)]
    if metrics:
        parts.append(", ".join(metrics))
    if getattr(spec, "condition", None):
        parts.append(f"rate where {spec.condition.describe()}")
    if spec.template_id == "distribution":
        parts.append(f"{spec.column} in {spec.bins} bins")
    if spec.template_id == "numeric_relationship":
        parts.append(f"{spec.y_column} vs {spec.x_column}")
    if spec.where:
        parts.append("only rows where " + " and ".join(c.describe() for c in spec.where))
    return f"{info.name}: " + "; ".join(parts)


def _metric_phrase(m: Metric) -> str:
    phrases = {
        "count": "the number of rows" if not m.column else f"the number of rows with a {m.column}",
        "count_distinct": f"the number of distinct {m.column} values",
        "sum": f"the total of {m.column}", "mean": f"the average {m.column}", "median": f"the median {m.column}",
        "min": f"the lowest {m.column}", "max": f"the highest {m.column}",
    }
    return f"{phrases[m.agg]} (\"{m.output_label()}\")"


def _period_phrase(spec) -> str:
    return f"each {spec.frequency} of {spec.date_column} (rows without a date are skipped)"


def explain_steps(spec) -> list[str]:
    """The exact computation a validated spec performs, as plain-English
    steps. Used as the analysis's computation logic in template mode, so
    the logic the PM reviews is always exactly what runs."""
    steps: list[str] = []
    if spec.where:
        steps.append("Keep only rows where " + " and ".join(c.describe() for c in spec.where) + ".")
    t = spec.template_id
    blank_note = " Blank values are kept as their own \"(blank)\" group."

    if t in ("group_aggregate", "top_n_ranking", "share_of_total"):
        steps.append(f"Group the rows by {spec.group_by}.{blank_note}")
        steps.append("For each group, compute " + "; ".join(_metric_phrase(m) for m in _metrics_of(spec)) + ".")
    if t == "group_aggregate":
        first = spec.metrics[0].output_label()
        order = {"desc": f"highest {first} first", "asc": f"lowest {first} first", "label": f"{spec.group_by} alphabetically"}[spec.sort]
        steps.append(f"Sort {order} and keep the first {spec.top_n or 50} groups.")
    elif t == "top_n_ranking":
        steps.append(f"Keep the {spec.direction} {spec.n} groups by {spec.metric.output_label()}.")
    elif t == "share_of_total":
        steps.append(
            f"Keep the largest {spec.max_slices - 1} groups and combine the rest into \"Other\", then divide each "
            "group's value by the overall total and multiply by 100 (\"Share (%)\")."
        )
    elif t == "cross_tab":
        steps.append(
            f"Keep the top {spec.max_categories} values of {spec.row_dimension} and of {spec.column_dimension} "
            "(by row count or metric total)."
        )
        steps.append(f"For each {spec.row_dimension} × {spec.column_dimension} combination, compute {_metric_phrase(spec.metric)}.")
    elif t == "time_trend":
        split = f", split by {spec.series_by} (top {spec.max_series} values)" if spec.series_by else ""
        steps.append(f"Group the rows by {_period_phrase(spec)}{split}.")
        steps.append("For each period, compute " + "; ".join(_metric_phrase(m) for m in spec.metrics) + ".")
        if spec.cumulative:
            steps.append("Turn each metric into a running total over time.")
        steps.append("Order the periods chronologically.")
    elif t in ("rate_by_group", "rate_over_time"):
        grouping = f"{spec.group_by}.{blank_note}" if t == "rate_by_group" else _period_phrase(spec) + "."
        steps.append(f"Group the rows by {grouping}")
        steps.append(f"For each group, count all rows (\"Rows\") and the rows where {spec.condition.describe()} (\"Matching\").")
        steps.append(f"{spec.rate_label} = Matching ÷ Rows × 100.")
        if t == "rate_by_group":
            min_rows = f" among groups with at least {spec.min_rows} rows" if spec.min_rows > 1 else ""
            steps.append(f"Sort by {spec.rate_label}, highest first, and keep the first {spec.top_n or 50} groups{min_rows}.")
        else:
            steps.append("Order the periods chronologically.")
    elif t == "distribution":
        steps.append(f"Take the numeric values of {spec.column} (blanks skipped).")
        steps.append(f"Split its range into {spec.bins} equal-width bins and count the rows in each bin.")
    elif t == "numeric_relationship":
        if spec.group_by:
            steps.append(f"Group the rows by {spec.group_by} and compute the {spec.agg} of {spec.x_column} and of {spec.y_column} for each group.")
        else:
            steps.append(f"Take every row with both {spec.x_column} and {spec.y_column} (a random sample of {_MAX_SCATTER_POINTS} if there are more).")
        steps.append(f"Plot {spec.y_column} against {spec.x_column}.")
    elif t == "overall_kpis":
        steps.append("Over all rows, compute " + "; ".join(_metric_phrase(m) for m in spec.metrics) + ".")
    return steps


def summarize(raw_spec: dict | None) -> str | None:
    """`describe` for a stored spec without the dataframe (shape check
    only) -- None if the spec doesn't even parse."""
    if not raw_spec:
        return None
    try:
        return describe(_ADAPTER.validate_python(raw_spec))
    except ValidationError:
        return None


# --- Execution ------------------------------------------------------------------


def _condition_mask(df: pd.DataFrame, cond: Condition) -> pd.Series:
    col = df[cond.column]
    if cond.op == "is_null":
        return col.isna()
    if cond.op == "not_null":
        return col.notna()
    if cond.op == "contains":
        return col.astype("string").str.contains(str(cond.value), case=False, regex=False).fillna(False)
    if cond.op in ("in", "not_in"):
        wanted = {str(v).strip().lower() for v in cond.value}
        hit = col.astype("string").str.strip().str.lower().isin(wanted).fillna(False)
        return hit if cond.op == "in" else ~hit & col.notna()

    numeric = as_numeric(col)
    if numeric is not None:
        values = pd.to_numeric(pd.Series(cond.value if cond.op == "between" else [cond.value]), errors="coerce").tolist()
        series = numeric
    else:
        dates = as_datetime(col)
        if dates is None:
            # eq / neq on plain text: case-insensitive exact match.
            if cond.op in ("eq", "neq"):
                hit = col.astype("string").str.strip().str.lower() == str(cond.value).strip().lower()
                hit = hit.fillna(False)
                return hit if cond.op == "eq" else ~hit & col.notna()
            raise TemplateError(f"Can't compare '{cond.column}' with '{cond.op}'.")
        values = pd.to_datetime(pd.Series(cond.value if cond.op == "between" else [cond.value]), errors="coerce").tolist()
        series = dates

    ops = {
        "gt": lambda s: s > values[0], "gte": lambda s: s >= values[0],
        "lt": lambda s: s < values[0], "lte": lambda s: s <= values[0],
        "eq": lambda s: s == values[0], "neq": lambda s: (s != values[0]) & s.notna(),
        "between": lambda s: s.between(min(values), max(values)),
    }
    return ops[cond.op](series).fillna(False).astype(bool)


def _apply_where(df: pd.DataFrame, conditions: list[Condition]) -> pd.DataFrame:
    for cond in conditions:
        df = df[_condition_mask(df, cond)]
    if df.empty:
        raise TemplateError("No rows are left after applying the template's row conditions.")
    return df


def _metric_values(df: pd.DataFrame, metric: Metric) -> pd.Series:
    if metric.agg == "count":
        return pd.Series(1, index=df.index) if not metric.column else df[metric.column].notna().astype(int)
    if metric.agg == "count_distinct":
        return df[metric.column]
    return as_numeric(df[metric.column])


def _agg_func(metric: Metric) -> str:
    return {"count": "sum", "count_distinct": "nunique"}.get(metric.agg, metric.agg)


def _grouped(df: pd.DataFrame, keys: dict[str, pd.Series], metrics: list[Metric]) -> pd.DataFrame:
    """Aggregates `metrics` over the group `keys` (name -> label series)."""
    frame = pd.DataFrame(keys, index=df.index)
    key_names = list(keys)
    for i, m in enumerate(metrics):
        frame[f"__m{i}"] = _metric_values(df, m)
    agg = {f"__m{i}": _agg_func(m) for i, m in enumerate(metrics)}
    out = frame.groupby(key_names, sort=False, dropna=False).agg(agg).reset_index()
    return out.rename(columns={f"__m{i}": m.output_label() for i, m in enumerate(metrics)})


def _period_labels(dates: pd.Series, frequency: str) -> tuple[pd.Series, pd.Series]:
    """(sort key, display label) for each row's period."""
    periods = dates.dt.to_period(_PERIOD_CODES[frequency])
    start = periods.dt.start_time
    fmt = {"day": "%Y-%m-%d", "week": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
    if frequency == "quarter":
        label = start.dt.year.astype(str) + "-Q" + start.dt.quarter.astype(str)
    else:
        label = start.dt.strftime(fmt[frequency])
    return start, label


def _sort_and_limit(out: pd.DataFrame, by: str, sort: str, limit: int | None, label_col: str) -> pd.DataFrame:
    if sort == "label":
        out = out.sort_values(label_col)
    else:
        out = out.sort_values(by, ascending=(sort == "asc"), na_position="last")
    return out.head(limit) if limit else out


def _run_group_aggregate(spec: GroupAggregate, df: pd.DataFrame) -> TemplateOutput:
    out = _grouped(df, {spec.group_by: as_labels(df[spec.group_by])}, spec.metrics)
    if spec.min_rows > 1:
        sizes = as_labels(df[spec.group_by]).value_counts()
        out = out[out[spec.group_by].map(sizes).fillna(0) >= spec.min_rows]
        if out.empty:
            raise TemplateError(f"No group has at least {spec.min_rows} rows.")
    first = spec.metrics[0].output_label()
    out = _sort_and_limit(out, first, spec.sort, spec.top_n or 50, spec.group_by)
    labels = [m.output_label() for m in spec.metrics]
    default = "grouped_bar" if len(labels) > 1 else "bar"
    allowed = CATALOG[spec.template_id].allowed_charts
    if len(labels) < 2:
        allowed = tuple(c for c in allowed if c != "combo")
    return TemplateOutput(out, ChartRoles(x=spec.group_by, y=labels), default, allowed)


def _run_top_n(spec: TopNRanking, df: pd.DataFrame) -> TemplateOutput:
    out = _grouped(df, {spec.group_by: as_labels(df[spec.group_by])}, [spec.metric])
    label = spec.metric.output_label()
    out = _sort_and_limit(out, label, "desc" if spec.direction == "top" else "asc", spec.n, spec.group_by)
    return TemplateOutput(out, ChartRoles(x=spec.group_by, y=[label]), "bar", CATALOG[spec.template_id].allowed_charts)


def _run_share(spec: ShareOfTotal, df: pd.DataFrame) -> TemplateOutput:
    out = _grouped(df, {spec.group_by: as_labels(df[spec.group_by])}, [spec.metric])
    label = spec.metric.output_label()
    out = out.sort_values(label, ascending=False)
    if len(out) > spec.max_slices:
        head, tail = out.head(spec.max_slices - 1), out.iloc[spec.max_slices - 1 :]
        other = pd.DataFrame({spec.group_by: ["Other"], label: [tail[label].sum()]})
        out = pd.concat([head, other], ignore_index=True)
    total = out[label].sum()
    out["Share (%)"] = (out[label] / total * 100) if total else 0.0
    return TemplateOutput(out, ChartRoles(x=spec.group_by, y=["Share (%)"]), "pie", CATALOG[spec.template_id].allowed_charts)


def _top_categories(values: pd.Series, weights: pd.Series, limit: int) -> set:
    totals = pd.DataFrame({"k": values, "w": weights.fillna(0)}).groupby("k")["w"].sum()
    return set(totals.sort_values(ascending=False).head(limit).index)


def _run_cross_tab(spec: CrossTab, df: pd.DataFrame) -> TemplateOutput:
    rows, cols = as_labels(df[spec.row_dimension]), as_labels(df[spec.column_dimension])
    weights = pd.Series(1, index=df.index) if spec.metric.agg in ("count", "count_distinct") else _metric_values(df, spec.metric)
    keep = rows.isin(_top_categories(rows, weights, spec.max_categories)) & cols.isin(
        _top_categories(cols, weights, spec.max_categories)
    )
    df, rows, cols = df[keep], rows[keep], cols[keep]
    out = _grouped(df, {spec.row_dimension: rows, spec.column_dimension: cols}, [spec.metric])
    out = out.sort_values([spec.row_dimension, spec.column_dimension])
    roles = ChartRoles(x=spec.row_dimension, y=[spec.metric.output_label()], series=spec.column_dimension)
    return TemplateOutput(out, roles, "heatmap", CATALOG[spec.template_id].allowed_charts)


def _dated(df: pd.DataFrame, date_column: str) -> tuple[pd.DataFrame, pd.Series]:
    dates = as_datetime(df[date_column])
    mask = dates.notna()
    if not mask.any():
        raise TemplateError(f"'{date_column}' has no usable dates.")
    return df[mask], dates[mask]


_ADDITIVE_AGGS = {"count", "count_distinct", "sum"}
# Guard against a pathological date range (e.g. a stray year-1900 value with
# daily frequency) exploding the filled-in period grid.
_MAX_FILLED_PERIODS = 1000


def _complete_periods(out: pd.DataFrame, dates: pd.Series, spec: TimeTrend, metric_labels: list[str]) -> pd.DataFrame:
    """Adds the periods (and period x series combinations) that had no rows,
    with 0 for each metric. Only valid for additive metrics -- a week with
    no trips has a trip count of 0, but no average temperature at all."""
    code = _PERIOD_CODES[spec.frequency]
    periods = pd.period_range(dates.min().to_period(code), dates.max().to_period(code), freq=code)
    if len(periods) > _MAX_FILLED_PERIODS:
        return out
    starts = pd.Series(periods.start_time)
    grid = pd.DataFrame({"__start": starts, "Period": _period_labels(starts, spec.frequency)[1]})
    keys = ["__start", "Period"]
    if spec.series_by:
        grid = grid.merge(pd.DataFrame({spec.series_by: out[spec.series_by].unique()}), how="cross")
        keys.append(spec.series_by)
    completed = grid.merge(out, on=keys, how="left")
    for metric, label in zip(spec.metrics, metric_labels):
        filled = completed[label].fillna(0)
        # The NaN introduced by the merge turned counts into floats.
        completed[label] = filled.astype(int) if metric.agg != "sum" else filled
    return completed


def _run_time_trend(spec: TimeTrend, df: pd.DataFrame) -> TemplateOutput:
    df, dates = _dated(df, spec.date_column)
    start, label = _period_labels(dates, spec.frequency)
    keys = {"__start": start, "Period": label}
    if spec.series_by:
        series = as_labels(df[spec.series_by])
        weights = pd.Series(1, index=df.index) if spec.metrics[0].agg in ("count", "count_distinct") else _metric_values(df, spec.metrics[0])
        keep = series.isin(_top_categories(series, weights, spec.max_series))
        df, series = df[keep], series[keep]
        keys = {"__start": start[keep], "Period": label[keep], spec.series_by: series}
    out = _grouped(df, keys, spec.metrics)
    labels = [m.output_label() for m in spec.metrics]
    if all(m.agg in _ADDITIVE_AGGS for m in spec.metrics):
        out = _complete_periods(out, dates, spec, labels)
    out = out.sort_values(["__start"] + ([spec.series_by] if spec.series_by else [])).drop(columns="__start")
    if spec.cumulative:
        for col in labels:
            out[col] = out.groupby(spec.series_by)[col].cumsum() if spec.series_by else out[col].cumsum()
    return TemplateOutput(out, ChartRoles(x="Period", y=labels, series=spec.series_by), "line", CATALOG[spec.template_id].allowed_charts)


def _rate_frame(df: pd.DataFrame, keys: dict[str, pd.Series], cond: Condition, rate_label: str) -> pd.DataFrame:
    frame = pd.DataFrame(keys, index=df.index)
    frame["Rows"] = 1
    frame["Matching"] = _condition_mask(df, cond).astype(int)
    out = frame.groupby(list(keys), sort=False, dropna=False)[["Rows", "Matching"]].sum().reset_index()
    out[rate_label] = out["Matching"] / out["Rows"] * 100
    return out


def _run_rate_by_group(spec: RateByGroup, df: pd.DataFrame) -> TemplateOutput:
    out = _rate_frame(df, {spec.group_by: as_labels(df[spec.group_by])}, spec.condition, spec.rate_label)
    out = out[out["Rows"] >= spec.min_rows]
    if out.empty:
        raise TemplateError(f"No group has at least {spec.min_rows} rows.")
    out = _sort_and_limit(out, spec.rate_label, "desc", spec.top_n or 50, spec.group_by)
    # "Rows" (each group's total count) is already computed by _rate_frame --
    # exposed as combo_y so a "combo" chart has real volume data for its
    # line, alongside the rate's bars. Kept out of `y` itself so the default
    # "bar" chart still draws only the rate, unchanged.
    return TemplateOutput(out, ChartRoles(x=spec.group_by, y=[spec.rate_label], combo_y="Rows"), "bar", CATALOG[spec.template_id].allowed_charts)


def _run_rate_over_time(spec: RateOverTime, df: pd.DataFrame) -> TemplateOutput:
    df, dates = _dated(df, spec.date_column)
    start, label = _period_labels(dates, spec.frequency)
    out = _rate_frame(df, {"__start": start, "Period": label}, spec.condition, spec.rate_label)
    out = out.sort_values("__start").drop(columns="__start")
    return TemplateOutput(out, ChartRoles(x="Period", y=[spec.rate_label], combo_y="Rows"), "line", CATALOG[spec.template_id].allowed_charts)


def _fmt_edge(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _run_distribution(spec: Distribution, df: pd.DataFrame) -> TemplateOutput:
    values = as_numeric(df[spec.column]).dropna()
    if values.empty:
        raise TemplateError(f"'{spec.column}' has no numeric values.")
    if values.nunique() == 1:
        out = pd.DataFrame({"Range": [_fmt_edge(values.iloc[0])], "Count": [len(values)]})
    else:
        binned = pd.cut(values, bins=spec.bins, include_lowest=True)
        counts = binned.value_counts(sort=False)
        out = pd.DataFrame({
            "Range": [f"{_fmt_edge(iv.left)} – {_fmt_edge(iv.right)}" for iv in counts.index],
            "Count": counts.values,
        })
    return TemplateOutput(out, ChartRoles(x="Range", y=["Count"]), "bar", CATALOG[spec.template_id].allowed_charts)


def _run_relationship(spec: NumericRelationship, df: pd.DataFrame) -> TemplateOutput:
    frame = pd.DataFrame({spec.x_column: as_numeric(df[spec.x_column]), spec.y_column: as_numeric(df[spec.y_column])})
    if spec.group_by:
        frame[spec.group_by] = as_labels(df[spec.group_by])
        out = frame.groupby(spec.group_by, dropna=False)[[spec.x_column, spec.y_column]].agg(spec.agg).reset_index()
    else:
        out = frame.dropna()
        if len(out) > _MAX_SCATTER_POINTS:
            out = out.sample(_MAX_SCATTER_POINTS, random_state=0)
    out = out.dropna(subset=[spec.x_column, spec.y_column])
    if out.empty:
        raise TemplateError("No rows have values for both columns.")
    roles = ChartRoles(x=spec.x_column, y=[spec.y_column], label=spec.group_by)
    return TemplateOutput(out, roles, "scatter", CATALOG[spec.template_id].allowed_charts)


def _run_overall_kpis(spec: OverallKpis, df: pd.DataFrame) -> TemplateOutput:
    rows = []
    for m in spec.metrics:
        values = _metric_values(df, m)
        func = _agg_func(m)
        rows.append({"Metric": m.output_label(), "Value": values.nunique() if func == "nunique" else getattr(values, func)()})
    out = pd.DataFrame(rows)
    return TemplateOutput(out, ChartRoles(x="Metric", y=["Value"]), "table", CATALOG[spec.template_id].allowed_charts)


_RUNNERS = {
    "group_aggregate": _run_group_aggregate,
    "top_n_ranking": _run_top_n,
    "share_of_total": _run_share,
    "cross_tab": _run_cross_tab,
    "time_trend": _run_time_trend,
    "rate_by_group": _run_rate_by_group,
    "rate_over_time": _run_rate_over_time,
    "distribution": _run_distribution,
    "numeric_relationship": _run_relationship,
    "overall_kpis": _run_overall_kpis,
}


def to_records(frame: pd.DataFrame) -> list[dict]:
    """JSON-safe rows: floats rounded to 2dp, NaN/inf -> None."""
    frame = frame.reset_index(drop=True).copy()
    for col in frame.columns:
        if pd.api.types.is_float_dtype(frame[col]):
            frame[col] = frame[col].round(2)
    frame = frame.replace([np.inf, -np.inf], np.nan)
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def execute(raw_spec: dict, df: pd.DataFrame) -> TemplateOutput:
    """Validates then runs a template against `df`. Raises TemplateError
    (never a raw pandas exception) when it can't produce a table."""
    spec = validate(raw_spec, df)
    try:
        filtered = _apply_where(df, spec.where)
        output = _RUNNERS[spec.template_id](spec, filtered)
    except TemplateError:
        raise
    except Exception as exc:
        raise TemplateError(f"The {CATALOG[spec.template_id].name} template failed on this data: {exc}") from exc
    if output.frame.empty:
        raise TemplateError("The template produced an empty table.")
    return output
