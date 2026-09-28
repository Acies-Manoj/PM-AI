import type { AnalysisRepositoryEntry } from "../api/audit";
import { IconBarChart, IconExpand, IconSparkle } from "./icons";
import "./AnalysisCard.css";

interface AnalysisCardProps {
  entry: AnalysisRepositoryEntry;
  running: boolean;
  /** Set when the run request itself failed (network / server error). */
  runFailure?: string;
  /** Only used to retry a failed run -- runs start automatically. */
  onRun: () => void;
  onExpand: () => void;
}

const SOURCE_LABELS: Record<string, string> = {
  predefined: "Predefined",
  planner: "Planner",
  custom: "Custom",
  ai_suggested: "AI",
  drilldown: "Drilldown",
};

export default function AnalysisCard({ entry, running, runFailure, onRun, onExpand }: AnalysisCardProps) {
  return (
    <div className="analysis-card">
      <div className="analysis-card__header">
        <span className="analysis-card__icon">
          <IconBarChart />
        </span>
        <div className="analysis-card__header-text">
          <h3 className="analysis-card__name">{entry.name}</h3>
        </div>
        {entry.source !== "predefined" && (
          <span className={entry.source === "ai_suggested" ? "analysis-card__ai-badge" : "analysis-card__custom-badge"}>
            {SOURCE_LABELS[entry.source] ?? entry.source}
          </span>
        )}
      </div>

      <p className="analysis-card__description">{entry.description}</p>

      {entry.run_status === "not_run" && !runFailure && (
        <p className="analysis-card__status" role="status">
          {running ? <span className="analysis-card__spinner" aria-hidden="true" /> : <IconSparkle />}
          {running ? "Computing this analysis…" : "Queued -- starts automatically"}
        </p>
      )}

      {entry.run_status === "not_run" && runFailure && !running && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{runFailure}</p>
          <button type="button" className="analysis-card__run-btn analysis-card__run-btn--retry" onClick={onRun}>
            Retry
          </button>
        </div>
      )}

      {entry.run_status === "error" && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{entry.error}</p>
          <button type="button" className="analysis-card__run-btn analysis-card__run-btn--retry" disabled={running} onClick={onRun}>
            {running ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {entry.run_status === "done" && (
        <>
          {entry.interpretation && (
            <p className="analysis-card__interpretation analysis-card__interpretation--oneline" title={entry.interpretation}>
              {entry.interpretation}
            </p>
          )}
          <button type="button" className="analysis-card__expand-btn" onClick={onExpand}>
            <IconExpand /> View chart & details{entry.drilldown_suggestions.length > 0 ? " / drilldowns" : ""}
          </button>
        </>
      )}
    </div>
  );
}
