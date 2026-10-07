import ThinkingLoader, { Spinner } from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import type { AnalysisRepositoryEntry } from "../api/audit";
import { sourceTag } from "../utils/analysisSourceTag";
import { tidyText } from "../utils/tidyText";
import { IconChevronRight } from "./icons";
import type { LevelNode } from "../utils/drilldownTree";
import "./AnalysisCard.css";
import "./DrilldownPanel.css";

interface AnalysisCardProps {
  entry: AnalysisRepositoryEntry;
  running: boolean;
  /** Set when the run request itself failed (network / server error). */
  runFailure?: string;
  /** Only used to retry a failed run: runs start automatically. */
  onRun: () => void;
  onExpand: () => void;
  /** Drill-down levels beneath this analysis, shown as an indented list. */
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

// The source tag colours (see utils/analysisSourceTag.ts) mapped onto the shared tag classes.
const TAG_CLASS: Record<string, string> = { blue: "analysis", purple: "purple", teal: "existing", amber: "attention" };

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

  // One status tag in the corner says where this analysis is.
  const status = failed
    ? { label: "Failed", cls: "error" }
    : entry.run_status === "done"
      ? { label: "Ready", cls: "success" }
      : running
        ? { label: "Running", cls: "attention" }
        : blocked
          ? { label: "Blocked", cls: "attention" }
          : { label: "Queued", cls: "new" };

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
      <div className="analysis-card__head">
        <span className={`tag tag--${TAG_CLASS[tag.color] ?? "new"}`}>{tag.label}</span>
        <span className={`tag tag--${status.cls}`}>{status.label}</span>
      </div>

      <h3 className="analysis-card__name">{entry.name}</h3>
      <p className="analysis-card__description">{tidyText(entry.description)}</p>

      {requiredFeatures.length > 0 && (
        <div className="analysis-card__section" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <p className="analysis-card__section-title">Required features</p>
          <ul className="analysis-card__required-list">
            {requiredFeatures.map((f) => {
              const statusText =
                f.message ||
                (f.state === "satisfied"
                  ? "Selected and computed"
                  : f.state === "not_computed"
                    ? "Approved, not computed yet"
                    : "Not selected");
              const key = f.feature_id ?? f.name;
              return (
                <li key={key} className="analysis-card__required-row">
                  <span className={`analysis-card__dot analysis-card__dot--${f.state}`} aria-hidden="true" />
                  <div className="analysis-card__required-text">
                    <span className="analysis-card__required-name">{f.name}</span>
                    <span className={`analysis-card__required-status analysis-card__required-status--${f.state}`}>{statusText}</span>
                  </div>
                  {(f.state === "not_approved" || f.state === "missing") && f.feature_id && (
                    <button
                      type="button"
                      className="btn btn--secondary btn--sm"
                      disabled={!!featureBusy}
                      onClick={() => onSelectFeature?.(f.feature_id!)}
                    >
                      {featureBusy === `select:${f.feature_id}` ? "Selecting…" : "Select"}
                    </button>
                  )}
                  {f.state === "not_computed" && (
                    <button type="button" className="btn btn--secondary btn--sm" disabled={!!featureBusy} onClick={() => onComputeFeatures?.()}>
                      {featureBusy === "compute" ? <><Spinner />Computing…</> : "Compute"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
          {featureError && <p className="analysis-card__error">{featureError}</p>}
        </div>
      )}

      {entry.run_status === "not_run" && !failed && running && (
        <ThinkingLoader variant="inline" messages={LOADING.analysisRun} />
      )}

      {failed && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{runFailure ?? entry.error}</p>
          <button
            type="button"
            className="btn btn--secondary btn--sm"
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

      {levels.length > 0 && (
        <div className="analysis-card__section" onClick={(e) => e.stopPropagation()}>
          <p className="analysis-card__section-title">Drill-downs</p>
          <ul className="analysis-card__levels" aria-label="Drill-down chain">
            {levels.map((l) => (
              <li key={l.id} style={{ paddingLeft: (l.depth - 1) * 14 }}>
                <button
                  type="button"
                  className="analysis-card__level"
                  title={l.label}
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
        </div>
      )}

      <span className="analysis-card__arrow" aria-hidden="true">
        <IconChevronRight />
      </span>
    </div>
  );
}
