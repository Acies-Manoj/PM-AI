import { useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import UploadPage from "./pages/UploadPage";
import AuditPage from "./pages/AuditPage";
import ScreeningPage from "./pages/ScreeningPage";
import FeaturesPage from "./pages/FeaturesPage";
import AnalysisPage from "./pages/AnalysisPage";
import ReportPage from "./pages/ReportPage";
import { AuditApiError, resolveIssue, uploadForAudit } from "./api/audit";
import type { AuditReport as AuditReportData } from "./api/audit";
import { isAudited } from "./constants/uploadSlots";
import type { UploadSlotId } from "./types/upload";
import type { BriefAnalysis } from "./api/brief";

export type FilesState = Record<UploadSlotId, File | null>;
export type AuditReportsState = Partial<Record<UploadSlotId, AuditReportData>>;
export type AuditLoadingState = Partial<Record<UploadSlotId, boolean>>;
export type AuditErrorsState = Partial<Record<UploadSlotId, string>>;
export type ResolvingState = Partial<Record<UploadSlotId, string>>;

export interface BriefState {
  text: string;
  analysis: BriefAnalysis | null;
}

const EMPTY_FILES: FilesState = {
  sensiwatch: null,
  coldstream: null,
  thresholds: null,
  customerKpis: null,
};

const EMPTY_BRIEF: BriefState = { text: "", analysis: null };

function App() {
  const [files, setFiles] = useState<FilesState>(EMPTY_FILES);
  const [auditReports, setAuditReports] = useState<AuditReportsState>({});
  const [auditLoading, setAuditLoading] = useState<AuditLoadingState>({});
  const [auditErrors, setAuditErrors] = useState<AuditErrorsState>({});
  const [resolvingIssueId, setResolvingIssueId] = useState<ResolvingState>({});
  const [brief, setBrief] = useState<BriefState>(EMPTY_BRIEF);
  const [analysisId, setAnalysisId] = useState<string | null>(null);

  const runAudit = async (id: UploadSlotId, file: File) => {
    setAuditLoading((prev) => ({ ...prev, [id]: true }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    try {
      const report = await uploadForAudit(id, file);
      setAuditReports((prev) => ({ ...prev, [id]: report }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not reach the audit agent. Is the backend running?",
      }));
    } finally {
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleSelect = (id: UploadSlotId, file: File) => {
    setFiles((prev) => ({ ...prev, [id]: file }));
    if (isAudited(id)) {
      setAuditReports((prev) => ({ ...prev, [id]: undefined }));
      setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  const handleRemove = (id: UploadSlotId) => {
    setFiles((prev) => ({ ...prev, [id]: null }));
    setAuditReports((prev) => ({ ...prev, [id]: undefined }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    setAuditLoading((prev) => ({ ...prev, [id]: false }));
  };

  const handleClearAll = () => {
    setFiles(EMPTY_FILES);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
    setBrief(EMPTY_BRIEF);
    setAnalysisId(null);
  };

  const handleResolveIssue = async (
    id: UploadSlotId,
    issueId: string,
    decisionId: string,
    selectedItems?: string[]
  ) => {
    const report = auditReports[id];
    if (!report) return;
    setResolvingIssueId((prev) => ({ ...prev, [id]: issueId }));
    try {
      const updated = await resolveIssue(report.session_id, issueId, decisionId, selectedItems);
      setAuditReports((prev) => ({ ...prev, [id]: updated }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not apply that decision.",
      }));
    } finally {
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/upload" replace />} />
        <Route
          path="/upload"
          element={
            <UploadPage
              files={files}
              brief={brief}
              onSelect={handleSelect}
              onRemove={handleRemove}
              onClearAll={handleClearAll}
              onBriefChange={(text) => setBrief((b) => ({ ...b, text }))}
              onBriefAnalyzed={(analysis) => setBrief((b) => ({ ...b, analysis }))}
            />
          }
        />
        <Route
          path="/audit"
          element={
            <AuditPage
              files={files}
              auditReports={auditReports}
              auditLoading={auditLoading}
              auditErrors={auditErrors}
              resolvingIssueId={resolvingIssueId}
              onRunAudit={runAudit}
              onResolveIssue={handleResolveIssue}
            />
          }
        />
        <Route
          path="/screening"
          element={<ScreeningPage files={files} auditReports={auditReports} />}
        />
        <Route
          path="/features"
          element={<FeaturesPage files={files} auditReports={auditReports} />}
        />
        <Route
          path="/analysis"
          element={
            <AnalysisPage
              files={files}
              auditReports={auditReports}
              brief={brief}
              onAnalysisStarted={setAnalysisId}
            />
          }
        />
        <Route
          path="/report"
          element={<ReportPage files={files} analysisId={analysisId} />}
        />
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
