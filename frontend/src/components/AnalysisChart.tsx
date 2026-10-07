import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { AnalysisChartSpec } from "../api/audit";
import { CHART_COLORS, CHART_HEATMAP_SCALE, CHART_PALETTE } from "../utils/chartTheme";
import ExcelTable from "./ExcelTable";
import "./AnalysisChart.css";

const Plot = createPlotlyComponent(Plotly);

interface AnalysisChartProps {
  chartSpec: AnalysisChartSpec | null;
  chartType: string | null;
  resultTable: Record<string, unknown>[] | null;
  /** Rows shown when rendering the plain table (default 20). */
  maxTableRows?: number;
  /** Fill the parent's height (no toolbar, tighter margins) -- used where the chart
   * has to fit a fixed box, like a slide preview, instead of its own 360px. */
  fill?: boolean;
  /** With `fill`: a non-interactive picture of the chart (thumbnails). */
  thumbnail?: boolean;
}

const CHART_HEIGHT = 360;
const AXIS_FONT = { family: "inherit", size: 10.5, color: CHART_COLORS.text };
// Legend sits ABOVE the plot, left-aligned: below it, it collided with slanted category labels and the
// axis title, and on the right it ate into charts that are already narrow.
const LEGEND_TOP: Partial<Plotly.Legend> = {
  orientation: "h",
  x: 0,
  xanchor: "left",
  y: 1.02,
  yanchor: "bottom",
  font: { size: 10.5, color: CHART_COLORS.text },
};

/** Axis styling shared by every chart: one tick-label size, one title size, and room between the two so
 * a long or slanted tick label can never sit on top of the axis title. */
function themeAxis(base: unknown, tickSize: number, titleSize: number, extra: object = {}): object {
  const axis = (base ?? {}) as { title?: unknown; tickfont?: object };
  const title = typeof axis.title === "string" ? { text: axis.title } : ((axis.title as object) ?? {});
  return {
    ...axis,
    automargin: true,
    gridcolor: CHART_COLORS.grid,
    tickfont: { size: tickSize, color: CHART_COLORS.text, ...(axis.tickfont ?? {}) },
    title: { standoff: 14, ...title, font: { size: titleSize, color: CHART_COLORS.text } },
    ...extra,
  };
}

/** The normal (non-slide) layout: the spec's own layout with the shared theme merged in. */
function themedLayout(spec: Partial<Plotly.Layout> | undefined): Partial<Plotly.Layout> {
  const base = (spec ?? {}) as Record<string, unknown>;
  const merged: Record<string, unknown> = {
    ...base,
    ...BASE_LAYOUT,
    xaxis: themeAxis(base.xaxis, 10.5, 11.5),
    yaxis: themeAxis(base.yaxis, 10.5, 11.5),
  };
  if (base.yaxis2) merged.yaxis2 = themeAxis(base.yaxis2, 10.5, 11.5, { showgrid: false });
  merged.legend = LEGEND_TOP;
  return merged as Partial<Plotly.Layout>;
}

const BASE_LAYOUT: Partial<Plotly.Layout> = {
  margin: { l: 56, r: 56, t: 44, b: 24 },
  height: CHART_HEIGHT,
  font: AXIS_FONT,
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  hovermode: "x",
  // Series without their own colour take the brand palette, the same one the exported slides use.
  colorway: CHART_PALETTE,
};
const PLOTLY_CONFIG: Partial<Plotly.Config> = { displayModeBar: "hover", displaylogo: false, responsive: true };
const FILL_LAYOUT: Partial<Plotly.Layout> = {
  ...BASE_LAYOUT,
  height: undefined,
  autosize: true,
  margin: { l: 44, r: 44, t: 30, b: 24 },
  font: { ...AXIS_FONT, family: "Arial, sans-serif", size: 9 },
  legend: { ...LEGEND_TOP, font: { size: 9, color: CHART_COLORS.text } },
};
const FILL_CONFIG: Partial<Plotly.Config> = { ...PLOTLY_CONFIG, displayModeBar: false };
// Thumbnails: no hover, zoom or toolbar -- they're pictures of a chart, and there can be dozens.
const STATIC_CONFIG: Partial<Plotly.Config> = { ...FILL_CONFIG, staticPlot: true, responsive: true };

/** Category labels for a chart axis, planned the way the exported slide plans them (see `_axis_plan` in
 * backend report_generator.py): if they fit flat in the width each category gets they are cut to that length
 * and stay horizontal; otherwise they slant 45 degrees with a longer cut. Different names are never cut into
 * the same label. */
