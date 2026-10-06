"""
Builds a downloadable .pptx report from analyses already computed on the
Analysis page: one slide per included, run_status == "done"
AnalysisRepositoryEntry (see analysis_agent.py / schemas.py), plus a closing
summary slide of bullet points synthesized fresh from those entries'
interpretations (see final_summary_agent.py) -- matching the reference
deck's own bullet-point closing slide, not a prose paragraph. Every chart is
a real, native PowerPoint chart object -- never a picture. No LLM decides
slide content here: each slide's heading/chart/caption is rule-driven from
the entry's own already-computed chart_type, chart_spec, and interpretation
-- this module never reinterprets a raw number itself.

Slide content is preferably built from `chart_spec` (the Analysis Agent's
validated Plotly.js trace data -- real x/y or labels/values arrays), falling
back to reshaping `result_table`/`result_columns` when a trace is missing or
empty. `chart_type` picks the slide shape:
  bar / grouped_bar / line / scatter -> one column or line chart (scatter is
    rendered as a single-series column chart -- a true XY scatter chart's
    axis styling is fragile in python-pptx once a secondary value axis is
    involved, and a bar reads just as clearly for the handful of points an
    aggregated table typically has)
  pie                                -> a native pie chart
  heatmap / table / anything with no usable numeric data -> a plain data
    table slide, the same fallback the on-screen AnalysisChart component
    uses when it has no chart_spec
"""
import copy
import io
import math
import re
from datetime import datetime
from xml.sax.saxutils import escape

import numpy as np
from lxml import etree
import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.chart.axis import ValueAxis
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.services.report import report_style as style
from app.services.report import translation_service

MAX_CHART_ROWS = 20
MAX_TABLE_ROWS = 15
MAX_TABLE_COLS = 6

REPORT_NAME = "Program Manager AI Report"  # standing report title/filename

PRIMARY = RGBColor.from_string(style.BAR_COLOR_HEX)
WHITE = RGBColor.from_string(style.WHITE_HEX)
DARK_TEXT = RGBColor.from_string(style.DARK_TEXT_HEX)
MUTED = RGBColor.from_string(style.MUTED_TEXT_HEX)
BAR_PALETTE = [RGBColor.from_string(h) for h in style.BAR_PALETTE_HEX]

BLANK_LAYOUT = 6

_ACTIVITY_DATE_HINTS = re.compile(r"arriv|depart|segment|trip create", re.IGNORECASE)

# Fixed English phrases the report builder writes itself -- never a data
# value (an analysis name, interpretation sentence, column name, or category
# value). Translated as one batch per report/language in build_report, then
# looked up via the `phrases` dict every builder carries (see
# ReportBuilder._t). PROGRAM_TITLE is deliberately excluded -- it's a
# product/brand name, not descriptive UI text, so it stays in English
# regardless of the selected language, same as the frontend's own "Program
# Manager AI" branding.
SUMMARY_HEADING = "Summary"
NO_OVERALL_CAPTION = "No overall analysis had been generated for this session yet."

TRANSLATABLE_PHRASES = [SUMMARY_HEADING, NO_OVERALL_CAPTION, style.PROPRIETARY_TEXT]


def _date_range_label(df: pd.DataFrame) -> str | None:
    date_cols = list(df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns)
    if not date_cols:
        return None
    activity_cols = [c for c in date_cols if _ACTIVITY_DATE_HINTS.search(str(c))]
    date_cols = activity_cols or date_cols

    overall_min, overall_max = None, None
    for col in date_cols:
        col_min, col_max = df[col].min(), df[col].max()
        if pd.isna(col_min) or pd.isna(col_max):
            continue
        overall_min = col_min if overall_min is None or col_min < overall_min else overall_min
        overall_max = col_max if overall_max is None or col_max > overall_max else overall_max
    if overall_min is None or overall_max is None:
        return None
    return f"{overall_min:%d.%m.%Y} – {overall_max:%d.%m.%Y}"


