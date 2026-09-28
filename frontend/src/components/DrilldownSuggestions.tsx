import type { AnalysisDrilldownSuggestion } from "../api/audit";
import { IconSparkle } from "./icons";
import "./AnalysisDetailModal.css";

interface DrilldownSuggestionsProps {
  suggestions: AnalysisDrilldownSuggestion[];
  triggeringDrilldownId: string | null;
  onTrigger: (drilldownId: string) => void;
  onOpenChild: (childEntryId: string) => void;
}

/** The Analysis Agent's own suggested follow-up analyses for one
 * already-computed entry -- shared between the detail modal and the inline
 * analysis tree on the page itself, so a PM can explore a drilldown without
 * having to open the modal first. */
export default function DrilldownSuggestions({ suggestions, triggeringDrilldownId, onTrigger, onOpenChild }: DrilldownSuggestionsProps) {
  if (suggestions.length === 0) return null;

  return (
    <div className="analysis-drilldowns">
      <h4 className="analysis-drilldowns__title">
        <IconSparkle /> Suggested drilldowns
      </h4>
      <div className="analysis-drilldowns__list">
        {suggestions.map((d) => (
          <div className="analysis-drilldowns__item" key={d.id}>
            <div className="analysis-drilldowns__item-text">
              <span className="analysis-drilldowns__item-name">{d.name}</span>
              <p className="analysis-drilldowns__item-description">{d.description}</p>
            </div>
            <button
              type="button"
              className="analysis-drilldowns__btn"
              disabled={triggeringDrilldownId === d.id}
              onClick={() => (d.triggered && d.child_entry_id ? onOpenChild(d.child_entry_id) : onTrigger(d.id))}
            >
              {triggeringDrilldownId === d.id ? "Exploring…" : d.triggered ? "View" : "Explore this"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
