import { useRef, useState } from "react";
import "./AddKpiForm.css";

export interface NewCustomKpi {
  name: string;
  calculation_intent: string;
  input_columns: string[];
}

interface AddKpiFormProps {
  columns: string[];
  busy: boolean;
  onAdd: (kpi: NewCustomKpi) => void;
  onCancel: () => void;
}

export default function AddKpiForm({ columns, busy, onAdd, onCancel }: AddKpiFormProps) {
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
    if (!name.trim()) return setError("Give the KPI a name.");
    if (!calculationIntent.trim()) return setError("Describe what this feature should calculate.");
    setError(null);
    onAdd({
      name: name.trim(),
      calculation_intent: calculationIntent.trim(),
      input_columns: columns.filter((c) => usedColumns.has(c)),
    });
  };

  return (
    <div className="add-kpi-form">
      <label className="add-kpi-form__field">
        <span>KPI name</span>
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Time in Transit" />
      </label>

      <label className="add-kpi-form__field">
        <span>What should this feature calculate?</span>
        <textarea
          ref={textRef}
          className="add-kpi-form__formula-input"
          value={calculationIntent}
          onChange={(e) => setCalculationIntent(e.target.value)}
          rows={4}
          placeholder="e.g. Average number of hours between Hub Arrival Time and Hub Departure Time, per Origin-Destination lane"
        />
        <p className="add-kpi-form__ai-hint">
          The Feature Agent plans the calculation, writes pandas code for it, runs it in a restricted
          sandbox, and validates the result before it's added -- describe the calculation in plain
          English or as a formula, either works.
        </p>
      </label>

      <div className="add-kpi-form__field">
        <span>Click a column to insert it</span>
        <div className="add-kpi-form__column-chips">
          {columns.map((c) => (
            <button type="button" key={c} className="add-kpi-form__chip" onClick={() => insertColumn(c)}>
              {c}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="add-kpi-form__error">{error}</p>}

      <div className="add-kpi-form__actions">
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--primary" disabled={busy} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add KPI"}
        </button>
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