def _blank_label(value) -> str:
    """Mirrors Excel's own PivotChart convention: a missing group value reads
    as "(blank)" rather than the Python str() of None/NaN leaking through."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return style.BLANK_LABEL
    text = str(value).strip()
    if not text or text.lower() in ("none", "nan"):
        return style.BLANK_LABEL
    return text


def _is_numeric(value) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return isinstance(value, (int, float, np.integer, np.floating))


def _to_number(value) -> float:
    return float(value) if _is_numeric(value) else 0.0


# -- chart styling (module-level so a future template-based builder can
# reuse the same look) -------------------------------------------------------

def style_axes_grid(category_axis, value_axis):
    """Left value-axis line + bottom category-axis line, both made visible, plus
    light horizontal (value) gridlines only -- like the reference deck's charts,
    no vertical gridlines competing with the bars."""
    grid_color = RGBColor.from_string(style.GRIDLINE_COLOR_HEX)
    category_axis.has_major_gridlines = False
    category_axis.has_minor_gridlines = False
    value_axis.has_major_gridlines = True
    value_axis.has_minor_gridlines = False
    value_axis.major_gridlines.format.line.color.rgb = grid_color
    value_axis.major_gridlines.format.line.width = Pt(0.75)
    for axis in (category_axis, value_axis):
        axis.format.line.color.rgb = MUTED
        axis.format.line.width = Pt(1)


def set_axis_title(axis, text: str):
    axis.axis_title.text_frame.text = text
    axis.axis_title.text_frame.paragraphs[0].font.size = Pt(style.CHART_AXIS_TITLE_FONT_PT)
    axis.axis_title.text_frame.paragraphs[0].font.name = style.FONT_BODY


# -- combo chart (bar + line, secondary axis) --------------------------------
# python-pptx has no public API for a chart with two plot types on two value
# axes, so this drops to the chart's own OOXML. Prototyped and validated
# standalone (schema validator + a round-trip re-read confirming python-pptx
# itself recognizes two distinct plots) before being wired in here.

_CHART_NS = (
    'xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


def _combo_axis_title_xml(text: str) -> str:
    return (
        "<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/>"
        f'<a:p><a:r><a:rPr lang="en-US" sz="{style.CHART_AXIS_TITLE_FONT_PT * 100}">'
        f'<a:solidFill><a:srgbClr val="{style.MUTED_TEXT_HEX}"/></a:solidFill>'
        f'<a:latin typeface="{style.FONT_BODY}"/></a:rPr><a:t>{escape(text)}</a:t></a:r></a:p>'
        "</c:rich></c:tx><c:overlay val=\"0\"/></c:title>"
    )


def _combo_tick_txpr_xml() -> str:
    return (
        f'<c:txPr><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{style.CHART_FONT_PT * 100}">'
        f'<a:solidFill><a:srgbClr val="{style.MUTED_TEXT_HEX}"/></a:solidFill>'
        f'<a:latin typeface="{style.FONT_BODY}"/></a:defRPr></a:pPr><a:endParaRPr lang="en-US"/></a:p></c:txPr>'
    )


def _secondary_major_unit_xml(step: float | None) -> str:
    return f'<c:crossBetween val="between"/><c:majorUnit val="{step:g}"/>' if step else ''


def _secondary_scaling_xml(sec_min: float | None, sec_max: float | None) -> str:
    bounds = ""
    if sec_min is not None and sec_max is not None:
        bounds = f'<c:max val="{sec_max:.6g}"/><c:min val="{sec_min:.6g}"/>'
    return f'<c:scaling><c:orientation val="minMax"/>{bounds}</c:scaling>'


def split_into_combo(
    chart, line_axis_title: str, sec_min: float | None = None, sec_max: float | None = None,
    sec_step: float | None = None, sec_format: str = "General;;0",
) -> bool:
    """Converts a freshly-built 2-series COLUMN_CLUSTERED chart into a real
    dual-axis combo: the 2nd series becomes a line plot on its own secondary
    value axis (visible, right side), paired with a new hidden secondary
    category axis (an axis pair needs two axes even when one is never shown).
    Returns False (leaving the chart as a plain 2-series bar) if there
    weren't 2 series to split."""
    plot_area = chart._chartSpace.chart.plotArea
    bar_chart_el = plot_area.find(qn("c:barChart"))
    sers = bar_chart_el.findall(qn("c:ser"))
    if len(sers) < 2:
        return False
    line_ser = sers[1]
    bar_chart_el.remove(line_ser)
    line_ser.append(parse_xml(f'<c:smooth {_CHART_NS} val="0"/>'))

    existing_ax_ids = [
        int(e.find(qn("c:axId")).get("val"))
        for e in plot_area.findall(qn("c:catAx")) + plot_area.findall(qn("c:valAx"))
    ]
    sec_cat_ax_id = max(existing_ax_ids) + 1
    sec_val_ax_id = max(existing_ax_ids) + 2

    line_chart_el = parse_xml(f'<c:lineChart {_CHART_NS}><c:grouping val="standard"/><c:varyColors val="0"/></c:lineChart>')
    line_chart_el.append(line_ser)
    line_chart_el.append(parse_xml(f'<c:marker {_CHART_NS} val="1"/>'))
    line_chart_el.append(parse_xml(f'<c:smooth {_CHART_NS} val="0"/>'))
    line_chart_el.append(parse_xml(f'<c:axId {_CHART_NS} val="{sec_cat_ax_id}"/>'))
    line_chart_el.append(parse_xml(f'<c:axId {_CHART_NS} val="{sec_val_ax_id}"/>'))
    bar_chart_el.addnext(line_chart_el)

    sec_val_ax = parse_xml(
        f'<c:valAx {_CHART_NS}>'
        f'<c:axId val="{sec_val_ax_id}"/>'
        + _secondary_scaling_xml(sec_min, sec_max) +
        '<c:delete val="0"/>'
        '<c:axPos val="r"/>'
        + _combo_axis_title_xml(line_axis_title) +
        # The axis starts below zero to leave room for the columns; those negative ticks are hidden.
        f'<c:numFmt formatCode="{escape(sec_format, {chr(34): "&quot;"})}" sourceLinked="0"/>'
        '<c:majorTickMark val="out"/>'
        '<c:minorTickMark val="none"/>'
        '<c:tickLblPos val="nextTo"/>'
        + _combo_tick_txpr_xml() +
        f'<c:crossAx val="{sec_cat_ax_id}"/>'
        '<c:crosses val="max"/>'
        + _secondary_major_unit_xml(sec_step) +
        "</c:valAx>"
    )
    sec_cat_ax = parse_xml(
        f'<c:catAx {_CHART_NS}>'
        f'<c:axId val="{sec_cat_ax_id}"/>'
        '<c:scaling><c:orientation val="minMax"/></c:scaling>'
        '<c:delete val="1"/>'
        '<c:axPos val="b"/>'
        '<c:majorTickMark val="out"/>'
        '<c:minorTickMark val="none"/>'
        '<c:tickLblPos val="nextTo"/>'
        f'<c:crossAx val="{sec_val_ax_id}"/>'
        '<c:crosses val="autoZero"/>'
        '<c:auto val="1"/>'
        '<c:lblAlgn val="ctr"/>'
        '<c:lblOffset val="100"/>'
        '<c:noMultiLvlLbl val="0"/>'
        "</c:catAx>"
    )
    existing_val_ax = plot_area.findall(qn("c:valAx"))[-1]
    existing_val_ax.addnext(sec_cat_ax)
    existing_val_ax.addnext(sec_val_ax)
    return True


def _flat(connector) -> None:
    """A python-pptx connector inherits the theme's line effect (a soft shadow);
    an empty effect list keeps the rule a clean, flat line."""
    sp_pr = connector._element.spPr
    if sp_pr.find(qn("a:effectLst")) is None:
        sp_pr.append(parse_xml('<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"/>'))


def _primary_value_axis(chart):
    """The left (primary) value axis of a combo chart -- `chart.value_axis` returns
    the right-hand one once a secondary axis has been added."""
    for el in chart._chartSpace.chart.plotArea.findall(qn("c:valAx")):
        pos = el.find(qn("c:axPos"))
        if pos is not None and pos.get("val") == "l":
            return ValueAxis(el)
    return chart.value_axis


def number_format_for(values, hide_zero: bool = False) -> str:
    """Whole numbers read '652', not '652.' (what '#,##0.##' prints); anything with decimals gets
    one decimal place. `hide_zero` blanks zero labels -- on grouped bars most categories have no
    value for most series, and a row of "0"s only clutters the chart."""
    nums = [v for v in values if _is_numeric(v)]
    fmt = "#,##0" if nums and all(float(v).is_integer() for v in nums) else "#,##0.0"
    return f"{fmt};-{fmt};;" if hide_zero else fmt


