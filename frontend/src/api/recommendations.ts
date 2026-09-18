import { AuditApiError } from "./audit";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type RecommendationType = "feature" | "analysis" | "feature_and_analysis" | "configuration";
export type RecommendationStatus = "existing" | "create_new" | "needs_clarification";

export interface FeatureDefinitionDraft {
  feature_name: string;
  formula: string;
  input_fields: string[];
  dimensions: string[];
  filters: string[];
  business_rules: string[];
}

export interface AnalysisDefinitionDraft {
  analysis_name: string;
  objective: string;
  metrics: string[];
  dimensions: string[];
  filters: string[];
  visualization: string;
  group_by: string[];
  sort_by: string[];
}

export interface ConfigurationDraft {
  required: boolean;
  parameters: string[];
}

export interface DataRequirementsDraft {
  required_fields: string[];
  missing_fields: string[];
}

export interface ValidationDraft {
  issues: string[];
  warnings: string[];
  clarifications_required: string[];
}

export interface Recommendation {
  id: string;
  type: RecommendationType;
  status: RecommendationStatus;
  name: string;
  description: string;
  reason: string;
  confidence: number;
  feature_definition: FeatureDefinitionDraft | null;
  analysis_definition: AnalysisDefinitionDraft | null;
  configuration: ConfigurationDraft | null;
  data_requirements: DataRequirementsDraft;
  validation: ValidationDraft;
}

export interface ClientRequirementSummary {
  original_input: string;
  interpreted_requirement: string;
  business_objective: string;
}

export interface RecommendationResponse {
  client_requirement: ClientRequirementSummary;
  recommendations: Recommendation[];
  errors: string[];
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

/** The AI Recommendation page's own call: reads the (already-translated)
 * brief and returns one recommendation per distinct feature/analysis/
 * configuration it identifies, for the user to review/edit/approve/reject
 * before anything is created -- see routers/orchestrator.py's /recommend. */
export async function getRecommendations(brief: string): Promise<RecommendationResponse> {
  const response = await fetch(`${API_BASE_URL}/api/orchestrator/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief }),
  });
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}
