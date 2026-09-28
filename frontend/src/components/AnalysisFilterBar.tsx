import { useEffect, useRef, useState } from "react";
import type { AnalysisFilter, AnalysisFilterSelection, AnalysisFilterSelections } from "../api/audit";
import { IconChevronDown } from "./icons";
import "./AnalysisFilterBar.css";

interface AnalysisFilterBarProps {
  filters: AnalysisFilter[];
  busy: boolean;
  /** Called (debounced) whenever the selections change; an empty object
   * means every filter is back to "All". */
  onChange: (selections: AnalysisFilterSelections) => void;
}

const SEARCH_THRESHOLD = 8;
const APPLY_DELAY_MS = 350;

function isEmpty(sel: AnalysisFilterSelection | undefined): boolean {
  if (!sel) return true;
  return !sel.values?.length && sel.min === undefined && sel.max === undefined && !sel.start && !sel.end;
}

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function rangeSummary(low: string | undefined, high: string | undefined): string {
  if (low && high) return `${low} – ${high}`;
  if (low) return `from ${low}`;
  if (high) return `to ${high}`;
  return "All";
}

function summaryOf(filter: AnalysisFilter, sel: AnalysisFilterSelection | undefined): string {
  if (isEmpty(sel)) return "All";
  if (filter.kind === "categorical") {
    const values = sel!.values ?? [];
    return values.length === 1 ? values[0] : `${values.length} selected`;
  }
  if (filter.kind === "numeric_range") {
    return rangeSummary(sel!.min?.toLocaleString(), sel!.max?.toLocaleString());
  }
  return rangeSummary(sel!.start && formatDay(sel!.start), sel!.end && formatDay(sel!.end));
}