def style_native_chart(chart, number_format: str, single_series: bool):
    style.set_chart_default_font(chart, style.CHART_DATA_LABEL_FONT_PT, style.FONT_BODY)
    chart.has_title = False
    chart.has_legend = not single_series
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(style.CHART_FONT_PT)
        chart.legend.font.name = style.FONT_BODY
    plot = chart.plots[0]
    plot.has_data_labels = True
    plot.data_labels.number_format = number_format
    plot.data_labels.number_format_is_linked = False
    plot.data_labels.font.size = Pt(style.CHART_DATA_LABEL_FONT_PT)
    plot.data_labels.font.name = style.FONT_BODY
    plot.data_labels.position = (
        XL_LABEL_POSITION.ABOVE if chart.chart_type == XL_CHART_TYPE.LINE_MARKERS else XL_LABEL_POSITION.OUTSIDE_END
    )
    for i, series in enumerate(plot.series):
        color = BAR_PALETTE[i % len(BAR_PALETTE)]
        if chart.chart_type == XL_CHART_TYPE.LINE_MARKERS:
            series.format.line.color.rgb = color
            series.format.line.width = Pt(2.25)
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = color
    style_axes_grid(chart.category_axis, chart.value_axis)
    chart.category_axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
    chart.category_axis.tick_labels.font.name = style.FONT_BODY
    chart.value_axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
    chart.value_axis.tick_labels.font.name = style.FONT_BODY


def _short_label(value, limit: int = 18) -> str:
    """Category labels are cut to `limit` characters so long names (carriers, lanes) can't run
    into their neighbours or the axis title."""
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _axis_plan(categories: list, width_in: float = 12.0) -> tuple[list[str], int]:
    """(labels, rotation in degrees) for a category axis. If the labels fit flat in the width each
    category gets they are cut to that length and left horizontal; otherwise they get a clean
    45-degree slant with a longer cut. Truncation never merges two different categories."""
    n = max(len(categories), 1)
    fit = int(width_in / n / 0.085 * 0.9)  # ~0.085in per character at 11pt Arial
    originals = [str(c) for c in categories]
    if fit >= 10:
        labels = [_short_label(c, min(fit, 24)) for c in originals]
        rotation = 0
    else:
        labels = [_short_label(c, 18) for c in originals]
        rotation = -45
    if len(set(labels)) < len(set(originals)):  # two long names collapsed into one label
        labels = [_short_label(c, 30) for c in originals]
        rotation = -45
    return labels, rotation


def _tidy_category_axis(axis, rotation: int) -> None:
    """Applies the planned rotation explicitly (not left to the renderer's guess) and keeps the
    tick font consistent."""
    axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
    axis.tick_labels.font.name = style.FONT_BODY
    body_pr = axis._element.find(qn("c:txPr")).find(qn("a:bodyPr"))
    body_pr.set("rot", str(rotation * 60000))
    body_pr.set("vert", "horz")
    # Show every category label: left to itself PowerPoint drops every other one when it judges
    # flat labels too wide. (Schema order: ... lblOffset, tickLblSkip, tickMarkSkip, noMultiLvlLbl.)
    el = axis._element
    if el.find(qn("c:tickLblSkip")) is None:
        skip = parse_xml(f'<c:tickLblSkip {_CHART_NS} val="1"/>')
        anchor = el.find(qn("c:noMultiLvlLbl"))
        if anchor is not None:
            anchor.addprevious(skip)
        else:
            el.append(skip)


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_CHART_LEAD_IN = re.compile(
    r"^(the|this)\s+(chart|graph|data|visuali[sz]ation)\s+(shows?|illustrates?|indicates?|reveals?|highlights?)\s*(that\s+)?",
    re.IGNORECASE,
)


