const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type Severity = "info" | "warning" | "critical";
export type IssueStatus = "pending" | "resolved";
export type ReportStatus = "pending_review" | "reviewed";

export interface IssueOption {
  id: string;
  label: string;
}

export interface OutlierChart {
  type: "boxplot";
  column: string;
  min: number;
  max: number;
  q1: number;
  median: number;
  q3: number;
  lower_bound: number;
  upper_bound: number;
  outlier_values: number[];
}

export interface AuditIssue {
  id: string;
  category: string;
  severity: Severity;
  title: string;
  description: string;
  affected_row_count: number;
  sample: Record<string, unknown>[];
  requires_decision: boolean;
  options: IssueOption[];
  selectable_items: string[];
  status: IssueStatus;
  resolution: string | null;
  recommended_action: string | null;
  recommendation: string | null;
  chart: OutlierChart | null;
}

export interface AuditReport {
  session_id: string;
  source: string;
  filename: string;
  row_count: number;
  column_count: number;
  columns: string[];
  summary: string;
  issues: AuditIssue[];
  status: ReportStatus;
  revertible_issue_id: string | null;
}

export interface FeatureResult {
  id: string;
  name: string;
  description: string;
  output_column: string;
  non_null_count: number;
  null_count: number;
  distribution: Record<string, number>;
  stats: Record<string, number>;
  // Only set for an "ai_generated" feature -- the pandas code Groq wrote to
  // compute it, after it ran successfully through the backend's sandbox.
  generated_code?: string | null;
}

export interface FeatureReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  features: FeatureResult[];
  skipped_notes: string[];
  excluded_feature_ids: string[];
}

export interface DataPreview {
  session_id: string;
  row_count: number;
  preview_row_count: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface FeatureDefinitionsSummary {
  filename: string;
  feature_count: number;
  feature_names: string[];
}

export type FeatureSuggestionType = "duration_hours" | "ratio" | "extract_month" | "custom_formula" | "ai_generated";

export interface FeatureSuggestion {
  id: string;
  name: string;
  description: string;
  output_column: string;
  type: FeatureSuggestionType;
  formula: string;
  summary: string;
  start_column: string | null;
  end_column: string | null;
  unit: string | null;
  numerator_columns: string[] | null;
  denominator_columns: string[] | null;
  source_columns: string[] | null;
  // Only used by type "ai_generated": the plain-English ask, and the
  // pandas code Groq wrote for it (filled in after the backend computes
  // it once -- not set when the KPI is first submitted).
  calculation_prompt?: string | null;
  generated_code?: string | null;
}

export interface FeatureSuggestionsResponse {
  session_id: string;
  suggestions: FeatureSuggestion[];
}

export type PivotAgg = "sum" | "mean" | "count" | "min" | "max" | "median" | "distinct_count" | "pct_of_total";

export interface PivotMetric {
  column: string;
  agg: PivotAgg;
  output_label: string;
}

export interface PivotFilter {
  column: string;
  op: "eq" | "neq" | "gt" | "gte" | "lt" | "lte" | "in";
  value: string | number | (string | number)[];
}

export interface PivotSort {
  metric: string;
  direction: "asc" | "desc";
}

export interface PivotSuggestion {
  id: string;
  name: string;
  description: string;
  group_by: string[];
  metrics: PivotMetric[];
  filters: PivotFilter[];
  sort_by: PivotSort | null;
  top_n: number | null;
}

export interface PivotResult {
  id: string;
  name: string;
  description: string;
  group_by: string[];
  metric_labels: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  filterable_columns: string[];
  filter_options: Record<string, string[]>;
  filter_combinations: Record<string, string>[];
}

export interface PivotReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  pivots: PivotResult[];
  skipped_notes: string[];
  pivot_filters: Record<string, PivotFilter[]>;
  excluded_pivot_ids: string[];
}

export interface PivotDefinitionsSummary {
  filename: string;
  pivot_count: number;
  pivot_names: string[];
}

export interface ReportTemplateSummary {
  filename: string | null;
}

export interface PivotSuggestionsResponse {
  session_id: string;
  suggestions: PivotSuggestion[];
}

export interface OverallHighlight {
  label: string;
  value: string;
}

export interface OverallAnalysisReport {
  session_id: string;
  row_count: number;
  highlights: OverallHighlight[];
  narrative: string;
}

