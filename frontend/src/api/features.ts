import { apiFetch } from "./client";
import type { FeatureReport } from "./audit";

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

export async function applyFeatures(sessionId: string): Promise<FeatureReport> {
  // Computes every APPROVED entry in this session's feature repository --
  // no body needed, the repository already holds everything server-side.
  return apiFetch(`/api/audit/${sessionId}/features`, { method: "POST" });
}

export async function fetchFeatureReport(sessionId: string): Promise<FeatureReport> {
  return apiFetch(`/api/audit/${sessionId}/features`);
}

export async function fetchFeatureRepository(sessionId: string): Promise<FeatureRepositoryResponse> {
  return apiFetch(`/api/features/repository/${sessionId}`);
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
  return apiFetch(`/api/features/repository/${sessionId}/draft`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
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
  return apiFetch(`/api/features/repository/${sessionId}/custom`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function suggestFeatureEntries(sessionId: string): Promise<SuggestFeatureEntriesResponse> {
  return apiFetch(`/api/features/repository/${sessionId}/suggest`, { method: "POST" });
}

export async function acceptFeatureEntry(sessionId: string, entryId: string): Promise<FeatureRepositoryEntry> {
  return apiFetch(`/api/features/repository/${sessionId}/entries/${entryId}/accept`, { method: "POST" });
}

export async function rejectFeatureEntry(sessionId: string, entryId: string): Promise<FeatureRepositoryEntry> {
  return apiFetch(`/api/features/repository/${sessionId}/entries/${entryId}/reject`, { method: "POST" });
}

export async function uploadFeatureDefinitions(file: File): Promise<FeatureDefinitionsSummary> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch(`/api/features/definitions`, { method: "POST", body: formData });
}
