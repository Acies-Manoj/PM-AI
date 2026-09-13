const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface AnalysisStep {
  step_number: number;
  step_type: string;
  content: string;
  chart_type: string | null;
  drill_down_suggestions: string[];
  formula_code: string | null;
  compute_result: Record<string, unknown> | null;
}

export interface AnalysisState {
  analysis_id: string;
  session_id: string;
  brief: string;
  steps: AnalysisStep[];
  status: string;
}

export interface FeatureSuggestion {
  name: string;
  description: string;
  rationale: string;
  feature_type: string;
}

export interface AIFeatureCodeResult {
  name: string;
  description: string;
  output_column: string;
  code: string;
  success: boolean;
  sample_values: unknown[];
  error: string | null;
}

export class AnalysisApiError extends Error {}

async function parseError(res: Response): Promise<string> {
  try {
    const b = await res.json();
    return b.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function startAnalysis(sessionId: string, brief: string): Promise<AnalysisState> {
  const res = await fetch(`${API_BASE_URL}/api/analysis/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, brief }),
  });
  if (!res.ok) throw new AnalysisApiError(await parseError(res));
  return res.json();
}

export async function nextAnalysisStep(analysisId: string, userAsk?: string): Promise<AnalysisState> {
  const res = await fetch(`${API_BASE_URL}/api/analysis/${analysisId}/next`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_ask: userAsk ?? null }),
  });
  if (!res.ok) throw new AnalysisApiError(await parseError(res));
  return res.json();
}

export async function computeFormula(analysisId: string, ask: string): Promise<AnalysisState> {
  const res = await fetch(`${API_BASE_URL}/api/analysis/${analysisId}/compute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ask }),
  });
  if (!res.ok) throw new AnalysisApiError(await parseError(res));
  return res.json();
}

export async function suggestFeatures(sessionId: string, brief: string): Promise<FeatureSuggestion[]> {
  const res = await fetch(`${API_BASE_URL}/api/features/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, brief }),
  });
  if (!res.ok) throw new AnalysisApiError(await parseError(res));
  return res.json();
}

export async function generateFeatureCode(sessionId: string, userRequest: string): Promise<AIFeatureCodeResult> {
  const res = await fetch(`${API_BASE_URL}/api/features/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, user_request: userRequest }),
  });
  if (!res.ok) throw new AnalysisApiError(await parseError(res));
  return res.json();
}
