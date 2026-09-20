import { useRef, useState } from "react";
import "./AddAnalysisForm.css";

export interface NewCustomAnalysis {
  name: string;
  calculation_intent: string;
  input_columns: string[];
}

interface AddAnalysisFormProps {
  columns: string[];
  busy: boolean;
  onAdd: (analysis: NewCustomAnalysis) => void;
  onCancel: () => void;
}

export default function AddAnalysisForm({ columns, busy, onAdd, onCancel }: AddAnalysisFormProps) {
  const [name, setName] = useState("");
  const [calculationIntent, setCalculationIntent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [usedColumns, setUsedColumns] = useState<Set<string>>(new Set());
  const textRef = useRef<HTMLTextAreaElement>(null);

  const insertColumn = (col: string) => {
    const el = textRef.current;
    if (!el) {
      setCalculationIntent((prev) => `${prev}${col}`);
      setUsedColumns((prev) => new Set(prev).add(col));
      return;
    }
    const start = el.selectionStart ?? calculationIntent.length;
    const end = el.selectionEnd ?? calculationIntent.length;
    const next = `${calculationIntent.slice(0, start)}${col}${calculationIntent.slice(end)}`;
    setCalculationIntent(next);
    setUsedColumns((prev) => new Set(prev).add(col));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + col.length, start + col.length);
    });
  };

  const handleSubmit = () => {
    if (!name.trim()) return setError("Give the analysis a name.");
    if (!calculationIntent.trim()) return setError("Describe what this analysis should show.");
    setError(null);
    onAdd({
      name: name.trim(),
      calculation_intent: calculationIntent.trim(),
      input_columns: columns.filter((c) => usedColumns.has(c)),
    });
  };

  return (
    <div className="add-analysis-form">
      <label className="add-analysis-form__field">
        <span>Analysis name</span>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Shipments by Carrier" />
      </label>

      <label className="add-analysis-form__field">
        <span>What should this analysis show?</span>
        <textarea
          ref={textRef}
          className="add-analysis-form__intent-input"
          value={calculationIntent}
          onChange={(e) => setCalculationIntent(e.target.value)}
          rows={4}
          placeholder="e.g. Total shipment count grouped by Carrier, sorted highest to lowest"
        />
        <p className="add-analysis-form__ai-hint">
          The Analysis Agent plans the aggregation, writes pandas code for it, runs it in a restricted
          sandbox, then picks a chart type and interprets the result -- describe what you want to see in
          plain English.
        </p>
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

      {error && <p className="add-analysis-form__error">{error}</p>}

      <div className="add-analysis-form__actions">
        <button type="button" className="add-analysis-form__btn add-analysis-form__btn--primary" disabled={busy} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add Analysis"}
        </button>
        <button type="button" className="add-analysis-form__btn add-analysis-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
