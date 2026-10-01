import { useEffect, useRef, useState } from "react";
import type {
  AnalysisFilterSelections,
  AnalysisRepositoryEntry,
  ConfirmDrilldownBody,
  DrilldownOptions,
  DrilldownPath,
  DrilldownProposal,
} from "../api/audit";
import { AuditApiError } from "../api/audit";
import Modal from "./Modal";
import AnalysisChart from "./AnalysisChart";
import AnalysisFilterBar from "./AnalysisFilterBar";
import DrilldownPanel from "./DrilldownPanel";
import DrilldownPaths from "./DrilldownPaths";
import type { LevelNode } from "../utils/drilldownTree";
import { IconChevronLeft, IconLayers, IconSparkle } from "./icons";
import { CHART_LABELS } from "../utils/analysisLabels";
import "./AnalysisCard.css";
import "./AnalysisDetailModal.css";
import "./FeatureCard.css";

interface AnalysisDetailModalProps {
  entry: AnalysisRepositoryEntry;
  /** Name of the analysis this one was drilled down from -- undefined for a
   * top-level (non-drilldown) entry. */
  parentName?: string;
  /** Ids the PM has explicitly hidden from the Selected Drill-downs list --
   * frontend-only, doesn't delete anything, just a "remove from this view". */
  dismissedIds: Set<string>;
  onDismiss: (id: string) => void;
  /** True while this entry's own run is in flight; drives the Retry button. */
  running: boolean;
  onRetry: () => void;
  onClose: () => void;
  onOpenChild: (childEntryId: string) => void;
  /** Returns a filtered VIEW of this entry; the stored result is untouched. */
  onApplyFilters: (filters: AnalysisFilterSelections) => Promise<AnalysisRepositoryEntry>;
  /** Ancestors of this entry (root first) for the chain breadcrumb. */
  trail: { id: string; label: string }[];
  /** Drill-down levels beneath this entry, depth-first. */
  childLevels: LevelNode[];
  /** Guided drill-down (see DrilldownPanel). Each rejects with an AuditApiError on failure. */
  onFetchDrilldownOptions: () => Promise<DrilldownOptions>;
  onProposeDrilldowns: (more: boolean) => Promise<DrilldownProposal[]>;
  /** Runs the picked drill-down and navigates to it -- see onOpenChild. */
  onConfirmDrilldown: (body: ConfirmDrilldownBody) => Promise<void>;
  /** Re-rank / refresh this chain level; the page refetches the repository afterwards. */
  onRefreshLevel: () => Promise<void>;
  /** Suggested drill-down PATHS (see DrilldownPaths): list, suggest, accept, reject. */
  onFetchPaths: () => Promise<DrilldownPath[]>;
  onSuggestPath: () => Promise<DrilldownPath>;
  onAcceptPath: (pathId: string) => Promise<DrilldownPath>;
  onRejectPath: (pathId: string) => Promise<DrilldownPath>;
  /** Increments after a guided drill-down is confirmed; switches to the Selected Drill-downs tab. */
  openSelectedSignal?: number;
}

type ModalTab = "analysis" | "paths" | "selected";

