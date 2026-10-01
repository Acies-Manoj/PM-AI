import ThinkingLoader, { Spinner } from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import type { AnalysisRepositoryEntry } from "../api/audit";
import { sourceTag } from "../utils/analysisSourceTag";
import { IconBarChart, IconChevronRight, IconShieldCheck } from "./icons";
import type { LevelNode } from "../utils/drilldownTree";
import "./AnalysisCard.css";
import "./DrilldownPanel.css";

interface AnalysisCardProps {
  entry: AnalysisRepositoryEntry;
  running: boolean;
  /** Set when the run request itself failed (network / server error). */
  runFailure?: string;
  /** Only used to retry a failed run -- runs start automatically. */
  onRun: () => void;
  onExpand: () => void;
  /** Drill-down levels beneath this analysis, shown as an indented chain. */
  levels?: LevelNode[];
  onOpenLevel?: (entryId: string) => void;
  /** Approve one required feature (then the page computes it). */
  onSelectFeature?: (featureId: string) => void;
  /** Compute the features so an approved required feature becomes usable. */
  onComputeFeatures?: () => void;
  /** "select:<featureId>" | "compute" while a required-feature action runs. */
  featureBusy?: string;
  featureError?: string;
}

export default function AnalysisCard({
  entry,
  running,
  runFailure,
  onRun,
  onExpand,
  levels = [],
  onOpenLevel,
  onSelectFeature,
  onComputeFeatures,
  featureBusy,
  featureError,
}: AnalysisCardProps) {
  const tag = sourceTag(entry.source);
  const requiredFeatures = entry.required_features ?? [];
  const blocked = entry.dependencies_satisfied === false;
  const blockedMessage = "Select all required features before continuing.";
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

      {requiredFeatures.length > 0 && (
        <div className="analysis-card__required" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <p className="analysis-card__required-title">Required features</p>
          <ul className="analysis-card__required-list">
            {requiredFeatures.map((f) => {
              const statusText =
                f.message ||
                (f.state === "satisfied"
                  ? "Selected and computed"
                  : f.state === "not_computed"
                    ? "Approved - not computed yet"
                    : "Required feature not selected");
              const key = f.feature_id ?? f.name;
              return (
                <li key={key} className="analysis-card__required-row">
                  <input type="checkbox" checked={f.satisfied || f.state === "satisfied"} disabled readOnly aria-label={`${f.name} selected`} />
                  <div className="analysis-card__required-text">
                    <span className="analysis-card__required-name">
                      {f.name}
                      {f.output_column && <code className="analysis-card__required-col">{f.output_column}</code>}
                    </span>
                    <span className={`analysis-card__required-status analysis-card__required-status--${f.state}`}>{statusText}</span>
                  </div>
                  {(f.state === "not_approved" || f.state === "missing") && f.feature_id && (
                    <button
                      type="button"
                      className="analysis-card__run-btn analysis-card__required-btn"
                      disabled={!!featureBusy}
                      onClick={() => onSelectFeature?.(f.feature_id!)}
                    >
                      {featureBusy === `select:${f.feature_id}` ? "Selecting…" : "Select"}
                    </button>
                  )}
                  {f.state === "not_computed" && (
                    <button
                      type="button"
                      className="analysis-card__run-btn analysis-card__required-btn"
                      disabled={!!featureBusy}
                      onClick={() => onComputeFeatures?.()}
                    >
                      {featureBusy === "compute" ? <><Spinner />Computing…</> : "Compute features"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {featureError && <p className="analysis-card__error">{featureError}</p>}
        </div>
      )}

      {entry.run_status === "not_run" && !failed && (
        running ? (
          <ThinkingLoader variant="inline" messages={LOADING.analysisRun} />
        ) : (
          <p className="analysis-card__status" role="status">
            <span className="analysis-card__status-dot" />
            {blocked ? blockedMessage : "Queued"}
          </p>
        )
      )}

      {failed && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{runFailure ?? entry.error}</p>
          <button
            type="button"
            className="analysis-card__run-btn analysis-card__run-btn--retry"
            disabled={blocked}
            title={blocked ? blockedMessage : undefined}
            onClick={(e) => {
              e.stopPropagation();
              onRun();
            }}
          >
            Retry
          </button>
          {blocked && <p className="analysis-card__required-status analysis-card__required-status--not_approved">{blockedMessage}</p>}
        </div>
      )}

      {entry.run_status === "done" && (
        <p className="analysis-card__ready">
          <IconShieldCheck /> Ready
        </p>
      )}

      {levels.length > 0 && (
        <ul className="drilldown-tree" aria-label="Drill-down chain">
          {levels.map((l) => (
            <li key={l.id} style={{ paddingLeft: (l.depth - 1) * 12 }}>
              <span aria-hidden="true">›</span>
              <button
                type="button"
                className="drilldown-tree__item"
                onClick={(e) => {
                  e.stopPropagation();
                  onOpenLevel?.(l.id);
                }}
                onKeyDown={(e) => e.stopPropagation()}
              >
                {l.label}
              </button>
              {l.stale && <span className="drilldown-tag drilldown-tag--stale">Stale</span>}
            </li>
          ))}
        </ul>
      )}

      <span className="analysis-card__arrow" aria-hidden="true">
        <IconChevronRight />
      </span>
    </div>
  );
}
