const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface ReportOutput {
  report_id: string;
  analysis_id: string;
  title: string;
  format: string;
  content: string;
}

export class ReportApiError extends Error {}

async function parseError(res: Response): Promise<string> {
  try {
    const b = await res.json();
    return b.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function generateReport(
  analysisId: string,
  fmt: "html" | "markdown" = "html"
): Promise<ReportOutput> {
  const res = await fetch(
    `${API_BASE_URL}/api/report/generate?analysis_id=${analysisId}&fmt=${fmt}`,
    { method: "POST" }
  );
  if (!res.ok) throw new ReportApiError(await parseError(res));
  return res.json();
}

export function reportDownloadUrl(analysisId: string, fmt: "html" | "markdown"): string {
  return `${API_BASE_URL}/api/report/download?analysis_id=${analysisId}&fmt=${fmt}`;
}