def short_explanation(text: str | None, max_chars: int | None = None) -> str:
    """The one/two-line takeaway shown under a slide's title: the first sentence of the
    analysis' interpretation, plus the second when both fit. Kept in step with
    `shortExplanation` in frontend/src/utils/slideText.ts so the on-screen preview reads
    exactly like the slide."""
    limit = max_chars or style.EXPLAIN_MAX_CHARS
    cleaned = _CHART_LEAD_IN.sub("", (text or "").strip())
    if not cleaned:
        return ""
    cleaned = cleaned[0].upper() + cleaned[1:]
    sentences = [s for s in _SENTENCE_END.split(cleaned) if s]
    out = sentences[0]
    if len(out) > limit:
        window = out[:limit]
        comma = window.rfind(", ")
        if comma >= limit * 0.45:  # a clause that stands on its own reads better than a cut-off word
            return window[:comma].rstrip(",;:- ") + "."
        return window[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:- ") + "…"
    for extra in sentences[1:2]:
        if len(out) + 1 + len(extra) <= limit:
            out = f"{out} {extra}"
    return out


def _template_theme_colors(tpl) -> dict[str, str]:
    """{scheme colour name: hex} of the template's theme, including the tx1/bg1/tx2/bg2 aliases."""
    colors: dict[str, str] = {}
    for rel in tpl.slide_masters[0].part.rels.values():
        if not rel.reltype.endswith("/theme"):
            continue
        root = etree.fromstring(rel.target_part.blob)
        ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        scheme = root.find(".//a:clrScheme", ns)
        for el in scheme if scheme is not None else []:
            name = el.tag.split("}")[1]
            child = el[0] if len(el) else None
            if child is not None:
                colors[name] = child.get("val") or child.get("lastClr") or "000000"
    colors.update({"tx1": colors.get("dk1", "000000"), "bg1": colors.get("lt1", "FFFFFF"),
                   "tx2": colors.get("dk2", "000000"), "bg2": colors.get("lt2", "FFFFFF")})
    return colors


def _nice_ceil(value: float) -> float:
    """Rounds up to 1, 2 or 5 times a power of ten -- an axis maximum that reads cleanly."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * magnitude:
            return float(step * magnitude)
    return float(10 * magnitude)


def _nice_step(value: float) -> float:
    """Smallest 1/2/5 x 10^k step that is >= value."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(value))
    for m in (1, 2, 5, 10):
        if value <= m * magnitude:
            return float(m * magnitude)
    return float(10 * magnitude)


def _combo_scale(bar_values: list[float], line_values: list[float]) -> dict | None:
    """Axis ranges that keep a combo chart legible: the columns use the lower ~55% of the plot and
    the line the upper ~40%, so the line, its labels and the column labels don't overlap. Both axes
    use round numbers; the line axis starts below zero to make that room (the negative ticks are
    hidden). None when the data can't be scaled this way (negative values, no line)."""
    bars = [float(v) for v in bar_values if _is_numeric(v)]
    line = [float(v) for v in line_values if _is_numeric(v)]
    if not bars or not line or min(bars) < 0 or min(line) < 0 or max(line) <= 0:
        return None
    primary_max = _nice_ceil(max(bars) / 0.55)
    step = _nice_step(max(line) / 5)
    top = math.ceil(max(line) * 1.12 / step) * step  # headroom, so the top labels clear their markers
    total = math.ceil(top / 0.4 / step) * step
    return {
        "primary_max": primary_max,
        "percent_bars": max(bars) <= 100 < primary_max,
        "secondary": (top - total, top),
        "step": step,
        # a rate never exceeds 100: don't label the headroom above it; either way hide the negative ticks
        "sec_format": '[<0]" ";[<=100]General;" "' if max(line) <= 100 else "General;;0",
    }


class ReportBuilder:
    """16:9 deck: title top-left with the Carrier logo top-right, a one/two-line
    explanation under the title, the chart full width below it, a small caption under
    the chart and the Carrier footer along the bottom (see report_style)."""

    def __init__(self, phrases: dict[str, str] | None = None):
        self.prs = Presentation()
        self.prs.slide_width = style.SLIDE_W
        self.prs.slide_height = style.SLIDE_H
        self._blank = self.prs.slide_layouts[BLANK_LAYOUT]
        self.slide_count = 0
        # {original English phrase: translated phrase} for the current
        # download's language -- empty (or missing key) means "keep the
        # original", so an untranslated/failed-translation phrase always
        # still renders correctly in English.
        self.phrases = phrases or {}

    def _t(self, text: str) -> str:
        return self.phrases.get(text, text)

    def _new_slide(self):
        slide = self.prs.slides.add_slide(self._blank)
        self.slide_count += 1
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = WHITE
        return slide

    # -- shared furniture -------------------------------------------------------
    @staticmethod
    def _style_run(run, size: int, color, bold: bool = False, italic: bool = False):
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = color
        run.font.name = style.FONT_BODY

    def _text(self, slide, left, top, width, height, text: str, size: int, color, bold: bool = False,
              align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic: bool = False):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = anchor
        p = tf.paragraphs[0]
        p.alignment = align
        run = p.add_run()
        run.text = text
        self._style_run(run, size, color, bold, italic)
        return box

    def _title(self, slide, heading: str):
        size = 28 if len(heading) <= 50 else 24 if len(heading) <= 70 else 20 if len(heading) <= 100 else 18
        self._text(slide, style.MARGIN_X, style.TITLE_TOP, style.TITLE_W, style.TITLE_H, heading,
                   size, PRIMARY, bold=True, anchor=MSO_ANCHOR.MIDDLE)

    def _explanation(self, slide, text: str | None):
        """The one/two-line plain-language takeaway directly under the title."""
        if text:
            self._text(slide, style.MARGIN_X, style.EXPLAIN_TOP, style.CONTENT_W, style.EXPLAIN_H,
                       text, style.EXPLAIN_PT, DARK_TEXT)

    def _caption(self, slide, text: str | None):
        """Small grey note under the chart (the drill-down's filter line)."""
        if text:
            self._text(slide, style.MARGIN_X, style.CAPTION_TOP, style.CONTENT_W, style.CAPTION_H,
                       text, 11, MUTED, italic=True)

    def _logo(self, slide):
        slide.shapes.add_picture(
            str(style.LOGO_PATH), style.LOGO_LEFT, style.LOGO_TOP, style.LOGO_WIDTH, style.LOGO_HEIGHT
        )

    def _footer(self, slide):
        """The Carrier footer: copyright on the left, 'A Carrier Company' on the right."""
        footer = RGBColor.from_string(style.FOOTER_HEX)
        self._text(slide, style.MARGIN_X, style.FOOTER_Y, Inches(7), Inches(0.25),
                   f"© {datetime.now().year} Carrier. All Rights Reserved.", style.FOOTER_PT, footer)
        self._text(slide, style.MARGIN_X + style.CONTENT_W - Inches(4), style.FOOTER_Y, Inches(4), Inches(0.25),
                   "A Carrier Company", style.FOOTER_PT, footer, align=PP_ALIGN.RIGHT)

    def _frame(self, slide, heading: str, explanation: str | None = None):
        """Title + logo + explanation -- the header every content slide shares."""
        self._title(slide, heading)
        self._logo(slide)
        self._explanation(slide, explanation)

    def _body_box(self):
        """(left, top, width, height) of the chart/table area."""
        return style.MARGIN_X, style.BODY_TOP, style.CONTENT_W, style.BODY_BOTTOM - style.BODY_TOP

    def _bullets(self, slide, bullets: list[str], left, top, width, height, size: int = 16):
        box = slide.shapes.add_textbox(left, top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        for i, bullet in enumerate(bullets):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            run = p.add_run()
            run.text = bullet
            self._style_run(run, size, DARK_TEXT)
            p.space_after = Pt(12)
            # A real hanging-indent bullet, so wrapped lines align under the text.
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", "285750")
            pPr.set("indent", "-285750")
            pPr.append(parse_xml(
                '<a:buClr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f'<a:srgbClr val="{style.BAR_COLOR_HEX}"/></a:buClr>'
            ))
            pPr.append(parse_xml(
                '<a:buChar xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" char="&#8226;"/>'
            ))

    # -- cover ------------------------------------------------------------------
    def _template_cover_shapes(self, slide) -> bool:
        """Copies the picture/colour-block/frame shapes of the Carrier template's cover
        layout onto `slide`, scaled from the template's 10in width to this deck's.
        Returns False (so the caller draws a plain cover) if the template is missing."""
        try:
            tpl = Presentation(str(style.DEFAULT_TEMPLATE_PATH))
            layout = next(
                lay for m in tpl.slide_masters for lay in m.slide_layouts if lay.name == style.COVER_LAYOUT_NAME
            )
        except Exception:
            return False

        scale = self.prs.slide_width / tpl.slide_width
        theme = _template_theme_colors(tpl)
        tree = slide.shapes._spTree
        for el in layout.shapes._spTree:
            tag = el.tag.split("}")[1]
            if tag not in ("sp", "pic", "grpSp", "cxnSp"):
                continue
            if el.find(".//" + qn("p:ph")) is not None:
                continue  # the title/subtitle placeholders: drawn as text boxes by the caller
            if b"svgBlip" in etree.tostring(el):
                continue  # the template's vector logo: the caller places this app's own PNG logo
            new = copy.deepcopy(el)
            for xfrm in new.iter(qn("a:xfrm")):
                off, ext = xfrm.find(qn("a:off")), xfrm.find(qn("a:ext"))
                if off is not None:
                    off.set("x", str(round(int(off.get("x")) * scale)))
                    off.set("y", str(round(int(off.get("y")) * scale)))
                if ext is not None:
                    ext.set("cx", str(round(int(ext.get("cx")) * scale)))
                    ext.set("cy", str(round(int(ext.get("cy")) * scale)))
            # Theme colours would resolve against THIS deck's default theme, so pin them to the
            # template's own values.
            for clr in list(new.iter(qn("a:schemeClr"))):
                hex_value = theme.get(clr.get("val"))
                if hex_value:
                    srgb = parse_xml(
                        f'<a:srgbClr xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" val="{hex_value}"/>'
                    )
                    for child in list(clr):
                        srgb.append(child)
                    clr.getparent().replace(clr, srgb)
            for blip in new.iter(qn("a:blip")):
                rid = blip.get(qn("r:embed"))
                if rid:
                    _, new_rid = slide.part.get_or_add_image_part(io.BytesIO(layout.part.related_part(rid).blob))
                    blip.set(qn("r:embed"), new_rid)
            cnv = next(new.iter(qn("p:cNvPr")), None)
            if cnv is not None:
                if cnv.get("name") == "Freeform 48":  # the top colour block: blue, as in the sample
                    for clr in new.find(qn("p:spPr")).iter(qn("a:srgbClr")):
                        clr.set("val", style.COVER_TOP_BLOCK_HEX)
                        break
                cnv.set("id", str(slide.shapes._next_shape_id))
            tree.append(new)
        return True

    def add_title_slide(self, title: str, subtitle: str | None, detail: str | None = None):
        """The title page, laid out like the Carrier template's cover: logo top-left, the
        title (blue) and a short subtitle at the left, the photo grid and colour blocks at the
        right."""
        slide = self._new_slide()
        has_art = self._template_cover_shapes(slide)
        k = 1.0 / 0.75  # the template is 10in wide, this deck 13.333in

        slide.shapes.add_picture(
            str(style.LOGO_PATH), Inches(0.32 * 1.3333), Inches(0.32 * 1.3333), Inches(1.19 * 1.3333), Inches(0.47 * 1.3333)
        )
        accent = RGBColor.from_string("0A2EF5")
        navy = RGBColor.from_string("152C73")
        left, width = Inches(0.352 * k), Inches(3.52 * k)
        if not has_art:  # no template available: a plain left-aligned cover, still on the same grid
            width = Inches(7.5)
        self._text(slide, left, Inches(1.26 * k), width, Inches(1.55 * k), title, 42, accent, anchor=MSO_ANCHOR.BOTTOM)
        lines = [t for t in (subtitle, detail) if t]
        if lines:
            box = slide.shapes.add_textbox(left, Inches(3.15 * k), width, Inches(0.9 * k))
            tf = box.text_frame
            tf.word_wrap = True
            tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
            for i, line in enumerate(lines):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                run = p.add_run()
                run.text = line
                self._style_run(run, 18, navy)

    # -- chart slides -----------------------------------------------------------
    def add_bar_or_line_slide(
        self, heading: str, description: str, categories: list[str], series: list[tuple[str, list[float]]],
        value_axis_title: str, category_axis_title: str, is_line: bool,
        subtitle: str | None = None,
    ):
        """One native column (or line) chart -- `series` is one or more
        (name, values) pairs sharing `categories`, so this covers a plain
        single-series bar, a multi-series "grouped bar", and a line trend
        alike."""
        slide = self._new_slide()
        self._frame(slide, heading, description)
        box = self._body_box()

        categories, rotation = _axis_plan(categories)
        data = CategoryChartData()
        data.categories = categories
        for name, values in series:
            data.add_series(name, values)

        chart_type = XL_CHART_TYPE.LINE_MARKERS if is_line else XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = slide.shapes.add_chart(chart_type, *box, data)
        chart = gf.chart
        style_native_chart(
            chart, number_format=number_format_for([v for _, vals in series for v in vals], hide_zero=not is_line),
            single_series=len(series) == 1,
        )
        set_axis_title(chart.value_axis, value_axis_title)
        set_axis_title(chart.category_axis, category_axis_title)
        _tidy_category_axis(chart.category_axis, rotation)
        self._caption(slide, subtitle)
        self._footer(slide)

    def add_combo_slide(
        self, heading: str, description: str, categories: list[str],
        bar_name: str, bar_values: list[float], line_name: str, line_values: list[float],
        bar_axis_title: str, line_axis_title: str, category_axis_title: str,
        subtitle: str | None = None,
    ):
        """One native combo chart -- `bar_name` on the primary (left) axis as
        columns, `line_name` on a secondary (right) axis as a line -- for two
        metrics of different scale (e.g. a 0-100% rate and a raw count) that
        would be unreadable sharing one axis. The two axes are scaled so the columns use the
        lower part of the plot and the line the upper part, so labels and markers don't
        pile on top of each other."""
        slide = self._new_slide()
        self._frame(slide, heading, description)
        box = self._body_box()

        categories, rotation = _axis_plan(categories)
        data = CategoryChartData()
        data.categories = categories
        data.add_series(bar_name, bar_values)
        data.add_series(line_name, line_values)

        gf = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, *box, data)
        chart = gf.chart
        scale = _combo_scale(bar_values, line_values)
        if not split_into_combo(
            chart, line_axis_title, *(scale["secondary"] if scale else (None, None)),
            sec_step=scale["step"] if scale else None, sec_format=scale["sec_format"] if scale else "General;;0",
        ):
            style_native_chart(chart, number_format=number_format_for(list(bar_values) + list(line_values)), single_series=False)
            set_axis_title(chart.value_axis, bar_axis_title)
            set_axis_title(chart.category_axis, category_axis_title)
            _tidy_category_axis(chart.category_axis, rotation)
            self._caption(slide, subtitle)
            self._footer(slide)
            return

        style.set_chart_default_font(chart, style.CHART_DATA_LABEL_FONT_PT, style.FONT_BODY)
        chart.has_title = False
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(style.CHART_FONT_PT)
        chart.legend.font.name = style.FONT_BODY

        bar_plot, line_plot = chart.plots[0], chart.plots[1]
        for plot, color, label_position, values, hide_zero in (
            (bar_plot, BAR_PALETTE[0], XL_LABEL_POSITION.OUTSIDE_END, bar_values, True),
            (line_plot, BAR_PALETTE[1], XL_LABEL_POSITION.ABOVE, line_values, False),
        ):
            plot.has_data_labels = True
            plot.data_labels.number_format = number_format_for(values, hide_zero=hide_zero)
            plot.data_labels.number_format_is_linked = False
            plot.data_labels.font.size = Pt(style.CHART_DATA_LABEL_FONT_PT)
            plot.data_labels.font.name = style.FONT_BODY
            plot.data_labels.position = label_position
            series = plot.series[0]
            if plot is line_plot:
                # The line's labels sit above its markers, in their own band of the plot.
                plot.data_labels.font.color.rgb = RGBColor.from_string("0B5CAD")
                plot.data_labels.font.bold = True
                series.format.line.color.rgb = color
                series.format.line.width = Pt(2.25)
                series.marker.format.fill.solid()
                series.marker.format.fill.fore_color.rgb = color
                series.marker.format.line.color.rgb = color
            else:
                series.format.fill.solid()
                series.format.fill.fore_color.rgb = color

        # After the split python-pptx's `chart.value_axis` is the SECONDARY (right) axis,
        # so the left/primary one has to be picked by position.
        primary = _primary_value_axis(chart)
        if scale:
            primary.minimum_scale = 0
            primary.maximum_scale = scale["primary_max"]
            if scale["percent_bars"]:  # a rate never exceeds 100: don't label the headroom above it
                primary.tick_labels.number_format = '[<=100]General;" "'
                primary.tick_labels.number_format_is_linked = False
        style_axes_grid(chart.category_axis, primary)
        chart.category_axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
        chart.category_axis.tick_labels.font.name = style.FONT_BODY
        primary.tick_labels.font.size = Pt(style.CHART_FONT_PT)
        primary.tick_labels.font.name = style.FONT_BODY
        set_axis_title(primary, bar_axis_title)
        set_axis_title(chart.category_axis, category_axis_title)
        _tidy_category_axis(chart.category_axis, rotation)
        self._caption(slide, subtitle)
        self._footer(slide)

    def add_scatter_slide(
        self, heading: str, description: str, points: list[tuple[float, float]], series_name: str,
        x_axis_title: str, y_axis_title: str, subtitle: str | None = None,
    ):
        """A native XY scatter: points are placed by their real x value (a column chart would space them evenly
        and misread a numeric axis)."""
        slide = self._new_slide()
        self._frame(slide, heading, description)
        box = self._body_box()

        data = XyChartData()
        series = data.add_series(series_name or "Series")
        for x, y in points:
            series.add_data_point(x, y)
        chart = slide.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER, *box, data).chart
        style.set_chart_default_font(chart, style.CHART_DATA_LABEL_FONT_PT, style.FONT_BODY)
        chart.has_title = False
        chart.has_legend = False
        plot = chart.plots[0]
        marker_series = plot.series[0]
        marker_series.format.line.fill.background()  # markers only, no connecting line
        marker_series.marker.style = XL_MARKER_STYLE.CIRCLE
        marker_series.marker.size = 9
        marker_series.marker.format.fill.solid()
        marker_series.marker.format.fill.fore_color.rgb = PRIMARY
        marker_series.marker.format.line.color.rgb = PRIMARY
        grid = RGBColor.from_string(style.GRIDLINE_COLOR_HEX)
        for axis, title in ((chart.category_axis, x_axis_title), (chart.value_axis, y_axis_title)):
            axis.has_major_gridlines = True
            axis.major_gridlines.format.line.color.rgb = grid
            axis.major_gridlines.format.line.width = Pt(0.75)
            axis.format.line.color.rgb = MUTED
            axis.tick_labels.font.size = Pt(style.CHART_FONT_PT)
            axis.tick_labels.font.name = style.FONT_BODY
            set_axis_title(axis, title)
        self._caption(slide, subtitle)
        self._footer(slide)

    def add_pie_slide(self, heading: str, description: str, labels: list[str], values: list[float], subtitle: str | None = None):
        slide = self._new_slide()
        self._frame(slide, heading, description)
        box = self._body_box()

        data = CategoryChartData()
        data.categories = [_short_label(label, 28) for label in labels]
        data.add_series(heading, [_to_number(v) for v in values])

        gf = slide.shapes.add_chart(XL_CHART_TYPE.PIE, *box, data)
        chart = gf.chart
        style.set_chart_default_font(chart, style.CHART_DATA_LABEL_FONT_PT, style.FONT_BODY)
        chart.has_title = False
        chart.has_legend = True
        chart.legend.position = XL_LEGEND_POSITION.RIGHT
        chart.legend.include_in_layout = False
        chart.legend.font.size = Pt(style.CHART_FONT_PT)
        chart.legend.font.name = style.FONT_BODY
        plot = chart.plots[0]
        plot.has_data_labels = True
        plot.data_labels.show_value = False
        plot.data_labels.show_percentage = True
        plot.data_labels.number_format = "0%"
        plot.data_labels.number_format_is_linked = False
        plot.data_labels.font.size = Pt(style.CHART_DATA_LABEL_FONT_PT)
        plot.data_labels.font.name = style.FONT_BODY
        plot.data_labels.font.color.rgb = DARK_TEXT
        plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END  # dark text stays readable on any slice colour
        for i, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = BAR_PALETTE[i % len(BAR_PALETTE)]
        self._caption(slide, subtitle)
        self._footer(slide)

    def add_table_slide(self, heading: str, description: str, columns: list[str], rows: list[dict], subtitle: str | None = None):
        slide = self._new_slide()
        self._frame(slide, heading, description)
        left, top, width, height = self._body_box()

        cols = columns[:MAX_TABLE_COLS]
        display_rows = rows[:MAX_TABLE_ROWS]
        if not cols or not display_rows:
            self._caption(slide, subtitle)
            self._footer(slide)
            return

        row_h = min(Inches(0.4), int(height / (len(display_rows) + 1)))
        gf = slide.shapes.add_table(len(display_rows) + 1, len(cols), left, top, width, row_h * (len(display_rows) + 1))
        table = gf.table

        for c, col in enumerate(cols):
            cell = table.cell(0, c)
            cell.text = str(col)
            cell.fill.solid()
            cell.fill.fore_color.rgb = PRIMARY
            p = cell.text_frame.paragraphs[0]
            p.font.size = Pt(style.CHART_FONT_PT)
            p.font.bold = True
            p.font.color.rgb = WHITE
            p.font.name = style.FONT_BODY

        for r, row in enumerate(display_rows, start=1):
            for c, col in enumerate(cols):
                cell = table.cell(r, c)
                cell.text = _blank_label(row.get(col))
                p = cell.text_frame.paragraphs[0]
                p.font.size = Pt(style.CHART_FONT_PT)
                p.font.color.rgb = DARK_TEXT
                p.font.name = style.FONT_BODY

        self._caption(slide, subtitle)
        self._footer(slide)

    def add_summary_slide(self, heading: str, bullets: list[str]):
        """Closing summary slide -- bullet points, not a prose paragraph,
        matching the reference deck's own closing slide (see
        final_summary_agent.py, which writes these bullets from the
        included analyses' own interpretations). `bullets` empty means no
        analysis was included to summarize."""
        slide = self._new_slide()
        self._frame(slide, self._t(heading))
        body_top = style.EXPLAIN_TOP + Inches(0.1)
        body_h = style.BODY_BOTTOM - body_top

        if not bullets:
            self._bullets(slide, [self._t(NO_OVERALL_CAPTION)], style.MARGIN_X, body_top, style.CONTENT_W, body_h)
        else:
            longest = max(len(b) for b in bullets)
            size = 18 if longest < 200 and len(bullets) <= 4 else 16 if longest < 320 else 14
            self._bullets(slide, bullets, style.MARGIN_X, body_top, style.CONTENT_W, body_h, size=size)
        self._footer(slide)

    def save_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.prs.save(buffer)
        return buffer.getvalue()


