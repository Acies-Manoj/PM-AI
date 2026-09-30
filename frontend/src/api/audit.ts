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
  // The pandas code the Feature Agent wrote to compute this column, after it
  // ran successfully through the backend's sandbox.
  generated_code?: string | null;
  // Which of the four repository sources this feature came from.
  source: FeatureSource;
  // The Feature Agent's own plain-English computation plan (its "Think"
  // step) -- shown in place of a static formula string.
  plan?: string | null;
  // The Feature Agent's own validation verdict on its result.
  validation_note?: string | null;
}

export interface FeatureReport {
  session_id: string;
  row_count: number;
  column_count: number;
  columns: string[];
  features: FeatureResult[];
  skipped_notes: string[];
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

// The four sources that can contribute a candidate feature to a session's
// repository -- see backend/app/services/feature_repository.py.
export type FeatureSource = "predefined" | "planner" | "custom" | "ai_suggested";
export type FeatureEntryStatus = "approved" | "pending" | "rejected";

export interface FeatureRepositoryEntry {
  id: string;
  source: FeatureSource;
  status: FeatureEntryStatus;
  name: string;
  description: string;
  output_column: string;
  // Plain-English description of the calculation -- the one input the
  // Feature Agent's Think step needs, regardless of which source proposed it.
  calculation_intent: string;
  input_columns: string[];
  // A precise plan already attached to this entry (Planner-generated and
  // PM-approved, or a fully structured predefined spec) -- null means the
  // Feature Agent hasn't thought about this one yet.
  formula: string | null;
  // Names of analyses that need this feature; non-empty => label it
  // REQUIRED FOR ANALYSIS.
  required_for_analysis: string[];
}

export interface FeatureRepositoryResponse {
  session_id: string;
  entries: FeatureRepositoryEntry[];
}

export interface SuggestFeatureEntriesResponse {
  session_id: string;
  entries: FeatureRepositoryEntry[];
}

// The five sources that can contribute a candidate analysis to a session's
// repository -- see backend/app/services/analysis_repository.py.
export type AnalysisSource = "predefined" | "planner" | "custom" | "ai_suggested" | "drilldown";
export type AnalysisEntryStatus = "approved" | "pending" | "rejected";
export type AnalysisRunStatus = "not_run" | "done" | "error";

export interface AnalysisDrilldownSuggestion {
  id: string;
  name: string;
  description: string;
  calculation_intent: string;
  // Set when this drilldown reuses the parent analysis's own chart type
  // (e.g. "combo") for visual consistency down a drill chain -- carried
  // through to the child entry's own chart pick server-side, not read
  // directly by the frontend.
  chart_type_hint: string | null;
  triggered: boolean;
  child_entry_id: string | null;
}

export interface AnalysisChartSpec {
  data: unknown[];
  layout: Record<string, unknown>;
}

export type AnalysisChartType = "bar" | "grouped_bar" | "combo" | "line" | "pie" | "scatter" | "heatmap" | "table";
export type AnalysisFilterKind = "categorical" | "numeric_range" | "date_range";
export type AnalysisComputationMode = "template" | "code";

export interface AnalysisChartAlternative {
  chart_type: AnalysisChartType;
  reason: string;
}

export interface AnalysisChartRecommendation {
  chart_type: AnalysisChartType;
  reason: string;
  alternatives: AnalysisChartAlternative[];
}

// One interactive filter declared for an analysis, plus what the current
// data offers for it: `values` for categorical, min/max for numeric_range,
// start/end (YYYY-MM-DD) for date_range.
export interface AnalysisFilter {
  column: string;
  kind: AnalysisFilterKind;
  reason: string;
  values: string[] | null;
  min: number | null;
  max: number | null;
  start: string | null;
  end: string | null;
}

export interface AnalysisFilterSelection {
  values?: string[];
  min?: number;
  max?: number;
  start?: string;
  end?: string;
}

export type AnalysisFilterSelections = Record<string, AnalysisFilterSelection>;

// A fully specified, not-yet-saved analysis returned by the Analysis
// Designer for the PM to review in the Add Analysis form.
export interface AnalysisDraft {
  name: string;
  description: string;
  formula: string;
  formula_steps: string[];
  group_by: string[];
  metrics: string[];
  computation_mode: AnalysisComputationMode;
  template: Record<string, unknown> | null;
  template_name: string | null;
  template_summary: string | null;
  template_reason: string;
  chart: AnalysisChartRecommendation;
  filters: AnalysisFilter[];
  preview_columns: string[];
  preview_rows: Record<string, unknown>[];
  preview_chart_spec: AnalysisChartSpec | null;
  notes: string[];
}

export interface DrilldownRank {
  mode: "top" | "bottom";
  n: number;
  by: "count" | "pct_in_spec";
}

export type DrilldownMetric = "count" | "pct_in_spec";

/** Marks an entry as one level of a guided drill-down chain (level 1 is the
 * original analysis, which has no `chain`). */
export interface DrilldownChain {
  chain_id: string;
  level: number;
  dimension: string;
  metric: DrilldownMetric;
  rank: DrilldownRank;
  where: Record<string, unknown>[];
  focus_dimension: string | null;
  focus_values: string[];
  focus_label: string;
  // One of several sibling slides created from one Confirm.
  split?: boolean;
  // An ancestor's rank/focus changed after this level was built.
  stale: boolean;
}

export interface DrilldownFocusOption {
  value: string;
  rows: number;
  child_count: number;
  is_wide: boolean;
}

export interface DrilldownOptions {
  entry_id: string;
  level: number;
  max_level: number;
  can_drill: boolean;
  reason: string;
  focus_dimension: string | null;
  child_dimension: string | null;
  candidate_dimensions: string[];
  focus_options: DrilldownFocusOption[];
  default_focus: string[];
  default_rank: DrilldownRank;
  metrics: DrilldownMetric[];
}

export interface DrilldownProposal {
  child_dimension: string;
  metric: DrilldownMetric;
  rank: DrilldownRank;
  focus_values: string[];
  reason: string;
  source: "ai" | "default";
}

export interface ConfirmDrilldownBody {
  focus_values: string[];
  child_dimension?: string | null;
  metric: DrilldownMetric;
  rank: DrilldownRank;
  // One slide (sibling level) per focus value instead of one combined level.
  split?: boolean;
}


export type RequiredFeatureState = "satisfied" | "not_approved" | "not_computed" | "missing";

/** One feature an analysis consumes and whether it is ready to use. */
export interface RequiredFeatureStatus {
  feature_id: string | null;
  name: string;
  output_column: string;
  definition: string;
  state: RequiredFeatureState;
  satisfied: boolean;
  message: string;
}

export interface AnalysisRepositoryEntry {
  id: string;
  source: AnalysisSource;
  status: AnalysisEntryStatus;
  name: string;
  description: string;
  calculation_intent: string;
  input_columns: string[];
  // A precise plan already attached to this entry (Planner-generated and
  // PM-approved, drafted in the Add Analysis form, or a predefined spec with
  // its own formula) -- null means the Analysis Agent hasn't thought about
  // this one yet.
  formula: string | null;
  // Set only for source === "drilldown": the entry id this one was spawned
  // from.
  parent_id: string | null;
  // Set when this entry is one level of a guided drill-down chain.
  chain: DrilldownChain | null;
  // Features this analysis requires. It cannot run (the backend returns 422)
  // until every one is satisfied: approved AND computed.
  required_features: RequiredFeatureStatus[];
  dependencies_satisfied: boolean;
  dependency_message: string | null;
  kpi_dependencies: Record<string, unknown>[];
  // Deterministic template this entry is computed with -- null means code
  // generation.
  template: Record<string, unknown> | null;
  template_summary: string | null;
  chart_recommendation: AnalysisChartRecommendation | null;
  filters: AnalysisFilter[];

