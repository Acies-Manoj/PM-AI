import { PlannerSkippedContext, hasBrief } from "./context/plannerSkipped";
import { useRef, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import WelcomePage from "./pages/WelcomePage";
import UploadPage from "./pages/UploadPage";
import PlannerPage from "./pages/PlannerPage";
import AuditPage from "./pages/AuditPage";
import FeaturesPage from "./pages/FeaturesPage";
import AnalysisPage from "./pages/AnalysisPage";
import ReportPage from "./pages/ReportPage";
import { AuditApiError, resolveIssue, revertIssue, runAudit, uploadOnly } from "./api/audit";
import type { AuditReport as AuditReportData } from "./api/audit";
import { isAudited } from "./constants/uploadSlots";
import type { UploadSlotId } from "./types/upload";
import { resetAllState, resetDownstreamState } from "./state/sessionStore";
import { EMPTY_BRIEF } from "./components/ClientBriefInput";
import type { BriefState } from "./components/ClientBriefInput";

export type FilesState = Record<UploadSlotId, File | null>;
export type UploadedSessionIdsState = Partial<Record<UploadSlotId, string>>;
export type AuditReportsState = Partial<Record<UploadSlotId, AuditReportData>>;
export type AuditLoadingState = Partial<Record<UploadSlotId, boolean>>;
export type AuditErrorsState = Partial<Record<UploadSlotId, string>>;
export type ResolvingState = Partial<Record<UploadSlotId, string>>;
export type { BriefState };

const EMPTY_FILES: FilesState = {
  sensiwatch: null,
  coldstream: null,
  customerKpis: null,
  analysisProfile: null,
};

function App() {
  const [files, setFiles] = useState<FilesState>(EMPTY_FILES);
  const [brief, setBrief] = useState<BriefState>(EMPTY_BRIEF);
  const [uploadedSessionIds, setUploadedSessionIds] = useState<UploadedSessionIdsState>({});
  const [plannerSessionId, setPlannerSessionId] = useState<string | null>(null);
  const [auditReports, setAuditReports] = useState<AuditReportsState>({});
  const [auditLoading, setAuditLoading] = useState<AuditLoadingState>({});
  const [auditErrors, setAuditErrors] = useState<AuditErrorsState>({});
  const [resolvingIssueId, setResolvingIssueId] = useState<ResolvingState>({});
  const [reuploadingSensiwatch, setReuploadingSensiwatch] = useState(false);
  const [reuploadError, setReuploadError] = useState<string | null>(null);

  const plannerSkipped = !hasBrief(brief);

  // Always-current session ids, so an async audit/resolve/revert that finishes
  // after its file was replaced or removed can tell its result is stale and drop it.
  const sessionIdsRef = useRef<UploadedSessionIdsState>({});
  sessionIdsRef.current = uploadedSessionIds;

  const handleUploadComplete = (sessionIds: UploadedSessionIdsState) => {
    resetAllState();
    setUploadedSessionIds(sessionIds);
    setPlannerSessionId(sessionIds.sensiwatch ?? null);
  };

  const handleRunAudit = async (id: UploadSlotId) => {
    const sessionId = uploadedSessionIds[id];
    if (!sessionId) return;
    setAuditLoading((prev) => ({ ...prev, [id]: true }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    try {
      const report = await runAudit(sessionId);
      if (sessionIdsRef.current[id] !== sessionId) return;
      setAuditReports((prev) => ({ ...prev, [id]: report }));
    } catch (err) {
      if (sessionIdsRef.current[id] !== sessionId) return;
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not run the data audit. Is the backend running?",
      }));
    } finally {
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
    }
  };

  const handleSelect = (id: UploadSlotId, file: File) => {
    setFiles((prev) => ({ ...prev, [id]: file }));
    if (isAudited(id)) {
      resetAllState();
      setUploadedSessionIds((prev) => ({ ...prev, [id]: undefined }));
      setAuditReports((prev) => ({ ...prev, [id]: undefined }));
      setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
      setAuditLoading((prev) => ({ ...prev, [id]: false }));
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  const handleRemove = (id: UploadSlotId) => {
    resetAllState();
    setFiles((prev) => ({ ...prev, [id]: null }));
    setUploadedSessionIds((prev) => ({ ...prev, [id]: undefined }));
    setAuditReports((prev) => ({ ...prev, [id]: undefined }));
    setAuditErrors((prev) => ({ ...prev, [id]: undefined }));
    setAuditLoading((prev) => ({ ...prev, [id]: false }));
    setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
  };

  const handleClearAll = () => {
    resetAllState();
    setFiles(EMPTY_FILES);
    setBrief(EMPTY_BRIEF);
    setUploadedSessionIds({});
    setPlannerSessionId(null);
    setAuditReports({});
    setAuditErrors({});
    setAuditLoading({});
    setResolvingIssueId({});
    setReuploadingSensiwatch(false);
    setReuploadError(null);
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
      if (sessionIdsRef.current[id] !== report.session_id) return;
      // The audited data changed, so anything built on it is out of date.
      resetDownstreamState();
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

  // A corrected file re-uploaded from the SensiWatch outlier-correction step
  // (see AuditPage / OutlierCorrectionStep) -- treated as a fresh upload for
  // that slot, same session-reset shape as handleSelect uses for a normal
  // first upload, so the audit pipeline re-runs cleanly from scratch on it.
  const handleReuploadSensiwatch = async (file: File) => {
    setReuploadingSensiwatch(true);
    setReuploadError(null);
    try {
      const result = await uploadOnly("sensiwatch", file);
      resetAllState();
      setFiles((prev) => ({ ...prev, sensiwatch: file }));
      setUploadedSessionIds((prev) => ({ ...prev, sensiwatch: result.session_id }));
      setAuditReports((prev) => ({ ...prev, sensiwatch: undefined }));
      setAuditErrors((prev) => ({ ...prev, sensiwatch: undefined }));
    } catch (err) {
      setReuploadError(err instanceof AuditApiError ? err.message : "Could not upload the corrected file.");
    } finally {
      setReuploadingSensiwatch(false);
    }
  };

  const handleRevertIssue = async (id: UploadSlotId, issueId: string) => {
    const report = auditReports[id];
    if (!report) return;
    setResolvingIssueId((prev) => ({ ...prev, [id]: issueId }));
    try {
      const updated = await revertIssue(report.session_id, issueId);
      if (sessionIdsRef.current[id] !== report.session_id) return;
      resetDownstreamState();
      setAuditReports((prev) => ({ ...prev, [id]: updated }));
    } catch (err) {
      setAuditErrors((prev) => ({
        ...prev,
        [id]: err instanceof AuditApiError ? err.message : "Could not revert that change.",
      }));
    } finally {
      setResolvingIssueId((prev) => ({ ...prev, [id]: undefined }));
    }
  };

  return (
    <BrowserRouter>
      <PlannerSkippedContext.Provider value={plannerSkipped}>
      <Routes>
        <Route path="/" element={<WelcomePage />} />
        <Route
          path="/upload"
          element={
            <UploadPage
              files={files}
              brief={brief}
              onSelect={handleSelect}
              onRemove={handleRemove}
              onClearAll={handleClearAll}
              onBriefChange={setBrief}
              onUploadComplete={handleUploadComplete}
            />
          }
        />
        <Route
          path="/planner"
          element={<PlannerPage sessionId={plannerSessionId} files={files} />}
        />
        <Route
          path="/audit"
          element={
            <AuditPage
              files={files}
              uploadedSessionIds={uploadedSessionIds}
              auditReports={auditReports}
              auditLoading={auditLoading}
              auditErrors={auditErrors}
              resolvingIssueId={resolvingIssueId}
              onRunAudit={handleRunAudit}
              onResolveIssue={handleResolveIssue}
              onRevertIssue={handleRevertIssue}
              onReuploadSensiwatch={handleReuploadSensiwatch}
              reuploadingSensiwatch={reuploadingSensiwatch}
              reuploadError={reuploadError}
            />
          }
        />
        <Route path="/features" element={<FeaturesPage files={files} auditReports={auditReports} />} />
        <Route path="/analysis" element={<AnalysisPage files={files} auditReports={auditReports} />} />
        <Route path="/report" element={<ReportPage files={files} auditReports={auditReports} />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </PlannerSkippedContext.Provider>
    </BrowserRouter>
  );
}

export default App;