def _axis_title(chart_spec: dict, axis: str, fallback: str = "") -> str:
    """The title the chart itself gives an axis ("xaxis"/"yaxis"), else `fallback` -- more reliable than the
    table's first column, which isn't always the x axis (a heatmap's table starts with its row field)."""
    title = ((chart_spec.get("layout") or {}).get(axis) or {}).get("title")
    text = title.get("text") if isinstance(title, dict) else title
    return str(text) if text else fallback


def _trace_xy(trace: dict) -> tuple[list, list]:
    if "labels" in trace and "values" in trace:
        return list(trace.get("labels") or []), list(trace.get("values") or [])
    return list(trace.get("x") or []), list(trace.get("y") or [])


def _numeric_columns(result_table: list[dict], result_columns: list[str]) -> list[str]:
    numeric = []
    for col in result_columns:
        values = [row.get(col) for row in result_table]
        if values and any(_is_numeric(v) for v in values):
            numeric.append(col)
    return numeric


def _label_column(result_columns: list[str], numeric_columns: list[str]) -> str | None:
    return next((c for c in result_columns if c not in numeric_columns), result_columns[0] if result_columns else None)


def _numeric_xy(trace: dict) -> bool:
    """True when a trace has numeric x AND y values (so it can be drawn as a real scatter)."""
    xs, ys = _trace_xy(trace)
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    return len(pairs) >= 2 and all(_is_numeric(x) and _is_numeric(y) for x, y in pairs)


