import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import AnalysisCard from "../components/AnalysisCard";
import AnalysisDetailModal from "../components/AnalysisDetailModal";
import Modal from "../components/Modal";
import AnalysisSuggestionCard from "../components/AnalysisSuggestionCard";
import AddAnalysisForm from "../components/AddAnalysisForm";
import type { NewCustomAnalysis } from "../components/AddAnalysisForm";
import OverallAnalysisCard from "../components/OverallAnalysisCard";
import { IconDoc, IconGrid, IconSparkle, IconChevronLeft, IconChevronRight, IconBarChart, IconLayers } from "../components/icons";
import {
  acceptAnalysisEntry,
  addCustomAnalysis,
  fetchAnalysisRepository,
  fetchFeatureReport,
  fetchOverallAnalysis,
  runAnalysisEntry,
  suggestAnalysisEntries,
  triggerDrilldown,
  uploadAnalysisDefinitions,
  AuditApiError,
  type AnalysisRepositoryEntry,
  type FeatureReport,
  type OverallAnalysisReport,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./AnalysisPage.css";

interface AnalysisPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type FeatureReportsState = Partial<Record<UploadSlotId, FeatureReport>>;
type RepositoryState = Partial<Record<UploadSlotId, AnalysisRepositoryEntry[]>>;
type OverallReportsState = Partial<Record<UploadSlotId, OverallAnalysisReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

const SOURCE_GROUP_LABELS: { source: AnalysisRepositoryEntry["source"]; label: string }[] = [
  { source: "predefined", label: "Predefined (Analysis Profile)" },
  { source: "planner", label: "Planner-Approved" },
  { source: "ai_suggested", label: "AI Suggested" },
  { source: "custom", label: "User Added" },
];

export default function AnalysisPage({ files, auditReports }: AnalysisPageProps) {
  const navigate = useNavigate();

  const [featureReports, setFeatureReports] = useState<FeatureReportsState>({});
  const [featureCheckLoading, setFeatureCheckLoading] = useState<LoadingState>({});
  const [featureCheckFailed, setFeatureCheckFailed] = useState<LoadingState>({});

  const [repositories, setRepositories] = useState<RepositoryState>({});
  const [repoLoading, setRepoLoading] = useState<LoadingState>({});
  const [repoError, setRepoError] = useState<ErrorsState>({});

  const [runningIds, setRunningIds] = useState<Record<string, boolean>>({});
  const [suggestLoading, setSuggestLoading] = useState<LoadingState>({});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useState<BusyIdState>({});
  const [showAddForm, setShowAddForm] = useState<LoadingState>({});
  const [addingAnalysis, setAddingAnalysis] = useState<LoadingState>({});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});
  const [triggeringDrilldownId, setTriggeringDrilldownId] = useState<string | null>(null);

  const [overallReports, setOverallReports] = useState<OverallReportsState>({});
  const [overallLoading, setOverallLoading] = useState<LoadingState>({});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [openEntry, setOpenEntry] = useState<{ slotId: UploadSlotId; entryId: string } | null>(null);

  const [defsError, setDefsError] = useState<string | null>(null);
  const [defsLoading, setDefsLoading] = useState(false);
  // True once we've either attempted the Analysis Profile upload (success or
  // failure) or confirmed there isn't one -- gates the first repository fetch
  // so predefined analyses are included when available, without ever
  // requiring the file to exist.
  const [defsAttempted, setDefsAttempted] = useState(false);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasAnalysisProfileFile = !!files.analysisProfile;

  // Step 0: confirm feature engineering has actually run for each audited
  // slot -- an analysis can group by engineered columns, so it needs that
  // step done first.
  useEffect(() => {
    for (const id of auditedReady) {
      if (featureReports[id] || featureCheckLoading[id] || featureCheckFailed[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setFeatureCheckLoading((prev) => ({ ...prev, [id]: true }));
      fetchFeatureReport(sessionId)
        .then((report) => setFeatureReports((prev) => ({ ...prev, [id]: report })))
        .catch(() => setFeatureCheckFailed((prev) => ({ ...prev, [id]: true })))
        .finally(() => setFeatureCheckLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  const slotsReady = auditedReady.filter((id) => (featureReports[id]?.features.length ?? 0) > 0);

  // Step 1 (optional): if an Analysis Profile was uploaded, parse it so its
  // analyses can join the repository as "predefined" entries. Not required --
  // planner-approved, custom, and AI-suggested analyses work with or without
  // this file.
  useEffect(() => {
    if (defsAttempted || defsLoading) return;
    if (!hasAnalysisProfileFile) {
      setDefsAttempted(true);
      return;
    }
    setDefsLoading(true);
    uploadAnalysisDefinitions(files.analysisProfile!)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Analysis Profile."))
      .finally(() => {
        setDefsLoading(false);
        setDefsAttempted(true);
      });
  }, [hasAnalysisProfileFile, files.analysisProfile, defsAttempted, defsLoading]);

  const refreshRepository = (id: UploadSlotId, sessionId: string) =>
    fetchAnalysisRepository(sessionId).then((repo) => setRepositories((prev) => ({ ...prev, [id]: repo.entries })));

  // Step 2: once the Analysis Profile upload has settled (or there wasn't
  // one), load the repository for each ready slot -- no auto-run: each entry
  // is computed on demand when the PM clicks "Run", since a run can be up to
  // six LLM calls.
  useEffect(() => {
    if (!defsAttempted) return;
    for (const id of slotsReady) {
      if (repositories[id] || repoLoading[id] || repoError[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setRepoLoading((prev) => ({ ...prev, [id]: true }));
      refreshRepository(id, sessionId)
        .catch((err) =>
          setRepoError((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not load the analysis repository.",
          }))
        )
        .finally(() => setRepoLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsAttempted, slotsReady, auditReports]);

  const updateEntry = (id: UploadSlotId, updated: AnalysisRepositoryEntry) => {
    setRepositories((prev) => ({
      ...prev,
      [id]: (prev[id] ?? []).map((e) => (e.id === updated.id ? updated : e)),
    }));
  };

  const runEntry = (id: UploadSlotId, entry: AnalysisRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setRunningIds((prev) => ({ ...prev, [entry.id]: true }));
    runAnalysisEntry(sessionId, entry.id)
      .then((updated) => updateEntry(id, updated))
      .catch((err) =>
        setRepoError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not run that analysis.",
        }))
      )
      .finally(() => setRunningIds((prev) => ({ ...prev, [entry.id]: false })));
  };

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestAnalysisEntries(sessionId)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  const acceptSuggestion = (id: UploadSlotId, entry: AnalysisRepositoryEntry) => {
    const sessionId = auditReports[id]!.session_id;
    setApplyingEntryId((prev) => ({ ...prev, [id]: entry.id }));
    acceptAnalysisEntry(sessionId, entry.id)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setRepoError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that analysis.",
        }))
      )
      .finally(() => setApplyingEntryId((prev) => ({ ...prev, [id]: undefined })));
  };

  const addAnalysis = (id: UploadSlotId, analysis: NewCustomAnalysis) => {
    const sessionId = auditReports[id]!.session_id;
    setAddingAnalysis((prev) => ({ ...prev, [id]: true }));
    addCustomAnalysis(sessionId, analysis)
      .then(() => refreshRepository(id, sessionId))
      .then(() => setShowAddForm((prev) => ({ ...prev, [id]: false })))
      .catch((err) =>
        setRepoError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that analysis.",
        }))
      )
      .finally(() => setAddingAnalysis((prev) => ({ ...prev, [id]: false })));
  };

  const handleTriggerDrilldown = (id: UploadSlotId, entryId: string, drilldownId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setTriggeringDrilldownId(drilldownId);
    triggerDrilldown(sessionId, entryId, drilldownId)
      .then((child) => refreshRepository(id, sessionId).then(() => setOpenEntry({ slotId: id, entryId: child.id })))
      .catch((err) =>
        setRepoError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not run that drilldown.",
        }))
      )
      .finally(() => setTriggeringDrilldownId(null));
  };

  const runOverallAnalysis = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setOverallLoading((prev) => ({ ...prev, [id]: true }));
    setOverallError((prev) => ({ ...prev, [id]: undefined }));
    fetchOverallAnalysis(sessionId)
      .then((report) => setOverallReports((prev) => ({ ...prev, [id]: report })))
      .catch((err) =>
        setOverallError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the analysis agent.",
        }))
      )
      .finally(() => setOverallLoading((prev) => ({ ...prev, [id]: false })));
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="analysis-page">
        <Header subtitle="Analysis" />
        <main className="analysis-page__main">
          <StepIndicator current={5} />
          <div className="analysis-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (auditedReady.length === 0) {
    return (
      <div className="analysis-page">
        <Header subtitle="Analysis" />
        <main className="analysis-page__main">
          <StepIndicator current={5} />
          <div className="analysis-page__empty">
            <p>Finish resolving the data audit before analysis can run.</p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (slotsReady.length === 0) {
    return (
      <div className="analysis-page">
        <Header subtitle="Analysis" />
        <main className="analysis-page__main">
          <StepIndicator current={5} />
          <div className="analysis-page__empty">
            <p>
              {Object.values(featureCheckLoading).some(Boolean)
                ? "Checking whether feature engineering has run…"
                : "No features have been computed yet -- an analysis can group by engineered columns (like Country of Origin or % In Spec), so finish the Features step first."}
            </p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/features")}>
              Go to Features
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="analysis-page">
      <Header subtitle="Analysis" />
      <main className="analysis-page__main">
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconBarChart />}
          title="Analysis"
          subtitle="The Analysis Agent drafts a formula, writes the code, picks a chart, and interprets the result for each analysis below -- predefined, planner-approved, custom, and AI-suggested -- one click at a time."
        />

        {defsLoading && <div className="analysis-page__loading">Reading analysis definitions from {files.analysisProfile!.name}…</div>}
        {defsError && <p className="analysis-page__error">{defsError}</p>}
        {!hasAnalysisProfileFile && (
          <p className="analysis-page__hint">
            No Analysis Profile uploaded -- predefined analyses are skipped, but planner-approved, custom,
            and AI-suggested analyses below still work.
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const repo = repositories[id] ?? [];
          const featureColumns = featureReports[id]?.columns ?? [];
          const pendingSuggestions = repo.filter((e) => e.source === "ai_suggested" && e.status === "pending");
          const visibleEntries = repo.filter((e) => e.status === "approved");
          const topLevelEntries = visibleEntries.filter((e) => !e.parent_id);
          const drilldownEntries = visibleEntries.filter((e) => e.parent_id);
          const nameById = Object.fromEntries(repo.map((e) => [e.id, e.name]));

          const panelsSection = (
            <div className="analysis-page__panels-grid">
              <div className="analysis-page__ai-panel">
                <div className="analysis-page__ai-panel-head">
                  <div className="analysis-page__panel-head-text">
                    <span className="analysis-page__panel-icon analysis-page__panel-icon--purple">
                      <IconSparkle />
                    </span>
                    <div>
                      <h3 className="analysis-page__ai-panel-title">AI Analysis Suggestions</h3>
                      <p className="analysis-page__ai-panel-hint">
                        The agent looks at this data's columns (including engineered ones) and proposes
                        analyses it can compute -- you choose which ones to add.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--primary analysis-page__panel-btn"
                  disabled={suggestLoading[id]}
                  onClick={() => {
                    if (pendingSuggestions.length === 0) runSuggest(id);
                    setShowSuggestionsModal((prev) => ({ ...prev, [id]: true }));
                  }}
                >
                  <IconSparkle />{" "}
                  {suggestLoading[id]
                    ? "Thinking…"
                    : pendingSuggestions.length > 0
                      ? `View Suggestions (${pendingSuggestions.length})`
                      : "Suggest Analyses"}
                </button>

                {suggestError[id] && <p className="analysis-page__error">{suggestError[id]}</p>}

                {showSuggestionsModal[id] && (
                  <Modal
                    title="AI Analysis Suggestions"
                    onClose={() => setShowSuggestionsModal((prev) => ({ ...prev, [id]: false }))}
                    headerExtra={
                      <button
                        type="button"
                        className="analysis-page__btn analysis-page__btn--secondary"
                        disabled={suggestLoading[id]}
                        onClick={() => runSuggest(id)}
                      >
                        {suggestLoading[id] ? "Thinking…" : "Suggest More"}
                      </button>
                    }
                  >
                    {pendingSuggestions.length === 0 ? (
                      <p className="analysis-page__ai-panel-hint">No suggestions yet.</p>
                    ) : (
                      <div className="analysis-page__ai-grid">
                        {pendingSuggestions.map((entry) => (
                          <AnalysisSuggestionCard
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

              <div className="analysis-page__custom-pivot">
                <div className="analysis-page__custom-pivot-head">
                  <div className="analysis-page__panel-head-text">
                    <span className="analysis-page__panel-icon analysis-page__panel-icon--blue">
                      <IconGrid />
                    </span>
                    <div>
                      <h3 className="analysis-page__custom-pivot-title">Add a Custom Analysis</h3>
                      <p className="analysis-page__custom-pivot-hint">
                        Describe what you want to see straight from this data's columns -- no need to edit
                        and re-upload the Analysis Profile file.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--secondary analysis-page__panel-btn"
                  onClick={() => setShowAddForm((prev) => ({ ...prev, [id]: true }))}
                >
                  + Add Custom Analysis
                </button>
                {showAddForm[id] && (
                  <Modal title="Add a Custom Analysis" onClose={() => setShowAddForm((prev) => ({ ...prev, [id]: false }))}>
                    <AddAnalysisForm
                      columns={featureColumns}
                      busy={!!addingAnalysis[id]}
                      onAdd={(analysis) => addAnalysis(id, analysis)}
                      onCancel={() => setShowAddForm((prev) => ({ ...prev, [id]: false }))}
                    />
                  </Modal>
                )}
              </div>
            </div>
          );

          return (
            <section className="analysis-page__card" key={id}>
              <div className="analysis-page__card-head">
                <div className="analysis-page__card-head-left">
                  <h2 className="analysis-page__slot-title">{slot.title}</h2>
                  <span className="analysis-page__pill">ANALYSIS REPOSITORY</span>
                </div>
                <span className="analysis-page__filename">{files[id]!.name}</span>
              </div>

              {repoLoading[id] && <div className="analysis-page__loading">Loading the analysis repository…</div>}
              {repoError[id] && <p className="analysis-page__error">{repoError[id]}</p>}

              <div className="analysis-page__stat-row">
                <StatTile icon={<IconDoc />} color="blue" value={(featureReports[id]?.row_count ?? 0).toLocaleString()} label="Rows" />
                <StatTile icon={<IconGrid />} color="teal" value={featureReports[id]?.column_count ?? 0} label="Columns" />
                <StatTile icon={<IconLayers />} color="purple" value={topLevelEntries.length} label="Analyses" />
                {drilldownEntries.length > 0 && <StatTile icon={<IconSparkle />} color="amber" value={drilldownEntries.length} label="Drilldowns" />}
              </div>

              {topLevelEntries.length > 0 && (
                <div className="analysis-page__summary">
                  <p className="analysis-page__summary-title">
                    {topLevelEntries.length} {topLevelEntries.length === 1 ? "analysis" : "analyses"} in this session's repository
                  </p>
                  {SOURCE_GROUP_LABELS.map(({ source, label }) => ({
                    label,
                    items: topLevelEntries.filter((e) => e.source === source),
                  }))
                    .filter((group) => group.items.length > 0)
                    .map((group) => (
                      <div className="analysis-page__summary-group" key={group.label}>
                        <span className="analysis-page__summary-group-label">{group.label}</span>
                        <ul className="analysis-page__summary-list">
                          {group.items.map((e) => (
                            <li key={e.id}>
                              <button
                                type="button"
                                className="analysis-page__summary-item"
                                onClick={() => setOpenEntry({ slotId: id, entryId: e.id })}
                              >
                                <span className="analysis-page__summary-name">{e.name}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                </div>
              )}

              {topLevelEntries.length === 0 ? (
                <p className="analysis-page__none">
                  No analyses in this session's repository yet -- upload an Analysis Profile, wait for
                  planner-approved analyses, or add a custom/AI-suggested one below.
                </p>
              ) : (
                <>
                  <h3 className="analysis-page__section-title">
                    <IconLayers /> Analyses
                  </h3>
                  <div className="analysis-page__grid">
                    {topLevelEntries.map((entry) => (
                      <AnalysisCard
                        key={entry.id}
                        entry={entry}
                        running={!!runningIds[entry.id]}
                        onRun={() => runEntry(id, entry)}
                        onExpand={() => setOpenEntry({ slotId: id, entryId: entry.id })}
                      />
                    ))}
                  </div>
                </>
              )}

              {drilldownEntries.length > 0 && (
                <>
                  <h3 className="analysis-page__section-title analysis-page__section-title--drilldowns">
                    <IconSparkle /> Drilldowns
                  </h3>
                  <div className="analysis-page__grid">
                    {drilldownEntries.map((entry) => (
                      <div key={entry.id}>
                        <span className="analysis-page__drilldown-origin">↳ from {nameById[entry.parent_id ?? ""] ?? "an analysis"}</span>
                        <AnalysisCard
                          entry={entry}
                          running={!!runningIds[entry.id]}
                          onRun={() => runEntry(id, entry)}
                          onExpand={() => setOpenEntry({ slotId: id, entryId: entry.id })}
                        />
                      </div>
                    ))}
                  </div>
                </>
              )}

              <OverallAnalysisCard
                report={overallReports[id]}
                loading={!!overallLoading[id]}
                error={overallError[id]}
                onRefresh={() => runOverallAnalysis(id)}
              />

              {panelsSection}
            </section>
          );
        })}

        <div className="analysis-page__actions">
          <button type="button" className="analysis-page__btn analysis-page__btn--secondary analysis-page__nav-btn" onClick={() => navigate("/features")}>
            <IconChevronLeft /> Back to Features
          </button>
          <button type="button" className="analysis-page__btn analysis-page__btn--primary analysis-page__nav-btn" onClick={() => navigate("/report")}>
            Continue to Report <IconChevronRight />
          </button>
        </div>
      </main>

      {openEntry &&
        (() => {
          const openEntryData = repositories[openEntry.slotId]?.find((e) => e.id === openEntry.entryId);
          if (!openEntryData) return null;
          return (
            <AnalysisDetailModal
              entry={openEntryData}
              triggeringDrilldownId={triggeringDrilldownId}
              onClose={() => setOpenEntry(null)}
              onTriggerDrilldown={(drilldownId) => handleTriggerDrilldown(openEntry.slotId, openEntry.entryId, drilldownId)}
              onOpenChild={(childEntryId) => setOpenEntry({ slotId: openEntry.slotId, entryId: childEntryId })}
            />
          );
        })()}
    </div>
  );
}
