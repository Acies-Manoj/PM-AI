import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import AuditReport from "../components/AuditReport";
import type { Tab } from "../components/AuditReport";
import AuditSummaryPanel from "../components/AuditSummaryPanel";
import OutlierCorrectionStep from "../components/OutlierCorrectionStep";
import { IconShieldSearch, IconDownload } from "../components/icons";
import { downloadCleansedFileUrl } from "../api/audit";
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
  onReuploadSensiwatch: (file: File) => Promise<void>;
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
  const [activeTabs, setActiveTabs] = useState<Partial<Record<UploadSlotId, Tab>>>({});
  const cardRefs = useRef<Partial<Record<UploadSlotId, HTMLElement | null>>>({});

  // The SensiWatch card shows three persistent tabs -- "Outliers Check" (duration/
  // temperature outlier review), "Standard Check" (the usual Standard Checks /
  // Human Decision flow), and "Summary" (what changed overall). Standard Check and
  // Summary stay disabled until the outlier review has been resolved or explicitly
  // skipped for the CURRENT session.
  const [wizardActiveTab, setWizardActiveTab] = useState<"outliers" | "standard" | "summary">("outliers");
  const [sensiwatchStandardUnlocked, setSensiwatchStandardUnlocked] = useState(false);
  const lastSensiwatchSessionId = useRef<string | undefined>(undefined);

  const submittedIds = useRef<Set<UploadSlotId>>(new Set());

  useEffect(() => {
    for (const id of AUDITED_SLOTS) {
      if (id === WIZARD_SLOT) continue; // deferred until the outlier step is passed -- see below
      if (!uploadedSessionIds[id]) continue;
      if (submittedIds.current.has(id)) continue;
      submittedIds.current.add(id);
      onRunAudit(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploadedSessionIds]);

  // A new (or freshly re-uploaded) SensiWatch session always starts back at
  // the outlier-review step, even if a previous session for this slot had
  // already reached Standard Checks.
  useEffect(() => {
    const id = uploadedSessionIds[WIZARD_SLOT];
    if (id && id !== lastSensiwatchSessionId.current) {
      lastSensiwatchSessionId.current = id;
      setWizardActiveTab("outliers");
      setSensiwatchStandardUnlocked(false);
      submittedIds.current.delete(WIZARD_SLOT);
    }
  }, [uploadedSessionIds]);

  const advanceSensiwatchToStandard = () => {
    setSensiwatchStandardUnlocked(true);
    setWizardActiveTab("standard");
    if (!submittedIds.current.has(WIZARD_SLOT)) {
      submittedIds.current.add(WIZARD_SLOT);
      onRunAudit(WIZARD_SLOT);
    }
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
            <button type="button" className="audit-page__btn audit-page__btn--primary" onClick={() => navigate("/upload")}>
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

        <PageHeader
          icon={<IconShieldSearch />}
          title="Data Audit"
          subtitle="The data audit agent has reviewed your tabular uploads below. Resolve any outstanding questions before continuing."
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
                      onFileCorrected={(file) => onReuploadSensiwatch(file)}
                      onProceed={advanceSensiwatchToStandard}
                      uploading={reuploadingSensiwatch}
                      uploadError={reuploadError}
                    />
                  ) : wizardActiveTab === "summary" ? (
                    report && <AuditSummaryPanel report={report} />
                  ) : (
                    <>
                      {auditLoading[id] && (
                        <div className="audit-page__audit-loading">Data audit agent is reviewing this file…</div>
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
                    <div className="audit-page__audit-loading">Data audit agent is reviewing this file…</div>
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

        <div className="audit-page__actions">
          <button type="button" className="audit-page__btn audit-page__btn--secondary" onClick={() => navigate("/upload")}>
            Back to Upload
          </button>
          <button
            type="button"
            className="audit-page__btn audit-page__btn--primary"
            disabled={!canContinue}
            onClick={() => navigate("/features")}
          >
            Continue to Features
          </button>
        </div>

        {!canContinue && !anyLoading && (
          <p className="audit-page__hint">Resolve the outstanding data audit questions above before continuing.</p>
        )}
      </main>
    </div>
  );
}
