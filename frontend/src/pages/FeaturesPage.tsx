import ThinkingLoader, { Spinner } from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useState } from "react";
import { useStoredState } from "../state/sessionStore";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import PageNav from "../components/PageNav";
import StatTile from "../components/StatTile";
import FeatureCard from "../components/FeatureCard";
import FeatureDetailModal from "../components/FeatureDetailModal";
import Modal from "../components/Modal";
import FeatureSuggestionCard from "../components/FeatureSuggestionCard";
import AddKpiForm from "../components/AddKpiForm";
import DataPreviewTable from "../components/DataPreviewTable";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconShieldCheck, IconDownload, IconClipboard } from "../components/icons";
import {
  acceptFeatureEntry,
  addCustomFeature,
  applyFeatures,
  draftCustomFeature,
  downloadCleansedFileUrl,
  fetchFeatureRepository,
  fetchPreview,
  suggestFeatureEntries,
  uploadFeatureDefinitions,
  AuditApiError,
  type DataPreview,
  type FeatureReport,
  type AddCustomFeatureBody,
  type FeatureRepositoryEntry,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./FeaturesPage.css";

interface FeaturesPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type FeatureReportsState = Partial<Record<UploadSlotId, FeatureReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type PreviewsState = Partial<Record<UploadSlotId, DataPreview>>;
type PreviewOpenState = Partial<Record<UploadSlotId, boolean>>;
type RepositoryState = Partial<Record<UploadSlotId, FeatureRepositoryEntry[]>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

const SOURCE_GROUP_LABELS: { source: FeatureRepositoryEntry["source"]; label: string }[] = [
  { source: "predefined", label: "Predefined (Customer KPI Profile)" },
  { source: "planner", label: "Planner-Approved" },
  { source: "ai_suggested", label: "AI Suggested" },
  { source: "custom", label: "User Added" },
];

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const [reports, setReports] = useStoredState<FeatureReportsState>("features.reports", {});
  const [loading, setLoading] = useStoredState<LoadingState>("features.loading", {});
  // Errors stay page-local on purpose: a failed compute is retried on the next visit.
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useStoredState<PreviewsState>("features.previews", {});
  const [previewOpen, setPreviewOpen] = useStoredState<PreviewOpenState>("features.previewOpen", {});

  const [repositories, setRepositories] = useStoredState<RepositoryState>("features.repositories", {});
  const [suggestLoading, setSuggestLoading] = useStoredState<LoadingState>("features.suggestLoading", {});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useStoredState<BusyIdState>("features.applyingEntryId", {});
  const [showAddKpiForm, setShowAddKpiForm] = useState<LoadingState>({});
  const [addingKpi, setAddingKpi] = useStoredState<LoadingState>("features.addingKpi", {});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});

  const [defsError, setDefsError] = useStoredState<string | null>("features.defsError", null);
  const [defsLoading, setDefsLoading] = useStoredState("features.defsLoading", false);
  // True once we've either attempted the Customer KPI Profile upload (success
  // or failure) or confirmed there isn't one -- gates the first compute so
  // predefined features are included when they're available, without ever
  // requiring the file to exist.
  const [defsAttempted, setDefsAttempted] = useStoredState("features.defsAttempted", false);

  const [openFeature, setOpenFeature] = useState<{ slotId: UploadSlotId; featureId: string } | null>(null);

  const slotsReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasKpiFile = !!files.customerKpis;

  // Step 1 (optional): if a Customer KPI Profile was uploaded, parse it so
  // its features can join the repository as "predefined" entries. Not
  // required -- planner-approved, custom, and AI-suggested features work
  // with or without this file.
  useEffect(() => {
    if (defsAttempted || defsLoading) return;
    if (!hasKpiFile) {
      setDefsAttempted(true);
      return;
    }
    setDefsLoading(true);
    uploadFeatureDefinitions(files.customerKpis!)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Customer KPI Profile."))
      .finally(() => {
        setDefsLoading(false);
        setDefsAttempted(true);
      });
  }, [hasKpiFile, files.customerKpis, defsAttempted, defsLoading]);

  const refreshRepository = (id: UploadSlotId, sessionId: string) =>
    fetchFeatureRepository(sessionId).then((repo) => setRepositories((prev) => ({ ...prev, [id]: repo.entries })));

  const computeAndRefresh = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setLoading((prev) => ({ ...prev, [id]: true }));
    setErrors((prev) => ({ ...prev, [id]: undefined }));
    return applyFeatures(sessionId)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not compute features.",
        }))
      )
      .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Step 2: once the KPI Profile upload has settled (or there wasn't one),
  // compute features for each audited slot -- predefined contributes zero
  // entries if no file was uploaded, planner/custom/AI-suggested work regardless.
  useEffect(() => {
    if (!defsAttempted) return;
    for (const id of slotsReady) {
      if (reports[id] || loading[id] || errors[id]) continue;
      computeAndRefresh(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsAttempted, files, auditReports]);

  const togglePreview = (id: UploadSlotId) => {
    const willOpen = !previewOpen[id];
    setPreviewOpen((prev) => ({ ...prev, [id]: willOpen }));
    if (willOpen && !previews[id]) {
      const sessionId = auditReports[id]!.session_id;
      fetchPreview(sessionId, 30).then((preview) => setPreviews((prev) => ({ ...prev, [id]: preview })));
    }
  };

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestFeatureEntries(sessionId)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  const acceptSuggestion = (id: UploadSlotId, entry: FeatureRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setApplyingEntryId((prev) => ({ ...prev, [id]: entry.id }));
    acceptFeatureEntry(sessionId, entry.id)
      .then(() => computeAndRefresh(id))
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that feature.",
        }))
      )
      .finally(() => setApplyingEntryId((prev) => ({ ...prev, [id]: undefined })));
  };

  // Rejects on failure so the Add KPI form (a modal) can show the error
  // itself -- the page-level error line is hidden behind the modal.
  const addCustomKpi = (id: UploadSlotId, kpi: AddCustomFeatureBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setAddingKpi((prev) => ({ ...prev, [id]: true }));
    return addCustomFeature(sessionId, kpi)
      .then(() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false })))
      .then(() => computeAndRefresh(id))
      .finally(() => setAddingKpi((prev) => ({ ...prev, [id]: false })));
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="features-page">
        <Header subtitle="Feature Engineering" />
        <main className="features-page__main">
          <StepIndicator current={4} />
          <div className="features-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="btn btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (slotsReady.length === 0) {
    return (
      <div className="features-page">
        <Header subtitle="Feature Engineering" />
        <main className="features-page__main">
          <StepIndicator current={4} />
          <div className="features-page__empty">
            <p>Finish resolving the data audit before features can be computed.</p>
            <button type="button" className="btn btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="features-page">
      <Header subtitle="Feature Engineering" />
      <main className="features-page__main">
        <StepIndicator current={4} />

        <PageNav position="top" onBack={() => navigate("/audit")}>
          <button type="button" className="btn btn--primary" onClick={() => navigate("/analysis")}>
            Proceed to Analysis
          </button>
        </PageNav>

        <PageHeader
          icon={<IconShieldCheck />}
          title="Feature Engineering"
          subtitle="The Feature Agent computes every approved feature below (predefined, planner-approved, custom, and AI-suggested) by planning, writing, and validating pandas code for each one."
        />

        {defsLoading && <ThinkingLoader variant="inline" messages={[`Reading ${files.customerKpis!.name}…`]} />}
        {defsError && <p className="features-page__error">{defsError}</p>}
        {!hasKpiFile && (
          <p className="features-page__hint">
            No Customer KPI Profile uploaded. Predefined features are skipped, but planner-approved,
            custom, and AI-suggested features below still work.
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const preview = previews[id];
          const repo = repositories[id] ?? [];
          const pendingSuggestions = repo.filter((e) => e.source === "ai_suggested" && e.status === "pending");
          // Analyses that need each feature (by feature id) -> "Required for analysis" tag.
          const requiredFor = (featureId: string): string[] => repo.find((e) => e.id === featureId)?.required_for_analysis ?? [];

          const panelsSection = report && (
            <div className="features-page__panels-grid">
              <div className="features-page__ai-panel">
                <div className="features-page__ai-panel-head">
                  <div className="features-page__panel-head-text">
                    <span className="features-page__panel-icon features-page__panel-icon--purple">
                      <IconSparkle />
                    </span>
                    <div>
                      <h3 className="features-page__ai-panel-title">AI Feature Suggestions</h3>
                      <p className="features-page__ai-panel-hint">
                        The agent looks at this data's column names and proposes new fields it can
                        compute. You choose which ones to add.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn--ai features-page__panel-btn"
                  disabled={suggestLoading[id]}
                  onClick={() => {
                    if (pendingSuggestions.length === 0) runSuggest(id);
                    setShowSuggestionsModal((prev) => ({ ...prev, [id]: true }));
                  }}
                >
                  <IconSparkle />{" "}
                  {suggestLoading[id]
                    ? <><Spinner />Thinking…</>
                    : pendingSuggestions.length > 0
                      ? `View Suggestions (${pendingSuggestions.length})`
                      : "Suggest Features"}
                </button>

                {suggestError[id] && <p className="features-page__error">{suggestError[id]}</p>}

                {showSuggestionsModal[id] && (
                  <Modal
                    title="AI Feature Suggestions"
                    onClose={() => setShowSuggestionsModal((prev) => ({ ...prev, [id]: false }))}
                    headerExtra={
                      <button
                        type="button"
                        className="btn btn--secondary"
                        disabled={suggestLoading[id]}
                        onClick={() => runSuggest(id)}
                      >
                        {suggestLoading[id] ? <><Spinner />Thinking…</> : "Suggest More"}
                      </button>
                    }
                  >
                    {pendingSuggestions.length === 0 ? (
                      <p className="features-page__ai-panel-hint">No suggestions yet.</p>
                    ) : (
                      <div className="features-page__ai-grid">
                        {pendingSuggestions.map((entry) => (
                          <FeatureSuggestionCard
                            key={entry.id}
                            suggestion={entry}
                            added={false}
                            busy={applyingEntryId[id] === entry.id}
                            onAdd={() => acceptSuggestion(id, entry)}
                          />
                        ))}
                      </div>
                    )}
                  </Modal>
                )}
              </div>

              <div className="features-page__custom-kpi">
                <div className="features-page__custom-kpi-head">
                  <div className="features-page__panel-head-text">
                    <span className="features-page__panel-icon features-page__panel-icon--blue">
                      <IconClipboard />
                    </span>
                    <div>
                      <h3 className="features-page__custom-kpi-title">Add a Custom KPI</h3>
                      <p className="features-page__custom-kpi-hint">
                        Define your own feature straight from this data's columns, with no need to edit and
                        re-upload the Customer KPI Profile file.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn--secondary features-page__panel-btn"
                  onClick={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: true }))}
                >
                  + Add Custom KPI
                </button>
                {showAddKpiForm[id] && (
                  <Modal title="Add a Custom KPI" onClose={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}>
                    <AddKpiForm
                      columns={report.columns}
                      busy={!!addingKpi[id]}
                      onDraft={(request) => draftCustomFeature(auditReports[id]!.session_id, request)}
                      onAdd={(kpi) => addCustomKpi(id, kpi)}
                      onCancel={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}
                    />
                  </Modal>
                )}
              </div>
            </div>
          );

          return (
            <section className="features-page__card" key={id}>
              <div className="features-page__card-head">
                <div className="features-page__card-head-left">
                  <h2 className="features-page__slot-title">{slot.title}</h2>
                  <span className="features-page__pill">FEATURE REPORT</span>
                  {report && <span className="features-page__status-pill">Computed</span>}
                </div>
                <span className="features-page__filename">{files[id]!.name}</span>
              </div>

              {loading[id] && <ThinkingLoader messages={LOADING.features} hint="The Feature Agent plans and calculates each new column." intervalMs={3500} showElapsed />}
              {errors[id] && <p className="features-page__error">{errors[id]}</p>}

              {report && (
                <>
                  <div className="features-page__stat-row">
                    <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                    <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
                    <StatTile icon={<IconSparkle />} color="purple" value={report.features.length} label="Features Added" />
                    {report.skipped_notes.length > 0 && (
                      <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                    )}
                  </div>

                  {report.features.length > 0 && (
                    <div className="features-page__summary">
                      <p className="features-page__summary-title">
                        {report.features.length} feature{report.features.length === 1 ? "" : "s"} added in total
                      </p>
                      {SOURCE_GROUP_LABELS.map(({ source, label }) => ({
                        label,
                        items: report.features.filter((f) => f.source === source),
                      }))
                        .filter((group) => group.items.length > 0)
                        .map((group) => (
                          <div className="features-page__summary-group" key={group.label}>
                            <span className="features-page__summary-group-label">{group.label}</span>
                            <ul className="features-page__summary-list">
                              {group.items.map((f) => (
                                <li key={f.id}>
                                  <button
                                    type="button"
                                    className="features-page__summary-item"
                                    onClick={() => setOpenFeature({ slotId: id, featureId: f.id })}
                                  >
                                    <span className="features-page__summary-name">{f.name}</span>
                                    <code className="features-page__summary-col">{f.output_column}</code>
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                    </div>
                  )}

                  {report.features.length === 0 ? (
                    <p className="features-page__none">
                      No features computed yet for this data. Upload a Customer KPI Profile, wait for
                      planner-approved features, or add a custom/AI-suggested one below.
                    </p>
                  ) : (
                    <>
                      <h3 className="features-page__section-title">
                        <IconSparkle /> Computed Features
                      </h3>
                      <div className="features-page__grid">
                        {report.features.map((f, idx) => (
                          <FeatureCard
                            key={f.id}
                            feature={f}
                            colorIndex={idx}
                            requiredFor={requiredFor(f.id)}
                            onExpand={() => setOpenFeature({ slotId: id, featureId: f.id })}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {report.skipped_notes.length > 0 && (
                    <ul className="features-page__skipped">
                      {report.skipped_notes.map((note, idx) => (
                        <li key={idx}>{note}</li>
                      ))}
                    </ul>
                  )}

                  {panelsSection}

                  <div className="features-page__row-actions">
                    <button type="button" className="features-page__link-btn" onClick={() => togglePreview(id)}>
                      {previewOpen[id] ? "Hide" : "View"} audited + engineered data ({report.row_count.toLocaleString()} rows, {report.column_count} columns)
                    </button>
                    <a className="features-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                      <IconDownload />
                      Download engineered file
                    </a>
                  </div>

                  {previewOpen[id] && (preview ? <DataPreviewTable preview={preview} /> : <ThinkingLoader variant="inline" messages={LOADING.preview} />)}
                </>
              )}
            </section>
          );
        })}

        <PageNav position="bottom" onBack={() => navigate("/audit")}>
          <button type="button" className="btn btn--primary" onClick={() => navigate("/analysis")}>
            Proceed to Analysis
          </button>
        </PageNav>
      </main>

      {openFeature &&
        (() => {
          const openFeatureData = reports[openFeature.slotId]?.features.find((f) => f.id === openFeature.featureId);
          if (!openFeatureData) return null;
          return <FeatureDetailModal feature={openFeatureData} onClose={() => setOpenFeature(null)} />;
        })()}
    </div>
  );
}
