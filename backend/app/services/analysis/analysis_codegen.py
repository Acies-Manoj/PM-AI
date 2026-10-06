"""Pandas code for an analysis that was computed by a template.

An analysis computed by a template (every predefined/planner one that fits one, and every guided drill-down
level) runs through deterministic Python, not through code the Analysis Agent wrote -- so it has no code of its
own. This module writes the pandas an analyst would type to get the same table from the template's spec, so every
analysis can show its code. It is a faithful equivalent for reading and reuse; the numbers shown on the page always
come from the template run itself (analysis_templates.execute), never from this text."""
from __future__ import annotations

from app.services.analysis import analysis_templates as t


def _q(value) -> str:
    return repr(value)


def _cond_expr(c: t.Condition) -> str:
    col = f"df[{_q(c.column)}]"
    if c.op == "is_null":
        return f"{col}.isna()"
    if c.op == "not_null":
        return f"{col}.notna()"
    if c.op == "contains":
        return f"{col}.astype(str).str.contains({_q(str(c.value))}, case=False, regex=False)"
    if c.op == "in":
        return f"{col}.isin({_q(list(c.value))})"
    if c.op == "not_in":
        return f"~{col}.isin({_q(list(c.value))})"
    if c.op == "between":
        return f"{col}.between({_q(c.value[0])}, {_q(c.value[1])})"
    symbols = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "neq": "!="}
    return f"{col} {symbols[c.op]} {_q(c.value)}"


def _where_lines(spec) -> list[str]:
    return [f"df = df[{_cond_expr(c)}]" for c in spec.where]


def _named_agg(m: t.Metric, fallback_col: str) -> str:
    """One `'Label': (column, func)` pair of a pandas named aggregation."""
    label = _q(m.output_label())
    if m.agg == "count":
        return f"{label}: ({_q(m.column or fallback_col)}, {_q('count' if m.column else 'size')})"
    func = "nunique" if m.agg == "count_distinct" else m.agg
    return f"{label}: ({_q(m.column)}, {_q(func)})"


def _agg_call(metrics: list[t.Metric], fallback_col: str) -> str:
    pairs = ", ".join(_named_agg(m, fallback_col) for m in metrics)
    return f".agg(**{{{pairs}}})"


def _sort_line(by: str, sort: str, label_col: str, limit: int | None, default_limit: int) -> list[str]:
    if sort == "label":
        line = f".sort_values({_q(label_col)})"
    else:
        line = f".sort_values({_q(by)}, ascending={sort == 'asc'})"
    return [line, f".head({limit or default_limit})"]


def _frequency(freq: str) -> str:
    return _q(t._PERIOD_CODES[freq])


def _chain(lines: list[str]) -> str:
    return "result = (\n" + "\n".join(f"    {l}" for l in lines) + "\n)"


