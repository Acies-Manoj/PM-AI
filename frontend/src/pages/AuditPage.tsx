import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import AuditReport from "../components/AuditReport";
import { downloadCleansedFileUrl } from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditErrorsState, AuditLoadingState, AuditReportsState, FilesState, ResolvingState } from "../App";
import "./AuditPage.css";

interface AuditPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
  auditLoading: AuditLoadingState;
  auditErrors: AuditErrorsState;
  resolvingIssueId: ResolvingState;
  onRunAudit: (id: UploadSlotId, file: File) => void;
  onResolveIssue: (id: UploadSlotId, issueId: string, decisionId: string, selectedItems?: string[]) => void;
}

export default function AuditPage({
  files,
  auditReports,
  auditLoading,
  auditErrors,
  resolvingIssueId,
  onRunAudit,
  onResolveIssue,
}: AuditPageProps) {
  const navigate = useNavigate();

  useEffect(() => {
    for (const id of AUDITED_SLOTS) {
      const file = files[id];
      if (!file) continue;
      if (auditReports[id] || auditLoading[id] || auditErrors[id]) continue;
      onRunAudit(id, file);
    }
    // Only re-scan when the selected files change -- audit state itself is
    // checked fresh above so this stays idempotent without needing it as a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  const auditedSlotsWithFiles = AUDITED_SLOTS.filter((id) => files[id]);
  const otherSlotsWithFiles = UPLOAD_SLOTS.filter((s) => !AUDITED_SLOTS.includes(s.id) && files[s.id]);
  const hasAnyFile = UPLOAD_SLOTS.some((s) => files[s.id]);

  const anyLoading = auditedSlotsWithFiles.some((id) => auditLoading[id]);
  const anyPending = auditedSlotsWithFiles.some((id) => auditReports[id]?.status === "pending_review");
  const canContinue = !!files.sensiwatch && !anyLoading && !anyPending;

  if (!hasAnyFile) {
    return (
      <div className="audit-page">
        <Header />
        <main className="audit-page__main">
          <StepIndicator current={2} />
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
      <Header />
      <main className="audit-page__main">
        <StepIndicator current={2} />

        <div className="audit-page__intro">
          <h1 className="audit-page__heading">Data Audit</h1>
          <p className="audit-page__lede">
            The data audit agent has reviewed your tabular uploads below. Resolve any outstanding
            questions before continuing.
          </p>
        </div>

        {auditedSlotsWithFiles.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = auditReports[id];
          return (
            <section className="audit-page__slot" key={id}>
              <div className="audit-page__slot-header">
                <h2 className="audit-page__slot-title">{slot.title}</h2>
                <span className="audit-page__filename">{files[id]!.name}</span>
              </div>

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
                    resolvingIssueId={resolvingIssueId[id] ?? null}
                  />
                  <a
                    className="audit-page__download-link"
                    href={downloadCleansedFileUrl(report.session_id)}
                    download
                  >
                    Download cleansed file
                  </a>
                </>
              )}
            </section>
          );
        })}

        {otherSlotsWithFiles.length > 0 && (
          <section className="audit-page__slot">
            <h2 className="audit-page__slot-title">Reference documents</h2>
            <ul className="audit-page__doc-list">
              {otherSlotsWithFiles.map((slot) => (
                <li key={slot.id} className="audit-page__doc-item">
                  <span className="audit-page__doc-name">{slot.title}</span>
                  <span className="audit-page__doc-file">{files[slot.id]!.name}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <div className="audit-page__actions">
          <button type="button" className="audit-page__btn audit-page__btn--secondary" onClick={() => navigate("/upload")}>
            Back to Upload
          </button>
          <button
            type="button"
            className="audit-page__btn audit-page__btn--primary"
            disabled={!canContinue}
            onClick={() => navigate("/screening")}
          >
            Continue to Screening
          </button>
        </div>

        {!canContinue && !anyLoading && (
          <p className="audit-page__hint">Resolve the outstanding data audit questions above before continuing.</p>
        )}
      </main>
    </div>
  );
}
