import { API_BASE_URL, apiFetch } from "./client";
import type { FeatureSource } from "./features";

// Feature/analysis/report types and functions are defined in their own
// files and re-exported here so pages can import everything from one
// place -- see features.ts / analysis.ts / report.ts / client.ts.
export * from "./client";
export * from "./features";
export * from "./analysis";
export * from "./report";

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

// Served by the audit router's /{session_id}/features endpoints (see
// routers/audit.py) -- computed values, as opposed to feature *definitions*
// (FeatureRepositoryEntry etc., see features.ts).
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
  return apiFetch(`/api/audit/upload`, { method: "POST", body: formData });
}

/** Run the audit agent on an already-uploaded session. */
export async function runAudit(sessionId: string): Promise<AuditReport> {
  return apiFetch(`/api/audit/${sessionId}/run`, { method: "POST" });
}

export async function resolveIssue(
  sessionId: string,
  issueId: string,
  decisionId: string,
  selectedItems?: string[]
): Promise<AuditReport> {
  return apiFetch(`/api/audit/${sessionId}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_id: issueId, decision_id: decisionId, selected_items: selectedItems ?? null }),
  });
}

export async function revertIssue(sessionId: string, issueId: string): Promise<AuditReport> {
  return apiFetch(`/api/audit/${sessionId}/issues/${issueId}/revert`, { method: "POST" });
}

export function downloadCleansedFileUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/download`;
}

export function downloadFlaggedOutliersUrl(sessionId: string): string {
  return `${API_BASE_URL}/api/audit/${sessionId}/outliers/download`;
}

export interface IssueRowsResponse {
  issue_id: string;
  total_matching: number;
  returned: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export async function fetchIssueRows(sessionId: string, issueId: string): Promise<IssueRowsResponse> {
  return apiFetch(`/api/audit/${sessionId}/issues/${issueId}/rows`);
}

export async function fetchPreview(sessionId: string, rows = 20): Promise<DataPreview> {
  return apiFetch(`/api/audit/${sessionId}/preview?rows=${rows}`);
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
  return apiFetch(`/api/audit/${sessionId}/outliers`);
}

// A PM's inline correction to one trip's Segment Days or Mean Temp, from the
// Segment/Temperature Outlier tabs' editable columns -- writes into the
// session's working dataframe and returns freshly recomputed outliers.
export async function updateTripValue(
  sessionId: string,
  params: { serial: string; tripId: string | number; field: "segment_days" | "mean_temp"; value: number }
): Promise<OutliersResponse> {
  return apiFetch(`/api/audit/${sessionId}/trip-value`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      serial: params.serial,
      trip_id: String(params.tripId),
      field: params.field,
      value: params.value,
    }),
  });
}
