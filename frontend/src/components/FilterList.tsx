import { useState } from "react";
import "./ExcelTable.css";

const MAX_LIST = 300;

interface FilterListProps {
  /** Every value that can be ticked, with how often it appears (null = don't show a count). */
  entries: [string, number | null][];
  /** The values currently allowed; null means every value is ticked (no filter). */
  allowed: Set<string> | null;
  onFilter: (allowed: Set<string> | null) => void;
  /** Never let the last ticked value be unticked (a filter that hides everything is no filter). */
  keepOne?: boolean;
  autoFocus?: boolean;
}

/** The tick-list used by EVERY filter in the app: a search box, "(Select all)", then one tick box per value with
 * its count in brackets. Column filters on tables and the Analysis filter bar share it so they look and behave
 * the same everywhere. */
export default function FilterList({ entries, allowed, onFilter, keepOne = false, autoFocus = false }: FilterListProps) {
  const [search, setSearch] = useState("");
  const shown = entries.filter(([v]) => v.toLowerCase().includes(search.trim().toLowerCase()));
  const isOn = (v: string) => allowed === null || allowed.has(v);
  const allShownOn = shown.length > 0 && shown.every(([v]) => isOn(v));
  const everything = () => new Set(entries.map(([v]) => v));

  const commit = (next: Set<string>) => {
    if (keepOne && next.size === 0) return;
    onFilter(next.size === entries.length ? null : next);
  };

  const toggle = (v: string) => {
    const base = allowed ? new Set(allowed) : everything();
    if (base.has(v)) base.delete(v);
    else base.add(v);
    commit(base);
  };

  const toggleShown = () => {
    const base = allowed ? new Set(allowed) : everything();
    for (const [v] of shown) {
      if (allShownOn) base.delete(v);
      else base.add(v);
    }
    commit(base);
  };

  return (
    <>
      <input
        className="excel-menu__search"
        type="search"
        placeholder="Search values…"
        value={search}
        autoFocus={autoFocus}
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
              {n !== null && <span className="excel-menu__n">({n})</span>}
            </label>
          </li>
        ))}
        {shown.length > MAX_LIST && <li className="excel-menu__more">+{shown.length - MAX_LIST} more. Search to narrow</li>}
        {shown.length === 0 && <li className="excel-menu__more">No values match.</li>}
      </ul>
    </>
  );
}
