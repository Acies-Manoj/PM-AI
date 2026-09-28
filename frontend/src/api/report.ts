import { API_BASE_URL, apiFetch } from "./client";

/** Builds the .pptx download link for whichever done analysis entries the
 * PM chose to include -- an empty list downloads nothing selected, so
 * callers should keep the Download control disabled in that case.
 * `language` optionally translates the report's own fixed phrases (see
 * report_generator.TRANSLATABLE_PHRASES) -- never the underlying analysis
 * names/interpretations/data, which always stay in their original language. */
export function downloadReportUrl(sessionId: string, entryIds: string[], language = "en"): string {
  const params = new URLSearchParams();
  for (const id of entryIds) params.append("entry_id", id);
  if (language !== "en") params.set("language", language);
  const query = params.toString();
  return `${API_BASE_URL}/api/report/${sessionId}/download${query ? `?${query}` : ""}`;
}

export interface LanguageOption {
  code: string;
  name: string;
}

export interface SupportedLanguagesResponse {
  languages: LanguageOption[];
}

export async function fetchSupportedReportLanguages(): Promise<SupportedLanguagesResponse> {
  return apiFetch(`/api/report/languages`);
}
