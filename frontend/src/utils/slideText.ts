// The one/two-line explanation shown under a slide's title. Mirrors `short_explanation`
// in backend/app/services/report/report_generator.py, so the on-screen preview reads exactly
// like the exported slide -- keep the two in step.
//
// The text is measured, not counted: a line wrap is simulated with approximate Arial widths, so a
// translation that is longer or in a wider script (Cyrillic, Chinese...) simply takes more lines, and the
// chart below is moved down to make room.

// The explanation keeps its font size and its full text; the chart below it moves down to make room for however
// many lines it takes (see SlidePreview). A second sentence is only added while it still fits
// EXPLAIN_PREFERRED_LINES; text beyond EXPLAIN_MAX_LINES is cut with an ellipsis so the chart keeps a usable height.
export const EXPLAIN_PREFERRED_LINES = 2;
export const EXPLAIN_MAX_LINES = 4;
export const EXPLAIN_PT = 18;
const CONTENT_WIDTH_PT = 12 * 72; // the slide's content width
const LINE_FILL = 0.92; // slack against a third line, since real fonts vary a little

const CHART_LEAD_IN =
  /^(the|this)\s+(chart|graph|data|visuali[sz]ation)\s+(shows?|illustrates?|indicates?|reveals?|highlights?)\s*(that\s+)?/i;

// Chinese / Japanese / Korean (and full-width) characters: as wide as the font size, and may wrap anywhere.
const WIDE = /[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏가-힣豈-﫿︰-﹯＀-｠￠-￦]/;
const CYRILLIC_OR_GREEK = /[Ͱ-ӿ]/;

/** Approximate advance width of one character in Arial, in ems. */
function charEm(ch: string): number {
  if (ch === " ") return 0.278;
  if (WIDE.test(ch)) return 1;
  if (/\d/.test(ch)) return 0.556;
  const upper = ch !== ch.toLowerCase();
  if (ch.toLowerCase() !== ch.toUpperCase()) {
    if (CYRILLIC_OR_GREEK.test(ch)) return upper ? 0.72 : 0.56;
    return upper ? 0.67 : 0.52;
  }
  return 0.35;
}

/** How many lines the text takes at the explanation size across the slide, wrapping at spaces
 * (and between any two Chinese/Japanese/Korean characters). */
export function explanationLines(text: string, pt = EXPLAIN_PT): number {
  const cap = (CONTENT_WIDTH_PT * LINE_FILL) / pt; // a line, in ems
  const tokens: { text: string; w: number }[] = [];
  let word = "";
  const flush = () => {
    if (word) tokens.push({ text: word, w: [...word].reduce((n, c) => n + charEm(c), 0) });
    word = "";
  };
  for (const ch of text) {
    if (ch === " " || WIDE.test(ch)) {
      flush();
      tokens.push({ text: ch, w: charEm(ch) });
    } else word += ch;
  }
  flush();

  let lines = 1;
  let x = 0;
  for (const tok of tokens) {
    if (tok.text === " ") {
      if (x > 0) x += tok.w;
      continue;
    }
    if (x + tok.w > cap && x > 0) {
      lines += 1;
      x = 0;
    }
    if (tok.w > cap) {
      lines += Math.floor(tok.w / cap);
      x = tok.w % cap;
    } else x += tok.w;
  }
  return lines;
}

/** Last resort, for text longer than EXPLAIN_MAX_LINES lines: its longest start that fits, ending in an ellipsis. */
function fitMaxLines(text: string): string {
  const chars = [...text];
  let lo = 0;
  let hi = chars.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (explanationLines(chars.slice(0, mid).join("") + "…") <= EXPLAIN_MAX_LINES) lo = mid;
    else hi = mid - 1;
  }
  let prefix = chars.slice(0, lo).join("");
  if (prefix.includes(" ") && !WIDE.test(prefix.slice(-1))) prefix = prefix.replace(/\s+\S*$/, "");
  const comma = Math.max(prefix.lastIndexOf(", "), prefix.lastIndexOf("，"), prefix.lastIndexOf("、"));
  if (comma > 0 && comma >= prefix.length * 0.5) {
    const clause = prefix.slice(0, comma).replace(/[,;:\- ，、]+$/, "");
    return clause + (WIDE.test(clause.slice(-1)) ? "。" : ".");
  }
  return `${prefix.replace(/[,;:\- ，、]+$/, "")}…`;
}

export function shortExplanation(text: string | null | undefined): string {
  let cleaned = (text ?? "").trim().replace(CHART_LEAD_IN, "");
  if (!cleaned) return "";
  cleaned = cleaned[0].toUpperCase() + cleaned.slice(1);

  const sentences = cleaned.split(/(?<=[.!?])\s+|(?<=[。！？])\s*/).filter(Boolean);
  let out = sentences[0];
  if (explanationLines(out) > EXPLAIN_MAX_LINES) return fitMaxLines(out);
  const extra = sentences[1];
  if (extra && explanationLines(`${out} ${extra}`) <= EXPLAIN_PREFERRED_LINES) out = `${out} ${extra}`;
  return out;
}
