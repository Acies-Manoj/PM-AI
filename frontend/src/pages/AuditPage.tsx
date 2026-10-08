import ThinkingLoader from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import PageNav from "../components/PageNav";
import AuditReport from "../components/AuditReport";
import type { Tab } from "../components/AuditReport";
import AuditSummaryPanel from "../components/AuditSummaryPanel";
import OutlierCorrectionStep from "../components/OutlierCorrectionStep";
import { IconShieldSearch, IconDownload } from "../components/icons";
import { downloadCleansedFileUrl } from "../api/audit";
import { useStoredState } from "../state/sessionStore";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditErrorsState, AuditLoadingState, AuditReportsState, FilesState, ResolvingState, UploadedSessionIdsState } from "../App";
import "./AuditPage.css";

// SensiWatch alone gets the outlier-checks-first wizard (see
// OutlierCorrectionStep) -- ColdStream keeps today's tabbed layout, run
// immediately on upload like every other audited slot.
const WIZARD_SLOT: UploadSlotId = "sensiwatch";

interface AuditPageProps {
  files: FilesState;
  uploadedSessionIds: UploadedSessionIdsState;
  auditReports: AuditReportsState;
  auditLoading: AuditLoadingState;
  auditErrors: AuditErrorsState;
  resolvingIssueId: ResolvingState;
  onRunAudit: (id: UploadSlotId) => void;
  onResolveIssue: (id: UploadSlotId, issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevertIssue: (id: UploadSlotId, issueId: string) => void;
  onReuploadSensiwatch: (file: File) => Promise<string | null>;
  reuploadingSensiwatch: boolean;
  reuploadError: string | null;
}

export default function AuditPage({
  files,
  uploadedSessionIds,
  auditReports,
  auditLoading,
  auditErrors,
  resolvingIssueId,
  onRunAudit,
  onResolveIssue,
  onRevertIssue,
  onReuploadSensiwatch,
  reuploadingSensiwatch,
  reuploadError,
}: AuditPageProps) {
  const navigate = useNavigate();
  // Held in the shared store (not local state) so leaving this page and coming
  // back keeps the PM where they were instead of replaying the outlier step.
  const [activeTabs, setActiveTabs] = useStoredState<Partial<Record<UploadSlotId, Tab>>>("audit.activeTabs", {});
  const cardRefs = useRef<Partial<Record<UploadSlotId, HTMLElement | null>>>({});

  // The SensiWatch card shows three persistent tabs -- "Outliers Check" (duration/
  // temperature outlier review), "Standard Check" (the usual Standard Checks /
  // Human Decision flow), and "Summary" (what changed overall). Standard Check and
  // Summary stay disabled until the outlier review has been resolved or explicitly
  // skipped for the CURRENT session. The unlock is remembered against that session
  // id, so a new or re-uploaded file (new id) starts back at the outlier step.
  const [storedWizardTab, setWizardActiveTab] = useStoredState<"outliers" | "standard" | "summary" | null>(
    "audit.wizardTab",
    null
  );
  const [unlockedForSession, setUnlockedForSession] = useStoredState<string | null>("audit.sensiwatchUnlockedFor", null);
  const sensiwatchSessionId = uploadedSessionIds[WIZARD_SLOT];
  const sensiwatchStandardUnlocked = !!sensiwatchSessionId && unlockedForSession === sensiwatchSessionId;
  const wizardActiveTab = storedWizardTab ?? "outliers";

  // An audit runs once per upload: never when a report already exists (it
  // holds the PM's resolved decisions), one is in flight, or it already failed.
  const needsAudit = (id: UploadSlotId) =>
    !!uploadedSessionIds[id] && !auditReports[id] && !auditLoading[id] && !auditErrors[id];

  useEffect(() => {
    for (const id of AUDITED_SLOTS) {
      // SensiWatch's audit is deferred until the outlier step is passed (skipped or corrected file uploaded).
      if (id === WIZARD_SLOT && !sensiwatchStandardUnlocked) continue;
      if (needsAudit(id)) onRunAudit(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadedSessionIds, auditReports, auditLoading, auditErrors, sensiwatchStandardUnlocked]);

  const advanceSensiwatchToStandard = (sessionId: string | null | undefined = sensiwatchSessionId) => {
    setUnlockedForSession(sessionId ?? null);
    setWizardActiveTab("standard");
  };

  // The corrected file replaces the original: skip a second outlier review and go straight to
  // the Standard Check on the new session.
  const handleCorrectedFile = async (file: File) => {
    const newSessionId = await onReuploadSensiwatch(file);
    if (newSessionId) advanceSensiwatchToStandard(newSessionId);
  };

  const auditedSlotsWithFiles = AUDITED_SLOTS.filter((id) => uploadedSessionIds[id]);
  const hasAnyFile = UPLOAD_SLOTS.some((s) => files[s.id]);

  const anyLoading = auditedSlotsWithFiles.some((id) => auditLoading[id]);
  const anyPending = auditedSlotsWithFiles.some((id) => auditReports[id]?.status === "pending_review");
  const canContinue =
    !!uploadedSessionIds.sensiwatch && sensiwatchStandardUnlocked && !anyLoading && !anyPending;

  if (!hasAnyFile) {
    return (
      <div className="audit-page">
        <Header subtitle="Data Audit" />
        <main className="audit-page__main">
          <StepIndicator current={3} />
          <div className="audit-page__empty">
            <p>No files have been uploaded yet.</p>
            <button type="button" className="btn btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="audit-page">
      <Header subtitle="Data Audit" />
      <main className="audit-page__main">
        <StepIndicator current={3} />

        <PageNav position="top" onBack={() => navigate("/planner")}>
          <button type="button" className="btn btn--primary" disabled={!canContinue} onClick={() => navigate("/features")}>
            Proceed to Features
          </button>
        </PageNav>

        <PageHeader
          icon={<IconShieldSearch />}
          title="Data Audit"
          subtitle="Automated data quality checks have been run on your tabular uploads below. Review each finding and confirm any outstanding decisions before continuing."
        />

        {auditedSlotsWithFiles.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = auditReports[id];
          const activeTab = activeTabs[id] ?? "quality";
          return (
            <section className="audit-page__card" key={id} ref={(el) => { cardRefs.current[id] = el; }}>
              <div className="audit-page__card-head">
                <div className="audit-page__card-head-left">
                  <h2 className="audit-page__slot-title">{slot.title}</h2>
                  <span className="audit-page__pill">DATA AUDIT SUMMARY</span>
                  {report && (
                    <span
                      className={`audit-page__status audit-page__status--${
                        report.status === "reviewed" ? "reviewed" : "pending"
                      }`}
                    >
                      {report.status === "reviewed"
                        ? "Reviewed"
                        : `${report.issues.filter((i) => i.requires_decision && i.status === "pending").length} decision(s) needed`}
                    </span>
                  )}
                </div>
                <span className="audit-page__filename">{files[id]!.name}</span>
              </div>

              {id === WIZARD_SLOT ? (
                <>
                  <div className="audit-page__wizard-tabs" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={wizardActiveTab === "outliers"}
                      className={`audit-page__wizard-tab ${
                        wizardActiveTab === "outliers" ? "audit-page__wizard-tab--active" : ""
                      }`}
                      onClick={() => setWizardActiveTab("outliers")}
                    >
                      Outliers Check
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={wizardActiveTab === "standard"}
                      className={`audit-page__wizard-tab ${
                        wizardActiveTab === "standard" ? "audit-page__wizard-tab--active" : ""
                      }`}
                      disabled={!sensiwatchStandardUnlocked}
                      title={
                        sensiwatchStandardUnlocked
                          ? undefined
                          : "Resolve or skip the outliers check first"
                      }
                      onClick={() => sensiwatchStandardUnlocked && setWizardActiveTab("standard")}
                    >
                      Standard Check
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={wizardActiveTab === "summary"}
                      className={`audit-page__wizard-tab ${
                        wizardActiveTab === "summary" ? "audit-page__wizard-tab--active" : ""
                      }`}
                      disabled={!report}
                      title={report ? undefined : "Resolve or skip the outliers check first"}
                      onClick={() => report && setWizardActiveTab("summary")}
                    >
                      Summary
                    </button>
                  </div>

                  {wizardActiveTab === "outliers" ? (
                    <OutlierCorrectionStep
                      sessionId={uploadedSessionIds[id]!}
                      onFileCorrected={handleCorrectedFile}
                      onProceed={() => advanceSensiwatchToStandard()}
                      uploading={reuploadingSensiwatch}
                      uploadError={reuploadError}
                    />
                  ) : wizardActiveTab === "summary" ? (
                    report && <AuditSummaryPanel report={report} />
                  ) : (
                    <>
                      {auditLoading[id] && (
                        <ThinkingLoader messages={LOADING.audit} hint="Data quality checks are running on this file." intervalMs={3500} showElapsed />
                      )}

                      {auditErrors[id] && <p className="audit-page__audit-error">{auditErrors[id]}</p>}

                      {report && (
                        <>
                          <AuditReport
                            report={report}
                            onResolve={(issueId, decisionId, selectedItems) =>
                              onResolveIssue(id, issueId, decisionId, selectedItems)
                            }
                            onRevert={(issueId) => onRevertIssue(id, issueId)}
                            resolvingIssueId={resolvingIssueId[id] ?? null}
                            activeTab={activeTab}
                            onTabChange={(tab) => setActiveTabs((prev) => ({ ...prev, [id]: tab }))}
                            hideOutlierTabs
                            hideSummaryTab
                          />
                          <div className="audit-page__row-actions">
                            <a className="audit-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                              <IconDownload />
                              Download cleansed file
                            </a>
                          </div>
                        </>
                      )}
                    </>
                  )}
                </>
              ) : (
                <>
                  {auditLoading[id] && (
                    <ThinkingLoader messages={LOADING.audit} hint="Data quality checks are running on this file." intervalMs={3500} showElapsed />
                  )}

                  {auditErrors[id] && <p className="audit-page__audit-error">{auditErrors[id]}</p>}

                  {report && (
                    <>
                      <AuditReport
                        report={report}
                        onResolve={(issueId, decisionId, selectedItems) =>
                          onResolveIssue(id, issueId, decisionId, selectedItems)
                        }
                        onRevert={(issueId) => onRevertIssue(id, issueId)}
                        resolvingIssueId={resolvingIssueId[id] ?? null}
                        activeTab={activeTab}
                        onTabChange={(tab) => setActiveTabs((prev) => ({ ...prev, [id]: tab }))}
                      />
                      <div className="audit-page__row-actions">
                        <a className="audit-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                          <IconDownload />
                          Download cleansed file
                        </a>
                      </div>
                    </>
                  )}
                </>
              )}
            </section>
          );
        })}

        <PageNav position="bottom" onBack={() => navigate("/planner")}>
          <button type="button" className="btn btn--primary" disabled={!canContinue} onClick={() => navigate("/features")}>
            Proceed to Features
          </button>
        </PageNav>

        {!canContinue && !anyLoading && (
          <p className="audit-page__hint">Resolve the outstanding data audit questions above before continuing.</p>
        )}
      </main>
    </div>
  );
}