  run_status: AnalysisRunStatus;
  plan_text: string | null;
  generated_code: string | null;
  result_table: Record<string, unknown>[] | null;
  result_columns: string[] | null;
  chart_type: string | null;
  chart_spec: AnalysisChartSpec | null;
  interpretation: string | null;
  error: string | null;
  drilldown_suggestions: AnalysisDrilldownSuggestion[];
  computation_mode: AnalysisComputationMode | null;
  notes: string[];
  // Set only on a filtered view returned by filterAnalysisEntry.
  applied_filters: Record<string, AnalysisFilterSelection> | null;
}

export interface AnalysisRepositoryResponse {
  session_id: string;
  entries: AnalysisRepositoryEntry[];
}

export interface SuggestAnalysisEntriesResponse {
  session_id: string;
  entries: AnalysisRepositoryEntry[];
}

export interface AnalysisDefinitionsSummary {
  filename: string;
  analysis_count: number;
  analysis_names: string[];
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

export interface UploadOnlyResponse {
  session_id: string;
  filename: string;
  row_count: number;
  column_count: number;
  columns: string[];
}

/** Upload a file and profile its columns. Does NOT run the audit agent. */
export async function uploadOnly(source: string, file: File): Promise<UploadOnlyResponse> {
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

/** Run the audit agent on an already-uploaded session. */
export async function runAudit(sessionId: string): Promise<AuditReport> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/run`, {
    method: "POST",
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

export function downloadCleansedFileUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/download`;
}

export function downloadFlaggedOutliersUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/outliers/download`;
}

export async function applyFeatures(sessionId: string): Promise<FeatureReport> {
  // Computes every APPROVED entry in this session's feature repository --
  // no body needed, the repository already holds everything server-side.
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/features`, { method: "POST" });
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

export async function fetchFeatureRepository(sessionId: string): Promise<FeatureRepositoryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// A user-requested feature drafted for review before it's added: the
// formula the Feature Agent wrote, dry-run on the real data.
export interface FeatureDraft {
  draft_token: string | null;
  name: string;
  output_column: string;
  formula: string;
  formula_steps: string[];
  columns_used: string[];
  output_dtype: string | null;
  status: "ok" | "failed";
  error: string | null;
  validation_note: string | null;
  preview_columns: string[];
  preview_rows: Record<string, unknown>[];
  summary: {
    non_null_count: number;
    null_count: number;
    stats: Record<string, number>;
    distribution: Record<string, number>;
  } | null;
  notes: string[];
}

export async function draftCustomFeature(
  sessionId: string,
  body: { name: string; description: string; input_columns?: string[]; formula?: string }
): Promise<FeatureDraft> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface AddCustomFeatureBody {
  name: string;
  description?: string;
  calculation_intent: string;
  input_columns?: string[];
  // From a reviewed FeatureDraft. The server reuses that dry run's code only
  // if `formula` is exactly what was dry-run.
  formula?: string;
  draft_token?: string | null;
}

export async function addCustomFeature(sessionId: string, body: AddCustomFeatureBody): Promise<FeatureRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function suggestFeatureEntries(sessionId: string): Promise<SuggestFeatureEntriesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}/suggest`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function acceptFeatureEntry(sessionId: string, entryId: string): Promise<FeatureRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}/entries/${entryId}/accept`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function rejectFeatureEntry(sessionId: string, entryId: string): Promise<FeatureRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/features/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
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

