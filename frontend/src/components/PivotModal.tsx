import { useEffect, useState } from "react";
import {
  applyPivotDrillDown,
  AuditApiError,
  fetchChartInterpretation,
  fetchPivotDrillDownSuggestions,
  type FormulaAnswerResponse,
  type PivotResult,
} from "../api/audit";
import Modal from "./Modal";
import PivotFilterBar from "./PivotFilterBar";
import PivotTableCard from "./PivotTableCard";
import PivotChart from "./PivotChart";
import "./PivotModal.css";

interface PivotModalProps {
  pivot: PivotResult;
  sessionId: string;
  filterSelections: Record<string, string[] | undefined>;
  onSaveFilters: (next: Record<string, string[] | undefined>) => void;
  savingFilters?: boolean;
  onClose: () => void;
  // Section 1's "click on an analysis -> drill downs -> add" loop: a
  // suggestion that resolves to a chart is handed back here so the caller
  // can fold it into its own pivot list (it also lives in the session's
  // drill_down_pivots on the backend, so a reload picks it up either way).
  onDrillDownAdded: (pivot: PivotResult) => void;
}

type Tab = "table" | "chart";

export default function PivotModal({
  pivot,
  sessionId,
  filterSelections,
  onSaveFilters,
  savingFilters,
  onClose,
  onDrillDownAdded,
}: PivotModalProps) {
  const [tab, setTab] = useState<Tab>("table");
  const [interpretation, setInterpretation] = useState<string | null>(null);
  const [interpretLoading, setInterpretLoading] = useState(false);
  const [interpretError, setInterpretError] = useState<string | null>(null);

  // Drill-downs FROM this chart specifically (not the session-wide list) --
  // fetched as soon as the modal opens, same as the interpretation above.
  const [drillDowns, setDrillDowns] = useState<string[] | null>(null);
  const [drillDownsLoading, setDrillDownsLoading] = useState(false);
  const [drillDownsError, setDrillDownsError] = useState<string | null>(null);
  const [addingSuggestion, setAddingSuggestion] = useState<string | null>(null);
  const [addedSuggestions, setAddedSuggestions] = useState<Set<string>>(new Set());
  const [nonChartAnswers, setNonChartAnswers] = useState<Record<string, FormulaAnswerResponse>>({});
  const [addError, setAddError] = useState<string | null>(null);

  useEffect(() => {
    setInterpretation(null);
    setInterpretError(null);
    setInterpretLoading(true);
    fetchChartInterpretation(sessionId, pivot.id)
      .then((res) => setInterpretation(res.interpretation))
      .catch((err) => setInterpretError(err instanceof AuditApiError ? err.message : "Could not reach the chart interpretation agent."))
      .finally(() => setInterpretLoading(false));

    setDrillDowns(null);
    setDrillDownsError(null);
    setDrillDownsLoading(true);
    setAddedSuggestions(new Set());
    setNonChartAnswers({});
    fetchPivotDrillDownSuggestions(sessionId, pivot.id)
      .then((res) => setDrillDowns(res.suggestions))
      .catch((err) => setDrillDownsError(err instanceof AuditApiError ? err.message : "Could not reach the drill-down suggestion agent."))
      .finally(() => setDrillDownsLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pivot.id, sessionId]);

  const handleInterpret = () => {
    setInterpretLoading(true);
    setInterpretError(null);
    fetchChartInterpretation(sessionId, pivot.id, interpretation !== null)
      .then((res) => setInterpretation(res.interpretation))
      .catch((err) => setInterpretError(err instanceof AuditApiError ? err.message : "Could not reach the chart interpretation agent."))
      .finally(() => setInterpretLoading(false));
  };

  const handleAddDrillDown = (suggestion: string) => {
    setAddingSuggestion(suggestion);
    setAddError(null);
    applyPivotDrillDown(sessionId, pivot.id, suggestion)
      .then((answer) => {
        setAddedSuggestions((prev) => new Set(prev).add(suggestion));
        if (answer.pivot) onDrillDownAdded(answer.pivot);
        else setNonChartAnswers((prev) => ({ ...prev, [suggestion]: answer }));
      })
      .catch((err) => setAddError(err instanceof AuditApiError ? err.message : "Could not add that drill-down."))
      .finally(() => setAddingSuggestion(null));
  };

  return (
    <Modal title={pivot.name} onClose={onClose}>
      <div className="pivot-modal__filters">
        <PivotFilterBar
          filterableColumns={pivot.filterable_columns}
          filterOptions={pivot.filter_options}
          combinations={pivot.filter_combinations ?? []}
          selected={filterSelections}
          onSave={onSaveFilters}
          saving={savingFilters}
        />
      </div>

      <div className="pivot-modal__tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "table"}
          className={`pivot-modal__tab ${tab === "table" ? "pivot-modal__tab--active" : ""}`}
          onClick={() => setTab("table")}
        >
          Table
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "chart"}
          className={`pivot-modal__tab ${tab === "chart" ? "pivot-modal__tab--active" : ""}`}
          onClick={() => setTab("chart")}
        >
          Chart
        </button>
      </div>

      <div className="pivot-modal__tab-content">
        {tab === "table" ? <PivotTableCard pivot={pivot} hideHeader /> : <PivotChart pivot={pivot} />}
      </div>

      <div className="pivot-modal__interpretation">
        <div className="pivot-modal__interpretation-head">
          <h4 className="pivot-modal__section-title">What this chart says</h4>
          <button type="button" className="pivot-modal__interpret-btn" disabled={interpretLoading} onClick={handleInterpret}>
            {interpretLoading ? "Interpreting…" : interpretation ? "Re-interpret" : "Interpret this chart (AI)"}
          </button>
        </div>
        {interpretError && <p className="pivot-modal__interpret-error">{interpretError}</p>}
        {interpretation && <p className="pivot-modal__interpret-text">{interpretation}</p>}
      </div>

      <div className="pivot-modal__drilldowns">
        <h4 className="pivot-modal__section-title">Possible drill-downs from this chart</h4>
        {drillDownsLoading && <p className="pivot-modal__drilldowns-hint">Thinking…</p>}
        {drillDownsError && <p className="pivot-modal__interpret-error">{drillDownsError}</p>}
        {addError && <p className="pivot-modal__interpret-error">{addError}</p>}
        {drillDowns && drillDowns.length === 0 && !drillDownsLoading && (
          <p className="pivot-modal__drilldowns-hint">Nothing stands out enough to suggest a drill-down yet.</p>
        )}
        {drillDowns && drillDowns.length > 0 && (
          <ul className="pivot-modal__drilldowns-list">
            {drillDowns.map((s) => {
              const added = addedSuggestions.has(s);
              const busy = addingSuggestion === s;
              const answer = nonChartAnswers[s];
              return (
                <li key={s} className="pivot-modal__drilldown-item">
                  <div className="pivot-modal__drilldown-row">
                    <span>{s}</span>
                    <button
                      type="button"
                      className="pivot-modal__drilldown-add-btn"
                      disabled={busy || added}
                      onClick={() => handleAddDrillDown(s)}
                    >
                      {added ? "Added ✓" : busy ? "Adding…" : "Add"}
                    </button>
                  </div>
                  {answer && (
                    <div className="pivot-modal__drilldown-answer">
                      <p className="pivot-modal__drilldown-answer-explanation">{answer.explanation}</p>
                      {answer.value != null && <p className="pivot-modal__drilldown-answer-value">{answer.value}</p>}
                      {answer.table && answer.table.length > 0 && (
                        <div className="pivot-modal__drilldown-answer-table-wrap">
                          <table className="pivot-modal__drilldown-answer-table">
                            <thead>
                              <tr>
                                {Object.keys(answer.table[0]).map((k) => (
                                  <th key={k}>{k}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {answer.table.map((row, i) => (
                                <tr key={i}>
                                  {Object.values(row).map((v, j) => (
                                    <td key={j}>{String(v)}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Modal>
  );
}
