import { useEffect, useState } from "react";
import type { AuditIssue } from "../api/audit";
import { IconChevronRight } from "./icons";
import OutlierBoxPlot from "./OutlierBoxPlot";
import IssueRowsModal from "./IssueRowsModal";
import "./AuditIssueCard.css";

export const COLUMN_SCOPED_CATEGORIES = new Set(["fully_empty_columns", "high_null_columns", "constant_value_columns"]);

interface AuditIssueCardProps {
  issue: AuditIssue;
  sessionId: string;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevert: (issueId: string) => void;
  resolving: boolean;
  // True when this resolution changed the data (dropped columns / removed
  // rows) but a later data-changing resolution now sits on top of it, so
  // reverting it out of order isn't safe -- the button stays visible but
  // disabled with an explanation, rather than reverting silently wrong.
}

// Resolution text like "Dropped 10 column(s): A, B, C." splits into a short
// headline plus an optional detail list, so a 10-column drop doesn't dump a
// wall of names into the card by default.
function splitResolution(resolution: string): { headline: string; detail: string | null } {
  const idx = resolution.indexOf(": ");
  if (idx === -1) return { headline: resolution, detail: null };
  return { headline: `${resolution.slice(0, idx)}.`, detail: resolution.slice(idx + 2) };
}

export default function AuditIssueCard({
  issue,
  sessionId,
  onResolve,
  onRevert,
  resolving,
}: AuditIssueCardProps) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [showRowsModal, setShowRowsModal] = useState(false);
  const [showResolutionDetail, setShowResolutionDetail] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(() => new Set(issue.selectable_items));
  const unit = COLUMN_SCOPED_CATEGORIES.has(issue.category) ? "column(s)" : "row(s)";
  const isSelectable = issue.selectable_items.length > 0;
  const resolutionParts = issue.resolution ? splitResolution(issue.resolution) : null;
  const isResolved = issue.status === "resolved" && resolutionParts;

  // Once resolved, this instance no longer has anything to show a detail
  // popup for -- close it out rather than leaving a stale modal reachable.
  useEffect(() => {
    if (isResolved) setDetailOpen(false);
  }, [isResolved]);

  useEffect(() => {
    if (!detailOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDetailOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detailOpen]);

  const toggleItem = (item: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  };

  const resolveAndClose = (decisionId: string, selectedItems?: string[]) => {
    onResolve(issue.id, decisionId, selectedItems);
    setDetailOpen(false);
  };

  const dropOption = issue.options.find((o) => o.id === "drop_selected");
  const keepOption = issue.options.find((o) => o.id === "keep");

  return (
    <div className={`audit-issue audit-issue--${issue.severity} ${isResolved ? "audit-issue--resolved" : ""}`}>
      {isResolved ? (
        <div className="audit-issue__resolved-block">
          <div className="audit-issue__resolved-row">
            <p className="audit-issue__resolved-title">{issue.title}</p>
            <button
              type="button"
              className="audit-issue__link audit-issue__revert-btn"
              disabled={resolving}
              onClick={() => onRevert(issue.id)}
            >
              {resolving ? "Reverting…" : "Revert"}
            </button>
          </div>
          <p className="audit-issue__resolution">
            <span className="audit-issue__resolution-icon">✓</span>
            {resolutionParts!.headline}
          </p>
          {resolutionParts!.detail && (
            <>
              <button
                type="button"
                className="audit-issue__sample-toggle"
                onClick={() => setShowResolutionDetail((s) => !s)}
              >
                {showResolutionDetail ? "Hide list" : "Show full list"}
              </button>
              {showResolutionDetail && <p className="audit-issue__resolution-detail">{resolutionParts!.detail}</p>}
            </>
          )}
        </div>
      ) : (
        <button type="button" className="audit-issue__tile" onClick={() => setDetailOpen(true)}>
          <div className="audit-issue__tile-head">
            <h4 className="audit-issue__title">{issue.title}</h4>
            <span className="audit-issue__tile-chevron">
              <IconChevronRight />
            </span>
          </div>
          <span className="audit-issue__affected">
            {issue.affected_row_count} {unit}
          </span>
        </button>
      )}

      {detailOpen && (
        <div className="audit-issue__modal-backdrop" onClick={() => setDetailOpen(false)}>
          <div className="audit-issue__modal" onClick={(e) => e.stopPropagation()}>
            <div className="audit-issue__modal-head">
              <div className="audit-issue__top">
                <h4 className="audit-issue__title">{issue.title}</h4>
                <span className="audit-issue__affected">
                  {issue.affected_row_count} {unit}
                </span>
              </div>
              <button type="button" className="audit-issue__modal-close" onClick={() => setDetailOpen(false)} aria-label="Close">
                ✕
              </button>
            </div>

            <div className="audit-issue__modal-body">
              <p className="audit-issue__description">{issue.description}</p>

              {issue.chart && (
                <div className="audit-issue__chart-panel">
                  <OutlierBoxPlot chart={issue.chart} />
                </div>
              )}

              {issue.sample.length > 0 && (
                <button type="button" className="audit-issue__sample-toggle" onClick={() => setShowRowsModal(true)}>
                  View all affected rows ({issue.affected_row_count}) ⤢
                </button>
              )}
              {showRowsModal && (
                <IssueRowsModal
                  title={issue.title}
                  sessionId={sessionId}
                  issueId={issue.id}
                  onClose={() => setShowRowsModal(false)}
                />
              )}

              {isSelectable ? (
                <div className="audit-issue__checklist-block">
                  <div className="audit-issue__checklist-toolbar">
                    <span className="audit-issue__checklist-count">{checked.size} of {issue.selectable_items.length} selected</span>
                    <button
                      type="button"
                      className="audit-issue__link"
                      onClick={() =>
                        setChecked(checked.size === issue.selectable_items.length ? new Set() : new Set(issue.selectable_items))
                      }
                    >
                      {checked.size === issue.selectable_items.length ? "Deselect all" : "Select all"}
                    </button>
                  </div>
                  <ul className="audit-issue__checklist">
                    {issue.selectable_items.map((item) => (
                      <li key={item} className="audit-issue__checklist-item">
                        <label>
                          <input
                            type="checkbox"
                            checked={checked.has(item)}
                            disabled={resolving}
                            onChange={() => toggleItem(item)}
                          />
                          <span>{item}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                  <div className="audit-issue__actions">
                    {dropOption && (
                      <button
                        type="button"
                        className={`btn btn--sm btn--primary`}
                        disabled={resolving || checked.size === 0}
                        onClick={() => resolveAndClose(dropOption.id, Array.from(checked))}
                      >
                        {dropOption.label} ({checked.size})
                      </button>
                    )}
                    {keepOption && (
                      <button
                        type="button"
                        className={`btn btn--sm btn--secondary`}
                        disabled={resolving}
                        onClick={() => resolveAndClose(keepOption.id)}
                      >
                        {keepOption.label}
                      </button>
                    )}
                  </div>
                </div>
              ) : issue.requires_decision ? (
                <div className="audit-issue__actions">
                  {issue.options.map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      className={`btn btn--sm ${opt.id === "keep" ? "btn--secondary" : "btn--primary"}`}
                      disabled={resolving}
                      onClick={() => resolveAndClose(opt.id)}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
