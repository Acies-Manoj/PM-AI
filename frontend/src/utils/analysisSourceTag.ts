import type { StatTileColor } from "../components/StatTile";
import type { AnalysisSource } from "../api/audit";

export interface AnalysisSourceTag {
  label: string;
  color: StatTileColor;
}

// Colors reuse the SAME accent tokens StatTile already defines
// (--accent-teal/-purple/-amber, --carrier-blue) -- no new palette.
const TAGS: Record<AnalysisSource, AnalysisSourceTag> = {
  predefined: { label: "Predefined", color: "blue" },
  planner: { label: "Planner", color: "purple" },
  ai_suggested: { label: "AI Suggested", color: "amber" },
  custom: { label: "User Added", color: "teal" },
  drilldown: { label: "Drilldown", color: "teal" },
};

export function sourceTag(source: AnalysisSource): AnalysisSourceTag {
  return TAGS[source];
}
