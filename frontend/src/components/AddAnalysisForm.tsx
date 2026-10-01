import { Spinner } from "./ThinkingLoader";
import { useRef, useState } from "react";
import type { AddCustomAnalysisBody, AnalysisChartType, AnalysisDraft } from "../api/audit";
import { AuditApiError } from "../api/audit";
import AnalysisChart from "./AnalysisChart";
import { CHART_LABELS, FILTER_KIND_LABELS } from "../utils/analysisLabels";
import "./AddAnalysisForm.css";

interface AddAnalysisFormProps {
  columns: string[];
  busy: boolean;
  /** Asks the Analysis Designer for computation logic, a template match,
   * a chart recommendation and filters. `formula` set = re-check the PM's
   * edited logic instead of generating new logic. */
  onDraft: (request: { name: string; description: string; formula?: string }) => Promise<AnalysisDraft>;
  /** Saves the analysis; rejects with the reason if it couldn't be saved. */
  onAdd: (analysis: AddCustomAnalysisBody) => Promise<void>;
  onCancel: () => void;
}

/** Two steps in one form: the PM describes the analysis, the designer
 * drafts how it will be computed and drawn, the PM reviews/edits that
 * draft, then saves. Saving is only possible from an up-to-date draft. */
export default function AddAnalysisForm({ columns, busy, onDraft, onAdd, onCancel }: AddAnalysisFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [usedColumns, setUsedColumns] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const [draft, setDraft] = useState<AnalysisDraft | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftedDescription, setDraftedDescription] = useState("");
  const [formula, setFormula] = useState("");
  const [chartType, setChartType] = useState<AnalysisChartType>("bar");
  const [selectedFilters, setSelectedFilters] = useState<Set<string>>(new Set());

  const insertColumn = (col: string) => {
    const el = textRef.current;
    setUsedColumns((prev) => new Set(prev).add(col));
    if (!el) {
      setDescription((prev) => `${prev}${col}`);
      return;
    }
    const start = el.selectionStart ?? description.length;
    const end = el.selectionEnd ?? description.length;
    setDescription(`${description.slice(0, start)}${col}${description.slice(end)}`);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + col.length, start + col.length);
    });
  };

  const requestDraft = (editedFormula?: string) => {
    if (!name.trim()) return setError("Give the analysis a name.");
    if (!description.trim()) return setError("Describe what this analysis should show.");
    setError(null);
    setDrafting(true);
    onDraft({ name: name.trim(), description: description.trim(), formula: editedFormula })
      .then((result) => {
        setDraft(result);
        setDraftedDescription(description.trim());
        setFormula(result.formula);
        setChartType(result.chart.chart_type);
        setSelectedFilters(new Set(result.filters.map((f) => f.column)));
      })
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Couldn't draft the computation logic."))
      .finally(() => setDrafting(false));
  };

  const descriptionStale = !!draft && description.trim() !== draftedDescription;
  const formulaEdited = !!draft && formula.trim() !== draft.formula.trim();
  const canSave = !!draft && !descriptionStale && !formulaEdited && !drafting && !busy;

  const handleSubmit = () => {
    if (!draft || !canSave) return;
    const chartOptions = [draft.chart, ...draft.chart.alternatives];
    const chosen = chartOptions.find((c) => c.chart_type === chartType) ?? draft.chart;
    setError(null);
    onAdd({
      name: name.trim(),
      description: description.trim(),
      calculation_intent: description.trim(),
      input_columns: columns.filter((c) => usedColumns.has(c)),
      formula: draft.formula,
      template: draft.template,
      chart_type: chosen.chart_type,
      chart_reason: chosen.reason,
      chart_alternatives: chartOptions.filter((c) => c.chart_type !== chosen.chart_type),
      filters: draft.filters.filter((f) => selectedFilters.has(f.column)).map((f) => ({ column: f.column, reason: f.reason })),
    }).catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not add that analysis."));
  };

  const toggleFilter = (column: string) =>
    setSelectedFilters((prev) => {
      const next = new Set(prev);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });

  const chartOptions = draft ? [draft.chart, ...draft.chart.alternatives] : [];
  const selectedChart = chartOptions.find((c) => c.chart_type === chartType);
  const previewIsCurrent = !!draft?.preview_chart_spec && chartType === draft.chart.chart_type;

  return (
    <div className="add-analysis-form">
      <label className="add-analysis-form__field">
        <span>Analysis name</span>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Excursion rate by carrier" />
      </label>

      <label className="add-analysis-form__field">
        <span>What should this analysis show?</span>
        <textarea
          ref={textRef}
          className="add-analysis-form__intent-input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="e.g. Percentage of shipments per carrier whose max temperature went above 8°C"
        />
      </label>

      <div className="add-analysis-form__field">
        <span>Click a column to insert it</span>
        <div className="add-analysis-form__column-chips">
          {columns.map((c) => (
            <button type="button" key={c} className="add-analysis-form__chip" onClick={() => insertColumn(c)}>
              {c}
            </button>
          ))}
        </div>
      </div>

      <button
        type="button"
        className={`add-analysis-form__btn ${draft ? "add-analysis-form__btn--secondary" : "add-analysis-form__btn--primary"} add-analysis-form__draft-btn`}
        disabled={drafting || busy}
        onClick={() => requestDraft()}
      >
        {drafting ? <><Spinner />Working out the logic…</> : draft ? "Regenerate from description" : "Generate computation logic"}
      </button>

      {descriptionStale && (
        <p className="add-analysis-form__warn">The description changed since this draft -- regenerate before adding.</p>
      )}

      {draft && (
        <div className="add-analysis-form__draft" aria-busy={drafting}>
          <section className="add-analysis-form__section">
            <h4 className="add-analysis-form__section-title">1. Computation logic</h4>
            <textarea
              className="add-analysis-form__formula-input"
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              rows={Math.min(10, Math.max(3, formula.split("\n").length + 1))}
            />
            {formulaEdited ? (
              <div className="add-analysis-form__inline-row">
                <p className="add-analysis-form__warn">You edited the logic -- re-check it so the template, chart and filters match.</p>
                <button
                  type="button"
                  className="add-analysis-form__btn add-analysis-form__btn--secondary"
                  disabled={drafting || !formula.trim()}
                  onClick={() => requestDraft(formula.trim())}
                >
                  {drafting ? "Re-checking…" : "Re-check edited logic"}
                </button>
              </div>
            ) : (
              <p className="add-analysis-form__ai-hint">Edit any step if it isn't what you meant, then re-check it.</p>
            )}
          </section>

          <section className="add-analysis-form__section">
            <h4 className="add-analysis-form__section-title">2. How it will be computed</h4>
            {draft.computation_mode === "template" ? (
              <div className="add-analysis-form__method add-analysis-form__method--template">
                <span className="add-analysis-form__badge add-analysis-form__badge--template">Template</span>
                <div>
                  <strong>{draft.template_name}</strong>
                  <p>{draft.template_summary}</p>
                  <p className="add-analysis-form__ai-hint">
                    Computed by a fixed, tested calculation -- no generated code, same result every run.
                  </p>
                </div>
              </div>
            ) : (
              <div className="add-analysis-form__method add-analysis-form__method--code">
                <span className="add-analysis-form__badge add-analysis-form__badge--code">Code generation</span>
                <div>
                  <p>{draft.template_reason}</p>
                  <p className="add-analysis-form__ai-hint">
                    The Analysis Agent will write pandas code for this logic when you run it, execute it in a
                    sandbox, and build both the table and the chart.
                  </p>
                </div>
              </div>
            )}
          </section>

          <section className="add-analysis-form__section">
            <h4 className="add-analysis-form__section-title">3. Chart</h4>
            <div className="add-analysis-form__chart-options" role="radiogroup" aria-label="Chart type">
              {chartOptions.map((option, i) => (
                <button
                  type="button"
                  role="radio"
                  aria-checked={chartType === option.chart_type}
                  key={option.chart_type}
                  className={`add-analysis-form__chart-option${chartType === option.chart_type ? " add-analysis-form__chart-option--active" : ""}`}
                  onClick={() => setChartType(option.chart_type)}
                >
                  {CHART_LABELS[option.chart_type]}
                  {i === 0 && <span className="add-analysis-form__recommended">Recommended</span>}
                </button>
              ))}
            </div>
            {selectedChart?.reason && <p className="add-analysis-form__ai-hint">{selectedChart.reason}</p>}

            {draft.computation_mode === "template" && draft.preview_rows.length > 0 && (
              <div className="add-analysis-form__preview">
                <span className="add-analysis-form__preview-label">Preview on your data</span>
                {previewIsCurrent ? (
                  <AnalysisChart chartSpec={draft.preview_chart_spec} chartType={chartType} resultTable={draft.preview_rows} />
                ) : (
                  <AnalysisChart chartSpec={null} chartType="table" resultTable={draft.preview_rows} />
                )}
              </div>
            )}
          </section>

          <section className="add-analysis-form__section">
            <h4 className="add-analysis-form__section-title">4. Filters on the chart</h4>
            {draft.filters.length === 0 ? (
              <p className="add-analysis-form__ai-hint">No useful filter columns were found for this analysis.</p>
            ) : (
              <ul className="add-analysis-form__filters">
                {draft.filters.map((f) => (
                  <li key={f.column}>
                    <label className="add-analysis-form__filter">
                      <input type="checkbox" checked={selectedFilters.has(f.column)} onChange={() => toggleFilter(f.column)} />
                      <span className="add-analysis-form__filter-name">{f.column}</span>
                      <span className="add-analysis-form__filter-kind">{FILTER_KIND_LABELS[f.kind]}</span>
                      {f.reason && <span className="add-analysis-form__filter-reason">{f.reason}</span>}
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {draft.notes.length > 0 && (
            <ul className="add-analysis-form__notes">
              {draft.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && <p className="add-analysis-form__error">{error}</p>}

      <div className="add-analysis-form__actions">
        <button type="button" className="add-analysis-form__btn add-analysis-form__btn--primary" disabled={!canSave} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add Analysis"}
        </button>
        <button type="button" className="add-analysis-form__btn add-analysis-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
