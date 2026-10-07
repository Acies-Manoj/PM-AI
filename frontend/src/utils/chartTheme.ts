// One chart palette for the whole app. The categorical series colours are the same ones the exported
// PowerPoint charts use (backend/app/services/report/report_style.py BAR_PALETTE_HEX), so a chart looks
// the same on screen and in the report.
export const CHART_PALETTE = ["#010198", "#1891F6", "#617080", "#61B549", "#F6D009", "#BAC0D0"];

export const CHART_COLORS = {
  primary: CHART_PALETTE[0], // first series, bars that are fine
  secondary: CHART_PALETTE[1], // second series, line series, the Low limit
  neutral: CHART_PALETTE[2], // reference lines such as an average
  negative: "#C62828", // breaches and outliers (same red as errors elsewhere)
  highlight: "#F59E0B", // a selected bar and the outlier threshold line
  text: "#5B6478",
  grid: "#EEF1F6",
};

// Sequential scale for heatmaps: pale blue to the primary navy.
export const CHART_HEATMAP_SCALE: [number, string][] = [
  [0, "#EAF1FB"],
  [1, CHART_PALETTE[0]],
];
