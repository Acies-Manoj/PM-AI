const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface BriefAnalysis {
  key_questions: string[];
  pipeline_description: string;
}

export interface TranslationResult {
  original_text: string;
  translated_text: string;
  detected_language: string;
  language_name: string;
  was_translated: boolean;
}

export class BriefApiError extends Error {}

async function parseError(res: Response): Promise<string> {
  try {
    const b = await res.json();
    return b.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function translateBrief(text: string): Promise<TranslationResult> {
  const res = await fetch(`${API_BASE_URL}/api/brief/translate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new BriefApiError(await parseError(res));
  return res.json();
}

export async function analyzeBrief(text: string): Promise<BriefAnalysis> {
  const res = await fetch(`${API_BASE_URL}/api/brief/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new BriefApiError(await parseError(res));
  return res.json();
}
