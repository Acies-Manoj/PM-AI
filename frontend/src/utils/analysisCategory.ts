import type { StatTileColor } from "../components/StatTile";

export interface AnalysisCategory {
  label: string;
  color: StatTileColor;
}

// Keyword -> domain category, checked in this order (first match wins) so a
// name mentioning several themes still gets one clear tag. Colors reuse the
// SAME accent tokens StatTile already defines (--accent-teal/-purple/-amber,
// --color-error, --carrier-blue) -- no new palette, just a consistent one.
const RULES: { keywords: string[]; category: AnalysisCategory }[] = [
  {
    keywords: ["temperature", "compliance", "spec", "excursion", "cold chain", "humidity"],
    category: { label: "Temperature & Compliance", color: "teal" },
  },
  {
    keywords: ["delay", "risk", "overdue", "late", "flag", "exception"],
    category: { label: "Delay & Risk", color: "error" },
  },
  {
    keywords: ["carrier", "driver", "transporter", "vendor"],
    category: { label: "Carrier Performance", color: "purple" },
  },
  {
    keywords: ["duration", "route", "segment", "transit", "lane", "origin", "destination", "trip"],
    category: { label: "Duration & Route", color: "blue" },
  },
  {
    keywords: ["volume", "trend", "count", "shipment", "monthly", "over time", "distribution"],
    category: { label: "Volume & Trend", color: "amber" },
  },
];

const FALLBACK: AnalysisCategory = { label: "General", color: "blue" };

export function categorizeAnalysis(name: string, description: string): AnalysisCategory {
  const text = `${name} ${description}`.toLowerCase();
  for (const rule of RULES) {
    if (rule.keywords.some((k) => text.includes(k))) return rule.category;
  }
  return FALLBACK;
}
