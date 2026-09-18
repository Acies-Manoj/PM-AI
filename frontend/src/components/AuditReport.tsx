import { useEffect, useMemo, useRef, useState } from "react";
import type { AuditIssue, AuditReport as AuditReportData } from "../api/audit";
import AuditIssueCard, { COLUMN_SCOPED_CATEGORIES } from "./AuditIssueCard";
import StatTile from "./StatTile";
import { IconDoc, IconGrid, IconSearch, IconWarnTriangle, IconClipboard, IconInfo } from "./icons";
import "./AuditReport.css";

interface AuditReportProps {
  report: AuditReportData;
  onResolve: (issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevert: (issueId: string) => void;
  resolvingIssueId: string | null;
  activeTab: Tab;
  onTabChange: (tab: Tab) => void;
}

export type Tab = "quality" | "summary";

// Resolution text is always machine-generated (see backend apply_decision) so
// the leading count is safe to parse back out for a rollup, rather than
// re-deriving it from selectable_items/affected_row_count which may have
// shifted since the issue was first detected.
function parseLeadingCount(resolution: string): number | null {
  const match = resolution.match(/^(?:Dropped|Removed) (\d+)/);
  return match ? Number(match[1]) : null;
}

function summarizeChanges(resolvedIssues: AuditIssue[]) {
  let columnsDropped = 0;
  let rowsRemoved = 0;
  let keptCount = 0;
  for (const issue of resolvedIssues) {
    const resolution = issue.resolution ?? "";
    if (resolution.startsWith("Kept")) {
      keptCount += 1;
      continue;
    }
    const count = parseLeadingCount(resolution);
    if (count === null) continue;
    if (COLUMN_SCOPED_CATEGORIES.has(issue.category)) columnsDropped += count;
    else rowsRemoved += count;
  }
  return { columnsDropped, rowsRemoved, keptCount };
}

function pluralize(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function joinClauses(clauses: string[]): string {
  if (clauses.length === 0) return "";
  if (clauses.length === 1) return `${clauses[0]}.`;
  return `${clauses.slice(0, -1).join(", ")}, and ${clauses[clauses.length - 1]}.`;
}

// Matches a typed column name/fragment against a finding: the columns it
// actually lists (selectable_items), the single column it's namespaced to
// (e.g. "statistical_outliers::Mean Value"), and finally its description --
// that last one is what catches categories with no structured column field
// at all (range_violations, key_duplicate_rows) since they still name the
// relevant column(s) in the generated text.
function issueMatchesColumnQuery(issue: AuditIssue, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if (issue.selectable_items.some((c) => c.toLowerCase().includes(q))) return true;
  const nsIdx = issue.category.indexOf("::");
  if (nsIdx !== -1 && issue.category.slice(nsIdx + 2).toLowerCase().includes(q)) return true;
  return issue.description.toLowerCase().includes(q);
}

export default function AuditReport({
  report,
  onResolve,
  onRevert,
  resolvingIssueId,
  activeTab,
  onTabChange,
}: AuditReportProps) {
  const decisionIssues = report.issues.filter((i) => i.requires_decision);
  const pendingCount = decisionIssues.filter((i) => i.status === "pending").length;
  const resolvedCount = decisionIssues.length - pendingCount;
  const criticalCount = report.issues.filter((i) => i.severity === "critical").length;
  const warningCount = report.issues.filter((i) => i.severity === "warning").length;

  const qualityIssues = report.issues;
  const resolvedIssues = useMemo(
    () => decisionIssues.filter((i) => i.status === "resolved" && i.resolution),
    [decisionIssues]
  );

  const [bulkApplying, setBulkApplying] = useState(false);
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0 });
  const [columnQuery, setColumnQuery] = useState("");
  const [columnDropdownOpen, setColumnDropdownOpen] = useState(false);
  const columnSearchRef = useRef<HTMLDivElement | null>(null);

  const activeIssues = activeTab === "quality" ? qualityIssues : [];
  const visibleIssues = useMemo(
    () => activeIssues.filter((i) => issueMatchesColumnQuery(i, columnQuery)),
    [activeIssues, columnQuery]
  );
  const matchingColumns = useMemo(() => {
    const q = columnQuery.trim().toLowerCase();
    const cols = report.columns ?? [];
    return q ? cols.filter((c) => c.toLowerCase().includes(q)) : cols;
  }, [report.columns, columnQuery]);

