import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { AnalysisChartSpec } from "../api/audit";
import "./AnalysisChart.css";

const Plot = createPlotlyComponent(Plotly);

interface AnalysisChartProps {
  chartSpec: AnalysisChartSpec | null;
  chartType: string | null;
  resultTable: Record<string, unknown>[] | null;
  /** Rows shown when rendering the plain table (default 20). */
  maxTableRows?: number;
}

const CHART_HEIGHT = 360;
const AXIS_FONT = { family: "inherit", size: 10.5, color: "#5B6478" };
const BASE_LAYOUT: Partial<Plotly.Layout> = {
  margin: { l: 48, r: 48, t: 16, b: 90 },
  height: CHART_HEIGHT,
  font: AXIS_FONT,
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  hovermode: "x",
};
const PLOTLY_CONFIG: Partial<Plotly.Config> = { displayModeBar: true, displaylogo: false, responsive: true };

/** Renders whatever chart the Analysis Agent produced -- its "data"/"layout"
 * are already a full Plotly figure spec (see analysis_agent.generate_chart_spec),
 * so this component only merges in the shared theme/config, never reshapes
 * the trace data itself. Falls back to a plain table when chart-spec
 * generation failed but the underlying table still computed. */
export default function AnalysisChart({ chartSpec, resultTable, maxTableRows = 20 }: AnalysisChartProps) {
  if (chartSpec) {
    return (
      <div className="analysis-chart">
        <Plot
          data={chartSpec.data as Partial<Plotly.PlotData>[]}
          // BASE_LAYOUT wins on any overlapping key (title/axis-titles/
          // barmode from chartSpec.layout still come through since
          // BASE_LAYOUT doesn't set those) -- the agent-produced layout is
          // never allowed to override sizing-critical keys like height.
          layout={{ ...chartSpec.layout, ...BASE_LAYOUT }}
          config={PLOTLY_CONFIG}
          // An explicit height is required: with `responsive` on, Plotly sizes
          // its inner container to 100% of this element, which collapses to 0
          // if the element's height is left to content.
          style={{ width: "100%", height: CHART_HEIGHT }}
          useResizeHandler
        />
      </div>
    );
  }

  if (resultTable && resultTable.length > 0) {
    const columns = Object.keys(resultTable[0]);
    return (
      <div className="analysis-chart analysis-chart__table-wrap">
        <table className="analysis-chart__table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {resultTable.slice(0, maxTableRows).map((row, idx) => (
              <tr key={idx}>
                {columns.map((c) => (
                  <td key={c}>{String(row[c] ?? "—")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return <p className="analysis-chart__empty">No chart data yet -- run this analysis to compute it.</p>;
}
