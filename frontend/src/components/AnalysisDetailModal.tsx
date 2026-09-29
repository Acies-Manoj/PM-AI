import { useEffect, useRef, useState } from "react";
import type {
  AnalysisFilterSelections,
  AnalysisRepositoryEntry,
  ConfirmDrilldownBody,
  DrilldownOptions,
  DrilldownProposal,
  DrilldownRank,
} from "../api/audit";
import { AuditApiError } from "../api/audit";
import Modal from "./Modal";
import AnalysisChart from "./AnalysisChart";
import AnalysisFilterBar from "./AnalysisFilterBar";
import DrilldownPanel, { DrilldownRankControl } from "./DrilldownPanel";
import type { LevelNode } from "../utils/drilldownTree";
import { IconChevronLeft, IconChevronRight, IconLayers, IconSparkle } from "./icons";
import { CHART_LABELS } from "../utils/analysisLabels";
import "./AnalysisCard.css";
import "./AnalysisDetailModal.css";
import "./FeatureCard.css";

interface AnalysisDetailModalProps {
  entry: AnalysisRepositoryEntry;
  /** Name of the analysis this one was drilled down from -- undefined for a
   * top-level (non-drilldown) entry. */
  parentName?: string;
  /** The drilldown suggestion ids the PM has selected for this entry --
   * frontend-only bookkeeping, undefined until seeded (see onSeedSelection). */
  selectedIds: Set<string> | undefined;
  onToggleSelect: (drilldownId: string) => void;
  /** Called once, the first time this entry is opened with no selection
   * recorded yet, so already-explored drilldowns start out selected. */
  onSeedSelection: (drilldownIds: string[]) => void;
  triggeringDrilldownId: string | null;
  /** Last Explore / Suggest-more failure (e.g. the backend session expired). */
  drilldownError?: string | null;
  /** True while a "Suggest more drill-downs" request for this entry is running. */
  suggestingMore: boolean;
  onSuggestMore: () => void;
  /** True while this entry's own run is in flight; drives the Retry button. */
  running: boolean;
  onRetry: () => void;
  onClose: () => void;
  onTriggerDrilldown: (drilldownId: string) => void;
  onOpenChild: (childEntryId: string) => void;
  /** Returns a filtered VIEW of this entry; the stored result is untouched. */
  onApplyFilters: (filters: AnalysisFilterSelections) => Promise<AnalysisRepositoryEntry>;
  /** Ancestors of this entry (root first) for the chain breadcrumb. */
  trail: { id: string; label: string }[];
  /** Drill-down levels beneath this entry, depth-first. */
  childLevels: LevelNode[];
  /** Guided drill-down (see DrilldownPanel). Each rejects with an AuditApiError on failure. */
  onFetchDrilldownOptions: () => Promise<DrilldownOptions>;
  onProposeDrilldowns: () => Promise<DrilldownProposal[]>;
  onConfirmDrilldown: (body: ConfirmDrilldownBody) => Promise<void>;
  /** Re-rank / refresh this chain level; the page refetches the repository afterwards. */
  onRerankLevel: (rank: DrilldownRank) => Promise<void>;
  onRefreshLevel: () => Promise<void>;
}

type ModalTab = "analysis" | "selected";

