// The chart types the Report page's export (report_generator.py's
// _add_entry_slide) knows how to render -- used to sanitize an entry's
// chart_type before it's sent to the download endpoint, since an
// unsupported type (e.g. "heatmap"/"table") would leave that slide's chart
// out of the .pptx entirely.
export const REPORT_CHART_TYPES = ["bar", "grouped_bar", "combo", "line", "scatter", "pie"] as const;
export type ReportChartType = (typeof REPORT_CHART_TYPES)[number];
