import { useEffect, useRef, useState } from "react";
import { IconChevronDown, IconFilter, IconPlus, IconSearch, IconSparkle } from "./icons";
import "./AnalysisToolbar.css";

export type AnalysisSortKey = "name" | "status" | "source";
export type AnalysisStatusFilter = "done" | "not_run" | "error";

const SORT_LABELS: Record<AnalysisSortKey, string> = {
  name: "Name (A-Z)",
  status: "Status",
  source: "Source (Predefined first)",
};

const STATUS_LABELS: Record<AnalysisStatusFilter, string> = {
  done: "Done",
  not_run: "Not run yet",
  error: "Error",
};

interface AnalysisToolbarProps {
  search: string;
  onSearchChange: (value: string) => void;
  sort: AnalysisSortKey;
  onSortChange: (value: AnalysisSortKey) => void;
  categories: string[];
  selectedCategories: string[];
  onToggleCategory: (label: string) => void;
  selectedStatuses: AnalysisStatusFilter[];
  onToggleStatus: (status: AnalysisStatusFilter) => void;
  activeFilterCount: number;
  onClearFilters: () => void;
  onAddCustom: () => void;
  onSuggestAI: () => void;
  suggestBusy: boolean;
  pendingSuggestionCount: number;
}

export default function AnalysisToolbar({
  search,
  onSearchChange,
  sort,
  onSortChange,
  categories,
  selectedCategories,
  onToggleCategory,
  selectedStatuses,
  onToggleStatus,
  activeFilterCount,
  onClearFilters,
  onAddCustom,
  onSuggestAI,
  suggestBusy,
  pendingSuggestionCount,
}: AnalysisToolbarProps) {
  const [openMenu, setOpenMenu] = useState<"filter" | "sort" | "add" | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!openMenu) return;
    const onMouseDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpenMenu(null);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenMenu(null);
    };
    document.addEventListener("mousedown", onMouseDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onMouseDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openMenu]);

  const toggle = (menu: "filter" | "sort" | "add") => setOpenMenu((prev) => (prev === menu ? null : menu));

  return (
    <div className="analysis-toolbar" ref={rootRef}>
      <div className="analysis-toolbar__search">
        <IconSearch />
        <input
          type="search"
          placeholder="Search analyses…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>

      <div className="analysis-toolbar__item">
        <button
          type="button"
          className={`analysis-toolbar__btn${activeFilterCount > 0 ? " analysis-toolbar__btn--active" : ""}`}
          aria-expanded={openMenu === "filter"}
          onClick={() => toggle("filter")}
        >
          <IconFilter />
          Filter
          {activeFilterCount > 0 && <span className="analysis-toolbar__count">{activeFilterCount}</span>}
        </button>
        {openMenu === "filter" && (
          <div className="analysis-toolbar__popover" role="dialog" aria-label="Filter analyses">
            {categories.length > 0 && (
              <>
                <span className="analysis-toolbar__popover-label">Category</span>
                <ul className="analysis-toolbar__check-list">
                  {categories.map((label) => (
                    <li key={label}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selectedCategories.includes(label)}
                          onChange={() => onToggleCategory(label)}
                        />
                        {label}
                      </label>
                    </li>
                  ))}
                </ul>
              </>
            )}
            <span className="analysis-toolbar__popover-label">Status</span>
            <ul className="analysis-toolbar__check-list">
              {(Object.keys(STATUS_LABELS) as AnalysisStatusFilter[]).map((status) => (
                <li key={status}>
                  <label>
                    <input
                      type="checkbox"
                      checked={selectedStatuses.includes(status)}
                      onChange={() => onToggleStatus(status)}
                    />
                    {STATUS_LABELS[status]}
                  </label>
                </li>
              ))}
            </ul>
            {activeFilterCount > 0 && (
              <button type="button" className="analysis-toolbar__reset" onClick={onClearFilters}>
                Clear filters
              </button>
            )}
          </div>
        )}
      </div>

      <div className="analysis-toolbar__item">
        <button
          type="button"
          className="analysis-toolbar__btn"
          aria-expanded={openMenu === "sort"}
          onClick={() => toggle("sort")}
        >
          Sort: {SORT_LABELS[sort]}
          <IconChevronDown />
        </button>
        {openMenu === "sort" && (
          <div className="analysis-toolbar__popover analysis-toolbar__popover--narrow" role="menu" aria-label="Sort analyses">
            {(Object.keys(SORT_LABELS) as AnalysisSortKey[]).map((key) => (
              <button
                type="button"
                key={key}
                role="menuitemradio"
                aria-checked={sort === key}
                className={`analysis-toolbar__menu-item${sort === key ? " analysis-toolbar__menu-item--active" : ""}`}
                onClick={() => {
                  onSortChange(key);
                  setOpenMenu(null);
                }}
              >
                {SORT_LABELS[key]}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="analysis-toolbar__item analysis-toolbar__item--add">
        <button
          type="button"
          className="analysis-toolbar__btn analysis-toolbar__btn--primary"
          aria-expanded={openMenu === "add"}
          onClick={() => toggle("add")}
        >
          <IconPlus /> Add
        </button>
        {openMenu === "add" && (
          <div className="analysis-toolbar__popover analysis-toolbar__popover--narrow analysis-toolbar__popover--right" role="menu" aria-label="Add an analysis">
            <button
              type="button"
              className="analysis-toolbar__menu-item"
              onClick={() => {
                setOpenMenu(null);
                onAddCustom();
              }}
            >
              Add Custom Analysis
            </button>
            <button
              type="button"
              className="analysis-toolbar__menu-item"
              disabled={suggestBusy}
              onClick={() => {
                setOpenMenu(null);
                onSuggestAI();
              }}
            >
              <IconSparkle />{" "}
              {suggestBusy
                ? "Thinking…"
                : pendingSuggestionCount > 0
                  ? `View AI Suggestions (${pendingSuggestionCount})`
                  : "Suggest with AI"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
