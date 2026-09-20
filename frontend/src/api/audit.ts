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
  triggered: boolean;
  child_entry_id: string | null;
}

export interface AnalysisChartSpec {
  data: unknown[];
  layout: Record<string, unknown>;
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
  // PM-approved, or a predefined spec with its own formula) -- null means
  // the Analysis Agent hasn't thought about this one yet.
  formula: string | null;
  // Set only for source === "drilldown": the entry id this one was spawned
  // from.
  parent_id: string | null;

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

export async function addCustomFeature(
  sessionId: string,
  body: { name: string; description?: string; calculation_intent: string; input_columns?: string[] }
): Promise<FeatureRepositoryEntry> {
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

export async function addCustomAnalysis(
  sessionId: string,
  body: { name: string; description?: string; calculation_intent: string; input_columns?: string[] }
): Promise<AnalysisRepositoryEntry> {
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

export async function fetchOverallAnalysis(sessionId: string): Promise<OverallAnalysisReport> {
  const response = await fetch(`${API_BASE_URL}/api/analysis/${sessionId}/overall`);
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
  status_type: "own_lane" | "peer_shrunk" | "insufficient";
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