def _heatmap_series(trace: dict, max_series: int = 6) -> tuple[list[str], list[tuple[str, list[float]]]]:
    """A heatmap trace as grouped-column data: its x labels are the categories and each y row becomes one
    series. With more than `max_series` rows, the ones with the largest totals are kept."""
    xs = [str(x) for x in (trace.get("x") or [])]
    ys = [str(y) for y in (trace.get("y") or [])]
    z = trace.get("z") or []
    if not xs or not ys or not z:
        return [], []
    rows = []
    for name, cells in zip(ys, z):
        values = [_to_number(v) for v in list(cells)[: len(xs)]]
        rows.append((name, values + [0.0] * (len(xs) - len(values))))
    rows.sort(key=lambda r: sum(r[1]), reverse=True)
    return xs, rows[:max_series]


def _bar_series(
    traces: list[dict], result_table: list[dict], result_columns: list[str], fallback_name: str,
) -> tuple[list[str], list[tuple[str, list[float]]]]:
    """Prefers the entry's own already-computed Plotly traces (real x/y
    arrays); falls back to reshaping result_table when a trace is missing or
    empty (e.g. a "scatter" chart_type, whose trace uses x/y the same way)."""
    categories: list[str] = []
    series: list[tuple[str, list[float]]] = []
    for trace in traces[:6]:
        xs, ys = _trace_xy(trace)
        if not xs or not ys:
            continue
        if not categories:
            categories = [str(x) for x in xs]
        name = trace.get("name") or fallback_name or "Series"
        series.append((name, [_to_number(v) for v in ys]))
    if series:
        return categories, series

    if result_table and result_columns:
        numeric = _numeric_columns(result_table, result_columns)
        label_col = _label_column(result_columns, numeric)
        if label_col and numeric:
            rows = result_table[:MAX_CHART_ROWS]
            categories = [_blank_label(row.get(label_col)) for row in rows]
            for metric in numeric[:4]:
                series.append((metric, [_to_number(row.get(metric)) for row in rows]))
    return categories, series


