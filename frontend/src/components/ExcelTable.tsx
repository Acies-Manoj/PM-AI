import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { IconFilter } from "./icons";
import "./ExcelTable.css";

type Row = Record<string, unknown>;

interface ExcelTableProps {
  columns: string[];
  rows: Row[];
  /** Columns pinned to the left, in this order -- they stay put while the rest scrolls sideways. */
  frozen?: string[];
  /** One column drawn in a tinted, bolder style (the value the PM is here to correct). */
  highlight?: string;
  /** Custom cell content for a column (e.g. an editable value). Return undefined to use the plain text. */
  renderCell?: (column: string, row: Row) => ReactNode | undefined;
  /** Shown when filters leave no rows. */
  emptyText?: string;
  /** Makes rows clickable (e.g. to select a trip and light up its bar in a chart). */
  onRowClick?: (row: Row) => void;
  /** Marks a row as the selected one. */
  isRowSelected?: (row: Row) => boolean;
  /** Gives the caller each row's element, to scroll a row into view. */
  rowRef?: (row: Row, el: HTMLTableRowElement | null) => void;
}

// Widths of the pinned columns, so each one's `left` offset is known without measuring the DOM.
const FROZEN_WIDTHS = [150, 110, 130];
const MAX_LIST = 300;

function text(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function asNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/** Numbers sort as numbers, everything else as text (ISO dates sort correctly that way); blanks go last. */
function compare(a: unknown, b: unknown): number {
  const blankA = a === null || a === undefined || a === "";
  const blankB = b === null || b === undefined || b === "";
  if (blankA || blankB) return blankA === blankB ? 0 : blankA ? 1 : -1;
  const na = asNumber(a);
  const nb = asNumber(b);
  if (na !== null && nb !== null) return na - nb;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

interface MenuState {
  column: string;
  left: number;
  top: number;
}

/** A data table that behaves like an Excel sheet: pinned first columns, and a menu on every header to sort
 * (A→Z / Z→A) and filter by ticking values. */
export default function ExcelTable({
  columns,
  rows,
  frozen = [],
  highlight,
  renderCell,
  emptyText = "No rows match the filters.",
  onRowClick,
  isRowSelected,
  rowRef,
}: ExcelTableProps) {
  const pinned = frozen.filter((c) => columns.includes(c));
  const ordered = [...pinned, ...columns.filter((c) => !pinned.includes(c))];

  const [sort, setSort] = useState<{ column: string; dir: "asc" | "desc" } | null>(null);
  // column -> the display values still allowed through (a missing column = no filter on it).
  const [filters, setFilters] = useState<Record<string, Set<string>>>({});
  const [menu, setMenu] = useState<MenuState | null>(null);

  const numericColumn = useMemo(() => {
    const out = new Set<string>();
    for (const c of columns) {
      const values = rows.map((r) => r[c]).filter((v) => v !== null && v !== undefined && v !== "");
      if (values.length > 0 && values.every((v) => asNumber(v) !== null)) out.add(c);
    }
    return out;
  }, [columns, rows]);

  const visibleRows = useMemo(() => {
    let out = rows.filter((row) => Object.entries(filters).every(([col, allowed]) => allowed.has(text(row[col]))));
    if (sort) {
      const sign = sort.dir === "asc" ? 1 : -1;
      out = [...out].sort((a, b) => sign * compare(a[sort.column], b[sort.column]));
    }
    return out;
  }, [rows, filters, sort]);

  const filterCount = Object.keys(filters).length;
  const leftOf = (index: number) => FROZEN_WIDTHS.slice(0, index).reduce((n, w) => n + w, 0);

  const setColumnFilter = (column: string, allowed: Set<string> | null) =>
    setFilters((prev) => {
      const next = { ...prev };
      if (allowed === null) delete next[column];
      else next[column] = allowed;
      return next;
    });

  return (
    <div className="excel-table">
      <div className="excel-table__bar">
        <span className="excel-table__count">
          {visibleRows.length === rows.length ? `${rows.length} rows` : `${visibleRows.length} of ${rows.length} rows`}
        </span>
        {(filterCount > 0 || sort) && (
          <button
            type="button"
            className="excel-table__clear"
            onClick={() => {
              setFilters({});
              setSort(null);
            }}
          >
            Clear filters and sorting
          </button>
        )}
      </div>

      <div className="excel-table__wrap">
        <table className="excel-table__table">
          <thead>
            <tr>
              {ordered.map((col, i) => {
                const isPinned = i < pinned.length;
                const active = !!filters[col];
                const sorted = sort?.column === col ? sort.dir : null;
                return (
                  <th
                    key={col}
                    className={[
                      isPinned ? "is-pinned" : "",
                      i === pinned.length - 1 ? "is-pinned-last" : "",
                      col === highlight ? "is-highlight" : "",
                    ].join(" ")}
                    style={isPinned ? { left: leftOf(i), minWidth: FROZEN_WIDTHS[i], maxWidth: FROZEN_WIDTHS[i] } : undefined}
                    aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"}
                  >
                    <span className="excel-table__head">
                      <span className="excel-table__label">{col}</span>
                      {sorted && <span className="excel-table__sort-mark">{sorted === "asc" ? "↑" : "↓"}</span>}
                      <button
                        type="button"
                        className={`excel-table__menu-btn${active ? " is-active" : ""}`}
                        aria-label={`Sort and filter ${col}`}
                        aria-haspopup="dialog"
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          setMenu((cur) => (cur?.column === col ? null : { column: col, left: Math.max(8, Math.min(rect.left, window.innerWidth - 260)), top: Math.max(8, Math.min(rect.bottom + 4, window.innerHeight - 380)) }));
                        }}
                      >
                        <IconFilter />
                      </button>
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, r) => (
              <tr
                key={r}
                ref={rowRef ? (el) => rowRef(row, el) : undefined}
                className={[onRowClick ? "is-clickable" : "", isRowSelected?.(row) ? "is-selected" : ""].join(" ")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {ordered.map((col, i) => {
                  const isPinned = i < pinned.length;
                  return (
                    <td
                      key={col}
                      className={[
                        isPinned ? "is-pinned" : "",
                        i === pinned.length - 1 ? "is-pinned-last" : "",
                        col === highlight ? "is-highlight" : "",
                      ].join(" ")}
                      style={isPinned ? { left: leftOf(i), minWidth: FROZEN_WIDTHS[i], maxWidth: FROZEN_WIDTHS[i] } : undefined}
                    >
                      {renderCell?.(col, row) ?? text(row[col])}
                    </td>
                  );
                })}
              </tr>
            ))}
            {visibleRows.length === 0 && (
              <tr>
                <td colSpan={ordered.length} className="excel-table__empty">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {menu && (
        <ColumnMenu
          column={menu.column}
          left={menu.left}
          top={menu.top}
          numeric={numericColumn.has(menu.column)}
          values={rows.map((r) => text(r[menu.column]))}
          allowed={filters[menu.column] ?? null}
          sortDir={sort?.column === menu.column ? sort.dir : null}
          onSort={(dir) => setSort(dir ? { column: menu.column, dir } : null)}
          onFilter={(allowed) => setColumnFilter(menu.column, allowed)}
          onClose={() => setMenu(null)}
        />
      )}
    </div>
  );
}

interface ColumnMenuProps {
  column: string;
  left: number;
  top: number;
  numeric: boolean;
  values: string[];
  allowed: Set<string> | null;
  sortDir: "asc" | "desc" | null;
  onSort: (dir: "asc" | "desc" | null) => void;
  onFilter: (allowed: Set<string> | null) => void;
  onClose: () => void;
}

/** The popup under a header: sort, then a searchable tick-list of the column's values. */
function ColumnMenu({ column, left, top, numeric, values, allowed, sortDir, onSort, onFilter, onClose }: ColumnMenuProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");

  // Distinct values with how often each appears, in a natural order.
  const distinct = useMemo(() => {
    const counts = new Map<string, number>();
    for (const v of values) counts.set(v, (counts.get(v) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => compare(a[0] === "—" ? null : a[0], b[0] === "—" ? null : b[0]));
  }, [values]);

  const shown = distinct.filter(([v]) => v.toLowerCase().includes(search.trim().toLowerCase()));
  const isOn = (v: string) => allowed === null || allowed.has(v);
  const allShownOn = shown.length > 0 && shown.every(([v]) => isOn(v));

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node) && !(e.target as HTMLElement).closest(".excel-table__menu-btn")) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    // The menu is position:fixed at the header's spot when opened, so scrolling the page (or the
    // table) would leave it floating over unrelated content -- close it instead.
    const onScroll = (e: Event) => {
      if (ref.current && e.target instanceof Node && ref.current.contains(e.target)) return;
      onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("resize", onClose);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("resize", onClose);
    };
  }, [onClose]);

  const toggle = (v: string) => {
    const base = new Set(allowed ?? distinct.map(([d]) => d));
    if (base.has(v)) base.delete(v);
    else base.add(v);
    onFilter(base.size === distinct.length ? null : base);
  };

  const toggleShown = () => {
    const base = new Set(allowed ?? distinct.map(([d]) => d));
    for (const [v] of shown) {
      if (allShownOn) base.delete(v);
      else base.add(v);
    }
    onFilter(base.size === distinct.length ? null : base);
  };

  return (
    <div ref={ref} className="excel-menu" role="dialog" aria-label={`Sort and filter ${column}`} style={{ left, top }}>
      <button type="button" className={`excel-menu__item${sortDir === "asc" ? " is-on" : ""}`} onClick={() => onSort(sortDir === "asc" ? null : "asc")}>
        {numeric ? "Sort smallest to largest" : "Sort A to Z"}
      </button>
      <button type="button" className={`excel-menu__item${sortDir === "desc" ? " is-on" : ""}`} onClick={() => onSort(sortDir === "desc" ? null : "desc")}>
        {numeric ? "Sort largest to smallest" : "Sort Z to A"}
      </button>
      <button type="button" className="excel-menu__item" disabled={allowed === null} onClick={() => onFilter(null)}>
        Clear filter from "{column}"
      </button>

      <div className="excel-menu__divider" />
      <input
        className="excel-menu__search"
        type="search"
        placeholder="Search values…"
        value={search}
        autoFocus
        onChange={(e) => setSearch(e.target.value)}
      />
      <ul className="excel-menu__list">
        <li>
          <label className="excel-menu__check">
            <input type="checkbox" checked={allShownOn} onChange={toggleShown} />
            <span>{search ? "(Select all search results)" : "(Select all)"}</span>
          </label>
        </li>
        {shown.slice(0, MAX_LIST).map(([v, n]) => (
          <li key={v}>
            <label className="excel-menu__check">
              <input type="checkbox" checked={isOn(v)} onChange={() => toggle(v)} />
              <span className="excel-menu__value">{v}</span>
              <span className="excel-menu__n">({n})</span>
            </label>
          </li>
        ))}
        {shown.length > MAX_LIST && <li className="excel-menu__more">+{shown.length - MAX_LIST} more -- search to narrow</li>}
        {shown.length === 0 && <li className="excel-menu__more">No values match.</li>}
      </ul>
    </div>
  );
}
