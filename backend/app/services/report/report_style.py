"""Shared visual constants for the PPTX report builder -- one place to hold
the brand palette (matches frontend/src/styles/theme.css) and layout numbers
so report_generator.py never hardcodes a hex or an Inches()
value independently."""

from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

from app.config import APP_DIR

SLIDE_W = Inches(10)
SLIDE_H = Inches(7.5)
# The heading is plain left-aligned text on a white slide (no full-width
# color band -- that reads as an AI-generated filler element), so this is
# just the vertical space it and the caption underneath it need, not a
# shape height.
HEADER_HEIGHT = Inches(0.5)
CHART_TOP = Inches(0.95)

# Matches the Carrier PowerPoint template's own font list.
FONT_BODY = "Franklin Gothic Medium Cond"  # captions, footer, summary copy -- 12pt
FONT_TITLE = "Franklin Gothic Demi Cond"   # each slide's own heading only -- 24pt
PROGRAM_TITLE = "Program Manager AI — Cold Chain Analysis"
PROPRIETARY_TEXT = "Proprietary and Confidential"

SIDE_BAND_WIDTH = Inches(0.12)  # solid navy strip along the slide's right edge, matching the Carrier template

# Dark-navy frame just inside the slide edges -- every content slide (Slide 2
# onward) gets one; the cover/title slide doesn't.
BORDER_MARGIN = Inches(0.08)
BORDER_WEIGHT = Pt(1.75)

# Every chart text element (legend/tick labels, data-label numbers, axis
# titles) uses the same size -- one uniform 10pt (sz="1000" in the raw OOXML)
# across the whole chart, by explicit standing choice, rather than the
# previous staggered per-role sizes.
CHART_FONT_PT = 10
CHART_DATA_LABEL_FONT_PT = 10
CHART_AXIS_TITLE_FONT_PT = 10

ASSETS_DIR = APP_DIR / "assets"
LOGO_PATH = ASSETS_DIR / "carrier-logo.png"
LOGO_WIDTH = Inches(0.7)
LOGO_HEIGHT = Inches(0.28)  # matches the logo's own aspect ratio (700x279)
TITLE_LOGO_WIDTH = Inches(1.6)   # the title slide's own larger mark -- same 2.5:1 aspect ratio
TITLE_LOGO_HEIGHT = Inches(0.64)

# Hex values below mirror frontend/src/styles/theme.css so the exported deck
# reads as the same product as the web app.
BAR_COLOR_HEX = "152C73"       # --carrier-blue
WHITE_HEX = "FFFFFF"
DARK_TEXT_HEX = "1B2333"       # --color-text
MUTED_TEXT_HEX = "5B6478"      # --color-text-muted
GRIDLINE_COLOR_HEX = "D9DCE3"  # light, low-contrast -- gridlines/axis lines frame the plot without competing with the data

# Categorical slots for a chart with more than one series -- ordered so
# adjacent slots stay distinguishable.
BAR_PALETTE_HEX = ["152C73", "1891F6", "6F42C1", "0F8B8D", "8A5A10", "1A8F5E"]

BLANK_LABEL = "(blank)"  # matches Excel's own PivotChart label for a missing group value


def set_chart_default_font(chart, size_pt: int, font_name: str) -> None:
    """Overrides a chart's own auto-generated chart-space-level default text
    style -- python-pptx creates one on every add_chart() call (sz="1800"
    i.e. 18pt, no typeface, so it silently inherits the theme's own default
    Latin font, e.g. Arial). Every more specific override this codebase sets
    (axis titles, tick labels, data labels, legend) already wins over this,
    but leaving the chart-space default untouched at 18pt/Arial is exactly
    what makes PowerPoint's own selection UI report "Arial 18" for anything
    that doesn't have a closer override -- lives here (not report_generator)
    since report_generator needs it and importing it there would be
    circular."""
    defRPr = chart._chartSpace.find(qn("c:txPr")).find(qn("a:p")).find(qn("a:pPr")).find(qn("a:defRPr"))
    defRPr.set("sz", str(size_pt * 100))
    latin = defRPr.find(qn("a:latin"))
    if latin is None:
        latin = defRPr.makeelement(qn("a:latin"), {})
        defRPr.append(latin)
    latin.set("typeface", font_name)
