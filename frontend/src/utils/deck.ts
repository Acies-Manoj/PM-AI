// The shape of a deck being edited in the Report editor, plus the pure helpers that change it.

export interface SlideEdit {
  heading?: string;
  explanation?: string;
  caption?: string;
}

export interface DeckState {
  /** entry id -> ticked (= in the deck). Deleting a slide just unticks it, so the list on the page stays in step. */
  selected: Record<string, boolean>;
  /** The PM's slide order (entry ids). */
  order: string[];
  edits: Record<string, SlideEdit>;
  cover: { title?: string; subtitle?: string };
  /** The closing summary. null = not generated yet. */
  bullets: string[] | null;
  /** True once the PM typed in the summary: it then stops auto-regenerating when slides change. */
  bulletsEdited: boolean;
}

/** Moves `id` next to `targetId` (before it, or after it). Only siblings -- same parent -- can swap places,
 * since a drill-down always stays under its own parent in the exported deck. */
export function moveSibling(
  order: string[],
  parentOf: Map<string, string | null>,
  id: string,
  targetId: string,
  after: boolean
): string[] {
  if (id === targetId || parentOf.get(id) !== parentOf.get(targetId)) return order;
  if (!order.includes(id) || !order.includes(targetId)) return order;
  const rest = order.filter((x) => x !== id);
  const at = rest.indexOf(targetId) + (after ? 1 : 0);
  return [...rest.slice(0, at), id, ...rest.slice(at)];
}
