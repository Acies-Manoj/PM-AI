import type { AnalysisChartType, AnalysisFilterKind } from "../api/audit";

export const CHART_LABELS: Record<AnalysisChartType, string> = {
  bar: "Bar",
  grouped_bar: "Grouped bar",
  line: "Line",
  pie: "Pie",
  scatter: "Scatter",
  heatmap: "Heatmap",
  table: "Table",
};

export const FILTER_KIND_LABELS: Record<AnalysisFilterKind, string> = {
  categorical: "Pick values",
  numeric_range: "Number range",
  date_range: "Date range",
};
