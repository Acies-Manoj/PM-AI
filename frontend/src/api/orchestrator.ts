import { AuditApiError } from "./audit";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface PlannedFeatureItem {
  feature_name: string;
  description: string;
}

export interface PlannedAnalysisItem {
  analysis_name: string;
  description: string;
}

export interface OrchestratorRouteResponse {
  // The Planner Agent's plan -- every distinct feature and analysis it
  // found in the brief, decided once here. Features/AnalysisPage each hand
  // their own half straight to submitClientBrief/submitAnalysisBrief
  // instead of re-deriving it from the brief text again.
  features: PlannedFeatureItem[];
  analyses: PlannedAnalysisItem[];
  // Both null when the brief was already English (or DeepL couldn't be
  // reached) -- nothing to show the user in that case.
  detected_language: string | null;
  translated_text: string | null;
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

/** The Planner Agent: reads the client's free-text brief and identifies
 * every distinct feature and analysis it's asking for, in one plan -- see
 * routers/orchestrator.py. */
export async function routeClientBrief(brief: string): Promise<OrchestratorRouteResponse> {
  const response = await fetch(`${API_BASE_URL}/api/orchestrator/route`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}