def translate_entry_texts(entries: list[dict], language: str) -> dict[str, str]:
    """Batch-translates every entry's name (its slide heading) and
    interpretation (its slide/preview caption) in one call -- natural-
    language text the Analysis Agent or the PM itself wrote, never a raw
    data value (a number, column name, or category value from the source
    spreadsheet), which always stays exactly as it appears in the uploaded
    file. Shared by build_report (the .pptx export) and the Report page's
    /translations preview endpoint, so the on-screen preview always matches
    what the download will actually say."""
    if language == "en":
        return {}
    texts: list[str] = []
    for entry in entries:
        name = entry.get("name")
        if name:
            texts.append(name)
        interpretation = entry.get("interpretation")
        if interpretation:
            texts.append(interpretation)
    if not texts:
        return {}
    return translation_service.translate_many(texts, language)


def _add_entry_slide(builder: ReportBuilder, entry: dict, content_phrases: dict[str, str] | None = None) -> bool:
    """Adds one slide for one done AnalysisRepositoryEntry-shaped dict.
    Returns False if the entry has nothing renderable (never raises -- one
    bad entry shouldn't break the whole export)."""
    content_phrases = content_phrases or {}
    raw_heading = entry.get("name") or "Analysis"
    heading = content_phrases.get(raw_heading, raw_heading)
    # Every slide (roots included) leads with its number so a drill-down
    # reads as "2.1  ..." right after its parent "2  ..."; the subtitle
    # (filter + rank line) only exists on drill-down levels.
    number = entry.get("slide_number")
    if number:
        heading = f"{number}  {heading}"
    subtitle = entry.get("subtitle") or None
    raw_description = entry.get("interpretation") or entry.get("description") or ""
    description = content_phrases.get(raw_description, raw_description) if raw_description else raw_description
    description = short_explanation(description) if entry.get("interpretation") else description
    chart_type = entry.get("chart_type")
    chart_spec = entry.get("chart_spec") or {}
    traces = chart_spec.get("data") or []
    result_table = entry.get("result_table") or []
    result_columns = entry.get("result_columns") or []

    # A heatmap's trace is a matrix (x columns, y rows, z cells), not x/y series: drawn as grouped columns
    # (one series per row), the closest native chart. This is decided by the trace itself, so a heatmap that
    # arrives labelled as another chart type is never turned into a row of zeros.
    if traces and traces[0].get("type") == "heatmap":
        categories, series = _heatmap_series(traces[0])
        if categories and series:
            colorbar = ((traces[0].get("colorbar") or {}).get("title") or {})
            builder.add_bar_or_line_slide(
                heading, description, categories, series,
                value_axis_title=colorbar.get("text") or "Value",
                category_axis_title=_axis_title(chart_spec, "xaxis", result_columns[0] if result_columns else ""),
                is_line=False, subtitle=subtitle,
            )
            return True

    elif chart_type == "pie":
        trace = traces[0] if traces else {}
        labels, values = _trace_xy(trace)
        if not (labels and values) and result_table and result_columns:
            numeric = _numeric_columns(result_table, result_columns)
            label_col = _label_column(result_columns, numeric)
            if label_col and numeric:
                rows = result_table[:MAX_CHART_ROWS]
                labels = [_blank_label(row.get(label_col)) for row in rows]
                values = [row.get(numeric[0]) for row in rows]
        if labels and values:
            builder.add_pie_slide(heading, description, list(labels)[:MAX_CHART_ROWS], list(values)[:MAX_CHART_ROWS], subtitle=subtitle)
            return True

    elif chart_type == "combo":
        categories, series = _bar_series(traces, result_table, result_columns, entry.get("name"))
        if categories and len(series) >= 2:
            (bar_name, bar_values), (line_name, line_values) = series[0], series[1]
            category_axis_title = _axis_title(chart_spec, "xaxis", result_columns[0] if result_columns else "")
            builder.add_combo_slide(
                heading, description, categories, bar_name, bar_values, line_name, line_values,
                bar_axis_title=bar_name, line_axis_title=line_name, category_axis_title=category_axis_title,
                subtitle=subtitle,
            )
            return True

    elif chart_type == "scatter" and traces and _numeric_xy(traces[0]):
        xs, ys = _trace_xy(traces[0])
        pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if _is_numeric(x) and _is_numeric(y)]
        builder.add_scatter_slide(
            heading, description, pairs, traces[0].get("name") or entry.get("name") or "",
            x_axis_title=_axis_title(chart_spec, "xaxis", result_columns[0] if result_columns else ""),
            y_axis_title=_axis_title(chart_spec, "yaxis", traces[0].get("name") or ""), subtitle=subtitle,
        )
        return True

    elif chart_type in ("bar", "grouped_bar", "line", "scatter"):
        categories, series = _bar_series(traces, result_table, result_columns, entry.get("name"))
        if categories and series:
            value_axis_title = series[0][0] if len(series) == 1 else "Value"
            category_axis_title = _axis_title(chart_spec, "xaxis", result_columns[0] if result_columns else "")
            builder.add_bar_or_line_slide(
                heading, description, categories, series,
                value_axis_title=value_axis_title, category_axis_title=category_axis_title,
                is_line=(chart_type == "line"), subtitle=subtitle,
            )
            return True

    # heatmap / table / no usable chart data -> plain data table, the same
    # fallback the on-screen AnalysisChart component uses.
    if result_table and result_columns:
        builder.add_table_slide(heading, description, result_columns, result_table[:MAX_TABLE_ROWS], subtitle=subtitle)
        return True

    return False