export class AuditApiError extends Error {}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function uploadForAudit(source: string, file: File): Promise<AuditReport> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("source", source);

  const response = await fetch(`${API_BASE_URL}/api/audit/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function resolveIssue(
  sessionId: string,
  issueId: string,
  decisionId: string,
  selectedItems?: string[]
): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_id: issueId, decision_id: decisionId, selected_items: selectedItems ?? null }),
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function revertIssue(sessionId: string, issueId: string): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/revert`, {
    method: "POST",
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// Outlier Screening's "Exclude from analysis" -- drops every row for this
// trip from the audit session's dataframe and records it as an
// already-resolved AuditIssue (see routers/audit.py's exclude_trip), so the
// same resolvingIssueId/onRevertIssue plumbing as any other finding applies.
export async function excludeTrip(sessionId: string, serial: string, tripId: number): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/exclude-trip`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ serial, trip_id: tripId }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export function downloadCleansedFileUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/download`;
}

/** `language` is one of fetchSupportedLanguages()' codes; "en" (the
 * default) skips translation entirely. */
export function downloadReportUrl(sessionId: string, language = "en"): string {
  const query = language && language !== "en" ? `?language=${encodeURIComponent(language)}` : "";
  return `${API_BASE_URL}/api/analysis/${sessionId}/report${query}`;
}

/** `excludedFeatureIds` omitted (undefined) leaves the session's exclusion
 * set as it was -- only pass it when actually changing which "Defined"/
 * "Client-Requested" features are checked (see the Features page). */
export async function applyFeatures(
  sessionId: string,
  extraFeatures?: FeatureSuggestion[],
  excludedFeatureIds?: string[]
): Promise<FeatureReport> {
  // extraFeatures omitted means "leave whatever this session already has
  // applied alone" (the backend now remembers it in extra_feature_defs) --
  // a bare recompute (e.g. on page load) must NOT send `[]`, or it would
  // wipe out every AI/custom/client-requested feature this session already
  // has. Same convention as excludedFeatureIds just below.
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(extraFeatures !== undefined ? { extra_features: extraFeatures } : {}),
      ...(excludedFeatureIds !== undefined ? { excluded_feature_ids: excludedFeatureIds } : {}),
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchFeatureReport(sessionId: string): Promise<FeatureReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function suggestFeatures(sessionId: string): Promise<FeatureSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** Step 2's "User Requests a Feature": a plain-language ask turned into a
 * ready-to-apply spec by the Feature Agent (see feature_request_agent.py) --
 * shaped exactly like an AI suggestion, so the caller applies/saves it the
 * same way (applyFeatures / saveCustomFeature). */
export async function requestFeature(sessionId: string, requestText: string): Promise<FeatureSuggestion> {
  const response = await fetch(`${API_BASE_URL}/api/features/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, request_text: requestText }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Client Brief -> multi-feature creation pipeline (see feature_orchestrator.py, kpi_store.py) --

export type FeatureSource = "CLIENT_REQUESTED" | "AI_SUGGESTED" | "USER_REQUESTED";

export interface ClientRequirement {
  feature_name: string;
  description: string;
  type: string;
  source: FeatureSource;
}

export interface KpiFeatureOutcome {
  feature_name: string;
  description: string;
  source: FeatureSource;
  status: "reused" | "created" | "failed";
  kpi_id: string | null;
  output_column: string | null;
  error: string | null;
}

export interface ClientBriefFeatureResponse {
  session_id: string;
  client_requirements: ClientRequirement[];
  ai_suggested: ClientRequirement[];
  outcomes: KpiFeatureOutcome[];
  accepted_specs: FeatureSuggestion[];
  feature_report: FeatureReport;
}

// Same shape as api/orchestrator.ts's PlannedFeatureItem/PlannedAnalysisItem
// -- declared locally (not imported) to avoid a circular import, since
// orchestrator.ts already imports AuditApiError from this file.
export interface PlannedFeatureItem {
  feature_name: string;
  description: string;
}

/** The Client Brief entry point for Feature Engineering: creates or reuses
 * (see kpi_store.py) every feature the Planner Agent already identified via
 * `plannedFeatures` (the normal case -- see UploadPage/orchestrator.ts), lets
 * the AI propose a few more that would help (AI_SUGGESTED), via the same
 * Feature Agent + execution engine as requestFeature above. Omitting
 * `plannedFeatures` falls back to extracting from `brief` on the backend
 * instead, for a caller that hasn't run the Planner first. */
export async function submitClientBrief(
  sessionId: string,
  brief: string,
  plannedFeatures?: PlannedFeatureItem[]
): Promise<ClientBriefFeatureResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/client-brief`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      brief,
      ...(plannedFeatures !== undefined ? { planned_features: plannedFeatures } : {}),
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface IssueRowsResponse {
  issue_id: string;
  total_matching: number;
  returned: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export async function fetchIssueRows(sessionId: string, issueId: string): Promise<IssueRowsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/issues/${issueId}/rows`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Audit page: Segment Days (per-trip transit-duration outliers) ---------

export interface SegmentDaysRow {
  serial: string | null;
  trip_id: number | null;
  origin: string;
  destination: string;
  segment_days: number;
  lower_fence_days: number | null;
  upper_fence_days: number | null;
  status: string;
}

export interface SegmentDaysResponse {
  session_id: string;
  total_trips: number;
  rows: SegmentDaysRow[];
}

export async function fetchSegmentDays(sessionId: string): Promise<SegmentDaysResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/segment-days`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchPreview(sessionId: string, rows = 20): Promise<DataPreview> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/preview?rows=${rows}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadFeatureDefinitions(file: File): Promise<FeatureDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/features/definitions`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadPivotDefinitions(file: File): Promise<PivotDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/definitions`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function uploadReportTemplate(file: File): Promise<ReportTemplateSummary> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/analysis/report-template`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function suggestPivots(sessionId: string): Promise<PivotSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function applyPivots(
  sessionId: string,
  /** Omit (undefined) to leave whatever AI/custom pivots were last applied
   * for this session alone -- e.g. the Report page changing only filters
   * shouldn't have to resend the Analysis page's full accepted list. */
  extraPivots?: PivotSuggestion[],
  pivotFilters: Record<string, PivotFilter[]> = {}
): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...(extraPivots !== undefined ? { extra_pivots: extraPivots } : {}),
      pivot_filters: pivotFilters,
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** The Analysis page's "Defined" checkboxes -- replaces the whole excluded
 * set (same "always send the full current selection" convention as
 * applyPivots' extraPivots). */
export async function setPivotSelection(sessionId: string, excludedIds: string[]): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivot-selection`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ excluded_ids: excludedIds }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Overall report filter ---------------------------------------------------
// Report-time only -- never recomputes a pivot's own rows/table on the
// Analysis page. ONE shared filter set for the whole report: a column with
// 2+ selected values fans out into one slide per value, for every pivot.

export interface ReportFiltersResponse {
  session_id: string;
  filters: PivotFilter[];
}

export async function fetchReportFilters(sessionId: string): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function saveReportFilters(sessionId: string, filters: PivotFilter[]): Promise<ReportFiltersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filters`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Per-pivot filter scope ---------------------------------------------------
// Which of the shared report_filters columns actually apply to ONE pivot --
// a pivot id absent from `scope` uses every active column (the default).

export interface ReportFilterScopeResponse {
  session_id: string;
  scope: Record<string, string[]>;
}

export async function fetchReportFilterScope(sessionId: string): Promise<ReportFilterScopeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filter-scope`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** `columns: null` clears the override (back to "every active column applies"). */
export async function saveReportFilterScope(
  sessionId: string,
  pivotId: string,
  columns: string[] | null
): Promise<ReportFilterScopeResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-filter-scope`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pivot_id: pivotId, columns }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Per-pivot report title ---------------------------------------------------
// Purely cosmetic -- renames a pivot's slide heading in the downloaded
// report. A pivot id absent from `titles` uses its own name (the default).

export interface ReportTitlesResponse {
  session_id: string;
  titles: Record<string, string>;
}

export async function fetchReportTitles(sessionId: string): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** `title: null` (or blank) clears the override, back to the pivot's own name. */
export async function saveReportTitle(sessionId: string, pivotId: string, title: string | null): Promise<ReportTitlesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/report-titles`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pivot_id: pivotId, title }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchPivotReport(sessionId: string): Promise<PivotReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchOverallAnalysis(sessionId: string): Promise<OverallAnalysisReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/overall`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Step 3, 2/3/4: chart interpretation, drill-down suggestions, formula agent

export interface ChartInterpretationResponse {
  session_id: string;
  pivot_id: string;
  interpretation: string;
}

/** `refresh=false` (the default) returns the most recent interpretation
 * already logged for this pivot -- e.g. one the Client Brief pipeline
 * computed automatically -- instead of another Groq call. Pass `true` for
 * the "Re-interpret" button's own explicit ask for a fresh take. */
export async function fetchChartInterpretation(
  sessionId: string,
  pivotId: string,
  refresh = false
): Promise<ChartInterpretationResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/analysis/${sessionId}/pivots/${pivotId}/interpretation?refresh=${refresh}`
  );
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface DrillDownSuggestionsResponse {
  session_id: string;
  suggestions: string[];
}

export type FormulaMode = "template" | "custom_python";

export interface FormulaAnswerResponse {
  session_id: string;
  question: string;
  mode: FormulaMode;
  pivot: PivotResult | null;
  table: Record<string, unknown>[] | null;
  value: string | null;
  explanation: string;
}

/** Step 3, 5: the Formula Agent. A drill-down suggestion or the user's own
 * plain-language question either land here the same way -- tries a pivot
 * template first, falls back to sandboxed generated Python. */
export async function askQuestion(sessionId: string, question: string): Promise<FormulaAnswerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, question }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Per-chart drill-down: "click an analysis" -> suggestions from THAT
// chart's own rows -> "Add" turns one into a new, first-class analysis ------

/** Drill-down suggestions scoped to one chart's own rows (not the whole
 * session) -- see routers/analysis.py's GET .../drill-down-suggestions. */
export async function fetchPivotDrillDownSuggestions(sessionId: string, pivotId: string): Promise<DrillDownSuggestionsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots/${pivotId}/drill-down-suggestions`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** "Add" on a per-chart drill-down suggestion -- answers it via the Formula
 * Agent and, when it comes back as a chart, keeps it as a new pivot (with
 * its own interpretation and its own further drill-downs) rather than just
 * showing the answer once. */
export async function applyPivotDrillDown(
  sessionId: string,
  pivotId: string,
  suggestion: string
): Promise<FormulaAnswerResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/pivots/${pivotId}/drill-down/apply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ suggestion }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Client Brief -> Step 3's AI-Assisted Analysis, run in one shot ---------

export interface AnalysisRequirement {
  analysis_name: string;
  description: string;
}

export interface AnalysisRequirementOutcome {
  analysis_name: string;
  description: string;
  status: "reused" | "created" | "failed";
  pivot_id: string | null;
  error: string | null;
}

export interface AnalysisBriefResponse {
  session_id: string;
  overall: OverallAnalysisReport | null;
  suggested_pivots: PivotSuggestion[];
  applied_pivot_ids: string[];
  interpretations: Record<string, string>;
  formula_answer: FormulaAnswerResponse | null;
  client_requirements: AnalysisRequirement[];
  outcomes: AnalysisRequirementOutcome[];
  pivot_report: PivotReport;
  errors: string[];
}

export interface PlannedAnalysisItem {
  analysis_name: string;
  description: string;
}

/** Step 3's whole "AI-Assisted Analysis, one step at a time" flow, run for a
 * Client Brief in one call instead of a click per stop: Chart Suggestion
 * (applied automatically, up to a few -- AI-Suggested), AI Summary, Chart
 * Interpretation for what was just applied, and every analysis the Planner
 * Agent already identified via `plannedAnalyses` (the normal case -- see
 * UploadPage/orchestrator.ts) resolved through the Formula Agent and added
 * (Client-Requested -- guaranteed present, not merely suggested). Omitting
 * `plannedAnalyses` falls back to extracting from `brief` on the backend
 * instead -- and, only if THAT finds nothing distinct either, answering the
 * whole brief directly as a single question. */
export async function submitAnalysisBrief(
  sessionId: string,
  brief: string,
  plannedAnalyses?: PlannedAnalysisItem[]
): Promise<AnalysisBriefResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/client-brief`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      brief,
      ...(plannedAnalyses !== undefined ? { planned_analyses: plannedAnalyses } : {}),
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Saved custom definitions (the persistent library) ------------------------
// A KPI or analysis the user built by hand, kept on disk between sessions.
// `scope` is the only thing separating the two save options the Add forms
// offer: "regular" is merged into every future run automatically, "suggested"
// just sits in their list until they add it.

export type SavedScope = "regular" | "suggested";

export interface SavedDefinition<TSpec> {
  id: string;
  name: string;
  description: string;
  scope: SavedScope;
  saved_at: string;
  /** The definition verbatim -- the same shape this client already sends as
   * an extra_features / extra_pivots entry, so it can be echoed straight
   * back into either path with no reshaping. */
  spec: TSpec;
}

export type SavedFeature = SavedDefinition<FeatureSuggestion>;
export type SavedPivot = SavedDefinition<PivotSuggestion>;

async function jsonRequest<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

function jsonBody(body: unknown): RequestInit {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

export async function fetchSavedFeatures(): Promise<{ items: SavedFeature[] }> {
  return jsonRequest(`${API_BASE_URL}/api/features/custom-features`);
}

export async function saveCustomFeature(definition: FeatureSuggestion, scope: SavedScope): Promise<SavedFeature> {
  return jsonRequest(`${API_BASE_URL}/api/features/custom-features`, jsonBody({ definition, scope }));
}

export async function setSavedFeatureScope(definitionId: string, scope: SavedScope): Promise<SavedFeature> {
  return jsonRequest(`${API_BASE_URL}/api/features/custom-features/${definitionId}/scope`, jsonBody({ scope }));
}

export async function deleteSavedFeature(definitionId: string): Promise<{ items: SavedFeature[] }> {
  return jsonRequest(`${API_BASE_URL}/api/features/custom-features/${definitionId}`, { method: "DELETE" });
}

export async function fetchSavedPivots(): Promise<{ items: SavedPivot[] }> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/custom-pivots`);
}

export async function saveCustomPivot(definition: PivotSuggestion, scope: SavedScope): Promise<SavedPivot> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/custom-pivots`, jsonBody({ definition, scope }));
}

