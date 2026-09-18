import type { SavedScope } from "../api/audit";
import "./SavedDefinitionCard.css";

interface SavedDefinitionCardProps {
  name: string;
  description: string;
  /** Short shape summary -- the formula for a KPI, the group-by/metrics for
   * an analysis. Rendered as plain secondary text under the description. */
  detail?: string;
  scope: SavedScope;
  /** True once this definition is part of the CURRENT session's results --
   * either the user just added it, or it's a "regular" and was computed
   * automatically. */
  added: boolean;
  busy: boolean;
  onAdd: () => void;
  onToggleScope: () => void;
  onDelete: () => void;
}

/**
 * One entry from the saved library (see custom_library_store.py), rendered
 * the same way on the Features and Analysis pages. The scope button is the
 * live version of the choice made when it was first saved: a "regular" is
 * already in every run, a "suggested" waits to be added.
 */
export default function SavedDefinitionCard({
  name,
  description,
  detail,
  scope,
  added,
  busy,
  onAdd,
  onToggleScope,
  onDelete,
}: SavedDefinitionCardProps) {
  const isRegular = scope === "regular";

  return (
    <article className="saved-def">
      <div className="saved-def__head">
        <h4 className="saved-def__name">{name}</h4>
        <span className={`saved-def__scope ${isRegular ? "saved-def__scope--regular" : ""}`}>
          {isRegular ? "Regular" : "Saved"}
        </span>
      </div>

      {description && <p className="saved-def__desc">{description}</p>}
      {detail && <code className="saved-def__detail">{detail}</code>}

      <div className="saved-def__actions">
        <button
          type="button"
          className="saved-def__btn saved-def__btn--primary"
          // A regular is already computed on every run, so there is nothing
          // for "Add" to do -- the button stays as a status instead.
          disabled={busy || added || isRegular}
          onClick={onAdd}
        >
          {isRegular ? "In every run" : added ? "Added" : "Add"}
        </button>
        <button type="button" className="saved-def__btn" disabled={busy} onClick={onToggleScope}>
          {isRegular ? "Move to my list" : "Keep as regular"}
        </button>
        <button type="button" className="saved-def__btn saved-def__btn--danger" disabled={busy} onClick={onDelete}>
          Remove
        </button>
      </div>
    </article>
  );
}
