import type { AnalysisRepositoryEntry, DrilldownChain } from "../api/audit";
import { aggLabel } from "./drilldownTree";

// Mirrors routers/report.py's tree ordering, numbering and subtitle so the
// on-screen list reads exactly like the exported deck.

const MAX_SUBTITLE_CHARS = 110;
const MAX_SUBTITLE_VALUES = 3;

/** Short filter/rank line for a drill-down slide (see _drilldown_subtitle). */
export function drilldownSubtitle(chain: DrilldownChain): string {
  const values = chain.focus_values ?? [];
  let focus: string;
  if (values.length > 1) {
    const extra = values.length - MAX_SUBTITLE_VALUES;
    focus = `${chain.focus_dimension ?? "Value"}s: ${values.slice(0, MAX_SUBTITLE_VALUES).join(", ")}${extra > 0 ? ` +${extra}` : ""}`;
  } else {
    focus = values[0] ?? chain.focus_label ?? "";
  }
  const by = chain.rank.by === "pct_in_spec" ? "% in spec" : "trips";
  const dims = (chain.dimensions?.length ? chain.dimensions : [chain.dimension]).join(" x ");
  let rank =
    chain.rank.mode === "all"
      ? `${dims} by ${by}`
      : `${chain.rank.mode === "bottom" ? "Bottom" : "Top"} ${chain.rank.n} ${dims} by ${by}`;
  if (chain.metric === "pct_in_spec" && chain.rank.by !== "pct_in_spec") rank += ", with % in spec";
  else if (chain.metric_column && ["mean", "sum", "median", "max", "min"].includes(chain.metric)) {
    rank += `, with ${aggLabel(chain.metric, chain.metric_column).toLowerCase()}`;
  }
  const text = focus ? `${focus} - ${rank}` : rank;
  return text.length > MAX_SUBTITLE_CHARS ? `${text.slice(0, MAX_SUBTITLE_CHARS - 1).trimEnd()}…` : text;
}

/** True when the entry's own chain level, or any ancestor's, is stale. */
export function isStaleEntry(entry: AnalysisRepositoryEntry, byId: Map<string, AnalysisRepositoryEntry>): boolean {
  const seen = new Set<string>();
  let current: AnalysisRepositoryEntry | undefined = entry;
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    if (current.chain?.stale) return true;
    current = current.chain && current.parent_id ? byId.get(current.parent_id) : undefined;
  }
  return false;
}

export interface TreeNode {
  entry: AnalysisRepositoryEntry;
  depth: number;
  number: string;
  /** Effective parent id (null for roots, incl. drill-downs whose parent is not in the list). */
  parentId: string | null;
}

/** Depth-first tree over `entries`: roots and siblings ordered by `order`
 * (ids; anything missing sorts after the ordered ones), a drill-down hanging
 * under its parent when that parent is in `entries`. */
export function buildReportTree(entries: AnalysisRepositoryEntry[], order: string[]): TreeNode[] {
  const ids = new Set(entries.map((e) => e.id));
  const rank = new Map(order.map((id, i) => [id, i]));
  const key = (e: AnalysisRepositoryEntry) => rank.get(e.id) ?? Number.MAX_SAFE_INTEGER;
  const children = new Map<string | null, AnalysisRepositoryEntry[]>();
  for (const e of entries) {
    const parent = e.chain && e.parent_id && ids.has(e.parent_id) ? e.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), e]);
  }
  const out: TreeNode[] = [];
  const walk = (parentId: string | null, prefix: string, depth: number) => {
    const siblings = [...(children.get(parentId) ?? [])].sort((a, b) => key(a) - key(b));
    siblings.forEach((entry, i) => {
      const number = prefix ? `${prefix}.${i + 1}` : String(i + 1);
      out.push({ entry, depth, number, parentId });
      walk(entry.id, number, depth + 1);
    });
  };
  walk(null, "", 0);
  return out;
}
