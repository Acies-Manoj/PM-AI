import { useRef, useState } from "react";
import type { AddCustomFeatureBody, FeatureDraft } from "../api/audit";
import { AuditApiError } from "../api/audit";
import "./AddKpiForm.css";

interface AddKpiFormProps {
  columns: string[];
  busy: boolean;
  /** Asks the Feature Agent for the formula and dry-runs it on the real
   * data. `formula` set = re-check the PM's edited formula instead of
   * writing a new one. */
  onDraft: (request: { name: string; description: string; input_columns: string[]; formula?: string }) => Promise<FeatureDraft>;
  /** Saves the reviewed feature; rejects with the reason if it couldn't. */
  onAdd: (kpi: AddCustomFeatureBody) => Promise<void>;
  onCancel: () => void;
}

function formatNumber(v: number): string {
  return Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return formatNumber(v);
  return String(v);
}

/** Human in the loop for a user-requested feature: the PM describes it, the
 * Feature Agent writes the formula and dry-runs it on the real data, and the
 * PM reviews (or edits and re-checks) the formula and a preview of the new
 * column before adding it. Adding is only possible from an up-to-date,
 * successful dry run. */
export default function AddKpiForm({ columns, busy, onDraft, onAdd, onCancel }: AddKpiFormProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [usedColumns, setUsedColumns] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const [draft, setDraft] = useState<FeatureDraft | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [draftedFor, setDraftedFor] = useState({ name: "", description: "" });
  const [formula, setFormula] = useState("");

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

  const inputColumns = () => columns.filter((c) => usedColumns.has(c));

  const requestDraft = (editedFormula?: string) => {
    if (!name.trim()) return setError("Give the KPI a name.");
    if (!description.trim()) return setError("Describe what this feature should calculate.");
    setError(null);
    setDrafting(true);
    onDraft({ name: name.trim(), description: description.trim(), input_columns: inputColumns(), formula: editedFormula })
      .then((result) => {
        setDraft(result);
        setDraftedFor({ name: name.trim(), description: description.trim() });
        setFormula(result.formula);
      })
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Couldn't draft the formula."))
      .finally(() => setDrafting(false));
  };

  // The name decides the output column, so a renamed KPI needs a fresh draft too.
  const requestStale = !!draft && (name.trim() !== draftedFor.name || description.trim() !== draftedFor.description);
  const formulaEdited = !!draft && formula.trim() !== draft.formula.trim();
  const canSave = !!draft && draft.status === "ok" && !requestStale && !formulaEdited && !drafting && !busy;

  const handleSubmit = () => {
    if (!draft || !canSave) return;
    setError(null);
    onAdd({
      name: name.trim(),
      description: description.trim(),
      calculation_intent: description.trim(),
      input_columns: inputColumns(),
      formula: draft.formula,
      draft_token: draft.draft_token,
    }).catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not add that feature."));
  };

  const summary = draft?.summary;
  const topValues = summary ? Object.entries(summary.distribution).slice(0, 5) : [];

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
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          placeholder="e.g. Number of hours between Hub Arrival Time and Hub Departure Time"
        />
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

      <button
        type="button"
        className={`add-kpi-form__btn ${draft ? "add-kpi-form__btn--secondary" : "add-kpi-form__btn--primary"} add-kpi-form__draft-btn`}
        disabled={drafting || busy}
        onClick={() => requestDraft()}
      >
        {drafting ? "Writing and testing the formula…" : draft ? "Regenerate from description" : "Generate formula"}
      </button>

      {requestStale && (
        <p className="add-kpi-form__warn">The name or description changed since this draft -- regenerate before adding.</p>
      )}

      {draft && (
        <div className="add-kpi-form__draft" aria-busy={drafting}>
          <section className="add-kpi-form__section">
            <h4 className="add-kpi-form__section-title">1. Formula</h4>
            <p className="add-kpi-form__ai-hint">
              New column: <code>{draft.output_column}</code>
              {draft.output_dtype ? ` · ${draft.output_dtype}` : ""}
            </p>
            <textarea
              className="add-kpi-form__steps-input"
              value={formula}
              onChange={(e) => setFormula(e.target.value)}
              rows={Math.min(10, Math.max(3, formula.split("\n").length + 1))}
            />
            {formulaEdited ? (
              <div className="add-kpi-form__inline-row">
                <p className="add-kpi-form__warn">You edited the formula -- re-check it to see the new result before adding.</p>
                <button
                  type="button"
                  className="add-kpi-form__btn add-kpi-form__btn--secondary"
                  disabled={drafting || !formula.trim()}
                  onClick={() => requestDraft(formula.trim())}
                >
                  {drafting ? "Re-checking…" : "Re-check formula"}
                </button>
              </div>
            ) : (
              <p className="add-kpi-form__ai-hint">Edit any step if it isn't what you meant, then re-check it.</p>
            )}
          </section>

          <section className="add-kpi-form__section">
            <h4 className="add-kpi-form__section-title">2. Result on your data</h4>
            {draft.status === "failed" ? (
              <p className="add-kpi-form__error">
                The Feature Agent couldn't compute this formula correctly: {draft.error} Edit the formula or the
                description and try again.
              </p>
            ) : (
              <>
                {draft.validation_note && (
                  <p className="add-kpi-form__verdict">
                    <span className="add-kpi-form__badge">Validated</span> {draft.validation_note}
                  </p>
                )}
                {summary && (
                  <p className="add-kpi-form__ai-hint">
                    {summary.non_null_count.toLocaleString()} rows filled, {summary.null_count.toLocaleString()} blank
                    {Object.keys(summary.stats).length > 0 &&
                      ` · ${Object.entries(summary.stats).map(([k, v]) => `${k} ${formatNumber(v)}`).join(" · ")}`}
                    {topValues.length > 0 && ` · most common: ${topValues.map(([k, v]) => `${k} (${v})`).join(", ")}`}
                  </p>
                )}
                <div className="add-kpi-form__preview">
                  <table>
                    <thead>
                      <tr>
                        {draft.preview_columns.map((c) => (
                          <th key={c} className={c === draft.output_column ? "add-kpi-form__preview-new" : undefined}>
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {draft.preview_rows.map((row, i) => (
                        <tr key={i}>
                          {draft.preview_columns.map((c) => (
                            <td key={c} className={c === draft.output_column ? "add-kpi-form__preview-new" : undefined}>
                              {formatCell(row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>

          {draft.notes.length > 0 && (
            <ul className="add-kpi-form__notes">
              {draft.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {error && <p className="add-kpi-form__error">{error}</p>}

      <div className="add-kpi-form__actions">
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--primary" disabled={!canSave} onClick={handleSubmit}>
          {busy ? "Adding…" : "Add KPI"}
        </button>
        <button type="button" className="add-kpi-form__btn add-kpi-form__btn--secondary" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
