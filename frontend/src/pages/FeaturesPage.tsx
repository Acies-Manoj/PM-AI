import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import FeatureCard from "../components/FeatureCard";
import FeatureDetailModal from "../components/FeatureDetailModal";
import Modal from "../components/Modal";
import FeatureSuggestionCard from "../components/FeatureSuggestionCard";
import AddKpiForm from "../components/AddKpiForm";
import SavedDefinitionCard from "../components/SavedDefinitionCard";
import DataPreviewTable from "../components/DataPreviewTable";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconShieldCheck, IconDownload, IconClipboard, IconChevronLeft, IconChevronRight } from "../components/icons";
import {
  applyFeatures,
  deleteSavedFeature,
  downloadCleansedFileUrl,
  fetchPreview,
  fetchSavedFeatures,
  saveCustomFeature,
  setSavedFeatureScope,
  submitClientBrief,
  suggestFeatures,
  AuditApiError,
  type ClientBriefFeatureResponse,
  type DataPreview,
  type FeatureReport,
  type FeatureSuggestion,
  type PlannedAnalysisItem,
  type PlannedFeatureItem,
  type SavedFeature,
  type SavedScope,
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
type SuggestionsState = Partial<Record<UploadSlotId, FeatureSuggestion[]>>;
type AcceptedState = Partial<Record<UploadSlotId, FeatureSuggestion[]>>;
type BusyIdState = Partial<Record<UploadSlotId, string>>;

/** The one-line "what does it actually compute" summary on a saved card. */
function featureDetail(spec: FeatureSuggestion): string | undefined {
  if (spec.type === "ai_generated") return spec.calculation_prompt ?? undefined;
  return spec.formula || undefined;
}

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [reports, setReports] = useState<FeatureReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useState<PreviewsState>({});
  const [previewOpen, setPreviewOpen] = useState<PreviewOpenState>({});

  const [suggestions, setSuggestions] = useState<SuggestionsState>({});
  const [suggestLoading, setSuggestLoading] = useState<LoadingState>({});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [accepted, setAccepted] = useState<AcceptedState>({});
  const [applyingSuggestionId, setApplyingSuggestionId] = useState<BusyIdState>({});
  const [showAddKpiForm, setShowAddKpiForm] = useState<LoadingState>({});
  const [addingKpi, setAddingKpi] = useState<LoadingState>({});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});

  // Client Brief -> Feature Engineering pipeline (see feature_orchestrator.py,
  // kpi_store.py): distinct from the single free-text ask above -- a brief
  // can resolve to several features at once (explicit client asks, plus
  // whatever the AI additionally suggests), each created or reused and
  // tagged with its own source.
  const [clientBrief, setClientBrief] = useState<Partial<Record<UploadSlotId, ClientBriefFeatureResponse>>>({});
  const [clientBriefLoading, setClientBriefLoading] = useState<LoadingState>({});
  const [clientBriefError, setClientBriefError] = useState<ErrorsState>({});
  // Set once, from the Orchestrator Agent's routing response (see
  // UploadPage's "Client requirement" box) -- null on either field means
  // the brief was already English, so there's nothing to show.
  const [clientBriefLanguage, setClientBriefLanguage] = useState<
    Partial<Record<UploadSlotId, { detected: string | null; translated: string | null }>>
  >({});

  // The persistent library (see custom_library_store.py) -- not per-slot and
  // not per-session, so it's fetched once and shared across every card below.
  const [savedFeatures, setSavedFeatures] = useState<SavedFeature[]>([]);
  const [savedBusyId, setSavedBusyId] = useState<string | null>(null);
  const [savedError, setSavedError] = useState<string | null>(null);

  const [openFeature, setOpenFeature] = useState<{ slotId: UploadSlotId; featureId: string } | null>(null);

  // "Customer KPI Profile (Defined)" + "Client-Requested" checkboxes --
  // excluded ids live on the backend (report.excluded_feature_ids), this is
  // just a per-slot busy flag while a toggle round-trips.
  const [featureSelectionBusy, setFeatureSelectionBusy] = useState<LoadingState>({});

  const slotsReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  // Feature definitions (the Customer KPI Profile) are always available --
  // bundled as a default on the backend and only overridden by an explicit
  // upload -- so features can be computed as soon as a slot is audit-ready.
  useEffect(() => {
    for (const id of slotsReady) {
      if (reports[id] || loading[id] || errors[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      applyFeatures(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not compute features.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files, auditReports]);

  const refreshSavedFeatures = () =>
    fetchSavedFeatures()
      .then((res) => setSavedFeatures(res.items))
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not load your saved KPIs."));

  useEffect(() => {
    refreshSavedFeatures();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A "regular" KPI is merged into the definition set on the BACKEND, so
  // promoting, demoting or deleting one only shows up once each slot
  // recomputes -- do that here rather than leaving the page showing a
  // feature list that no longer matches the library.
  const recomputeAll = () =>
    Promise.all(
      slotsReady.map((id) =>
        applyFeatures(auditReports[id]!.session_id, accepted[id] ?? [])
          .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
          .then(() => setPreviews((prev) => ({ ...prev, [id]: undefined })))
      )
    );

  const handleToggleSavedScope = (item: SavedFeature) => {
    const next: SavedScope = item.scope === "regular" ? "suggested" : "regular";
    setSavedBusyId(item.id);
    setSavedError(null);
    setSavedFeatureScope(item.id, next)
      .then(refreshSavedFeatures)
      .then(recomputeAll)
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not change that KPI's scope."))
      .finally(() => setSavedBusyId(null));
  };

  const handleDeleteSaved = (item: SavedFeature) => {
    setSavedBusyId(item.id);
    setSavedError(null);
    deleteSavedFeature(item.id)
      .then((res) => setSavedFeatures(res.items))
      .then(recomputeAll)
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not remove that saved KPI."))
      .finally(() => setSavedBusyId(null));
  };

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
    suggestFeatures(sessionId)
      .then((res) => setSuggestions((prev) => ({ ...prev, [id]: res.suggestions })))
      .catch((err) =>
        setSuggestError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the suggestion agent.",
        }))
      )
      .finally(() => setSuggestLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Shared by both the AI suggester and the manual "Add Custom KPI" form --
  // either way it's just another entry in the same extra_features list sent
  // to the same recompute endpoint, so both paths land in the same feature
  // grid and summary. Errors are set here but re-thrown so each caller can
  // decide what to do next (e.g. the KPI form keeps itself open on failure).
  const addFeature = (id: UploadSlotId, feature: FeatureSuggestion): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    const nextAccepted = [...(accepted[id] ?? []), feature];
    return applyFeatures(sessionId, nextAccepted)
      .then((report) => {
        setReports((prev) => ({ ...prev, [id]: report }));
        setAccepted((prev) => ({ ...prev, [id]: nextAccepted }));
        setPreviews((prev) => ({ ...prev, [id]: undefined }));
      })
      .catch((err) => {
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not add that feature.",
        }));
        throw err;
      });
  };

  const acceptSuggestion = (id: UploadSlotId, suggestion: FeatureSuggestion) => {
    setApplyingSuggestionId((prev) => ({ ...prev, [id]: suggestion.id }));
    addFeature(id, suggestion)
      .catch(() => {})
      .finally(() => setApplyingSuggestionId((prev) => ({ ...prev, [id]: undefined })));
  };

  const handleClientBrief = (id: UploadSlotId, brief: string, plannedFeatures?: PlannedFeatureItem[]) => {
    const text = brief.trim();
    if (!text) return Promise.resolve();
    const sessionId = auditReports[id]!.session_id;
    setClientBriefLoading((prev) => ({ ...prev, [id]: true }));
    setClientBriefError((prev) => ({ ...prev, [id]: undefined }));
    return submitClientBrief(sessionId, text, plannedFeatures)
      .then((res) => {
        setClientBrief((prev) => ({ ...prev, [id]: res }));
        setReports((prev) => ({ ...prev, [id]: res.feature_report }));
        setPreviews((prev) => ({ ...prev, [id]: undefined }));
        // Fold in every spec the brief resolved (reused or newly created) so
        // a later recompute (adding another custom KPI, toggling a saved
        // one's scope, ...) doesn't drop them -- same list `addFeature`/
        // `acceptSuggestion` already maintain for every other entry point.
        setAccepted((prev) => {
          const current = prev[id] ?? [];
          const existingIds = new Set(current.map((s) => s.id));
          const additions = res.accepted_specs.filter((s) => !existingIds.has(s.id));
          return { ...prev, [id]: [...current, ...additions] };
        });
      })
      .catch((err) =>
        setClientBriefError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the client brief agent.",
        }))
      )
      .finally(() => setClientBriefLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Same idea as the request-prefill effect above, but for the richer
  // multi-feature pipeline -- the Orchestrator sends the ORIGINAL (cleaned)
  // brief text here, not a single reduced-down request line. Once the
  // features it explicitly asks for are created (or reused), this page
  // stays put -- the user reviews the created feature(s) here first -- and
  // hands the brief's analysis half to "Continue to Analysis" below, so it
  // still gets created there when they move on, just not before they've had
  // a chance to look at what landed on this page.
  const clientBriefFiredRef = useRef(false);
  const [pendingAnalysisHandoff, setPendingAnalysisHandoff] = useState<{
    prefill: string;
    prefillDetectedLanguage?: string | null;
    prefillTranslatedText?: string | null;
    prefillPlannedAnalyses?: PlannedAnalysisItem[];
  } | null>(null);
  useEffect(() => {
    const state = location.state as {
      prefillClientBrief?: string;
      prefillDetectedLanguage?: string | null;
      prefillTranslatedText?: string | null;
      prefillPlannedFeatures?: PlannedFeatureItem[];
      prefillPlannedAnalyses?: PlannedAnalysisItem[];
    } | null;
    const prefill = state?.prefillClientBrief;
    if (!prefill || slotsReady.length === 0 || clientBriefFiredRef.current) return;
    clientBriefFiredRef.current = true;
    const id = slotsReady[0];
    if (state?.prefillDetectedLanguage) {
      setClientBriefLanguage((prev) => ({
        ...prev,
        [id]: { detected: state.prefillDetectedLanguage ?? null, translated: state.prefillTranslatedText ?? null },
      }));
    }
    handleClientBrief(id, prefill, state?.prefillPlannedFeatures).then(() => {
      setPendingAnalysisHandoff({
        prefill,
        prefillDetectedLanguage: state?.prefillDetectedLanguage,
        prefillTranslatedText: state?.prefillTranslatedText,
        // The Planner Agent's own analysis half, carried forward --
        // AnalysisPage computes exactly this, it doesn't re-derive it.
        prefillPlannedAnalyses: state?.prefillPlannedAnalyses,
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, slotsReady]);

  // Computing it for this session and saving it to the library are two
  // separate steps on purpose: the compute is what the user asked for, so a
  // library write that fails afterwards surfaces as a warning rather than
  // throwing away a KPI that already computed fine.
  const addCustomKpi = (id: UploadSlotId, kpi: FeatureSuggestion, scope: SavedScope) => {
    setAddingKpi((prev) => ({ ...prev, [id]: true }));
    setSavedError(null);
    addFeature(id, kpi)
      .then(() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false })))
      .then(() => saveCustomFeature(kpi, scope))
      .then(refreshSavedFeatures)
      .catch((err) => {
        if (err instanceof AuditApiError && !errors[id]) {
          setSavedError(`"${kpi.name}" was added to this session, but could not be saved for next time: ${err.message}`);
        }
      })
      .finally(() => setAddingKpi((prev) => ({ ...prev, [id]: false })));
  };

  // Toggling a "Defined"/"Client-Requested" checkbox flips its id in/out of
  // the excluded set and recomputes immediately, resending accepted[id] (the
  // AI/custom/client extra_features already applied) alongside it -- unlike
  // pivots, features have no session-side persisted "extra defs" list, so
  // the frontend's own accepted[] is the only record of them.
  const toggleDefinedFeature = (id: UploadSlotId, featureId: string, currentlyExcluded: string[]) => {
    const nextExcluded = currentlyExcluded.includes(featureId)
      ? currentlyExcluded.filter((x) => x !== featureId)
      : [...currentlyExcluded, featureId];
    const sessionId = auditReports[id]!.session_id;
    setFeatureSelectionBusy((prev) => ({ ...prev, [id]: true }));
    applyFeatures(sessionId, accepted[id] ?? [], nextExcluded)
      .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not update the feature selection.",
        }))
      )
      .finally(() => setFeatureSelectionBusy((prev) => ({ ...prev, [id]: false })));
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="features-page">
        <Header subtitle="Feature Engineering" />
        <main className="features-page__main">
          <StepIndicator current={3} />
          <div className="features-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/upload")}>
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
          <StepIndicator current={3} />
          <div className="features-page__empty">
            <p>Finish resolving the data audit before features can be computed.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/audit")}>
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
        <StepIndicator current={3} />

        <PageHeader
          icon={<IconShieldCheck />}
          title="Feature Engineering"
          subtitle="Review the engineered features below, or ask the AI agent to suggest more from your data's own columns."
        />

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const preview = previews[id];
          const slotSuggestions = suggestions[id] ?? [];
          const slotAccepted = accepted[id] ?? [];
          const acceptedIds = new Set(slotAccepted.map((s) => s.id));
          const slotFormulas = Object.fromEntries(slotAccepted.map((s) => [s.id, s.formula]));
          const definedFeatures = report ? report.features.filter((f) => !f.id.startsWith("ai_") && !f.id.startsWith("custom_") && !f.id.startsWith("client_")) : [];
          const clientFeatures = report ? report.features.filter((f) => f.id.startsWith("client_")) : [];
          const aiFeatures = report ? report.features.filter((f) => f.id.startsWith("ai_")) : [];
          const userFeatures = report ? report.features.filter((f) => f.id.startsWith("custom_")) : [];
          const aiFeatureCount = aiFeatures.length;
          const customFeatureCount = userFeatures.length;
          const excludedFeatureIds = report?.excluded_feature_ids ?? [];

          const panelsSection = report && (
            <div className="features-page__panels-grid">
              <div className="features-page__ai-panel">
                <div className="features-page__ai-panel-head">
                  <div className="features-page__panel-head-text">
                    <span className="features-page__panel-icon features-page__panel-icon--purple">
                      <IconSparkle />
                    </span>
                    <div>
                      <h3 className="features-page__ai-panel-title">Suggested KPIs</h3>
                      <p className="features-page__ai-panel-hint">
                        The agent proposes KPIs from this data's own column names -- it drafts a spec (a
                        template if one fits, sandboxed Python otherwise) for you to review before adding.
                        {savedFeatures.length > 0 && ` ${savedFeatures.length} saved.`}
                      </p>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  className="features-page__btn features-page__btn--primary features-page__panel-btn"
                  disabled={suggestLoading[id]}
                  onClick={() => {
                    if (slotSuggestions.length === 0) runSuggest(id);
                    setShowSuggestionsModal((prev) => ({ ...prev, [id]: true }));
                  }}
                >
                  <IconSparkle />{" "}
                  {suggestLoading[id]
                    ? "Thinking…"
                    : slotSuggestions.length + savedFeatures.length > 0
                      ? `View Suggestions (${slotSuggestions.length + savedFeatures.length})`
                      : "Suggest Features"}
                </button>
                {suggestError[id] && <p className="features-page__error">{suggestError[id]}</p>}

                {showSuggestionsModal[id] && (
                  <Modal
                    title="Suggested KPIs"
                    onClose={() => setShowSuggestionsModal((prev) => ({ ...prev, [id]: false }))}
                    headerExtra={
                      <button
                        type="button"
                        className="features-page__btn features-page__btn--secondary"
                        disabled={suggestLoading[id]}
                        onClick={() => runSuggest(id)}
                      >
                        {suggestLoading[id] ? "Thinking…" : "Suggest More"}
                      </button>
                    }
                  >
                    {savedError && <p className="features-page__error">{savedError}</p>}

                    {savedFeatures.length > 0 && (
                      <section className="features-page__saved-section">
                        <h4 className="features-page__saved-title">Saved by you</h4>
                        <p className="features-page__ai-panel-hint">
                          KPIs you created earlier, kept between sessions. A "Regular" one is already
                          computed on every run -- the rest wait here until you add them.
                        </p>
                        <div className="features-page__ai-grid">
                          {savedFeatures.map((item) => (
                            <SavedDefinitionCard
                              key={item.id}
                              name={item.name}
                              description={item.description}
                              detail={featureDetail(item.spec)}
                              scope={item.scope}
                              added={acceptedIds.has(item.id)}
                              busy={savedBusyId === item.id || applyingSuggestionId[id] === item.id}
                              onAdd={() => acceptSuggestion(id, item.spec)}
                              onToggleScope={() => handleToggleSavedScope(item)}
                              onDelete={() => handleDeleteSaved(item)}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    <section className="features-page__saved-section">
                      <h4 className="features-page__saved-title">From the AI agent</h4>
                      {slotSuggestions.length === 0 ? (
                        <p className="features-page__ai-panel-hint">No suggestions yet.</p>
                      ) : (
                        <div className="features-page__ai-grid">
                          {slotSuggestions.map((s) => (
                            <FeatureSuggestionCard
                              key={s.id}
                              suggestion={s}
                              added={acceptedIds.has(s.id)}
                              busy={applyingSuggestionId[id] === s.id}
                              onAdd={() => acceptSuggestion(id, s)}
                            />
                          ))}
                        </div>
                      )}
                    </section>
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
                        Define your own duration, ratio, or month-extraction feature straight from this
                        data's columns -- no need to edit and re-upload the Customer KPI Profile file.
                        Whatever you create is saved to your library for next time.
                      </p>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="features-page__btn features-page__btn--secondary features-page__panel-btn"
                  onClick={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: true }))}
                >
                  + Add Custom KPI
                </button>
                {showAddKpiForm[id] && (
                  <Modal title="Add a Custom KPI" onClose={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}>
                    <AddKpiForm
                      columns={report.columns}
                      busy={!!addingKpi[id]}
                      onAdd={(kpi, scope) => addCustomKpi(id, kpi, scope)}
                      onCancel={() => setShowAddKpiForm((prev) => ({ ...prev, [id]: false }))}
                    />
                  </Modal>
                )}
              </div>
            </div>
          );

          const briefResult = clientBrief[id];
          const briefLanguage = clientBriefLanguage[id];
          const clientBriefSection = (clientBriefLoading[id] || clientBriefError[id] || briefResult) && (
            <div className="features-page__client-brief">
              <div className="features-page__panel-head-text">
                <span className="features-page__panel-icon features-page__panel-icon--purple">
                  <IconSparkle />
                </span>
                <div>
                  <h3 className="features-page__ai-panel-title">Client Brief</h3>
                  <p className="features-page__ai-panel-hint">
                    Every feature the brief explicitly asked for was created (or reused from an existing,
                    equivalent one) automatically -- the AI's own extra suggestions are marked separately below.
                  </p>
                  {briefLanguage?.detected && (
                    <details className="features-page__client-brief-language">
                      <summary>Detected language: {briefLanguage.detected} -- show translation</summary>
                      <p className="features-page__client-brief-translation">{briefLanguage.translated}</p>
                    </details>
                  )}
                </div>
              </div>

              {clientBriefLoading[id] && <div className="features-page__loading">Reading the brief, creating features…</div>}
              {clientBriefError[id] && <p className="features-page__error">{clientBriefError[id]}</p>}

              {briefResult && (
                <>
                  {[
                    { label: "Client-Requested", tag: "CLIENT_REQUESTED" as const, items: briefResult.client_requirements },
                    { label: "AI-Suggested", tag: "AI_SUGGESTED" as const, items: briefResult.ai_suggested },
                  ]
                    .filter((group) => group.items.length > 0)
                    .map((group) => (
                      <div className="features-page__client-brief-group" key={group.label}>
                        <span className="features-page__summary-group-label">{group.label}</span>
                        <ul className="features-page__client-brief-list">
                          {group.items.map((item) => {
                            const outcome = briefResult.outcomes.find((o) => o.feature_name === item.feature_name);
                            const status = outcome?.status ?? "failed";
                            return (
                              <li key={item.feature_name} className={`features-page__client-brief-item features-page__client-brief-item--${status}`}>
                                <div className="features-page__client-brief-item-head">
                                  <span className="features-page__client-brief-item-name">{item.feature_name}</span>
                                  <span className={`features-page__client-brief-status features-page__client-brief-status--${status}`}>
                                    {status === "created" ? "Created" : status === "reused" ? "Reused existing" : "Failed"}
                                  </span>
                                </div>
                                <p className="features-page__client-brief-item-desc">{item.description}</p>
                                {outcome?.status === "failed" && outcome.error && (
                                  <p className="features-page__error">{outcome.error}</p>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ))}
                </>
              )}
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

              {loading[id] && <div className="features-page__loading">Computing features…</div>}
              {errors[id] && <p className="features-page__error">{errors[id]}</p>}

              {report && (
                <>
                  <div className="features-page__stat-row">
                    <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                    <StatTile icon={<IconGrid />} color="teal" value={report.column_count} label="Columns" />
                    <StatTile icon={<IconSparkle />} color="purple" value={report.features.length} label="Features Added" />
                    {aiFeatureCount > 0 && (
                      <StatTile icon={<IconSparkle />} color="amber" value={aiFeatureCount} label="AI Suggested" />
                    )}
                    {customFeatureCount > 0 && (
                      <StatTile icon={<IconClipboard />} color="blue" value={customFeatureCount} label="Custom KPIs" />
                    )}
                    {report.skipped_notes.length > 0 && (
                      <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                    )}
                  </div>

                  {clientBriefSection}

                  {report.features.length === 0 ? (
                    <p className="features-page__none">
                      None of the uploaded feature definitions could be computed against this data.
                    </p>
                  ) : (
                    [
                      {
                        key: "defined",
                        label: "Customer KPI Profile (Defined)",
                        hint: "Uncheck one to leave it out of this session -- it stays out until you check it again.",
                        items: definedFeatures,
                        checkable: true,
                      },
                      {
                        key: "client",
                        label: "Client-Requested Features",
                        hint: "Explicitly asked for in a Client Brief -- still checkable, but created automatically regardless.",
                        items: clientFeatures,
                        checkable: true,
                      },
                      { key: "ai", label: "AI-Suggested Features", hint: "Proposed by the AI -- from a Client Brief, or from Suggest Features.", items: aiFeatures, checkable: false },
                      { key: "user", label: "User-Requested Features", hint: "Drafted by the Feature Agent from your own plain-language ask, or built with Add a Custom KPI.", items: userFeatures, checkable: false },
                    ]
                      .filter((group) => group.items.length > 0)
                      .map((group) => (
                        <div className="features-page__feature-section" key={group.key}>
                          <h3 className="features-page__section-title">
                            <IconSparkle /> {group.label} ({group.items.length})
                          </h3>
                          <p className="features-page__ai-panel-hint">{group.hint}</p>
                          <div className="features-page__grid">
                            {group.items.map((f, idx) =>
                              group.checkable ? (
                                <div className="features-page__defined-row" key={f.id}>
                                  <input
                                    type="checkbox"
                                    className="features-page__defined-checkbox"
                                    checked={!excludedFeatureIds.includes(f.id)}
                                    disabled={!!featureSelectionBusy[id]}
                                    onChange={() => toggleDefinedFeature(id, f.id, excludedFeatureIds)}
                                    aria-label={`Include ${f.name}`}
                                  />
                                  <FeatureCard
                                    feature={f}
                                    colorIndex={idx}
                                    formula={slotFormulas[f.id]}
                                    onExpand={() => setOpenFeature({ slotId: id, featureId: f.id })}
                                  />
                                </div>
                              ) : (
                                <FeatureCard
                                  key={f.id}
                                  feature={f}
                                  colorIndex={idx}
                                  formula={slotFormulas[f.id]}
                                  onExpand={() => setOpenFeature({ slotId: id, featureId: f.id })}
                                />
                              )
                            )}
                          </div>
                        </div>
                      ))
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

                  {previewOpen[id] && (preview ? <DataPreviewTable preview={preview} /> : <div className="features-page__loading">Loading preview…</div>)}
                </>
              )}
            </section>
          );
        })}

        <div className="features-page__actions">
          <button type="button" className="features-page__btn features-page__btn--secondary features-page__nav-btn" onClick={() => navigate("/audit")}>
            <IconChevronLeft /> Back to Audit
          </button>
          <button
            type="button"
            className="features-page__btn features-page__btn--primary features-page__nav-btn"
            onClick={() =>
              navigate("/analysis", pendingAnalysisHandoff ? { state: { prefillRequest: pendingAnalysisHandoff.prefill, prefillDetectedLanguage: pendingAnalysisHandoff.prefillDetectedLanguage, prefillTranslatedText: pendingAnalysisHandoff.prefillTranslatedText, prefillPlannedAnalyses: pendingAnalysisHandoff.prefillPlannedAnalyses } } : undefined)
            }
          >
            Continue to Analysis <IconChevronRight />
          </button>
        </div>
      </main>

      {openFeature &&
        (() => {
          const openFeatureData = reports[openFeature.slotId]?.features.find((f) => f.id === openFeature.featureId);
          if (!openFeatureData) return null;
          const openFeatureFormula = (accepted[openFeature.slotId] ?? []).find((s) => s.id === openFeature.featureId)?.formula;
          return <FeatureDetailModal feature={openFeatureData} formula={openFeatureFormula} onClose={() => setOpenFeature(null)} />;
        })()}
    </div>
  );
}
