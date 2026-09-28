"""Deterministic Plotly chart builder for computed analysis tables.

The chart is always drawn from the REAL computed table by code -- an LLM
only ever picks the chart TYPE (and, for templates, the column roles are
known up front). Having a model transcribe table values into a figure spec
risks invented or dropped numbers and costs tokens proportional to the
table, so this module replaces that step entirely. It is also what lets a
filtered re-run redraw its chart without any LLM call.

Output shape is a plain Plotly figure {"data": [...], "layout": {...}} --
the same shape the frontend's AnalysisChart and report_generator already
consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CHART_TYPES = ("bar", "grouped_bar", "line", "pie", "scatter", "heatmap", "table")
# Shared by analysis_agent.suggest_chart and analysis_designer's chart+filter
# recommendation -- both cap the alternates shown to the PM at the same count.
MAX_CHART_ALTERNATIVES = 2

MAX_SERIES = 12
MAX_PIE_SLICES = 20
MAX_Y_COLUMNS = 4


@dataclass
class ChartRoles:
    """Which table column plays which part in the chart. `series` splits
    one metric into several traces (grouped bar / multi-line / heatmap
    rows); `label` is hover text for scatter points."""

    x: str
    y: list[str]
    series: str | None = None
    label: str | None = None

    def to_dict(self) -> dict:
        return {"x": self.x, "y": list(self.y), "series": self.series, "label": self.label}


@dataclass
class ChartResult:
    chart_type: str
    spec: dict | None
    notes: list[str] = field(default_factory=list)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_columns(table: list[dict], columns: list[str]) -> list[str]:
    numeric = []
    for col in columns:
        values = [row.get(col) for row in table if row.get(col) is not None]
        if values and all(_is_number(v) for v in values):
            numeric.append(col)
    return numeric


def infer_roles(table: list[dict], chart_type: str) -> ChartRoles | None:
    """Best-guess roles for a table whose shape wasn't declared up front
    (the code-generation path). The code-writing prompt asks for the
    category/time column first, an optional series column second, then the
    metrics -- this reads the table in that same order."""
    if not table:
        return None
    columns = list(table[0].keys())
    numeric = _numeric_columns(table, columns)
    categorical = [c for c in columns if c not in numeric]

    if chart_type == "scatter":
        if len(numeric) < 2:
            return None
        return ChartRoles(x=numeric[0], y=[numeric[1]], label=categorical[0] if categorical else None)

    if not numeric:
        return None
    if categorical:
        x = categorical[0]
        series = categorical[1] if len(categorical) > 1 and chart_type in ("grouped_bar", "line", "heatmap", "bar") else None
        return ChartRoles(x=x, y=numeric[:MAX_Y_COLUMNS], series=series)
    # All-numeric table (e.g. a year column stored as a number): the first
    # column is the axis, the rest are metrics.
    if len(numeric) < 2:
        return None
    return ChartRoles(x=numeric[0], y=numeric[1 : 1 + MAX_Y_COLUMNS])


def _ordered_unique(values: list) -> list:
    return list(dict.fromkeys(values))


def _series_values(table: list[dict], roles: ChartRoles) -> list:
    """Series values, capped at MAX_SERIES -- the largest by total metric."""
    totals: dict = {}
    for row in table:
        key = row.get(roles.series)
        v = row.get(roles.y[0])
        totals[key] = totals.get(key, 0) + (v if _is_number(v) else 0)
    ordered = _ordered_unique([row.get(roles.series) for row in table])
    if len(ordered) <= MAX_SERIES:
        return ordered
    keep = set(sorted(totals, key=lambda k: totals[k], reverse=True)[:MAX_SERIES])
    return [s for s in ordered if s in keep]


def _axis(title) -> dict:
    # Plotly.js 3 only accepts titles as {"text": ...} objects.
    return {"title": {"text": str(title)}}


def _num_or_none(v):
    return v if _is_number(v) else None


def _xy_traces(table: list[dict], roles: ChartRoles, trace_type: str, mode: str | None) -> list[dict]:
    def trace(name: str, xs: list, ys: list) -> dict:
        t = {"type": trace_type, "name": name, "x": xs, "y": ys}
        if mode:
            t["mode"] = mode
        return t

    if roles.series:
        metric = roles.y[0]
        xs_all = _ordered_unique([row.get(roles.x) for row in table])
        traces = []
        for s in _series_values(table, roles):
            lookup = {row.get(roles.x): row.get(metric) for row in table if row.get(roles.series) == s}
            traces.append(trace(str(s), xs_all, [_num_or_none(lookup.get(x)) for x in xs_all]))
        return traces

    xs = [row.get(roles.x) for row in table]
    return [trace(col, xs, [_num_or_none(row.get(col)) for row in table]) for col in roles.y]


def build_chart(table: list[dict], chart_type: str, roles: ChartRoles | None = None) -> ChartResult:
    """Builds the figure for `table` as `chart_type`. Falls back to a plain
    table (spec None -- the frontend and report both render the data table
    then) whenever the table's shape can't honestly support the chart."""
    if chart_type not in CHART_TYPES or chart_type == "table" or not table:
        return ChartResult("table", None)

    roles = roles or infer_roles(table, chart_type)
    if roles is None or not roles.y:
        return ChartResult("table", None, ["The result has no numeric column to chart, so it is shown as a table."])

    y_title = roles.y[0] if len(roles.y) == 1 else "Value"
    layout: dict = {"xaxis": _axis(roles.x), "yaxis": _axis(y_title)}

    if chart_type in ("bar", "grouped_bar"):
        data = _xy_traces(table, roles, "bar", None)
        if len(data) > 1:
            layout["barmode"] = "group"
        return ChartResult(chart_type, {"data": data, "layout": layout})

    if chart_type == "line":
        return ChartResult("line", {"data": _xy_traces(table, roles, "scatter", "lines+markers"), "layout": layout})

    if chart_type == "pie":
        rows = [r for r in table if _is_number(r.get(roles.y[0])) and r.get(roles.y[0]) >= 0]
        if not rows or roles.series:
            return ChartResult("bar", {"data": _xy_traces(table, roles, "bar", None), "layout": layout},
                               ["A pie chart needs one category and one non-negative metric, so a bar chart is shown instead."])
        notes = []
        if len(rows) > MAX_PIE_SLICES:
            notes.append(f"Only the first {MAX_PIE_SLICES} slices are shown.")
            rows = rows[:MAX_PIE_SLICES]
        trace = {"type": "pie", "labels": [r.get(roles.x) for r in rows], "values": [r.get(roles.y[0]) for r in rows]}
        return ChartResult("pie", {"data": [trace], "layout": {}}, notes)

    if chart_type == "scatter":
        xs = [row.get(roles.x) for row in table]
        ys = [row.get(roles.y[0]) for row in table]
        if not all(_is_number(v) for v in xs if v is not None):
            return build_chart(table, "bar", roles)
        trace = {"type": "scatter", "mode": "markers", "name": roles.y[0], "x": xs, "y": [_num_or_none(v) for v in ys]}
        if roles.label:
            trace["text"] = [str(row.get(roles.label)) for row in table]
        return ChartResult("scatter", {"data": [trace], "layout": layout})

    if chart_type == "heatmap":
        if not roles.series:
            return build_chart(table, "bar", roles)
        metric = roles.y[0]
        xs = _ordered_unique([row.get(roles.x) for row in table])
        ys = _series_values(table, roles)
        lookup = {(row.get(roles.x), row.get(roles.series)): row.get(metric) for row in table}
        z = [[_num_or_none(lookup.get((x, y))) for x in xs] for y in ys]
        trace = {"type": "heatmap", "x": xs, "y": [str(y) for y in ys], "z": z, "colorbar": {"title": {"text": str(metric)}}}
        return ChartResult("heatmap", {"data": [trace], "layout": {"xaxis": _axis(roles.x), "yaxis": _axis(roles.series)}})

    return ChartResult("table", None)
