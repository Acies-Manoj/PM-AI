import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import PivotCard from "../components/PivotCard";
import PivotModal from "../components/PivotModal";
import Modal from "../components/Modal";
import PivotSuggestionCard from "../components/PivotSuggestionCard";
import AddPivotForm from "../components/AddPivotForm";
import OverallAnalysisCard from "../components/OverallAnalysisCard";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconChevronLeft, IconChevronRight, IconBarChart, IconLayers } from "../components/icons";
import {
  applyPivots,
  fetchFeatureReport,
  fetchOverallAnalysis,
  suggestPivots,
  uploadPivotDefinitions,
  AuditApiError,
  type FeatureReport,
  type OverallAnalysisReport,
  type PivotDefinitionsSummary,
  type PivotFilter,
  type PivotReport,
  type PivotSuggestion,
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
type PivotReportsState = Partial<Record<UploadSlotId, PivotReport>>;
type OverallReportsState = Partial<Record<UploadSlotId, OverallAnalysisReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type SuggestionsState = Partial<Record<UploadSlotId, PivotSuggestion[]>>;
type AcceptedState = Partial<Record<UploadSlotId, PivotSuggestion[]>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;
// slot -> pivot id -> column -> selected values (undefined column entry = "all", no filter)
type PivotFilterSelections = Record<string, string[] | undefined>;
type FilterSelectionsState = Partial<Record<UploadSlotId, Record<string, PivotFilterSelections>>>;


export default function AnalysisPage({ files, auditReports }: AnalysisPageProps) {
  const navigate = useNavigate();

  const [featureReports, setFeatureReports] = useState<FeatureReportsState>({});
  const [featureCheckLoading, setFeatureCheckLoading] = useState<LoadingState>({});
  const [featureCheckFailed, setFeatureCheckFailed] = useState<LoadingState>({});

  const [reports, setReports] = useState<PivotReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});

  const [suggestions, setSuggestions] = useState<SuggestionsState>({});
  const [suggestLoading, setSuggestLoading] = useState<LoadingState>({});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [accepted, setAccepted] = useState<AcceptedState>({});
  const [applyingSuggestionId, setApplyingSuggestionId] = useState<BusyIdState>({});
  const [applyingAll, setApplyingAll] = useState<LoadingState>({});
  const [showAddPivotForm, setShowAddPivotForm] = useState<LoadingState>({});
  const [addingPivot, setAddingPivot] = useState<LoadingState>({});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});

  const [overallReports, setOverallReports] = useState<OverallReportsState>({});
  const [overallLoading, setOverallLoading] = useState<LoadingState>({});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [filterSelections, setFilterSelections] = useState<FilterSelectionsState>({});
  const [savingFilters, setSavingFilters] = useState<Record<string, boolean>>({});
  const [openPivot, setOpenPivot] = useState<{ slotId: UploadSlotId; pivotId: string } | null>(null);

  const [defsSummary, setDefsSummary] = useState<PivotDefinitionsSummary | null>(null);
  const [defsLoading, setDefsLoading] = useState(false);
  const [defsError, setDefsError] = useState<string | null>(null);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasAnalysisProfileFile = !!files.analysisProfile;

  // Step 0: confirm feature engineering has actually run for each audited
  // slot -- pivots can reference engineered columns, so they need that step
  // done first, and this app doesn't lift FeaturesPage's report state up to
  // App, so we ask the backend directly.
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

  // Step 1: upload the Analysis Profile file itself (pivot definitions live
  // INSIDE it -- nothing is bundled/default, same pattern as Customer KPI Profile).
  useEffect(() => {
    if (!hasAnalysisProfileFile || defsSummary || defsLoading || defsError) return;
    setDefsLoading(true);
    uploadPivotDefinitions(files.analysisProfile!)
      .then(setDefsSummary)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Analysis Profile."))
      .finally(() => setDefsLoading(false));
  }, [hasAnalysisProfileFile, files.analysisProfile, defsSummary, defsLoading, defsError]);

  // Step 2: once definitions are uploaded, compute pivots for each ready slot.
  useEffect(() => {
    if (!defsSummary) return;
    for (const id of slotsReady) {
      if (reports[id] || loading[id] || errors[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      applyPivots(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not compute analysis tables.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsSummary, slotsReady, auditReports]);

  const runSuggest = (id: UploadSlotId) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestLoading((prev) => ({ ...prev, [id]: true }));
    setSuggestError((prev) => ({ ...prev, [id]: undefined }));
    suggestPivots(sessionId)
      .then((res) => setSuggestions((prev) => ({ ...prev, [id]: res.suggestions })))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Shared by both the AI suggester and the manual "Add Pivot" form.
  const addPivot = (id: UploadSlotId, pivot: PivotSuggestion): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    const nextAccepted = [...(accepted[id] ?? []), pivot];
    return applyPivots(sessionId, nextAccepted)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        setAccepted((prev) => ({ ...prev, [id]: nextAccepted }));
      })
      .catch((err) => {
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that analysis.",
        }));
        throw err;
      });
  };

  const acceptSuggestion = (id: UploadSlotId, suggestion: PivotSuggestion) => {
    setApplyingSuggestionId((prev) => ({ ...prev, [id]: suggestion.id }));
    addPivot(id, suggestion)
      .catch(() => {})
      .finally(() => setApplyingSuggestionId((prev) => ({ ...prev, [id]: undefined })));
  };

  const acceptAllSuggestions = (id: UploadSlotId) => {
    const currentAccepted = accepted[id] ?? [];
    const acceptedIds = new Set(currentAccepted.map((s) => s.id));
    const pending = (suggestions[id] ?? []).filter((s) => !acceptedIds.has(s.id));
    if (pending.length === 0) return;

    const sessionId = auditReports[id]!.session_id;
    const nextAccepted = [...currentAccepted, ...pending];
    setApplyingAll((prev) => ({ ...prev, [id]: true }));
    applyPivots(sessionId, nextAccepted)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        setAccepted((prev) => ({ ...prev, [id]: nextAccepted }));
      })
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add all analyses.",
        }))
      )
      .finally(() => setApplyingAll((prev) => ({ ...prev, [id]: false })));
  };

  const addCustomPivot = (id: UploadSlotId, pivot: PivotSuggestion) => {
    setAddingPivot((prev) => ({ ...prev, [id]: true }));
    addPivot(id, pivot)
      .then(() => setShowAddPivotForm((prev) => ({ ...prev, [id]: false })))
      .catch(() => {})
      .finally(() => setAddingPivot((prev) => ({ ...prev, [id]: false })));
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

  // Auto-generate the overall analysis as soon as pivots are computed, since
  // it's now the headline summary at the top of the page rather than
  // something the user has to remember to click for.
  useEffect(() => {
    for (const id of slotsReady) {
      if (!reports[id] || overallReports[id] || overallLoading[id] || overallError[id]) continue;
      runOverallAnalysis(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reports, slotsReady]);

  const buildPivotFiltersPayload = (slotSelections: Record<string, PivotFilterSelections>): Record<string, PivotFilter[]> => {
    const payload: Record<string, PivotFilter[]> = {};
    for (const [pivotId, columns] of Object.entries(slotSelections)) {
      const filters: PivotFilter[] = [];
      for (const [column, values] of Object.entries(columns)) {
        if (values !== undefined) filters.push({ column, op: "in", value: values });
      }
      // Always include the pivot id, even with zero filters -- the backend
      // merges pivot_filters per pivot id, so a present-but-empty entry is
      // how "this pivot's filters were cleared back to All" gets communicated;
      // omitting the key entirely would just leave its prior filters alone.
      payload[pivotId] = filters;
    }
    return payload;
  };

  // Filters are staged locally in PivotFilterBar and only committed here on
  // an explicit "Save Filters" click -- once saved, session.pivots on the
  // backend reflects this exact filter set, which is what both the Report
  // page's "N pivots" summary and the downloaded .pptx read directly, so
  // saving here is what "reflects in the report" for that pivot.
  const handleSaveFilters = (id: UploadSlotId, pivotId: string, nextPivotSelections: PivotFilterSelections) => {
    const nextSlotSelections = { ...(filterSelections[id] ?? {}), [pivotId]: nextPivotSelections };
    setFilterSelections((prev) => ({ ...prev, [id]: nextSlotSelections }));

    const sessionId = auditReports[id]!.session_id;
    setSavingFilters((prev) => ({ ...prev, [pivotId]: true }));
    applyPivots(sessionId, accepted[id] ?? [], buildPivotFiltersPayload(nextSlotSelections))
      .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not save filters.",
        }))
      )
      .finally(() => setSavingFilters((prev) => ({ ...prev, [pivotId]: false })));
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
                : "No features have been computed yet -- analysis tables can group by engineered columns (like Country of Origin or % In Spec), so finish the Features step first."}
            </p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/features")}>
              Go to Features
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (!hasAnalysisProfileFile) {
    return (
      <div className="analysis-page">
        <Header subtitle="Analysis" />
        <main className="analysis-page__main">
          <StepIndicator current={5} />
          <div className="analysis-page__empty">
            <p>
              No Analysis Profile has been uploaded. Analysis table definitions (which columns to group by,
              which metrics to aggregate) live entirely in that file -- there's no default, so nothing is
              computed until it's uploaded.
            </p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
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
          subtitle="Analysis tables and a summary rolled up from the audited + feature-engineered data, or ask the AI agent to suggest more analyses from your data's own columns."
        />

        {defsLoading && <div className="analysis-page__loading">Reading analysis definitions from {files.analysisProfile!.name}…</div>}
        {defsError && <p className="analysis-page__error">{defsError}</p>}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const featureColumns = featureReports[id]?.columns ?? [];
          const slotSuggestions = suggestions[id] ?? [];
          const slotAccepted = accepted[id] ?? [];
          const acceptedIds = new Set(slotAccepted.map((s) => s.id));
          const pendingSuggestionCount = slotSuggestions.filter((s) => !acceptedIds.has(s.id)).length;
          const aiPivotCount = report ? report.pivots.filter((p) => p.id.startsWith("ai_pivot_")).length : 0;
          const customPivotCount = report ? report.pivots.filter((p) => p.id.startsWith("custom_pivot_")).length : 0;


          const panelsSection = report && (
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
                        analysis tables it can compute -- you choose which ones to add.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--primary analysis-page__panel-btn"
                  disabled={suggestLoading[id]}
                  onClick={() => {
                    if (slotSuggestions.length === 0) runSuggest(id);
                    setShowSuggestionsModal((prev) => ({ ...prev, [id]: true }));
                  }}
                >
                  <IconSparkle />{" "}
                  {suggestLoading[id]
                    ? "Thinking…"
                    : slotSuggestions.length > 0
                      ? `View Suggestions (${slotSuggestions.length})`
                      : "Suggest Analyses"}
                </button>

                {suggestError[id] && <p className="analysis-page__error">{suggestError[id]}</p>}

                {showSuggestionsModal[id] && (
                  <Modal title="AI Analysis Suggestions" onClose={() => setShowSuggestionsModal((prev) => ({ ...prev, [id]: false }))}>
                    <div className="analysis-page__panel-btn-row">
                      {pendingSuggestionCount > 0 && (
                        <button
                          type="button"
                          className="analysis-page__btn analysis-page__btn--secondary analysis-page__panel-btn"
                          disabled={!!applyingAll[id]}
                          onClick={() => acceptAllSuggestions(id)}
                        >
                          {applyingAll[id] ? "Applying…" : `Apply All (${pendingSuggestionCount})`}
                        </button>
                      )}
                      <button
                        type="button"
                        className="analysis-page__btn analysis-page__btn--secondary analysis-page__panel-btn"
                        disabled={suggestLoading[id]}
                        onClick={() => runSuggest(id)}
                      >
                        {suggestLoading[id] ? "Thinking…" : "Suggest More"}
                      </button>
                    </div>

                    {slotSuggestions.length === 0 ? (
                      <p className="analysis-page__ai-panel-hint">No suggestions yet.</p>
                    ) : (
                      <div className="analysis-page__ai-grid">
                        {slotSuggestions.map((s) => (
                          <PivotSuggestionCard
                            key={s.id}
                            suggestion={s}
                            added={acceptedIds.has(s.id)}
                            busy={applyingSuggestionId[id] === s.id || !!applyingAll[id]}
                            onAdd={() => acceptSuggestion(id, s)}
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
                        Define your own group-by + aggregation logic straight from this data's columns --
                        no need to edit and re-upload the Analysis Profile file.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--secondary analysis-page__panel-btn"
                  onClick={() => setShowAddPivotForm((prev) => ({ ...prev, [id]: true }))}
                >
                  + Add Custom Analysis
                </button>
                {showAddPivotForm[id] && (
                  <Modal title="Add a Custom Analysis" onClose={() => setShowAddPivotForm((prev) => ({ ...prev, [id]: false }))}>
                    <AddPivotForm
                      columns={featureColumns}
                      busy={!!addingPivot[id]}
                      onAdd={(pivot) => addCustomPivot(id, pivot)}
                      onCancel={() => setShowAddPivotForm((prev) => ({ ...prev, [id]: false }))}
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
                  <span className="analysis-page__pill">ANALYSIS REPORT</span>
                  {report && <span className="analysis-page__status-pill">Computed</span>}
                </div>
                <span className="analysis-page__filename">{files[id]!.name}</span>
              </div>

              {loading[id] && <div className="analysis-page__loading">Computing analysis tables…</div>}
              {errors[id] && <p className="analysis-page__error">{errors[id]}</p>}

              {report && (
                <>
                  <div className="analysis-page__stat-row">
                    <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                    <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
                    <StatTile icon={<IconLayers />} color="purple" value={report.pivots.length} label="Analysis Tables" />
                    {aiPivotCount > 0 && <StatTile icon={<IconSparkle />} color="amber" value={aiPivotCount} label="AI Suggested" />}
                    {customPivotCount > 0 && <StatTile icon={<IconGrid />} color="blue" value={customPivotCount} label="Custom Analyses" />}
                    {report.skipped_notes.length > 0 && (
                      <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                    )}
                  </div>

                  {report.pivots.length > 0 && (
                    <div className="analysis-page__summary">
                      <p className="analysis-page__summary-title">
                        ✓ {report.pivots.length} {report.pivots.length === 1 ? "analysis" : "analyses"} added in total
                      </p>
                      {[
                        { label: "Defined", items: report.pivots.filter((p) => !p.id.startsWith("ai_pivot_") && !p.id.startsWith("custom_pivot_")) },
                        { label: "AI Suggested", items: report.pivots.filter((p) => p.id.startsWith("ai_pivot_")) },
                        { label: "User Added", items: report.pivots.filter((p) => p.id.startsWith("custom_pivot_")) },
                      ]
                        .filter((group) => group.items.length > 0)
                        .map((group) => (
                          <div className="analysis-page__summary-group" key={group.label}>
                            <span className="analysis-page__summary-group-label">{group.label}</span>
                            <ul className="analysis-page__summary-list">
                              {group.items.map((p) => (
                                <li key={p.id}>
                                  <button
                                    type="button"
                                    className="analysis-page__summary-item"
                                    onClick={() => setOpenPivot({ slotId: id, pivotId: p.id })}
                                  >
                                    <span className="analysis-page__summary-name">{p.name}</span>
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                    </div>
                  )}

                  {report.pivots.length === 0 ? (
                    <p className="analysis-page__none">None of the uploaded analysis definitions could be computed against this data.</p>
                  ) : (
                    <>
                      <h3 className="analysis-page__section-title">
                        <IconLayers /> Analysis Tables
                      </h3>
                      <div className="analysis-page__pivot-list">
                        {report.pivots.map((p, idx) => (
                          <PivotCard key={p.id} pivot={p} colorIndex={idx} onOpen={() => setOpenPivot({ slotId: id, pivotId: p.id })} />
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

                  {report.skipped_notes.length > 0 && (
                    <ul className="analysis-page__skipped">
                      {report.skipped_notes.map((note, idx) => (
                        <li key={idx}>{note}</li>
                      ))}
                    </ul>
                  )}

                  {panelsSection}
                </>
              )}
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

      {openPivot &&
        (() => {
          const openPivotData = reports[openPivot.slotId]?.pivots.find((p) => p.id === openPivot.pivotId);
          if (!openPivotData) return null;
          return (
            <PivotModal
              pivot={openPivotData}
              filterSelections={filterSelections[openPivot.slotId]?.[openPivot.pivotId] ?? {}}
              onSaveFilters={(next) => handleSaveFilters(openPivot.slotId, openPivot.pivotId, next)}
              savingFilters={!!savingFilters[openPivot.pivotId]}
              onClose={() => setOpenPivot(null)}
            />
          );
        })()}
    </div>
  );
}
