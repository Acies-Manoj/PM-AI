import { useState } from "react";
import { tidyText } from "../utils/tidyText";
import type { AnalysisRepositoryEntry } from "../api/audit";
import { IconExpand } from "./icons";
import Modal from "./Modal";
import "./AnalysisSuggestionCard.css";

interface AnalysisSuggestionCardProps {
  suggestion: AnalysisRepositoryEntry;
  added: boolean;
  busy: boolean;
  onAdd: () => void;
}

export default function AnalysisSuggestionCard({ suggestion, added, busy, onAdd }: AnalysisSuggestionCardProps) {
  const [showIntent, setShowIntent] = useState(false);

  return (
    <>
      <div className={`analysis-suggestion ${added ? "analysis-suggestion--added" : ""}`}>
        <div className="analysis-suggestion__body">
          <h4 className="analysis-suggestion__name">{suggestion.name}</h4>
          <p className="analysis-suggestion__description">{tidyText(suggestion.description)}</p>

          <button type="button" className="analysis-suggestion__intent-toggle" onClick={() => setShowIntent(true)}>
            <IconExpand />
            View calculation
          </button>
        </div>

        <button type="button" className="analysis-suggestion__btn" disabled={added || busy} onClick={onAdd}>
          {added ? "Added" : busy ? "Adding…" : "Add this analysis"}
        </button>
      </div>

      {showIntent && (
        <Modal title={suggestion.name} onClose={() => setShowIntent(false)}>
          <p className="analysis-suggestion__modal-description">{tidyText(suggestion.description)}</p>
          <p className="analysis-suggestion__intent">{suggestion.calculation_intent}</p>
        </Modal>
      )}
    </>
  );
}
