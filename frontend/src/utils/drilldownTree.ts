import type { AnalysisRepositoryEntry } from "../api/audit";

export interface LevelNode {
  id: string;
  label: string;
  depth: number;
  stale: boolean;
  /** What this drill-down analyses, e.g. "Destination × Origin · Trips" -- the
   * same for every slide made from one drill-down, whichever value it covers. */
  analysis: string;
  /** The value this slide covers, e.g. a carrier ("" for a free-text drill-down). */
  focus: string;
  /** The X-axis columns of this drill-down, e.g. "Origin × Destination" ("" for a free-text one). */
  axes: string;
  /** What it measures, e.g. "Trips" or "Avg Mean Value". */
  measure: string;
  /** Level number in the chain (the analysis you started from is level 1). */
  level: number;
  /** Values from the first drill-down down to this one, e.g. ["MSC", "Kiwi"]. */
  path: string[];
}

const AGG_PREFIX: Record<string, string> = { mean: "Avg", sum: "Total", median: "Median", max: "Max", min: "Min" };

/** "Avg Mean Value", or "Max of Max Value" when the column already starts with the word. */
export function aggLabel(metric: string, column: string): string {
  const prefix = AGG_PREFIX[metric];
  return column.toLowerCase().startsWith(prefix.toLowerCase()) ? `${prefix} of ${column}` : `${prefix} ${column}`;
}

/** The X-axis columns and measure of a guided level ("" / "" for a free-text drill-down). */
export function axesAndMeasure(entry: AnalysisRepositoryEntry): { axes: string; measure: string } {
  const chain = entry.chain;
  if (!chain) return { axes: "", measure: "" };
  const axes = (chain.dimensions?.length ? chain.dimensions : [chain.dimension]).join(" × ");
  const measure =
    AGG_PREFIX[chain.metric] && chain.metric_column
      ? aggLabel(chain.metric, chain.metric_column)
      : chain.metric === "pct_in_spec"
        ? "% in spec"
        : "Trips";
  return { axes, measure };
}

/** "Destination × Origin · Trips" for a guided level; the plain name otherwise. */
export function analysisLabel(entry: AnalysisRepositoryEntry): string {
  const { axes, measure } = axesAndMeasure(entry);
  return axes ? `${axes} · ${measure}` : entry.name;
}

/** "Level 2 · Table Grapes" for a guided chain level; the plain name for a
 * free-text drill-down. */
export function levelLabel(entry: AnalysisRepositoryEntry): string {
  return entry.chain ? `Level ${entry.chain.level} · ${entry.chain.focus_label || entry.name}` : entry.name;
}

/** Every drill-down beneath `rootId`, depth-first, so siblings of one parent
 * sit together under it. */
export function buildLevelTree(entries: AnalysisRepositoryEntry[], rootId: string): LevelNode[] {
  const out: LevelNode[] = [];
  const walk = (parentId: string, depth: number, prefix: string[]) => {
    for (const e of entries.filter((c) => c.parent_id === parentId && c.status === "approved")) {
      const focus = e.chain?.focus_label ?? "";
      const path = [...prefix, focus || e.name];
      out.push({
        id: e.id,
        label: levelLabel(e),
        depth,
        stale: !!e.chain?.stale,
        analysis: analysisLabel(e),
        ...axesAndMeasure(e),
        focus,
        level: e.chain?.level ?? depth + 1,
        path,
      });
      walk(e.id, depth + 1, path);
    }
  };
  walk(rootId, 1, []);
  return out;
}

/** Ancestors of an entry, root first (the entry itself excluded). */
export function ancestorTrail(entries: AnalysisRepositoryEntry[], entry: AnalysisRepositoryEntry): { id: string; label: string }[] {
  const trail: { id: string; label: string }[] = [];
  let cur = entry.parent_id ? entries.find((e) => e.id === entry.parent_id) : undefined;
  while (cur && trail.length < 10) {
    trail.unshift({ id: cur.id, label: cur.chain ? levelLabel(cur) : `Level 1 · ${cur.name}` });
    cur = cur.parent_id ? entries.find((e) => e.id === cur!.parent_id) : undefined;
  }
  return trail;
}