export default function AnalysisDetailModal({
  entry,
  parentName,
  selectedIds,
  onToggleSelect,
  onSeedSelection,
  triggeringDrilldownId,
  drilldownError,
  suggestingMore,
  onSuggestMore,
  running,
  onRetry,
  onClose,
  onTriggerDrilldown,
  onOpenChild,
  onApplyFilters,
  trail,
  childLevels,
  onFetchDrilldownOptions,
  onProposeDrilldowns,
  onConfirmDrilldown,
  onRerankLevel,
  onRefreshLevel,
}: AnalysisDetailModalProps) {
  // The filtered view, if filters are applied. Reset whenever the stored
  // entry changes (a re-run, or navigating to another entry).
  const [view, setView] = useState<AnalysisRepositoryEntry | null>(null);
  const [filtering, setFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [modalTab, setModalTab] = useState<ModalTab>("analysis");
  const [dataSubTab, setDataSubTab] = useState<"table" | "chart">("chart");
  // Only the latest filter request may update the view -- an older, slower
  // response must not overwrite a newer selection.
  const latestRequest = useRef(0);
  const [drillOptions, setDrillOptions] = useState<DrilldownOptions | null>(null);
  const [drillError, setDrillError] = useState<string | null>(null);
  const [levelBusy, setLevelBusy] = useState(false);
  const [levelError, setLevelError] = useState<string | null>(null);
  const fetchOptionsRef = useRef(onFetchDrilldownOptions);
  fetchOptionsRef.current = onFetchDrilldownOptions;

  useEffect(() => {
    latestRequest.current += 1;
    setView(null);
    setFilterError(null);
    setFiltering(false);
    setModalTab("analysis");
  }, [entry]);

  // Options belong to one entry; drop them when navigating to another.
  useEffect(() => {
    setDrillOptions(null);
    setDrillError(null);
    setLevelError(null);
  }, [entry.id]);

  // Refetched whenever the stored entry changes (a re-rank or refresh alters
  // what the next level can offer); the previous options stay up meanwhile.
  useEffect(() => {
    if (entry.run_status !== "done") return;
    let cancelled = false;
    fetchOptionsRef.current()
      .then((o) => {
        if (!cancelled) {
          setDrillOptions(o);
          setDrillError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setDrillError(err instanceof AuditApiError ? err.message : "Couldn't load drill-down options.");
      });
    return () => {
      cancelled = true;
    };
  }, [entry]);

  useEffect(() => {
    if (selectedIds === undefined) {
      onSeedSelection(entry.drilldown_suggestions.filter((d) => d.triggered).map((d) => d.id));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.id, selectedIds]);

  const shown = view ?? entry;
  const canFilter = entry.run_status === "done" && entry.filters.length > 0;
  const suggestionCount = entry.drilldown_suggestions.length;
  const selectedCount = selectedIds?.size ?? 0;

  const chain = entry.chain;
  const runLevelAction = (action: () => Promise<void>) => {
    setLevelBusy(true);
    setLevelError(null);
    action()
      .catch((err) => setLevelError(err instanceof AuditApiError ? err.message : "Couldn't update this drill-down level."))
      .finally(() => setLevelBusy(false));
  };

  const changeFilters = (filters: AnalysisFilterSelections) => {
    const request = ++latestRequest.current;
    setFilterError(null);
    if (Object.keys(filters).length === 0) {
      setView(null);
      setFiltering(false);
      return;
    }
    setFiltering(true);
    onApplyFilters(filters)
      .then((result) => {
        if (request === latestRequest.current) setView(result.applied_filters ? result : null);
      })
      .catch((err) => {
        if (request === latestRequest.current) {
          setFilterError(err instanceof AuditApiError ? err.message : "Couldn't apply those filters.");
        }
      })
      .finally(() => {
        if (request === latestRequest.current) setFiltering(false);
      });
  };

  return (
    <Modal title={entry.name} onClose={onClose}>
      {entry.parent_id && parentName && (
        <button type="button" className="analysis-detail__back-btn" onClick={() => onOpenChild(entry.parent_id!)}>
          <IconChevronLeft /> Back to {parentName}
        </button>
      )}

      {chain && trail.length > 0 && (
        <nav className="drilldown-crumbs" aria-label="Drill-down chain">
          {trail.map((t) => (
            <span key={t.id}>
              <button type="button" onClick={() => onOpenChild(t.id)}>{t.label}</button> ›{" "}
            </span>
          ))}
          <span>{`Level ${chain.level} · ${chain.focus_label || entry.name}`}</span>
        </nav>
      )}

      <p className="analysis-card__description">{entry.description}</p>

      {chain && (
        <>
          <div className="drilldown-level">
            <span className="drilldown-level__chip">{`Level ${chain.level} · ${chain.focus_label || entry.name}`}</span>
            {chain.stale && <span className="drilldown-tag drilldown-tag--stale">Stale</span>}
            <DrilldownRankControl
              rank={chain.rank}
              metrics={drillOptions?.metrics ?? ["count"]}
              disabled={levelBusy}
              onChange={(rank) => runLevelAction(() => onRerankLevel(rank))}
            />
          </div>
          {chain.stale && (
            <div className="drilldown-stale" role="status">
              Stale - upstream changed
              <button type="button" className="drilldown-btn" disabled={levelBusy} onClick={() => runLevelAction(onRefreshLevel)}>
                {levelBusy ? "Refreshing…" : "Refresh"}
              </button>
            </div>
          )}
          {levelError && <p className="analysis-card__error">{levelError}</p>}
        </>
      )}

      {entry.run_status === "error" && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{entry.error ?? "This analysis couldn't be computed."}</p>
          <button type="button" className="analysis-card__run-btn analysis-card__run-btn--retry" disabled={running} onClick={onRetry}>
            {running ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}
      {entry.run_status === "not_run" && running && <p className="analysis-card__status" role="status">Computing…</p>}

      {entry.run_status === "done" && (
        <div className="analysis-detail__meta-row">
          <span className={`analysis-detail__method-badge analysis-detail__method-badge--${entry.computation_mode === "template" ? "template" : "code"}`}>
            {entry.computation_mode === "template" ? "Template" : "Generated Code"}
          </span>
          {entry.chart_recommendation && (
            <span className="analysis-detail__chart-badge">{CHART_LABELS[entry.chart_recommendation.chart_type]} chart</span>
          )}
        </div>
      )}

      {entry.run_status === "done" && (entry.template_summary || entry.chart_recommendation?.reason || entry.computation_mode === "code") && (
        <p className="analysis-detail__meta-note">
          {entry.computation_mode === "template"
            ? entry.template_summary ?? "Computed by a deterministic template."
            : "Computed by pandas code the Analysis Agent wrote and ran in a sandbox."}
          {entry.chart_recommendation?.reason ? ` · ${entry.chart_recommendation.reason}` : ""}
        </p>
      )}

      {entry.interpretation && (
        <div className="analysis-detail__insight">
          <span className="analysis-detail__insight-icon">
            <IconSparkle />
          </span>
          <div className="analysis-detail__insight-body">
            <span className="analysis-detail__insight-label">Key Insight</span>
            <p className="analysis-detail__insight-text">{entry.interpretation}</p>
          </div>
        </div>
      )}

      {entry.run_status === "done" && (
        <>
          <div className="analysis-detail__modal-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={modalTab === "analysis"}
              className={`analysis-detail__modal-tab${modalTab === "analysis" ? " analysis-detail__modal-tab--active" : ""}`}
              onClick={() => setModalTab("analysis")}
            >
              Analysis
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={modalTab === "selected"}
              className={`analysis-detail__modal-tab${modalTab === "selected" ? " analysis-detail__modal-tab--active" : ""}`}
              onClick={() => setModalTab("selected")}
            >
              <IconLayers /> Selected Drill-downs
              {selectedCount > 0 && <span className="analysis-detail__modal-tab-count">{selectedCount}</span>}
            </button>
          </div>

          {modalTab === "analysis" ? (
            <>
              {canFilter && (
                <AnalysisFilterBar key={entry.id} filters={entry.filters} busy={filtering} onChange={changeFilters} />
              )}
              {filterError && <p className="analysis-card__error">{filterError}</p>}
              {view?.applied_filters && (
                <p className="analysis-filter__banner">
                  Filtered view. The interpretation and drilldowns describe the full, unfiltered data.
                </p>
              )}
              {shown.run_status === "error" && view && <p className="analysis-card__error">{shown.error}</p>}

              {shown.run_status === "done" && (
                <>
                  <div className="analysis-detail__tabs" role="tablist">
                    {(["table", "chart"] as const).map((t) => (
                      <button
                        type="button"
                        role="tab"
                        key={t}
                        aria-selected={dataSubTab === t}
                        className={`analysis-detail__tab${dataSubTab === t ? " analysis-detail__tab--active" : ""}`}
                        onClick={() => setDataSubTab(t)}
                      >
                        {t === "table" ? "Table" : "Chart"}
                      </button>
                    ))}
                  </div>
                  {dataSubTab === "chart" ? (
                    <AnalysisChart chartSpec={shown.chart_spec} chartType={shown.chart_type} resultTable={shown.result_table} />
                  ) : (
                    <AnalysisChart chartSpec={null} chartType="table" resultTable={shown.result_table} maxTableRows={500} />
                  )}
                </>
              )}
              {shown.notes.length > 0 && (
                <ul className="analysis-detail__notes">
                  {shown.notes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              )}
              {shown.generated_code && (
                <div className="feature-card__code-block">
                  <span className="feature-card__code-label">Analysis Agent-generated pandas code</span>
                  <pre className="feature-card__code"><code>{shown.generated_code}</code></pre>
                </div>
              )}

              <div className="analysis-detail__suggested-drilldowns">
                <div className="analysis-detail__suggested-drilldowns-head">
                  <h4 className="analysis-detail__suggested-drilldowns-title">Suggested Drill-downs</h4>
                  {entry.run_status === "done" && (
                    <button
                      type="button"
                      className="analysis-detail__suggest-more-btn"
                      disabled={suggestingMore}
                      onClick={onSuggestMore}
                    >
                      <IconSparkle />
                      {suggestingMore ? "Finding more…" : "Suggest more"}
                    </button>
                  )}
                </div>
                {drillError && <p className="analysis-card__error">{drillError}</p>}
                {drilldownError && <p className="analysis-card__error">{drilldownError}</p>}
                {drillOptions && drillOptions.can_drill && (
                  <DrilldownPanel
                    key={entry.id}
                    options={drillOptions}
                    multiFocus={!!chain}
                    onPropose={onProposeDrilldowns}
                    onConfirm={onConfirmDrilldown}
                  />
                )}
                {drillOptions && !drillOptions.can_drill && drillOptions.reason && (
                  <p className="analysis-detail__empty-drilldown">{drillOptions.reason}</p>
                )}
                {childLevels.length > 0 && (
                  <ul className="drilldown-levels">
                    {childLevels.map((l) => (
                      <li key={l.id} style={{ paddingLeft: (l.depth - 1) * 16 }}>
                        <button type="button" className="drilldown-tree__item" onClick={() => onOpenChild(l.id)}>
                          {l.label}
                        </button>
                        {l.stale && <span className="drilldown-tag drilldown-tag--stale">Stale</span>}
                      </li>
                    ))}
                  </ul>
                )}
                {suggestionCount === 0 ? (
                  <p className="analysis-detail__empty-drilldown">No follow-up analyses suggested for this one yet.</p>
                ) : (
                  <ol className="analysis-detail__drilldown-list">
                    {entry.drilldown_suggestions.map((d, i) => {
                      const checked = selectedIds?.has(d.id) ?? false;
                      return (
                        <li key={d.id}>
                          <div className={`analysis-detail__drilldown-item${checked ? " analysis-detail__drilldown-item--selected" : ""}`}>
                            <span className="analysis-detail__drilldown-index">{i + 1}</span>
                            <div className="analysis-detail__drilldown-text">
                              <span className="analysis-detail__drilldown-name">
                                {d.name}
                                <span className="analysis-detail__drilldown-ai-tag" title="Written by the AI from this analysis's result">AI idea</span>
                                {d.triggered && <span className="analysis-detail__drilldown-explored-tag">Explored</span>}
                              </span>
                              <p className="analysis-detail__drilldown-desc">{d.description}</p>
                            </div>
                            <button
                              type="button"
                              className="analysis-detail__drilldown-action-btn"
                              disabled={triggeringDrilldownId === d.id}
                              onClick={() => {
                                if (!checked) onToggleSelect(d.id);
                                if (d.triggered && d.child_entry_id) onOpenChild(d.child_entry_id);
                                else onTriggerDrilldown(d.id);
                              }}
                            >
                              {triggeringDrilldownId === d.id ? "Exploring…" : "Explore more"}
                              <IconChevronRight />
                            </button>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </div>
            </>
          ) : (
            <div className="analysis-detail__drilldown-tab">
              {selectedCount === 0 ? (
                <div className="analysis-detail__empty-drilldown-block">
                  <p className="analysis-detail__empty-drilldown">No drill-downs selected yet.</p>
                  <p className="analysis-detail__empty-drilldown-hint">
                    Select a suggested drill-down from the Analysis tab to explore this analysis further.
                  </p>
                  <button type="button" className="analysis-detail__add-drilldown-btn" onClick={() => setModalTab("analysis")}>
                    + Add Drill-down
                  </button>
                </div>
              ) : (
                <ol className="analysis-detail__drilldown-list">
                  {entry.drilldown_suggestions
                    .filter((d) => selectedIds?.has(d.id))
                    .map((d) => (
                      <li key={d.id}>
                        <div className="analysis-detail__selected-item">
                          <span className="analysis-detail__drilldown-name">{d.name}</span>
                          <button
                            type="button"
                            className="analysis-detail__drilldown-action-btn"
                            disabled={triggeringDrilldownId === d.id}
                            onClick={() => (d.triggered && d.child_entry_id ? onOpenChild(d.child_entry_id) : onTriggerDrilldown(d.id))}
                          >
                            {triggeringDrilldownId === d.id ? "Exploring…" : d.triggered ? "View" : "Explore"}
                            <IconChevronRight />
                          </button>
                          <button
                            type="button"
                            className="analysis-detail__remove-btn"
                            aria-label={`Remove ${d.name} from selected drill-downs`}
                            onClick={() => onToggleSelect(d.id)}
                          >
                            ×
                          </button>
                        </div>
                      </li>
                    ))}
                </ol>
              )}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
