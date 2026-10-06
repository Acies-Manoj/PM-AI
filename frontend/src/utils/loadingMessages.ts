// Phrases for the ThinkingLoader, one set per kind of wait, in the order the work really happens.
export const LOADING = {
  planner: [
    "Reading your client brief…",
    "Checking your KPIs and existing analyses…",
    "Matching them to your columns…",
    "Deciding which calculations are needed…",
    "Working out each formula…",
    "Drafting the analyses…",
  ],
  audit: [
    "Reading every column…",
    "Looking for empty and constant columns…",
    "Checking for duplicates and gaps…",
    "Scanning for outliers…",
    "Writing recommendations…",
  ],
  features: [
    "Reading the feature definitions…",
    "Planning each calculation…",
    "Calculating the new columns…",
    "Checking the results look right…",
  ],
  analysisRepository: ["Loading your analyses…", "Matching them to your data…"],
  analysisRun: ["Thinking through the approach…", "Calculating the numbers…", "Choosing the right chart…", "Writing the insight…"],
  summary: ["Reading the finished analyses…", "Spotting the key findings…", "Writing the summary…"],
  proposals: ["Looking at what stands out…", "Comparing your columns…", "Shaping the drill-downs…", "Picking the most useful ones…"],
  path: [
    "Reading your data's structure…",
    "Designing the drill-down path…",
    "Picking the leading values…",
    "Running each step…",
    "Drawing the charts…",
    "Writing the insights…",
  ],
  paths: ["Loading the suggested paths…"],
  reportSummary: ["Reading the selected analyses…", "Spotting the key findings…", "Writing the final summary…"],
  segmentOutliers: ["Analyzing segment lengths…", "Flagging unusual durations…"],
  temperatureOutliers: ["Analyzing temperature readings…", "Flagging unusual values…"],
  outliers: ["Checking journey durations…", "Checking temperature readings…", "Flagging outliers…"],
  rows: ["Loading the affected rows…"],
  preview: ["Loading a preview of your data…"],
} as const;

export type LoadingKind = keyof typeof LOADING;
