"""
Builds a downloadable .pptx report from analyses already computed on the
Analysis page: one slide per included, run_status == "done"
AnalysisRepositoryEntry (see analysis_agent.py / schemas.py), plus a summary
slide from the session's last-computed OverallAnalysisReport. Every chart is
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
import io
import re

import numpy as np
import pandas as pd
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

from app.schemas import OverallAnalysisReport
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
# Highlight-label keyword prefixes (see overall_analysis.py's
# build_highlights) -- translated once, then substituted back onto the
# FRONT of the label ahead of whatever data-derived text follows (a
# feature/analysis name), via translate_highlight_label below, so a data
# value is never itself sent to the translator.
HIGHLIGHT_LABEL_PREFIXES = ["Total Rows Analyzed", "Most common", "Highest", "Lowest", "Avg"]

TRANSLATABLE_PHRASES = [SUMMARY_HEADING, NO_OVERALL_CAPTION, style.PROPRIETARY_TEXT, *HIGHLIGHT_LABEL_PREFIXES]


def translate_highlight_label(label: str, phrases: dict[str, str]) -> str:
    """Swaps in the translated version of whichever HIGHLIGHT_LABEL_PREFIXES
    keyword `label` starts with, leaving the rest of the label (a
    feature/analysis name -- data, not a phrase) untouched."""
    for prefix in HIGHLIGHT_LABEL_PREFIXES:
        if label.startswith(prefix):
            return phrases.get(prefix, prefix) + label[len(prefix):]
    return label


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
    """Left value-axis line + bottom category-axis line, both made visible,
    plus horizontal (value) and vertical (category) major gridlines --
    frames the plot without a full boxed border."""
    grid_color = RGBColor.from_string(style.GRIDLINE_COLOR_HEX)
    for axis in (category_axis, value_axis):
        axis.has_major_gridlines = True
        axis.has_minor_gridlines = False
        axis.major_gridlines.format.line.color.rgb = grid_color
        axis.major_gridlines.format.line.width = Pt(0.75)
        axis.format.line.color.rgb = MUTED
        axis.format.line.width = Pt(1)


def set_axis_title(axis, text: str):
    axis.axis_title.text_frame.text = text
    axis.axis_title.text_frame.paragraphs[0].font.size = Pt(style.CHART_AXIS_TITLE_FONT_PT)
    axis.axis_title.text_frame.paragraphs[0].font.name = style.FONT_BODY


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
    plot.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
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


class ReportBuilder:
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

    def _new_slide(self, bordered: bool = True):
        slide = self.prs.slides.add_slide(self._blank)
        self.slide_count += 1
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = WHITE
        self._side_band(slide)
        if bordered:
            self._add_border(slide)
        return slide

    def _add_border(self, slide):
        # A thin dark-navy frame just inside the slide edges -- every
        # content slide (Slide 2 onward) gets one; the cover slide doesn't.
        border = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, style.BORDER_MARGIN, style.BORDER_MARGIN,
            style.SLIDE_W - 2 * style.BORDER_MARGIN, style.SLIDE_H - 2 * style.BORDER_MARGIN,
        )
        border.fill.background()
        border.line.color.rgb = PRIMARY
        border.line.width = style.BORDER_WEIGHT
        border.shadow.inherit = False

    def _side_band(self, slide):
        # Solid navy strip down the slide's right edge, matching the Carrier
        # template's own master slide -- every content box already keeps a
        # 0.5in right margin, well clear of this band.
        band = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, style.SLIDE_W - style.SIDE_BAND_WIDTH, 0, style.SIDE_BAND_WIDTH, style.SLIDE_H
        )
        band.fill.solid()
        band.fill.fore_color.rgb = PRIMARY
        band.line.fill.background()
        band.shadow.inherit = False

    def _header(self, slide, heading: str):
        # Plain left-aligned text on the white slide background -- no
        # full-width color band. A decorative bar spanning the slide reads
        # as filler, and the reference deck's own clean look skips it too.
        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.22), style.SLIDE_W - Inches(1.0), style.HEADER_HEIGHT)
        tf = box.text_frame
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = heading
        p.font.size = Pt(24)
        p.font.bold = True
        p.font.color.rgb = PRIMARY
        p.font.name = style.FONT_TITLE

    def _footer(self, slide):
        logo_top = style.SLIDE_H - Inches(0.365)
        slide.shapes.add_picture(str(style.LOGO_PATH), Inches(0.4), logo_top, style.LOGO_WIDTH, style.LOGO_HEIGHT)

        tb = slide.shapes.add_textbox(Inches(1.25), style.SLIDE_H - Inches(0.35), Inches(2.5), Inches(0.25))
        p = tb.text_frame.paragraphs[0]
        p.text = style.PROGRAM_TITLE
        p.font.size = Pt(12)
        p.font.color.rgb = MUTED
        p.font.name = style.FONT_BODY

        proprietary = slide.shapes.add_textbox(Inches(3.85), style.SLIDE_H - Inches(0.35), Inches(2.3), Inches(0.25))
        pr = proprietary.text_frame.paragraphs[0]
        pr.text = self._t(style.PROPRIETARY_TEXT)
        pr.font.size = Pt(12)
        pr.alignment = PP_ALIGN.CENTER
        pr.font.color.rgb = MUTED
        pr.font.name = style.FONT_BODY

        page = slide.shapes.add_textbox(Inches(8.6), style.SLIDE_H - Inches(0.35), Inches(0.9), Inches(0.25))
        pp = page.text_frame.paragraphs[0]
        pp.text = str(self.slide_count)
        pp.font.size = Pt(12)
        pp.alignment = PP_ALIGN.RIGHT
        pp.font.color.rgb = MUTED
        pp.font.name = style.FONT_BODY

    def _caption(self, slide, text: str, top):
        box = slide.shapes.add_textbox(Inches(0.5), top, style.SLIDE_W - Inches(1.0), Inches(0.35))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = text
        run = tf.paragraphs[0].runs[0]
        run.font.size = Pt(12)
        run.font.color.rgb = MUTED
        run.font.name = style.FONT_BODY

    # -- slides ---------------------------------------------------------------
    def add_title_slide(self, title: str, subtitle: str | None):
        """Cover slide: logo top-left, title/subtitle on the left, and a
        photo-collage-shaped block of flat colour on the right -- no actual
        photography is available for this deck, so solid colour panels stand
        in for where a Carrier-branded cover would place its imagery, rather
        than faking or downloading photos."""
        slide = self._new_slide(bordered=False)

        slide.shapes.add_picture(str(style.LOGO_PATH), Inches(0.4), Inches(0.35), style.TITLE_LOGO_WIDTH, style.TITLE_LOGO_HEIGHT)

        tf = slide.shapes.add_textbox(Inches(0.4), Inches(3.1), Inches(3.9), Inches(1.6)).text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = title
        p.font.size = Pt(28)
        p.font.bold = True
        p.font.color.rgb = PRIMARY
        p.font.name = style.FONT_TITLE
        if subtitle:
            p2 = tf.add_paragraph()
            p2.text = subtitle
            p2.font.size = Pt(13)
            p2.font.color.rgb = MUTED
            p2.font.name = style.FONT_BODY

        # Photo-collage stand-in: one large panel above two smaller ones,
        # occupying the right half of the slide (clear of the side band).
        collage_x, collage_w = Inches(4.6), style.SLIDE_W - Inches(4.6) - Inches(0.3)
        large = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, collage_x, Inches(0.5), collage_w, Inches(3.6))
        large.fill.solid()
        large.fill.fore_color.rgb = PRIMARY
        large.line.fill.background()
        large.shadow.inherit = False

        gap = Inches(0.2)
        small_w = (collage_w - gap) / 2
        for i, hex_color in enumerate((style.BAR_PALETTE_HEX[3], style.BAR_PALETTE_HEX[4])):  # teal, amber
            small = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, collage_x + i * (small_w + gap), Inches(4.3), small_w, Inches(2.4)
            )
            small.fill.solid()
            small.fill.fore_color.rgb = RGBColor.from_string(hex_color)
            small.line.fill.background()
            small.shadow.inherit = False

    def add_bar_or_line_slide(
        self, heading: str, description: str, categories: list[str], series: list[tuple[str, list[float]]],
        value_axis_title: str, category_axis_title: str, is_line: bool,
    ):
        """One native column (or line) chart -- `series` is one or more
        (name, values) pairs sharing `categories`, so this covers a plain
        single-series bar, a multi-series "grouped bar", and a line trend
        alike."""
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        data = CategoryChartData()
        data.categories = categories
        for name, values in series:
            data.add_series(name, values)

        chart_type = XL_CHART_TYPE.LINE_MARKERS if is_line else XL_CHART_TYPE.COLUMN_CLUSTERED
        gf = slide.shapes.add_chart(
            chart_type, Inches(0.5), style.CHART_TOP, style.SLIDE_W - Inches(1.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
        chart = gf.chart
        style_native_chart(chart, number_format="#,##0.##", single_series=len(series) == 1)
        set_axis_title(chart.value_axis, value_axis_title)
        set_axis_title(chart.category_axis, category_axis_title)
        self._footer(slide)

    def add_pie_slide(self, heading: str, description: str, labels: list[str], values: list[float]):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        data = CategoryChartData()
        data.categories = [str(label) for label in labels]
        data.add_series(heading, [_to_number(v) for v in values])

        gf = slide.shapes.add_chart(
            XL_CHART_TYPE.PIE, Inches(1.5), style.CHART_TOP, style.SLIDE_W - Inches(3.0), style.SLIDE_H - style.CHART_TOP - Inches(0.6), data,
        )
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
        plot.data_labels.font.color.rgb = WHITE
        for i, point in enumerate(plot.series[0].points):
            point.format.fill.solid()
            point.format.fill.fore_color.rgb = BAR_PALETTE[i % len(BAR_PALETTE)]
        self._footer(slide)

    def add_table_slide(self, heading: str, description: str, columns: list[str], rows: list[dict]):
        slide = self._new_slide()
        self._header(slide, heading)
        self._caption(slide, description, top=Inches(0.6))

        cols = columns[:MAX_TABLE_COLS]
        display_rows = rows[:MAX_TABLE_ROWS]
        if not cols or not display_rows:
            self._footer(slide)
            return

        table_top = Inches(1.3)
        table_height = style.SLIDE_H - table_top - Inches(0.6)
        gf = slide.shapes.add_table(len(display_rows) + 1, len(cols), Inches(0.5), table_top, style.SLIDE_W - Inches(1.0), table_height)
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

        self._footer(slide)

    def add_summary_slide(self, heading: str, overall: OverallAnalysisReport | None):
        slide = self._new_slide()
        self._header(slide, self._t(heading))

        if overall is None:
            self._caption(slide, self._t(NO_OVERALL_CAPTION), top=Inches(0.6))
            self._footer(slide)
            return

        box = slide.shapes.add_textbox(Inches(0.5), Inches(0.75), style.SLIDE_W - Inches(1.0), Inches(1.5))
        tf = box.text_frame
        tf.word_wrap = True
        tf.text = overall.narrative
        tf.paragraphs[0].font.size = Pt(12)
        tf.paragraphs[0].font.color.rgb = DARK_TEXT
        tf.paragraphs[0].font.name = style.FONT_BODY

        list_box = slide.shapes.add_textbox(Inches(0.5), Inches(2.4), style.SLIDE_W - Inches(1.0), style.SLIDE_H - Inches(2.9))
        tf2 = list_box.text_frame
        tf2.word_wrap = True
        for i, h in enumerate(overall.highlights):
            p = tf2.paragraphs[0] if i == 0 else tf2.add_paragraph()
            p.text = f"•  {translate_highlight_label(h.label, self.phrases)}: {h.value}"
            p.font.size = Pt(12)
            p.font.color.rgb = DARK_TEXT
            p.font.name = style.FONT_BODY
            p.space_after = Pt(8)
        self._footer(slide)

    def save_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self.prs.save(buffer)
        return buffer.getvalue()


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


def _add_entry_slide(builder: ReportBuilder, entry: dict) -> bool:
    """Adds one slide for one done AnalysisRepositoryEntry-shaped dict.
    Returns False if the entry has nothing renderable (never raises -- one
    bad entry shouldn't break the whole export)."""
    heading = entry.get("name") or "Analysis"
    description = entry.get("interpretation") or entry.get("description") or ""
    chart_type = entry.get("chart_type")
    chart_spec = entry.get("chart_spec") or {}
    traces = chart_spec.get("data") or []
    result_table = entry.get("result_table") or []
    result_columns = entry.get("result_columns") or []

    if chart_type == "pie":
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
            builder.add_pie_slide(heading, description, list(labels)[:MAX_CHART_ROWS], list(values)[:MAX_CHART_ROWS])
            return True

    elif chart_type in ("bar", "grouped_bar", "line", "scatter"):
        categories, series = _bar_series(traces, result_table, result_columns, entry.get("name"))
        if categories and series:
            value_axis_title = series[0][0] if len(series) == 1 else "Value"
            category_axis_title = result_columns[0] if result_columns else ""
            builder.add_bar_or_line_slide(
                heading, description, categories, series,
                value_axis_title=value_axis_title, category_axis_title=category_axis_title,
                is_line=(chart_type == "line"),
            )
            return True

    # heatmap / table / no usable chart data -> plain data table, the same
    # fallback the on-screen AnalysisChart component uses.
    if result_table and result_columns:
        builder.add_table_slide(heading, description, result_columns, result_table[:MAX_TABLE_ROWS])
        return True

    return False


def build_report(
    source_label: str, df: pd.DataFrame | None, entries: list[dict], overall: OverallAnalysisReport | None,
    language: str = "en",
) -> bytes:
    """Builds the deck from `entries` (already filtered by the router to
    run_status == "done" analyses the PM chose to include) plus whatever
    overall analysis was last computed on the Analysis page -- never
    recomputes either itself. `language` optionally translates the report's
    own fixed English phrases (see TRANSLATABLE_PHRASES) via
    translation_service -- never the underlying data (analysis names,
    interpretations, column names, category values), which always stays
    exactly as it appears in the source spreadsheet / as the Analysis Agent
    wrote it."""
    phrases = translation_service.translate_many(TRANSLATABLE_PHRASES, language) if language != "en" else {}
    builder = ReportBuilder(phrases=phrases)
    subtitle = _date_range_label(df) if df is not None else None
    builder.add_title_slide(source_label, subtitle)

    for entry in entries:
        _add_entry_slide(builder, entry)

    builder.add_summary_slide("Summary", overall)
    return builder.save_bytes()