def build_report(
    source_label: str, df: pd.DataFrame | None, entries: list[dict], summary_bullets: list[str],
    language: str = "en",
) -> bytes:
    """Builds the deck from `entries` (already filtered by the router to
    run_status == "done" analyses the PM chose to include) plus
    `summary_bullets` (see final_summary_agent.generate_summary) for the
    closing slide -- never recomputes either itself. `language` optionally
    translates the report's own fixed English phrases (see
    TRANSLATABLE_PHRASES) plus each entry's name (its slide heading) and
    interpretation (its caption) via translation_service (see
    translate_entry_texts) -- never a raw data value (a number, column
    name, or category value from the source spreadsheet), which always
    stays exactly as it appears in the uploaded file."""
    phrases = translation_service.translate_many(TRANSLATABLE_PHRASES, language) if language != "en" else {}
    content_phrases = translate_entry_texts(entries, language)
    builder = ReportBuilder(phrases=phrases)
    dates = _date_range_label(df) if df is not None else None
    stem = re.sub(r"\.(xlsx|xlsm|xls|csv)$", "", source_label or "", flags=re.IGNORECASE)
    builder.add_title_slide("Cold Chain Analysis", stem or None, dates)

    for entry in entries:
        _add_entry_slide(builder, entry, content_phrases)

    builder.add_summary_slide("Summary", summary_bullets)
    return builder.save_bytes()