export async function uploadAnalysisDefinitions(file: File): Promise<AnalysisDefinitionsSummary> {
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

export async function fetchAnalysisRepository(sessionId: string): Promise<AnalysisRepositoryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function draftAnalysis(
  sessionId: string,
  body: { name: string; description: string; formula?: string }
): Promise<AnalysisDraft> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface AddCustomAnalysisBody {
  name: string;
  description?: string;
  calculation_intent: string;
  input_columns?: string[];
  // From a reviewed AnalysisDraft -- re-validated by the backend on save.
  formula?: string;
  template?: Record<string, unknown> | null;
  chart_type?: AnalysisChartType;
  chart_reason?: string;
  chart_alternatives?: AnalysisChartAlternative[];
  filters?: { column: string; reason: string }[];
}

export async function addCustomAnalysis(sessionId: string, body: AddCustomAnalysisBody): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function suggestAnalysisEntries(sessionId: string): Promise<SuggestAnalysisEntriesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/suggest`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function acceptAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/accept`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function rejectAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function runAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/run`, { method: "POST" });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** A filtered view of an already-run analysis. Never replaces the stored
 * (unfiltered) result, and never calls an LLM on the backend. */
export async function filterAnalysisEntry(
  sessionId: string,
  entryId: string,
  filters: AnalysisFilterSelections
): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/filter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function triggerDrilldown(sessionId: string, entryId: string, drilldownId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(
    `${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/drilldowns/${drilldownId}/trigger`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function suggestMoreDrilldowns(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(
    `${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/drilldowns/suggest-more`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

async function postDrilldown<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${path}`, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** What a guided drill-down from this analysis can look like (wide values,
 * default focus and top-N). No LLM. */
export async function fetchDrilldownOptions(sessionId: string, entryId: string): Promise<DrilldownOptions> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/drilldown/options`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

/** 10-15 AI-suggested next drill-downs, validated against the data --
 * cached on the entry after the first call, so opening an entry again costs
 * nothing; pass `more: true` (the single "AI" button) to append a fresh,
 * non-repeating batch. */
export function proposeDrilldowns(sessionId: string, entryId: string, more = false): Promise<DrilldownProposal[]> {
  return postDrilldown(`${sessionId}/entries/${entryId}/drilldown/propose${more ? "?more=true" : ""}`);
}

/** The PM's Confirm: builds and runs the next chain level. */
export function confirmDrilldown(sessionId: string, entryId: string, body: ConfirmDrilldownBody): Promise<AnalysisRepositoryEntry> {
  return postDrilldown(`${sessionId}/entries/${entryId}/drilldown`, body);
}

/** Changes a level's Top/Bottom and N; levels below it become stale. */
export function rerankDrilldown(sessionId: string, entryId: string, rank: DrilldownRank): Promise<AnalysisRepositoryEntry> {
  return postDrilldown(`${sessionId}/entries/${entryId}/drilldown/rank`, rank);
}

/** Rebuilds a stale level from its parent's current groups. */
export function refreshDrilldown(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  return postDrilldown(`${sessionId}/entries/${entryId}/drilldown/refresh`);
}

/** Approves one required feature of an analysis (it still has to be
 * computed on the Features step before the analysis can run). */
export async function selectRequiredFeature(sessionId: string, entryId: string, featureId: string): Promise<AnalysisRepositoryEntry> {
  const response = await fetch(
    `${API_BASE_URL}/api/analysis/repository/${sessionId}/entries/${entryId}/required-features/select`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ feature_id: featureId }) }
  );
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

/** Builds the .pptx download link for whichever done analysis entries the
 * PM chose to include, in the PM's own chosen slide order (see
 * ReportPage.tsx's drag reorder) -- an empty list downloads nothing
 * selected, so callers should keep the Download control disabled in that
 * case. `slides[].chartType` optionally overrides that slide's chart type
 * (always sent, one per slide, positionally paired with `entry_id` -- pass
 * the entry's own `chart_type` when there's no override). `language`
 * optionally translates the report's own fixed phrases (see
 * report_generator.TRANSLATABLE_PHRASES) plus each entry's name and
 * interpretation (see fetchReportTranslations, which mirrors this same
 * translation onto the on-screen preview) -- never a raw data value (a
 * number, column name, or category value), which always stays exactly as
 * it appears in the uploaded file. */
export function downloadReportUrl(
  sessionId: string,
  slides: { entryId: string; chartType: string }[],
  language = "en"
): string {
  const params = new URLSearchParams();
  for (const slide of slides) {
    params.append("entry_id", slide.entryId);
    params.append("chart_type", slide.chartType);
  }
  if (language !== "en") params.set("language", language);
  const query = params.toString();
  return `${API_BASE_URL}/api/report/${sessionId}/download${query ? `?${query}` : ""}`;
}

// The Report page's own closing-slide bullet points -- synthesized from the
// interpretations of whichever entries are included, distinct from
// OverallAnalysisReport (the Analysis page's KPI-highlights Summary).
// Bullets, not one prose narrative, to match the reference deck's own
// bullet-point closing slide (see final_summary_agent.py).
export interface ReportSummaryResponse {
  session_id: string;
  bullets: string[];
}

export async function fetchReportSummary(sessionId: string, entryIds: string[]): Promise<ReportSummaryResponse> {
  const params = new URLSearchParams();
  for (const id of entryIds) params.append("entry_id", id);
  const response = await fetch(`${API_BASE_URL}/api/report/${sessionId}/summary?${params.toString()}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// Mirrors report_generator.translate_entry_texts -- the on-screen preview's
// translated name/interpretation for one analysis entry, matching exactly
// what that entry's slide will say once downloaded.
export interface EntryTranslation {
  name: string;
  interpretation: string | null;
}

export interface ReportTranslationsResponse {
  translations: Record<string, EntryTranslation>;
}

export async function fetchReportTranslations(
  sessionId: string,
  language: string,
  entryIds: string[]
): Promise<ReportTranslationsResponse> {
  const params = new URLSearchParams();
  params.set("language", language);
  for (const id of entryIds) params.append("entry_id", id);
  const response = await fetch(`${API_BASE_URL}/api/report/${sessionId}/translations?${params.toString()}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export interface LanguageOption {
  code: string;
  name: string;
}

export interface SupportedLanguagesResponse {
  languages: LanguageOption[];
}

export async function fetchSupportedReportLanguages(): Promise<SupportedLanguagesResponse> {
  const response = await fetch(`${API_BASE_URL}/api/report/languages`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Outlier detection -------------------------------------------------------

export interface LaneResult {
  origin: string;
  destination: string;
  n_trips: number;
  n_valid: number;
  n_outliers: number;
  status_type: "own_lane" | "insufficient";
  status_label: string;
  lower_fence: number | null;
  upper_fence: number | null;
  outlier_rows: Record<string, unknown>[];
}

// One flagged trip, flattened out of its lane -- the "outliers themselves,
// not the fence numbers" table (Segment Outlier tab).
export interface SegmentOutlierRow {
  serial: string | null;
  trip_id: number | string | null;
  origin: string;
  destination: string;
  segment_days: number | null;
  lower_fence_days: number | null;
  upper_fence_days: number | null;
  status: string;
}

export interface SegmentOutliersResult {
  column_found: boolean;
  total_trips: number;
  flagged_trips: number;
  columns: string[];
  lanes: LaneResult[];
  outlier_rows: SegmentOutlierRow[];
}

// One trip's mean-temperature reading against its own configured limits --
// every trip for a product, not just the flagged ones, so the product's
// chart can plot the full picture.
export interface ProductTemperatureTrip {
  serial: string | null;
  trip_id: number | string | null;
  mean_temp: number | null;
  limit_low: number | null;
  limit_ideal: number | null;
  limit_high: number | null;
  status: "too_warm" | "too_cold" | "in_spec";
  flag_count: number;
}

export interface ProductTemperatureResult {
  product: string;
  total: number;
  too_warm: number;
  too_cold: number;
  in_spec: number;
  trips: ProductTemperatureTrip[];
}

export interface TemperatureOutliersResult {
  columns_found: Record<string, boolean>;
  total_trips: number;
  too_warm_count: number;
  too_cold_count: number;
  by_product: ProductTemperatureResult[];
}

export interface OutliersResponse {
  session_id: string;
  segment: SegmentOutliersResult;
  temperature: TemperatureOutliersResult;
}

export async function fetchOutliers(sessionId: string): Promise<OutliersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/outliers`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// A PM's inline correction to one trip's Segment Days or Mean Temp, from the
// Segment/Temperature Outlier tabs' editable columns -- writes into the
// session's working dataframe and returns freshly recomputed outliers.
export async function updateTripValue(
  sessionId: string,
  params: { serial: string; tripId: string | number; field: "segment_days" | "mean_temp"; value: number }
): Promise<OutliersResponse> {
  const response = await fetch(`${API_BASE_URL}/api/audit/${sessionId}/trip-value`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      serial: params.serial,
      trip_id: String(params.tripId),
      field: params.field,
      value: params.value,
    }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}
