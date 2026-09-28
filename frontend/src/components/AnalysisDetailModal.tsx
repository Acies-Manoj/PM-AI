import { useEffect, useRef, useState } from "react";
import type { AnalysisFilterSelections, AnalysisRepositoryEntry } from "../api/audit";
import { AuditApiError } from "../api/audit";
import Modal from "./Modal";
import AnalysisChart from "./AnalysisChart";
import AnalysisFilterBar from "./AnalysisFilterBar";
import { IconChevronLeft, IconChevronRight, IconLayers } from "./icons";
import { CHART_LABELS } from "../utils/analysisLabels";
import "./AnalysisCard.css";
import "./AnalysisDetailModal.css";
import "./FeatureCard.css";

interface AnalysisDetailModalProps {
  entry: AnalysisRepositoryEntry;
  /** Name of the analysis this one was drilled down from -- undefined for a
   * top-level (non-drilldown) entry. */
  parentName?: string;
  /** This entry's own already-triggered drilldown children, if any. */
  childEntries: AnalysisRepositoryEntry[];
  onClose: () => void;
  onOpenChild: (childEntryId: string) => void;
  /** Returns a filtered VIEW of this entry; the stored result is untouched. */
  onApplyFilters: (filters: AnalysisFilterSelections) => Promise<AnalysisRepositoryEntry>;
}

type ModalTab = "data" | "drilldown";

export default function AnalysisDetailModal({
  entry,
  parentName,
  childEntries,
  onClose,
  onOpenChild,
  onApplyFilters,
}: AnalysisDetailModalProps) {
  // The filtered view, if filters are applied. Reset whenever the stored
  // entry changes (a re-run, or navigating to another entry).
  const [view, setView] = useState<AnalysisRepositoryEntry | null>(null);
  const [filtering, setFiltering] = useState(false);
  const [filterError, setFilterError] = useState<string | null>(null);
  const [modalTab, setModalTab] = useState<ModalTab>("data");
  const [dataSubTab, setDataSubTab] = useState<"table" | "chart">("chart");
  // Only the latest filter request may update the view -- an older, slower
  // response must not overwrite a newer selection.
  const latestRequest = useRef(0);

  useEffect(() => {
    latestRequest.current += 1;
    setView(null);
    setFilterError(null);
    setFiltering(false);
    setModalTab("data");
  }, [entry]);

  const shown = view ?? entry;
  const canFilter = entry.run_status === "done" && entry.filters.length > 0;
  const drilldownCount = childEntries.length;

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

      <p className="analysis-card__description">{entry.description}</p>

      {entry.run_status === "done" && (
        <p className="analysis-detail__method">
          {entry.computation_mode === "template" ? (
            <>
              <span className="analysis-detail__method-badge analysis-detail__method-badge--template">Template</span>
              {entry.template_summary ?? "Computed by a deterministic template."}
            </>
          ) : (
            <>
              <span className="analysis-detail__method-badge analysis-detail__method-badge--code">Generated code</span>
              Computed by pandas code the Analysis Agent wrote and ran in a sandbox.
            </>
          )}
        </p>
      )}

      {entry.run_status === "done" && entry.chart_recommendation && (
        <p className="analysis-detail__chart-choice">
          <strong>{CHART_LABELS[entry.chart_recommendation.chart_type]} chart</strong>, chosen from the computation logic before
          computing{entry.chart_recommendation.reason ? ` -- ${entry.chart_recommendation.reason}` : "."}
        </p>
      )}

      {entry.interpretation && <p className="analysis-card__interpretation">{entry.interpretation}</p>}

      {entry.run_status === "done" && (
        <>
          <div className="analysis-detail__modal-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={modalTab === "data"}
              className={`analysis-detail__modal-tab${modalTab === "data" ? " analysis-detail__modal-tab--active" : ""}`}
              onClick={() => setModalTab("data")}
            >
              Table &amp; Chart
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={modalTab === "drilldown"}
              className={`analysis-detail__modal-tab${modalTab === "drilldown" ? " analysis-detail__modal-tab--active" : ""}`}
              onClick={() => setModalTab("drilldown")}
            >
              <IconLayers /> Drill Down
              {drilldownCount > 0 && <span className="analysis-detail__modal-tab-count">{drilldownCount}</span>}
            </button>
          </div>

          {modalTab === "data" ? (
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
            </>
          ) : (
            <div className="analysis-detail__drilldown-tab">
              {childEntries.length > 0 ? (
                <div className="analysis-detail__explored">
                  <h4 className="analysis-drilldowns__title">
                    <IconLayers /> Already explored
                  </h4>
                  <div className="analysis-detail__explored-list">
                    {childEntries.map((child) => (
                      <button
                        type="button"
                        key={child.id}
                        className="analysis-detail__explored-item"
                        onClick={() => onOpenChild(child.id)}
                      >
                        <span className="analysis-detail__explored-name">{child.name}</span>
                        <IconChevronRight />
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="analysis-detail__empty-drilldown">
                  No drilldowns explored yet for this analysis. Check "Suggested Drilldowns" on the main
                  Analysis page to explore one.
                </p>
              )}
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
