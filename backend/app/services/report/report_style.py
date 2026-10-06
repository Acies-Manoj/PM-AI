"""Shared visual constants for the PPTX report builder -- one place to hold
the brand palette (matches frontend/src/styles/theme.css) and layout numbers
so report_generator.py and chart_xml.py never hardcode a hex or an Inches()
value independently."""

from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.config import APP_DIR

# 16:9 widescreen (13.333in x 7.5in) -- the same slide size as the PM's reference
# deck, so a generated report opens and prints exactly like theirs.
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)

# Layout grid. Title top-left, a one/two-line explanation directly under it, the chart
# full width below, a small caption under the chart, the footer along the bottom and the
# logo top-right. Everything left/right aligns to MARGIN_X / CONTENT_W.
MARGIN_X = Inches(0.67)
CONTENT_W = Inches(12.0)                 # MARGIN_X .. MARGIN_X + CONTENT_W (12.67in)
TITLE_TOP = Inches(0.32)
TITLE_W = Inches(10.3)                   # stops short of the logo
TITLE_H = Inches(0.7)
EXPLAIN_TOP = Inches(1.12)               # one/two-line explanation under the title
EXPLAIN_H = Inches(0.75)
EXPLAIN_PT = 18
BODY_TOP = Inches(2.0)                   # chart / table area
BODY_BOTTOM = Inches(6.5)
CAPTION_TOP = Inches(6.58)               # small grey caption under the chart (drill-down filter)
CAPTION_H = Inches(0.3)
FOOTER_Y = Inches(7.08)
FOOTER_PT = 10
FOOTER_HEX = "5C8AA5"                    # the steel-blue footer text of the Carrier footer sample
EXPLAIN_MAX_CHARS = 190                  # about two lines at 18pt across 12in

# Arial throughout, like the reference deck's theme.
FONT_BODY = "Arial"
FONT_TITLE = "Arial"
PROGRAM_TITLE = "Program Manager AI — Cold Chain Analysis"
PROPRIETARY_TEXT = "Proprietary and Confidential"

# Chart text: one size for ticks/legend/axis titles, a touch smaller for data labels.
CHART_FONT_PT = 11
CHART_DATA_LABEL_FONT_PT = 10
CHART_AXIS_TITLE_FONT_PT = 11

ASSETS_DIR = APP_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "carrier-logo.png"
# Top-right, right edge on the content margin (the reference deck's logo sits in the
# same corner). The logo's own aspect ratio is 700x279 (2.5:1).
LOGO_WIDTH = Inches(1.32)
LOGO_HEIGHT = Inches(0.526)
LOGO_LEFT = MARGIN_X + CONTENT_W - LOGO_WIDTH
LOGO_TOP = Inches(0.4)
TITLE_LOGO_WIDTH = Inches(2.0)
TITLE_LOGO_HEIGHT = Inches(0.797)

# Cover slide: built from this layout of assets/carrier-template.pptx (logo top-left, title
# block, photo grid and three colour blocks on the right).
COVER_LAYOUT_NAME = "Cover 1, example 1"
COVER_TOP_BLOCK_HEX = "0A2EF5"          # the sample's blue top block (the template ships it black)

# The permanent, built-in base for every report -- report_generator.build_report
# falls back to this whenever no template was explicitly uploaded to
# report_template_store (see routers/analysis.py's /report-template), so a
# fresh session with nothing uploaded still gets this exact look.
DEFAULT_TEMPLATE_PATH = ASSETS_DIR / "carrier-template.pptx"

# Brand colours. #010198 is the Carrier blue the client specified; the rest of the
# palette is the reference deck's own accent set (light blue, slate, green, amber).
BAR_COLOR_HEX = "010198"       # primary: titles, rule, first series
LINE_COLOR_HEX = "1891F6"      # secondary: line series / second bar series
WHITE_HEX = "FFFFFF"
DARK_TEXT_HEX = "1B2333"
MUTED_TEXT_HEX = "5B6478"
PANEL_HEX = "F3F5FA"           # commentary panel background
REFERENCE_LINE_COLOR_HEX = "C62828"
GRIDLINE_COLOR_HEX = "D9DCE3"  # light, low-contrast -- gridlines frame the plot without competing with the data

# Categorical slots for a chart with more than one series -- ordered so
# adjacent slots stay distinguishable.
BAR_PALETTE_HEX = ["010198", "1891F6", "617080", "61B549", "F6D009", "BAC0D0"]

Y_AXIS_SHIPMENT_COUNT_LABEL = "Shipments"

# A two-level grouped-bar slide renders one bar per (level1, level2) pair
# rather than folding low-volume pairs into an "Other" series, so this caps
# total bars for readability instead -- the lowest-value pairs are dropped.
MULTI_LEVEL_MAX_LEAVES = 40
BLANK_LABEL = "(blank)"  # matches Excel's own PivotChart label for a missing group value


def set_chart_default_font(chart, size_pt: int, font_name: str) -> None:
    """Overrides a chart's own auto-generated chart-space-level default text
    style -- python-pptx creates one on every add_chart() call (sz="1800"
    i.e. 18pt, no typeface, so it silently inherits the theme's own default
    Latin font, e.g. Arial). Every more specific override this codebase sets
    (axis titles, tick labels, data labels, legend) already wins over this,
    but leaving the chart-space default untouched at 18pt/Arial is exactly
    what makes PowerPoint's own selection UI report "Arial 18" for anything
    that doesn't have a closer override -- lives here (not report_generator
    or chart_xml) since both of those need it and importing either into the
    other would be circular."""
    defRPr = chart._chartSpace.find(qn("c:txPr")).find(qn("a:p")).find(qn("a:pPr")).find(qn("a:defRPr"))
    defRPr.set("sz", str(size_pt * 100))
    latin = defRPr.find(qn("a:latin"))
    if latin is None:
        latin = defRPr.makeelement(qn("a:latin"), {})
        defRPr.append(latin)
    latin.set("typeface", font_name)
