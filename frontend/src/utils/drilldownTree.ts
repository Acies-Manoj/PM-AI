import type { AnalysisRepositoryEntry } from "../api/audit";

export interface LevelNode {
  id: string;
  label: string;
  depth: number;
  stale: boolean;
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
  const walk = (parentId: string, depth: number) => {
    for (const e of entries.filter((c) => c.parent_id === parentId && c.status === "approved")) {
      out.push({ id: e.id, label: levelLabel(e), depth, stale: !!e.chain?.stale });
      walk(e.id, depth + 1);
    }
  };
  walk(rootId, 1);
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
