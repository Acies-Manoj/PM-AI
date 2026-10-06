// A Key Insight reads as 2-3 lines: the standout finding in a sentence, plus a second only while it stays short.
// New interpretations are already written that tight (see INTERPRET_SYSTEM in backend/app/prompts/analysis_agent.py);
// this trims ones generated earlier, for display only -- the full text is still what the report uses.

const MAX_INSIGHT_CHARS = 230;

export function briefInsight(text: string): string {
  const sentences = text.trim().split(/(?<=[.!?])\s+/).filter(Boolean);
  if (sentences.length === 0) return text;
  let out = sentences[0];
  for (const next of sentences.slice(1, 2)) {
    if (out.length + 1 + next.length <= MAX_INSIGHT_CHARS) out = `${out} ${next}`;
  }
  return out;
}
