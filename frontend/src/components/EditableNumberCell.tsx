import { useRef, useState } from "react";
import "./OutlierTabs.css";

interface Props {
  value: number | null;
  suffix?: string;
  onSave: (next: number) => Promise<void>;
}

// A table cell that reads as plain text until clicked, then becomes a
// number input -- Enter/blur commits (calling `onSave`, which round-trips
// to the backend and recomputes outliers), Escape discards the edit.
export default function EditableNumberCell({ value, suffix = "", onSave }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);

  const startEdit = () => {
    cancelledRef.current = false;
    setDraft(value != null ? String(value) : "");
    setError(null);
    setEditing(true);
  };

  const cancel = () => {
    cancelledRef.current = true;
    setEditing(false);
  };

  const commit = async () => {
    if (cancelledRef.current) {
      setEditing(false);
      return;
    }
    const parsed = Number(draft);
    if (draft.trim() === "" || Number.isNaN(parsed)) {
      setError("Enter a number");
      return;
    }
    if (parsed === value) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(parsed);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
    } finally {
      setSaving(false);
    }
  };

  if (!editing) {
    return (
      <button type="button" className="outlier-tab__editable-cell" onClick={startEdit} title="Click to edit">
        {value != null ? `${value}${suffix}` : "—"}
      </button>
    );
  }

  return (
    <span className="outlier-tab__edit-wrap">
      <input
        type="number"
        step="any"
        autoFocus
        className={`outlier-tab__edit-input ${error ? "outlier-tab__edit-input--error" : ""}`}
        value={draft}
        disabled={saving}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") cancel();
        }}
      />
      {error && <span className="outlier-tab__edit-error">{error}</span>}
    </span>
  );
}
