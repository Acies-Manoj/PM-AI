import type { AnalysisRepositoryEntry } from "../api/audit";
import Modal from "./Modal";
import PlanText from "./PlanText";
import AnalysisChart from "./AnalysisChart";
import { IconSparkle } from "./icons";
import "./AnalysisCard.css";
import "./AnalysisDetailModal.css";
import "./FeatureCard.css";

interface AnalysisDetailModalProps {
  entry: AnalysisRepositoryEntry;
  triggeringDrilldownId: string | null;
  onClose: () => void;
  onTriggerDrilldown: (drilldownId: string) => void;
  onOpenChild: (childEntryId: string) => void;
}

export default function AnalysisDetailModal({
  entry,
  triggeringDrilldownId,
  onClose,
  onTriggerDrilldown,
  onOpenChild,
}: AnalysisDetailModalProps) {
  return (
    <Modal title={entry.name} onClose={onClose}>
      {(entry.formula || entry.plan_text) && (
        <PlanText plan={entry.plan_text ?? entry.formula ?? ""} label="Analysis plan" className="analysis-card__formula" />
      )}
      <p className="analysis-card__description">{entry.description}</p>

      {entry.run_status === "done" && (
        <>
          <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} />
          {entry.interpretation && <p className="analysis-card__interpretation">{entry.interpretation}</p>}

          {entry.generated_code && (
            <div className="feature-card__code-block">
              <span className="feature-card__code-label">Analysis Agent-generated pandas code</span>
              <pre className="feature-card__code"><code>{entry.generated_code}</code></pre>
            </div>
          )}

          {entry.drilldown_suggestions.length > 0 && (
            <div className="analysis-drilldowns">
              <h4 className="analysis-drilldowns__title">
                <IconSparkle /> Suggested drilldowns
              </h4>
              <div className="analysis-drilldowns__list">
                {entry.drilldown_suggestions.map((d) => (
                  <div className="analysis-drilldowns__item" key={d.id}>
                    <div className="analysis-drilldowns__item-text">
                      <span className="analysis-drilldowns__item-name">{d.name}</span>
                      <p className="analysis-drilldowns__item-description">{d.description}</p>
                    </div>
                    <button
                      type="button"
                      className="analysis-drilldowns__btn"
                      disabled={triggeringDrilldownId === d.id}
                      onClick={() => (d.triggered && d.child_entry_id ? onOpenChild(d.child_entry_id) : onTriggerDrilldown(d.id))}
                    >
                      {triggeringDrilldownId === d.id ? "Exploring…" : d.triggered ? "View" : "Explore this"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