function toNumber(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

function CategoricalOptions({
  filter,
  selection,
  onChange,
}: {
  filter: AnalysisFilter;
  selection: AnalysisFilterSelection | undefined;
  onChange: (sel: AnalysisFilterSelection) => void;
}) {
  const [query, setQuery] = useState("");
  const chosen = new Set(selection?.values ?? []);
  const all = filter.values ?? [];
  const visible = all.filter((v) => v.toLowerCase().includes(query.toLowerCase()));
  const toggle = (value: string) => {
    const next = new Set(chosen);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onChange({ values: [...next] });
  };

  return (
    <>
      {all.length > SEARCH_THRESHOLD && (
        <input
          type="search"
          className="analysis-filter__search"
          placeholder="Search…"
          value={query}
          autoFocus
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      <ul className="analysis-filter__options">
        {!query && (
          <li>
            <label>
              <input type="checkbox" checked={chosen.size === 0} onChange={() => onChange({})} />
              All
            </label>
          </li>
        )}
        {visible.map((value) => (
          <li key={value}>
            <label>
              <input type="checkbox" checked={chosen.has(value)} onChange={() => toggle(value)} />
              {value}
            </label>
          </li>
        ))}
        {visible.length === 0 && <li className="analysis-filter__no-match">No matches</li>}
      </ul>
    </>
  );
}

function RangeOptions({
  filter,
  selection,
  onChange,
}: {
  filter: AnalysisFilter;
  selection: AnalysisFilterSelection | undefined;
  onChange: (sel: AnalysisFilterSelection) => void;
}) {
  const sel = selection ?? {};
  if (filter.kind === "numeric_range") {
    return (
      <div className="analysis-filter__range">
        <label>
          Min
          <input
            type="number"
            placeholder={filter.min !== null ? String(filter.min) : ""}
            value={sel.min ?? ""}
            onChange={(e) => onChange({ ...sel, min: toNumber(e.target.value) })}
          />
        </label>
        <label>
          Max
          <input
            type="number"
            placeholder={filter.max !== null ? String(filter.max) : ""}
            value={sel.max ?? ""}
            onChange={(e) => onChange({ ...sel, max: toNumber(e.target.value) })}
          />
        </label>
      </div>
    );
  }
  return (
    <div className="analysis-filter__range">
      <label>
        From
        <input
          type="date"
          min={filter.start ?? undefined}
          max={filter.end ?? undefined}
          value={sel.start ?? ""}
          onChange={(e) => onChange({ ...sel, start: e.target.value || undefined })}
        />
      </label>
      <label>
        To
        <input
          type="date"
          min={filter.start ?? undefined}
          max={filter.end ?? undefined}
          value={sel.end ?? ""}
          onChange={(e) => onChange({ ...sel, end: e.target.value || undefined })}
        />
      </label>
    </div>
  );
}

/** One pill per filter ("Carrier  All ⌄"); clicking a pill opens its
 * options in a popover. Selections apply on their own shortly after the
 * last change, and are applied on the backend to the source rows (the
 * analysis re-aggregates), so every chart type filters the same way. */
export default function AnalysisFilterBar({ filters, busy, onChange }: AnalysisFilterBarProps) {
  const [selections, setSelections] = useState<AnalysisFilterSelections>({});
  const [openColumn, setOpenColumn] = useState<string | null>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  // Close the open popover on a click outside the bar or on Escape. Escape
  // is caught in the capture phase and stopped, so it closes only the
  // popover and not the modal around it (the modal also listens for Escape).
  useEffect(() => {
    if (!openColumn) return;
    const onMouseDown = (e: MouseEvent) => {
      if (!barRef.current?.contains(e.target as Node)) setOpenColumn(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      setOpenColumn(null);
    };
    document.addEventListener("mousedown", onMouseDown);
    window.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("keydown", onKeyDown, true);
    };
  }, [openColumn]);

  // Debounced apply, so ticking several values sends one request.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    const active = Object.fromEntries(Object.entries(selections).filter(([, s]) => !isEmpty(s)));
    const timer = window.setTimeout(() => onChange(active), APPLY_DELAY_MS);
    return () => window.clearTimeout(timer);
    // onChange is intentionally not a dependency: a new callback identity
    // from the parent must not re-send the same selections.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selections]);

  const setOne = (column: string, sel: AnalysisFilterSelection) => setSelections((prev) => ({ ...prev, [column]: sel }));
  const anyActive = Object.values(selections).some((s) => !isEmpty(s));

  return (
    <div className="analysis-filter" ref={barRef} aria-busy={busy}>
      {filters.map((f) => {
        const sel = selections[f.column];
        const active = !isEmpty(sel);
        const open = openColumn === f.column;
        return (
          <div className="analysis-filter__item" key={f.column}>
            <button
              type="button"
              className={`analysis-filter__pill${active ? " analysis-filter__pill--active" : ""}`}
              aria-expanded={open}
              title={f.reason || undefined}
              onClick={() => setOpenColumn(open ? null : f.column)}
            >
              <span className="analysis-filter__pill-label">{f.column}</span>
              <span className="analysis-filter__pill-value">{summaryOf(f, sel)}</span>
              <IconChevronDown />
            </button>
            {open && (
              <div className="analysis-filter__popover" role="dialog" aria-label={`Filter by ${f.column}`}>
                {f.kind === "categorical" ? (
                  <CategoricalOptions filter={f} selection={sel} onChange={(next) => setOne(f.column, next)} />
                ) : (
                  <RangeOptions filter={f} selection={sel} onChange={(next) => setOne(f.column, next)} />
                )}
                {active && (
                  <button type="button" className="analysis-filter__reset-one" onClick={() => setOne(f.column, {})}>
                    Reset {f.column}
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
      {anyActive && (
        <button
          type="button"
          className="analysis-filter__reset-all"
          onClick={() => {
            setSelections({});
            setOpenColumn(null);
          }}
        >
          Reset all
        </button>
      )}
      {busy && <span className="analysis-filter__busy">Updating…</span>}
    </div>
  );
}