function shortLabel(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1).trimEnd()}…`;
}

function axisPlan(categories: string[], widthIn = 12): { labels: string[]; angle: number } {
  const fit = Math.floor((widthIn / Math.max(categories.length, 1) / 0.085) * 0.9);
  let labels: string[];
  let angle: number;
  if (fit >= 10) {
    labels = categories.map((c) => shortLabel(c, Math.min(fit, 24)));
    angle = 0;
  } else {
    labels = categories.map((c) => shortLabel(c, 18));
    angle = -45;
  }
  if (new Set(labels).size < new Set(categories).size) {
    labels = categories.map((c) => shortLabel(c, 30));
    angle = -45;
  }
  return { labels, angle };
}

type Trace = { x?: unknown[]; y?: unknown[]; type?: string };

/** Fill-mode layout: the agent's own layout, plus automatic margins and a planned x axis so tick labels,
 * axis titles and the legend never sit on top of one another. */
function fillLayout(spec: Partial<Plotly.Layout> | undefined, data: Trace[]): Partial<Plotly.Layout> {
  const base = (spec ?? {}) as Record<string, unknown>;
  const axis = (key: string, extra: object = {}) => themeAxis(base[key], 9, 10, extra);

  let xExtra: object = {};
  const first = data.find((t) => Array.isArray(t.x) && t.x.length > 0 && typeof t.x[0] !== "number");
  if (first?.x) {
    const cats = [...new Set(first.x.map(String))];
    const plan = axisPlan(cats);
    xExtra = { tickmode: "array", tickvals: cats, ticktext: plan.labels, tickangle: plan.angle, tickfont: { size: 9 } };
  }
  let yExtra: object = {};
  const heat = data.find((t) => t.type === "heatmap" && Array.isArray(t.y));
  if (heat?.y) {
    const rows = [...new Set(heat.y.map(String))];
    yExtra = { tickmode: "array", tickvals: rows, ticktext: rows.map((r) => shortLabel(r, 22)), tickfont: { size: 9 } };
  }

  const merged: Record<string, unknown> = { ...base, ...FILL_LAYOUT, xaxis: axis("xaxis", xExtra), yaxis: axis("yaxis", yExtra) };
  if (base.yaxis2) merged.yaxis2 = axis("yaxis2");
  return merged as Partial<Plotly.Layout>;
}

/** Renders whatever chart the Analysis Agent produced -- its "data"/"layout"
 * are already a full Plotly figure spec (see analysis_agent.generate_chart_spec),
 * so this component only merges in the shared theme/config, never reshapes
 * the trace data itself. Falls back to a plain table when chart-spec
 * generation failed but the underlying table still computed. */
function withBrandScale(data: Partial<Plotly.PlotData>[]): Partial<Plotly.PlotData>[] {
  return data.map((t) => (t.type === "heatmap" && !("colorscale" in t) ? { ...t, colorscale: CHART_HEATMAP_SCALE } : t));
}

export default function AnalysisChart({ chartSpec, resultTable, maxTableRows = 20, fill = false, thumbnail = false }: AnalysisChartProps) {
  if (chartSpec) {
    return (
      <div className={fill ? "analysis-chart analysis-chart--fill" : "analysis-chart"}>
        <Plot
          data={withBrandScale(chartSpec.data as Partial<Plotly.PlotData>[])}
          // BASE_LAYOUT wins on any overlapping key (title/axis-titles/
          // barmode from chartSpec.layout still come through since
          // BASE_LAYOUT doesn't set those) -- the agent-produced layout is
          // never allowed to override sizing-critical keys like height.
          layout={fill ? fillLayout(chartSpec.layout, chartSpec.data as Trace[]) : themedLayout(chartSpec.layout)}
          config={fill ? (thumbnail ? STATIC_CONFIG : FILL_CONFIG) : PLOTLY_CONFIG}
          // An explicit height is required: with `responsive` on, Plotly sizes
          // its inner container to 100% of this element, which collapses to 0
          // if the element's height is left to content. In fill mode the parent
          // box has a definite height, so 100% is explicit enough.
          style={{ width: "100%", height: fill ? "100%" : CHART_HEIGHT }}
          useResizeHandler
        />
      </div>
    );
  }

  if (resultTable && resultTable.length > 0) {
    const columns = Object.keys(resultTable[0]);
    return (
      <div className="analysis-chart analysis-chart__table-wrap">
        <ExcelTable columns={columns} rows={resultTable.slice(0, maxTableRows)} />
      </div>
    );
  }

  return <p className="analysis-chart__empty">No chart data yet. Run this analysis to compute it.</p>;
}