export async function setSavedPivotScope(definitionId: string, scope: SavedScope): Promise<SavedPivot> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/custom-pivots/${definitionId}/scope`, jsonBody({ scope }));
}

export async function deleteSavedPivot(definitionId: string): Promise<{ items: SavedPivot[] }> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/custom-pivots/${definitionId}`, { method: "DELETE" });
}

// -- Report translation -------------------------------------------------------

export interface LanguageOption {
  code: string;
  name: string;
}

export interface SupportedLanguagesResponse {
  languages: LanguageOption[];
  /** False when the backend can't actually translate -- no DEEPL_API_KEY, or
   * the `deepl` package isn't installed in the environment serving the API.
   * Picking a language would silently return English, so the Report page
   * says so instead. */
  available: boolean;
}

export async function fetchSupportedLanguages(): Promise<SupportedLanguagesResponse> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/languages`);
}

// -- Report preview / slide selection -----------------------------------------
// The backend hands back the exact slide plan the .pptx is built from (see
// report_generator.plan_report), so the preview can't drift from the file.

export type ReportSlideChart =
  | {
      type: "grouped_bar";
      /** level1 -> [(level2, value), ...] -- one bar per pair, grouped on a
       * two-level category axis, same as the deck's own chart. */
      groups: [string, [string, number][]][];
      y_axis_title: string;
      category_axis_title: string;
    }
  | {
      type: "combo";
      categories: string[];
      category_axis_title: string;
      bar_name: string;
      bar_values: number[];
      line_name: string;
      line_values: number[];
    }
  | {
      type: "simple";
      categories: string[];
      category_axis_title: string;
      metric_label: string;
      values: number[];
      is_trend: boolean;
    };

export interface ReportSlide {
  /** Stable across re-plans (pivot id + filter combo, not position), so a
   * deselected slide stays deselected while filters are edited around it. */
  key: string;
  kind: "cover" | "chart" | "summary";
  title: string;
  subtitle: string | null;
  chart: ReportSlideChart | null;
  narrative: string | null;
  bullets: string[];
  pivot_id: string | null;
  combo_label: string | null;
  included: boolean;
}

export interface ReportPreviewResponse {
  session_id: string;
  language: string;
  slides: ReportSlide[];
}

export async function fetchReportPreview(sessionId: string, language = "en"): Promise<ReportPreviewResponse> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/${sessionId}/report-preview?language=${encodeURIComponent(language)}`);
}

export interface ReportSlidesResponse {
  session_id: string;
  excluded_keys: string[];
}

export async function fetchReportSlides(sessionId: string): Promise<ReportSlidesResponse> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/${sessionId}/report-slides`);
}

/** Replaces the deselected set wholesale -- always send the full current
 * selection, not a delta. */
export async function saveReportSlides(sessionId: string, excludedKeys: string[]): Promise<ReportSlidesResponse> {
  return jsonRequest(`${API_BASE_URL}/api/analysis/${sessionId}/report-slides`, jsonBody({ excluded_keys: excludedKeys }));
}
