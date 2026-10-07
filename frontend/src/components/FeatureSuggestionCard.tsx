import { useState } from "react";
import { tidyText } from "../utils/tidyText";
import type { FeatureRepositoryEntry } from "../api/audit";
import { IconExpand } from "./icons";
import Modal from "./Modal";
import "./FeatureSuggestionCard.css";

interface FeatureSuggestionCardProps {
  suggestion: FeatureRepositoryEntry;
  added: boolean;
  busy: boolean;
  onAdd: () => void;
}

export default function FeatureSuggestionCard({ suggestion, added, busy, onAdd }: FeatureSuggestionCardProps) {
  const [showFormula, setShowFormula] = useState(false);

  return (
    <>
      <div className={`feature-suggestion ${added ? "feature-suggestion--added" : ""}`}>
        <div className="feature-suggestion__body">
          <div className="feature-suggestion__top">
            <h4 className="feature-suggestion__name">{suggestion.name}</h4>
            <span className="feature-suggestion__column">{suggestion.output_column}</span>
          </div>
          <p className="feature-suggestion__description">{tidyText(suggestion.description)}</p>

          <button type="button" className="feature-suggestion__formula-toggle" onClick={() => setShowFormula(true)}>
            <IconExpand />
            View calculation
          </button>
        </div>

        <button type="button" className="feature-suggestion__btn" disabled={added || busy} onClick={onAdd}>
          {added ? "Added" : busy ? "Adding…" : "Add this feature"}
        </button>
      </div>

      {showFormula && (
        <Modal title={suggestion.name} onClose={() => setShowFormula(false)}>
          <p className="feature-suggestion__modal-description">{tidyText(suggestion.description)}</p>
          <p className="feature-suggestion__formula">{suggestion.calculation_intent}</p>
        </Modal>
      )}
    </>
  );
}
