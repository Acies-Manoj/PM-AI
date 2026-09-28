import { apiFetch } from "./client";

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

export type AnalysisChartType = "bar" | "grouped_bar" | "line" | "pie" | "scatter" | "heatmap" | "table";
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

export async function uploadAnalysisDefinitions(file: File): Promise<AnalysisDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch(`/api/analysis/definitions`, { method: "POST", body: formData });
}

export async function fetchAnalysisRepository(sessionId: string): Promise<AnalysisRepositoryResponse> {
  return apiFetch(`/api/analysis/repository/${sessionId}`);
}

export async function draftAnalysis(
  sessionId: string,
  body: { name: string; description: string; formula?: string }
): Promise<AnalysisDraft> {
  return apiFetch(`/api/analysis/repository/${sessionId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
  return apiFetch(`/api/analysis/repository/${sessionId}/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function suggestAnalysisEntries(sessionId: string): Promise<SuggestAnalysisEntriesResponse> {
  return apiFetch(`/api/analysis/repository/${sessionId}/suggest`, { method: "POST" });
}

export async function acceptAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  return apiFetch(`/api/analysis/repository/${sessionId}/entries/${entryId}/accept`, { method: "POST" });
}

export async function rejectAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  return apiFetch(`/api/analysis/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
}

export async function runAnalysisEntry(sessionId: string, entryId: string): Promise<AnalysisRepositoryEntry> {
  return apiFetch(`/api/analysis/repository/${sessionId}/entries/${entryId}/run`, { method: "POST" });
}

/** A filtered view of an already-run analysis. Never replaces the stored
 * (unfiltered) result, and never calls an LLM on the backend. */
export async function filterAnalysisEntry(
  sessionId: string,
  entryId: string,
  filters: AnalysisFilterSelections
): Promise<AnalysisRepositoryEntry> {
  return apiFetch(`/api/analysis/repository/${sessionId}/entries/${entryId}/filter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters }),
  });
}

export async function triggerDrilldown(sessionId: string, entryId: string, drilldownId: string): Promise<AnalysisRepositoryEntry> {
  return apiFetch(
    `/api/analysis/repository/${sessionId}/entries/${entryId}/drilldowns/${drilldownId}/trigger`,
    { method: "POST" }
  );
}

export async function fetchOverallAnalysis(sessionId: string): Promise<OverallAnalysisReport> {
  return apiFetch(`/api/analysis/${sessionId}/overall`);
}
