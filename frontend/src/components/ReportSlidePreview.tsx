import { useMemo } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { ReportSlide, ReportSlideChart } from "../api/audit";
import "./ReportSlidePreview.css";

const Plot = createPlotlyComponent(Plotly);

// Same palette the exported deck uses (report_style.py's BAR_COLOR_HEX /
// LINE_COLOR_HEX), so a slide looks the same here and in PowerPoint.
const BAR_COLOR = "#152C73";
const LINE_COLOR = "#1891F6";

const PLOTLY_CONFIG: Partial<Plotly.Config> = { displayModeBar: false, displaylogo: false, responsive: true, staticPlot: true };
const AXIS_FONT = { family: "inherit", size: 9.5, color: "#5B6478" };
const BASE_LAYOUT: Partial<Plotly.Layout> = {
  margin: { l: 46, r: 46, t: 10, b: 74 },
  height: 260,
  font: AXIS_FONT,
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  showlegend: false,
};

interface ReportSlidePreviewProps {
  slide: ReportSlide;
  /** 1-based position in the deck as it will actually be exported -- i.e.
   * counting only the slides that are still selected. */
  number: number | null;
  /** Omitted for the cover, which isn't the user's to switch off. */
  onToggle?: () => void;
  busy?: boolean;
}

/**
 * One slide of the planned deck, drawn from the plan the backend hands back
 * (see report_generator.plan_report). The chart data here is the very same
 * data python-pptx is given, not a second computation of it -- which is what
 * makes this a preview rather than an approximation.
 */
export default function ReportSlidePreview({ slide, number, onToggle, busy }: ReportSlidePreviewProps) {
  return (
    <article className={`slide-preview ${slide.included ? "" : "slide-preview--off"}`}>
      <header className="slide-preview__bar">
        <label className="slide-preview__pick">
          <input
            type="checkbox"
            checked={slide.included}
            disabled={!onToggle || busy}
            onChange={() => onToggle?.()}
            aria-label={`Include "${slide.title}" in the report`}
          />
          <span>{slide.included ? (number !== null ? `Slide ${number}` : "Included") : "Left out"}</span>
        </label>
        <span className="slide-preview__kind">
          {slide.kind === "cover" ? "Cover" : slide.kind === "summary" ? "Summary" : slide.combo_label ?? "Chart"}
        </span>
      </header>

      <div className="slide-preview__canvas">
        <h4 className="slide-preview__title">{slide.title}</h4>
        {slide.subtitle && <p className="slide-preview__subtitle">{slide.subtitle}</p>}

        {slide.kind === "summary" && (
          <>
            {slide.narrative && <p className="slide-preview__narrative">{slide.narrative}</p>}
            {slide.bullets.length > 0 ? (
              <ul className="slide-preview__bullets">
                {slide.bullets.map((bullet, idx) => (
                  <li key={idx}>{bullet}</li>
                ))}
              </ul>
            ) : (
              !slide.narrative && <p className="slide-preview__empty">No overall analysis has been generated yet.</p>
            )}
          </>
        )}

        {slide.chart && <SlideChart chart={slide.chart} />}
      </div>
    </article>
  );
}

function SlideChart({ chart }: { chart: ReportSlideChart }) {
  const { data, layout } = useMemo(() => buildPlot(chart), [chart]);
  return <Plot data={data} layout={layout} config={PLOTLY_CONFIG} style={{ width: "100%" }} useResizeHandler />;
}

function buildPlot(chart: ReportSlideChart): { data: Partial<Plotly.PlotData>[]; layout: Partial<Plotly.Layout> } {
  if (chart.type === "grouped_bar") {
    // Plotly's own multi-level category axis: x as [outer, inner] parallel
    // arrays draws level1 as a grouping row beneath level2's tick labels --
    // the same two-level axis the deck's multi-level c:catAx produces.
    const outer: string[] = [];
    const inner: string[] = [];
    const values: number[] = [];
    for (const [level1, leaves] of chart.groups) {
      for (const [level2, value] of leaves) {
        outer.push(level1);
        inner.push(level2);
        values.push(value);
      }
    }
    return {
      data: [{ type: "bar", x: [outer, inner], y: values, marker: { color: BAR_COLOR } }],
      layout: {
        ...BASE_LAYOUT,
        yaxis: { title: { text: chart.y_axis_title }, gridcolor: "#EEF1F6", zeroline: false },
        xaxis: { title: { text: chart.category_axis_title }, tickfont: AXIS_FONT },
      },
    };
  }

  if (chart.type === "combo") {
    return {
      data: [
        { type: "bar", name: chart.bar_name, x: chart.categories, y: chart.bar_values, marker: { color: BAR_COLOR }, yaxis: "y" },
        {
          type: "scatter",
          mode: "lines+markers",
          name: chart.line_name,
          x: chart.categories,
          y: chart.line_values,
          line: { color: LINE_COLOR, width: 2 },
          marker: { color: LINE_COLOR, size: 6 },
          yaxis: "y2",
        },
      ],
      layout: {
        ...BASE_LAYOUT,
        showlegend: true,
        legend: { orientation: "h", y: -0.35, font: AXIS_FONT },
        yaxis: { title: { text: chart.bar_name }, gridcolor: "#EEF1F6", zeroline: false },
        yaxis2: { title: { text: chart.line_name }, overlaying: "y", side: "right", showgrid: false, zeroline: false },
        xaxis: { tickangle: -40, tickfont: AXIS_FONT },
        margin: { ...BASE_LAYOUT.margin, r: 58 },
      },
    };
  }

  const shared = { x: chart.categories, y: chart.values };
  return {
    data: chart.is_trend
      ? [{ type: "scatter", mode: "lines+markers", ...shared, line: { color: LINE_COLOR, width: 2 }, marker: { color: LINE_COLOR, size: 6 } }]
      : [{ type: "bar", ...shared, marker: { color: BAR_COLOR } }],
    layout: {
      ...BASE_LAYOUT,
      yaxis: { title: { text: chart.metric_label }, gridcolor: "#EEF1F6", zeroline: false },
      xaxis: { tickangle: -40, tickfont: AXIS_FONT },
    },
  };
}