  useEffect(() => {
    if (!columnDropdownOpen) return;
    const onMouseDown = (e: MouseEvent) => {
      if (columnSearchRef.current && !columnSearchRef.current.contains(e.target as Node)) {
        setColumnDropdownOpen(false);
      }
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setColumnDropdownOpen(false);
    };
    window.addEventListener("mousedown", onMouseDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("mousedown", onMouseDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [columnDropdownOpen]);

  const selectColumn = (col: string) => {
    setColumnQuery(col);
    setColumnDropdownOpen(false);
  };

  const clearColumnQuery = () => {
    setColumnQuery("");
    setColumnDropdownOpen(false);
  };
  // Bulk-apply only acts on whatever the column search is currently showing --
  // what you see is what gets applied.
  const pendingInActiveTab = useMemo(
    () => visibleIssues.filter((i) => i.requires_decision && i.status === "pending"),
    [visibleIssues]
  );

  // Snapshot the pending list at click time and work through it in order --
  // each onResolve re-renders the parent with a shrinking `activeIssues`, so
  // recomputing the work list mid-loop would make it shrink out from under
  // us. Each finding's own recommended_action/selectable_items are static
  // audit-time metadata (the backend re-validates them fresh against the
  // current dataframe on every resolve), so acting on the snapshot is safe
  // even if an earlier resolve in this same batch changed row/column counts.
  const applyAllRecommendations = async () => {
    const toApply = pendingInActiveTab;
    setBulkApplying(true);
    setBulkProgress({ done: 0, total: toApply.length });
    for (const issue of toApply) {
      const decisionId = issue.recommended_action ?? "keep";
      const selectedItems = issue.selectable_items.length > 0 ? issue.selectable_items : undefined;
      await onResolve(issue.id, decisionId, selectedItems);
      setBulkProgress((p) => ({ ...p, done: p.done + 1 }));
    }
    setBulkApplying(false);
  };

  const changeTotals = useMemo(() => summarizeChanges(resolvedIssues), [resolvedIssues]);
  const originalRowCount = report.row_count + changeTotals.rowsRemoved;
  const originalColumnCount = report.column_count + changeTotals.columnsDropped;
  const datasetChanged = changeTotals.columnsDropped > 0 || changeTotals.rowsRemoved > 0;

  const summaryClauses: string[] = [];
  if (changeTotals.columnsDropped > 0) summaryClauses.push(`dropped ${pluralize(changeTotals.columnsDropped, "column")}`);
  if (changeTotals.rowsRemoved > 0) summaryClauses.push(`removed ${pluralize(changeTotals.rowsRemoved, "row")}`);
  if (changeTotals.keptCount > 0) summaryClauses.push(`kept ${pluralize(changeTotals.keptCount, "finding")} as-is`);
  const summarySentence = joinClauses(summaryClauses);

  return (
    <div className="audit-report">
      <div className="audit-report__overview">
        <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
        <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
        <StatTile icon={<IconSearch />} color="purple" value={report.issues.length} label="Findings" />
        {criticalCount > 0 && <StatTile icon={<IconWarnTriangle />} color="error" value={criticalCount} label="Critical" />}
        {warningCount > 0 && <StatTile icon={<IconWarnTriangle />} color="amber" value={warningCount} label="Warning" />}
        <StatTile icon={<IconClipboard />} color="blue" value={`${resolvedCount}/${decisionIssues.length}`} label="Decisions" />
      </div>

      {report.summary && (
        <div className="audit-report__summary">
          <span className="audit-report__summary-icon">
            <IconInfo />
          </span>
          <p className="audit-report__summary-text">{report.summary}</p>
        </div>
      )}

      {report.issues.length > 0 && (
        <>
          <div className="audit-report__tabs-row">
            <div className="audit-report__tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "quality"}
                className={`audit-report__tab ${activeTab === "quality" ? "audit-report__tab--active" : ""}`}
                disabled={bulkApplying}
                onClick={() => onTabChange("quality")}
              >
                Overall Checks
                <span className="audit-report__tab-count">{qualityIssues.length}</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "summary"}
                className={`audit-report__tab ${activeTab === "summary" ? "audit-report__tab--active" : ""}`}
                disabled={bulkApplying}
                onClick={() => onTabChange("summary")}
              >
                Summary
                <span className="audit-report__tab-count">{resolvedCount}</span>
              </button>
            </div>
            {activeTab !== "summary" && (
              <div className="audit-report__tab-actions">
                <div className="audit-report__col-search" ref={columnSearchRef}>
                  <span className="audit-report__col-search-icon">
                    <IconSearch />
                  </span>
                  <input
                    type="text"
                    className="audit-report__col-search-input"
                    placeholder="Search by column…"
                    value={columnQuery}
                    disabled={bulkApplying}
                    onFocus={() => setColumnDropdownOpen(true)}
                    onChange={(e) => {
                      setColumnQuery(e.target.value);
                      setColumnDropdownOpen(true);
                    }}
                  />
                  {columnQuery && (
                    <button
                      type="button"
                      className="audit-report__col-search-clear"
                      aria-label="Clear column filter"
                      onClick={clearColumnQuery}
                    >
                      ✕
                    </button>
                  )}
                  {columnDropdownOpen && !bulkApplying && matchingColumns.length > 0 && (
                    <ul className="audit-report__col-dropdown" role="listbox">
                      {matchingColumns.map((col) => (
                        <li key={col}>
                          <button
                            type="button"
                            className="audit-report__col-option"
                            role="option"
                            aria-selected={col === columnQuery}
                            onClick={() => selectColumn(col)}
                          >
                            {col}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {(bulkApplying || pendingInActiveTab.length > 0) && (
                  <button
                    type="button"
                    className="audit-report__bulk-btn"
                    disabled={bulkApplying}
                    onClick={applyAllRecommendations}
                  >
                    {bulkApplying
                      ? `Applying ${bulkProgress.done} of ${bulkProgress.total}…`
                      : `Apply AI Recommendations (${pendingInActiveTab.length})`}
                  </button>
                )}
              </div>
            )}
          </div>

          {activeTab === "summary" ? (
            resolvedCount > 0 ? (
              <div
                className={`audit-report__changes ${
                  report.status === "reviewed" ? "audit-report__changes--complete" : ""
                }`}
              >
                <div className="audit-report__changes-head">
                  <span className="audit-report__changes-icon">{report.status === "reviewed" ? "✓" : "…"}</span>
                  <div className="audit-report__changes-copy">
                    <p className="audit-report__changes-title">
                      {report.status === "reviewed"
                        ? "Audit complete -- here's what changed"
                        : `${resolvedCount} of ${decisionIssues.length} findings resolved so far`}
                    </p>
                    <p className="audit-report__changes-sentence">
                      {summarySentence || "No changes made yet -- every finding so far was kept as-is."}
                      {datasetChanged && (
                        <>
                          {" "}Dataset is now <strong>{report.row_count.toLocaleString()}</strong> rows ×{" "}
                          <strong>{report.column_count}</strong> columns (from {originalRowCount.toLocaleString()} ×{" "}
                          {originalColumnCount}).
                        </>
                      )}
                    </p>
                  </div>
                </div>
                <p className="audit-report__changes-list-heading">Findings resolved ({resolvedCount})</p>
                <ul className="audit-report__changes-list">
                  {resolvedIssues.map((issue) => (
                    <li key={issue.id}>
                      <span className="audit-report__changes-item-title">{issue.title}:</span> {issue.resolution}
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="audit-report__empty-tab">No changes yet -- resolve some findings to see a summary here.</p>
            )
          ) : (
            <div className="audit-report__issues">
              {visibleIssues.length > 0 ? (
                visibleIssues.map((issue) => (
                  <AuditIssueCard
                    key={issue.id}
                    issue={issue}
                    sessionId={report.session_id}
                    onResolve={onResolve}
                    onRevert={onRevert}
                    resolving={resolvingIssueId === issue.id}
                    revertLocked={
                      issue.status === "resolved" &&
                      !(issue.resolution ?? "").startsWith("Kept") &&
                      issue.id !== report.revertible_issue_id
                    }
                  />
                ))
              ) : columnQuery ? (
                <p className="audit-report__empty-tab">No findings match column "{columnQuery}".</p>
              ) : (
                <p className="audit-report__empty-tab">No issues found.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