export default function AnalysisDetailModal({
  entry,
  parentName,
  dismissedIds,
  onDismiss,
  running,
  onRetry,
  onClose,
  onOpenChild,
  onApplyFilters,
  trail,
  childLevels,
  onFetchDrilldownOptions,
  onProposeDrilldowns,
  onConfirmDrilldown,
  onRefreshLevel,
  openSelectedSignal = 0,
  onFetchPaths,
  onSuggestPath,
  onAcceptPath,
  onRejectPath,
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

  // Declared after the reset above so it wins when both fire in the same render.
  useEffect(() => {
    if (openSelectedSignal > 0) setModalTab("selected");
  }, [openSelectedSignal]);

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

  const shown = view ?? entry;
  const canFilter = entry.run_status === "done" && entry.filters.length > 0;
  // Selected = every existing child level (guided drill-downs, incl. every
  // sibling from a split confirm) -- derived straight from real data every
  // render, not hand-tracked, so it can't fall out of sync with what
  // actually got created.
  const selectedLevels = childLevels.filter((l) => !dismissedIds.has(l.id));
  // A plain list of every drill-down beneath this analysis, sectioned by level
  // (2, 3, 4...). One row per DRILL-DOWN (an analysis) with the values it was run
  // for -- not one row per slide, which repeats the same carrier names.
  const levelSections: { level: number; groups: { analysis: string; levels: LevelNode[] }[] }[] = [];
  for (const l of selectedLevels) {
    let section = levelSections.find((x) => x.level === l.level);
    if (!section) {
      section = { level: l.level, groups: [] };
      levelSections.push(section);
    }
    const group = section.groups.find((g) => g.analysis === l.analysis);
    if (group) group.levels.push(l);
    else section.groups.push({ analysis: l.analysis, levels: [l] });
  }
  levelSections.sort((x, y) => x.level - y.level);
  // The tab badge counts drill-downs (analyses), not slides.
  const selectedCount = levelSections.reduce((n, sec) => n + sec.groups.length, 0);

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
    <Modal title={entry.name} onClose={onClose} resetScrollKey={`${entry.id}:${modalTab}`}>
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
            {entry.run_status === "done" && (
              <button
                type="button"
                role="tab"
                aria-selected={modalTab === "paths"}
                className={`analysis-detail__modal-tab${modalTab === "paths" ? " analysis-detail__modal-tab--active" : ""}`}
                onClick={() => setModalTab("paths")}
              >
                <IconSparkle /> Drill-down Paths
              </button>
            )}
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

          {modalTab === "paths" ? (
            <DrilldownPaths
              key={entry.id}
              onFetch={onFetchPaths}
              onSuggest={onSuggestPath}
              onAccept={onAcceptPath}
              onReject={onRejectPath}
              onViewSelected={() => setModalTab("selected")}
            />
          ) : modalTab === "analysis" ? (
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
                {drillError && <p className="analysis-card__error">{drillError}</p>}
                {drillOptions && drillOptions.can_drill && (
                  <DrilldownPanel
                    key={entry.id}
                    options={drillOptions}
                    onPropose={onProposeDrilldowns}
                    onConfirm={onConfirmDrilldown}
                  />
                )}
                {drillOptions && !drillOptions.can_drill && drillOptions.reason && (
                  <p className="analysis-detail__empty-drilldown">{drillOptions.reason}</p>
                )}
              </div>
            </>
          ) : (
            <div className="analysis-detail__drilldown-tab">
              {selectedCount === 0 ? (
                <div className="analysis-detail__empty-drilldown-block">
                  <p className="analysis-detail__empty-drilldown">No drill-downs selected yet.</p>
                  <p className="analysis-detail__empty-drilldown-hint">
                    Confirm a guided drill-down from the Analysis tab -- it'll show up here.
                  </p>
                  <button type="button" className="analysis-detail__add-drilldown-btn" onClick={() => setModalTab("analysis")}>
                    + Add Drill-down
                  </button>
                </div>
              ) : (
                <div className="analysis-detail__levels">
                  {levelSections.map((section) => (
                    <section key={section.level} className="analysis-detail__level-section">
                      <h5 className="analysis-detail__level-heading">Level {section.level}</h5>
                      <ol className="analysis-detail__drilldown-list">
                        {section.groups.map((g, i) => (
                          <li key={g.analysis}>
                            <div className="analysis-detail__selected-group">
                              <div className="analysis-detail__selected-group-head">
                                <span className="analysis-detail__drilldown-index">{i + 1}</span>
                                <span className="analysis-detail__drilldown-name">
                                  <span className="analysis-detail__group-parent">{entry.name}</span>
                                  {g.levels[0].axes ? (
                                    <>
                                      {" › "}
                                      <span className="analysis-detail__group-axes">X axis: {g.levels[0].axes}</span> · {g.levels[0].measure}
                                    </>
                                  ) : (
                                    <> › {g.analysis}</>
                                  )}
                                </span>
                                <span className="analysis-detail__selected-group-count">
                                  {g.levels.length} slide{g.levels.length === 1 ? "" : "s"}
                                </span>
                              </div>
                              <div className="analysis-detail__selected-group-chips">
                                {g.levels.map((l) => (
                                  <span className="analysis-detail__selected-chip" key={l.id}>
                                    <button type="button" onClick={() => onOpenChild(l.id)} title={`Open ${l.label}`}>
                                      {l.path.join(" › ")}
                                    </button>
                                    {l.stale && <span className="drilldown-tag drilldown-tag--stale">Stale</span>}
                                    <button
                                      type="button"
                                      className="analysis-detail__selected-chip-remove"
                                      aria-label={`Remove ${l.path.join(" › ")} from selected drill-downs`}
                                      onClick={() => onDismiss(l.id)}
                                    >
                                      ×
                                    </button>
                                  </span>
                                ))}
                              </div>
                            </div>
                          </li>
                        ))}
                      </ol>
                    </section>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
