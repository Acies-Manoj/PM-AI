// The one/two-line explanation shown under a slide's title. Mirrors `short_explanation`
// in backend/app/services/report/report_generator.py, so the on-screen preview reads exactly
// like the exported slide -- keep the two in step.

export const EXPLAIN_MAX_CHARS = 190; // about two lines at 18pt across the slide

const CHART_LEAD_IN =
  /^(the|this)\s+(chart|graph|data|visuali[sz]ation)\s+(shows?|illustrates?|indicates?|reveals?|highlights?)\s*(that\s+)?/i;

export function shortExplanation(text: string | null | undefined, max = EXPLAIN_MAX_CHARS): string {
  let cleaned = (text ?? "").trim().replace(CHART_LEAD_IN, "");
  if (!cleaned) return "";
  cleaned = cleaned[0].toUpperCase() + cleaned.slice(1);

  const sentences = cleaned.split(/(?<=[.!?])\s+/).filter(Boolean);
  let out = sentences[0];
  if (out.length > max) {
    const window = out.slice(0, max);
    const comma = window.lastIndexOf(", ");
    // A clause that stands on its own reads better than a cut-off word.
    if (comma >= max * 0.45) return `${window.slice(0, comma).replace(/[,;:\- ]+$/, "")}.`;
    return `${window.slice(0, max - 1).replace(/\s+\S*$/, "").replace(/[,;:\- ]+$/, "")}…`;
  }
  const extra = sentences[1];
  if (extra && out.length + 1 + extra.length <= max) out = `${out} ${extra}`;
  return out;
}
