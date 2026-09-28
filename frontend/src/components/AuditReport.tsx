import { useEffect, useMemo, useRef, useState } from "react";
import type { AuditIssue, AuditReport as AuditReportData, OutliersResponse } from "../api/audit";
import { fetchOutliers } from "../api/audit";
import AuditIssueCard from "./AuditIssueCard";
import AuditSummaryPanel from "./AuditSummaryPanel";
import SegmentOutlierTab from "./SegmentOutlierTab";
import TemperatureOutlierTab from "./TemperatureOutlierTab";
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
  // Hides the Segment Outlier / Temperature Outliers tabs -- for a source
  // (SensiWatch) whose own dedicated outlier-correction step already showed
  // this same data before Standard Checks ran, so showing it again here
  // would just be a duplicate of what the PM already reviewed.
  hideOutlierTabs?: boolean;
  // Hides this report's own Summary tab -- for a source (SensiWatch) whose
  // wizard already exposes Summary as its own top-level tab (see AuditPage),
  // so showing it again here would just be a duplicate.
  hideSummaryTab?: boolean;
}

export type Tab = "quality" | "segment" | "temperature" | "summary";

// statistical_outliers and missing_identifier issues are now shown under
// Overall Checks since Variable-Level Checks has been removed.
export function classifyIssue(_issue: AuditIssue): Tab {
  return "quality";
}

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
  hideOutlierTabs = false,
  hideSummaryTab = false,
}: AuditReportProps) {
  const decisionIssues = report.issues.filter((i) => i.requires_decision);
  const pendingCount = decisionIssues.filter((i) => i.status === "pending").length;
  const resolvedCount = decisionIssues.length - pendingCount;
  const criticalCount = report.issues.filter((i) => i.severity === "critical").length;
  const warningCount = report.issues.filter((i) => i.severity === "warning").length;

  const qualityIssues = useMemo(() => report.issues, [report.issues]);

  const [bulkApplying, setBulkApplying] = useState(false);
  const [bulkProgress, setBulkProgress] = useState({ done: 0, total: 0 });
  const [columnQuery, setColumnQuery] = useState("");
  const [columnDropdownOpen, setColumnDropdownOpen] = useState(false);
  const columnSearchRef = useRef<HTMLDivElement | null>(null);

  // Outlier data — loaded lazily on first visit to segment or temperature tab.
  // Reset whenever the session changes (new file uploaded).
  const [outlierData, setOutlierData] = useState<OutliersResponse | null>(null);
  const [outlierLoading, setOutlierLoading] = useState(false);
  const [outlierError, setOutlierError] = useState<string | null>(null);
  const lastSessionRef = useRef<string | null>(null);

  useEffect(() => {
    if (report.session_id !== lastSessionRef.current) {
      lastSessionRef.current = report.session_id;
      setOutlierData(null);
      setOutlierError(null);
    }
  }, [report.session_id]);

  const loadOutliers = () => {
    setOutlierLoading(true);
    setOutlierError(null);
    fetchOutliers(report.session_id)
      .then(setOutlierData)
      .catch((e: Error) => setOutlierError(e.message))
      .finally(() => setOutlierLoading(false));
  };

  const refreshOutliers = () => {
    setOutlierData(null);
    loadOutliers();
  };

  useEffect(() => {
    if (activeTab !== "segment" && activeTab !== "temperature") return;
    if (outlierData || outlierLoading || outlierError) return;
    loadOutliers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, report.session_id, outlierData, outlierLoading, outlierError]);

  const visibleIssues = useMemo(
    () => qualityIssues.filter((i) => issueMatchesColumnQuery(i, columnQuery)),
    [qualityIssues, columnQuery]
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

  const pendingInActiveTab = useMemo(
    () => visibleIssues.filter((i) => i.requires_decision && i.status === "pending"),
    [visibleIssues]
  );

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

  const segmentFlagged = outlierData?.segment.flagged_trips ?? null;
  const tempBreaches =
    outlierData != null
      ? outlierData.temperature.too_warm_count + outlierData.temperature.too_cold_count
      : null;

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
              {!hideOutlierTabs && (
                <>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "segment"}
                    className={`audit-report__tab ${activeTab === "segment" ? "audit-report__tab--active" : ""}`}
                    disabled={bulkApplying}
                    onClick={() => onTabChange("segment")}
                  >
                    Segment Outlier
                    {segmentFlagged !== null && (
                      <span className="audit-report__tab-count">{segmentFlagged}</span>
                    )}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={activeTab === "temperature"}
                    className={`audit-report__tab ${activeTab === "temperature" ? "audit-report__tab--active" : ""}`}
                    disabled={bulkApplying}
                    onClick={() => onTabChange("temperature")}
                  >
                    Temperature Outliers
                    {tempBreaches !== null && (
                      <span className="audit-report__tab-count">{tempBreaches}</span>
                    )}
                  </button>
                </>
              )}
              {!hideSummaryTab && (
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
              )}
            </div>

            {(activeTab === "segment" || activeTab === "temperature") && outlierData !== null && !outlierLoading && (
              <div className="audit-report__tab-actions">
                <button
                  type="button"
                  className="audit-report__bulk-btn"
                  onClick={refreshOutliers}
                >
                  ↻ Refresh analysis
                </button>
              </div>
            )}

            {activeTab === "quality" && (
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
            <AuditSummaryPanel report={report} />
          ) : activeTab === "segment" ? (
            outlierLoading ? (
              <p className="outlier-tab__loading">Analyzing segment lengths…</p>
            ) : outlierError ? (
              <div className="outlier-tab__error">
                Could not load outlier data: {outlierError}
                <button type="button" className="outlier-tab__retry" onClick={loadOutliers}>Retry</button>
              </div>
            ) : outlierData ? (
              <SegmentOutlierTab data={outlierData.segment} sessionId={report.session_id} onUpdated={setOutlierData} />
            ) : null
          ) : activeTab === "temperature" ? (
            outlierLoading ? (
              <p className="outlier-tab__loading">Analyzing temperature data…</p>
            ) : outlierError ? (
              <div className="outlier-tab__error">
                Could not load outlier data: {outlierError}
                <button type="button" className="outlier-tab__retry" onClick={loadOutliers}>Retry</button>
              </div>
            ) : outlierData ? (
              <TemperatureOutlierTab data={outlierData.temperature} sessionId={report.session_id} onUpdated={setOutlierData} />
            ) : null
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
                <p className="audit-report__empty-tab">No overall issues found.</p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