def render(spec) -> str:
    """The pandas for `spec` (a validated template spec), ending with the table in `result`."""
    head = _where_lines(spec)
    prefix = ("\n".join(head) + "\n\n") if head else ""
    kind = spec.template_id

    if kind == "group_aggregate":
        first = spec.metrics[0].output_label()
        if spec.min_rows > 1:  # drop groups with too few rows before aggregating
            prefix += f"df = df[df.groupby({_q(spec.group_by)})[{_q(spec.group_by)}].transform('size') >= {spec.min_rows}]" + "\n\n"
        lines = [f"df.groupby({_q(spec.group_by)}, dropna=False)", _agg_call(spec.metrics, spec.group_by), ".reset_index()"]
        lines += _sort_line(first, spec.sort, spec.group_by, spec.top_n, 50)
        return prefix + _chain(lines)

    if kind == "multi_group":
        first = spec.metrics[0].output_label()
        lines = [f"df.groupby({_q(list(spec.dimensions))}, dropna=False)", _agg_call(spec.metrics, spec.dimensions[0]), ".reset_index()"]
        lines += _sort_line(first, spec.sort, spec.dimensions[0], spec.top_n, 100)
        return prefix + _chain(lines)

    if kind == "top_n_ranking":
        label = spec.metric.output_label()
        lines = [f"df.groupby({_q(spec.group_by)}, dropna=False)", _agg_call([spec.metric], spec.group_by), ".reset_index()"]
        lines += _sort_line(label, "desc" if spec.direction == "top" else "asc", spec.group_by, spec.n, spec.n)
        return prefix + _chain(lines)

    if kind == "share_of_total":
        label = spec.metric.output_label()
        body = _chain([
            f"df.groupby({_q(spec.group_by)}, dropna=False)", _agg_call([spec.metric], spec.group_by),
            ".reset_index()", f".sort_values({_q(label)}, ascending=False)",
        ])
        return (
            prefix + body + f"\n\n# Groups beyond the top {spec.max_slices - 1} are folded into 'Other'.\n"
            f"top = result.head({spec.max_slices - 1})\n"
            f"other = result.iloc[{spec.max_slices - 1}:]\n"
            f"if len(other):\n"
            f"    top = pd.concat([top, pd.DataFrame({{{_q(spec.group_by)}: ['Other'], {_q(label)}: [other[{_q(label)}].sum()]}})])\n"
            f"result = top.assign(**{{'Share (%)': top[{_q(label)}] / top[{_q(label)}].sum() * 100}})"
        )

    if kind == "cross_tab":
        label = spec.metric.output_label()
        keys = [spec.row_dimension, spec.column_dimension]
        lines = [f"df.groupby({_q(keys)}, dropna=False)", _agg_call([spec.metric], spec.row_dimension), ".reset_index()", f".sort_values({_q(keys)})"]
        return prefix + _chain(lines) + f"\n# Keeps the {spec.max_categories} largest {spec.row_dimension} and {spec.column_dimension} values."

    if kind == "time_trend":
        keys = ["Period"] + ([spec.series_by] if spec.series_by else [])
        lines = [
            f"df.assign(Period=pd.to_datetime(df[{_q(spec.date_column)}], errors='coerce').dt.to_period({_frequency(spec.frequency)}).astype(str))",
            f".groupby({_q(keys)}, dropna=False)", _agg_call(spec.metrics, spec.date_column), ".reset_index()", ".sort_values(" + _q(keys) + ")",
        ]
        code = prefix + _chain(lines)
        if spec.cumulative:
            labels = [m.output_label() for m in spec.metrics]
            grouper = f".groupby({_q(spec.series_by)})" if spec.series_by else ""
            code += "\n\n" + "\n".join(f"result[{_q(l)}] = result{grouper}[{_q(l)}].cumsum()" for l in labels)
        return code

    if kind in ("rate_by_group", "rate_over_time"):
        if kind == "rate_by_group":
            keys, setup = [spec.group_by], ""
        else:
            keys = ["Period"]
            setup = (
                f"df = df.assign(Period=pd.to_datetime(df[{_q(spec.date_column)}], errors='coerce')"
                f".dt.to_period({_frequency(spec.frequency)}).astype(str))\n"
            )
        body = (
            f"df = df.assign(Matching=({_cond_expr(spec.condition)}).astype(int))\n"
            + setup
            + _chain([
                f"df.groupby({_q(keys)}, dropna=False)",
                ".agg(Rows=('Matching', 'size'), Matching=('Matching', 'sum'))",
                ".reset_index()",
                f".assign(**{{{_q(spec.rate_label)}: lambda d: d['Matching'] / d['Rows'] * 100}})",
            ])
        )
        if kind == "rate_by_group":
            body += f"\nresult = result[result['Rows'] >= {spec.min_rows}].sort_values({_q(spec.rate_label)}, ascending=False).head({spec.top_n or 50})"
        else:
            body += "\nresult = result.sort_values('Period')"
        return prefix + body

    if kind == "distribution":
        return (
            prefix
            + f"values = pd.to_numeric(df[{_q(spec.column)}], errors='coerce').dropna()\n"
            + f"counts = pd.cut(values, bins={spec.bins}, include_lowest=True).value_counts(sort=False)\n"
            + "result = pd.DataFrame({'Range': counts.index.astype(str), 'Count': counts.values})"
        )

    if kind == "numeric_relationship":
        cols = [spec.x_column, spec.y_column]
        convert = f"df[{_q(cols)}].apply(pd.to_numeric, errors='coerce')"
        if spec.group_by:
            return prefix + _chain([
                f"df.assign(**{{c: pd.to_numeric(df[c], errors='coerce') for c in {_q(cols)}}})",
                f".groupby({_q(spec.group_by)}, dropna=False)[{_q(cols)}]", f".agg({_q(spec.agg)})", ".reset_index()",
                f".dropna(subset={_q(cols)})",
            ])
        return prefix + f"result = {convert}.dropna()"

    if kind == "overall_kpis":
        rows = []
        for m in spec.metrics:
            if m.agg == "count":
                value = f"len(df)" if not m.column else f"df[{_q(m.column)}].notna().sum()"
            elif m.agg == "count_distinct":
                value = f"df[{_q(m.column)}].nunique()"
            else:
                value = f"pd.to_numeric(df[{_q(m.column)}], errors='coerce').{m.agg}()"
            rows.append(f"    {{'Metric': {_q(m.output_label())}, 'Value': {value}}},")
        return prefix + "result = pd.DataFrame([\n" + "\n".join(rows) + "\n])"

    return prefix + "# (no code view for this template)"


def for_template(raw_template: dict, df) -> str | None:
    """Code for a raw template dict, or None if it can't be rendered (the page then simply has no code to show)."""
    try:
        return render(t.validate(raw_template, df))
    except Exception:
        return None
