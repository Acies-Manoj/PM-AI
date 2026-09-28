import type { AnalysisRepositoryEntry } from "../api/audit";

export interface AnalysisTreeNode {
  entry: AnalysisRepositoryEntry;
  children: AnalysisTreeNode[];
}

/** Turns the flat `parent_id`-linked entry list into a proper tree -- nesting
 * is unbounded in the data (a drilldown can itself be drilled into again),
 * so this recurses rather than assuming a single level. An entry whose
 * parent isn't in `entries` (e.g. filtered out, or somehow missing) is
 * treated as its own root rather than being silently dropped. */
export function buildAnalysisTree(entries: AnalysisRepositoryEntry[]): AnalysisTreeNode[] {
  const byId = new Map(entries.map((e) => [e.id, e]));
  const childrenByParent = new Map<string, AnalysisRepositoryEntry[]>();
  const roots: AnalysisRepositoryEntry[] = [];

  for (const entry of entries) {
    if (entry.parent_id && byId.has(entry.parent_id)) {
      const siblings = childrenByParent.get(entry.parent_id) ?? [];
      siblings.push(entry);
      childrenByParent.set(entry.parent_id, siblings);
    } else {
      roots.push(entry);
    }
  }

  const build = (entry: AnalysisRepositoryEntry): AnalysisTreeNode => ({
    entry,
    children: (childrenByParent.get(entry.id) ?? []).map(build),
  });

  return roots.map(build);
}
