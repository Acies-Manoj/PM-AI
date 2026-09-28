import type { AnalysisRepositoryEntry } from "../api/audit";
import { sourceTag } from "../utils/analysisSourceTag";
import { IconBarChart, IconChevronRight, IconShieldCheck } from "./icons";
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

export default function AnalysisCard({ entry, running, runFailure, onRun, onExpand }: AnalysisCardProps) {
  const tag = sourceTag(entry.source);
  const failed = entry.run_status === "error" || (entry.run_status === "not_run" && !!runFailure && !running);

  return (
    <div
      className="analysis-card"
      role="button"
      tabIndex={0}
      onClick={onExpand}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") onExpand();
      }}
    >
      <div className="analysis-card__top">
        <span className={`analysis-card__icon analysis-card__icon--${tag.color}`}>
          <IconBarChart />
        </span>
        <span className={`analysis-card__pill analysis-card__pill--${tag.color}`}>{tag.label}</span>
      </div>

      <h3 className="analysis-card__name">{entry.name}</h3>
      <p className="analysis-card__description">{entry.description}</p>

      {entry.run_status === "not_run" && !failed && (
        <p className="analysis-card__status" role="status">
          {running ? <span className="analysis-card__spinner" aria-hidden="true" /> : <span className="analysis-card__status-dot" />}
          {running ? "Computing…" : "Queued"}
        </p>
      )}

      {failed && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{runFailure ?? entry.error}</p>
          <button
            type="button"
            className="analysis-card__run-btn analysis-card__run-btn--retry"
            onClick={(e) => {
              e.stopPropagation();
              onRun();
            }}
          >
            Retry
          </button>
        </div>
      )}

      {entry.run_status === "done" && (
        <p className="analysis-card__ready">
          <IconShieldCheck /> Ready
        </p>
      )}

      <span className="analysis-card__arrow" aria-hidden="true">
        <IconChevronRight />
      </span>
    </div>
  );
}
