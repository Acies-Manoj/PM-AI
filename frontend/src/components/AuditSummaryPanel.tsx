import { useMemo } from "react";
import type { AuditIssue, AuditReport as AuditReportData } from "../api/audit";
import { COLUMN_SCOPED_CATEGORIES } from "./AuditIssueCard";
import "./AuditReport.css";

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

interface AuditSummaryPanelProps {
  report: AuditReportData;
}

// The "what changed" recap -- shared between AuditReport's own Summary tab
// (non-wizard sources) and the wizard's top-level Summary tab (SensiWatch),
// so both stay in sync from one implementation.
export default function AuditSummaryPanel({ report }: AuditSummaryPanelProps) {
  const decisionIssues = report.issues.filter((i) => i.requires_decision);
  const resolvedCount = decisionIssues.filter((i) => i.status === "resolved").length;
  const resolvedIssues = useMemo(
    () => decisionIssues.filter((i) => i.status === "resolved" && i.resolution),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [report.issues]
  );

  const changeTotals = useMemo(() => summarizeChanges(resolvedIssues), [resolvedIssues]);
  const originalRowCount = report.row_count + changeTotals.rowsRemoved;
  const originalColumnCount = report.column_count + changeTotals.columnsDropped;
  const datasetChanged = changeTotals.columnsDropped > 0 || changeTotals.rowsRemoved > 0;

  const summaryClauses: string[] = [];
  if (changeTotals.columnsDropped > 0) summaryClauses.push(`dropped ${pluralize(changeTotals.columnsDropped, "column")}`);
  if (changeTotals.rowsRemoved > 0) summaryClauses.push(`removed ${pluralize(changeTotals.rowsRemoved, "row")}`);
  if (changeTotals.keptCount > 0) summaryClauses.push(`kept ${pluralize(changeTotals.keptCount, "finding")} as-is`);
  const summarySentence = joinClauses(summaryClauses);

  if (resolvedCount === 0) {
    return <p className="audit-report__empty-tab">No changes yet — resolve some findings to see a summary here.</p>;
  }

  return (
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
              ? "Audit complete — here's what changed"
              : `${resolvedCount} of ${decisionIssues.length} findings resolved so far`}
          </p>
          <p className="audit-report__changes-sentence">
            {summarySentence || "No changes made yet — every finding so far was kept as-is."}
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
  );
}
