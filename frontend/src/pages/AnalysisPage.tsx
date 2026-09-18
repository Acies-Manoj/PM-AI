import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import PivotCard from "../components/PivotCard";
import PivotModal from "../components/PivotModal";
import PivotTableCard from "../components/PivotTableCard";
import Modal from "../components/Modal";
import AddPivotForm from "../components/AddPivotForm";
import PivotSuggestionCard from "../components/PivotSuggestionCard";
import SavedDefinitionCard from "../components/SavedDefinitionCard";
import OverallAnalysisCard from "../components/OverallAnalysisCard";
import { IconDoc, IconGrid, IconSparkle, IconWarnTriangle, IconChevronLeft, IconChevronRight, IconBarChart, IconLayers } from "../components/icons";
import {
  applyPivots,
  deleteSavedPivot,
  fetchFeatureReport,
  fetchOverallAnalysis,
  fetchSavedPivots,
  setPivotSelection,
  setSavedPivotScope,
  submitAnalysisBrief,
  suggestPivots,
  AuditApiError,
  type AnalysisRequirement,
  type AnalysisRequirementOutcome,
  type FeatureReport,
  type FormulaAnswerResponse,
  type OverallAnalysisReport,
  type PivotFilter,
  type PlannedAnalysisItem,
  type PivotReport,
  type PivotResult,
  type PivotSuggestion,
  type SavedPivot,
  type SavedScope,
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


/** The one-line "what does it actually compute" summary on a saved card. */
function pivotDetail(spec: PivotSuggestion): string {
  return `${spec.group_by.join(" / ")} → ${spec.metrics.map((m) => m.output_label).join(", ")}`;
}

export default function AnalysisPage({ files, auditReports }: AnalysisPageProps) {
  const navigate = useNavigate();
  const location = useLocation();

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
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});

  const [overallReports, setOverallReports] = useState<OverallReportsState>({});
  const [overallLoading, setOverallLoading] = useState<LoadingState>({});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [filterSelections, setFilterSelections] = useState<FilterSelectionsState>({});
  const [savingFilters, setSavingFilters] = useState<Record<string, boolean>>({});
  const [openPivot, setOpenPivot] = useState<{ slotId: UploadSlotId; pivotId: string } | null>(null);

  // Section 1's "Defined" checkboxes -- excluded ids live on the backend
  // (report.excluded_pivot_ids), this is just a per-slot busy flag while a
  // toggle round-trips.
  const [pivotSelectionBusy, setPivotSelectionBusy] = useState<LoadingState>({});

  // A Client Brief's own single-question fallback (see formula_agent.py,
  // used only when the Planner didn't identify anything distinct enough to
  // list as its own analysis) surfaces its answer/errors in the Client
  // Brief section below -- there's no more manual free-text "ask a
  // question" box on this page; "Add a Custom Analysis" (the structured
  // form) is the one manual entry point now.
  const [askBusy, setAskBusy] = useState<LoadingState>({});
  const [askError, setAskError] = useState<ErrorsState>({});
  const [askAnswer, setAskAnswer] = useState<Partial<Record<UploadSlotId, FormulaAnswerResponse>>>({});

  // "Add a Custom Analysis" -- a structured group-by/metric/filter form
  // (AddPivotForm) that builds a PivotSuggestion directly, no Groq call
  // needed, shown in its own card next to "AI Analysis Suggestions".
  const [showAddPivotForm, setShowAddPivotForm] = useState<LoadingState>({});
  const [addingPivot, setAddingPivot] = useState<LoadingState>({});

  // Every analysis a Client Brief explicitly asked for -- one outcome per
  // requirement (created/reused/failed), same status-list treatment as the
  // Features page's own Client Brief panel.
  const [briefRequirements, setBriefRequirements] = useState<Partial<Record<UploadSlotId, AnalysisRequirement[]>>>({});
  const [briefOutcomes, setBriefOutcomes] = useState<Partial<Record<UploadSlotId, AnalysisRequirementOutcome[]>>>({});
  // Set once, from the Orchestrator Agent's routing response (see
  // UploadPage's "Client requirement" box) -- null on either field means
  // the brief was already English, so there's nothing to show.
  const [briefLanguage, setBriefLanguage] = useState<
    Partial<Record<UploadSlotId, { detected: string | null; translated: string | null }>>
  >({});

  // The persistent library (see custom_library_store.py) -- not per-slot and
  // not per-session, so it's fetched once and shared across every card below.
  const [savedPivots, setSavedPivots] = useState<SavedPivot[]>([]);
  const [savedBusyId, setSavedBusyId] = useState<string | null>(null);
  const [savedError, setSavedError] = useState<string | null>(null);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

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

  // Analysis (pivot) definitions are always available -- bundled as a
  // default on the backend and only overridden by an explicit upload -- so
  // pivots can be computed as soon as a slot's features are ready.
  useEffect(() => {
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
  }, [slotsReady, auditReports]);

  const refreshSavedPivots = () =>
    fetchSavedPivots()
      .then((res) => setSavedPivots(res.items))
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not load your saved analyses."));

  useEffect(() => {
    refreshSavedPivots();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A "regular" analysis is merged into the definition set on the BACKEND,
  // so promoting, demoting or deleting one only shows up once each slot
  // recomputes -- do that here rather than leaving the page showing an
  // analysis list that no longer matches the library.
  const recomputeAll = () =>
    Promise.all(
      slotsReady.map((id) =>
        applyPivots(auditReports[id]!.session_id, accepted[id] ?? []).then((report) =>
          setReports((prev) => ({ ...prev, [id]: report }))
        )
      )
    );

  const handleToggleSavedScope = (item: SavedPivot) => {
    const next: SavedScope = item.scope === "regular" ? "suggested" : "regular";
    setSavedBusyId(item.id);
    setSavedError(null);
    setSavedPivotScope(item.id, next)
      .then(refreshSavedPivots)
      .then(recomputeAll)
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not change that analysis's scope."))
      .finally(() => setSavedBusyId(null));
  };

  const handleDeleteSaved = (item: SavedPivot) => {
    setSavedBusyId(item.id);
    setSavedError(null);
    deleteSavedPivot(item.id)
      .then((res) => setSavedPivots(res.items))
      .then(recomputeAll)
      .catch((err) => setSavedError(err instanceof AuditApiError ? err.message : "Could not remove that saved analysis."))
      .finally(() => setSavedBusyId(null));
  };

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

  const addCustomPivot = (id: UploadSlotId, pivot: PivotSuggestion) => {
    setAddingPivot((prev) => ({ ...prev, [id]: true }));
    addPivot(id, pivot)
      .then(() => setShowAddPivotForm((prev) => ({ ...prev, [id]: false })))
      .catch(() => {})
      .finally(() => setAddingPivot((prev) => ({ ...prev, [id]: false })));
  };

  // Step 3's whole "AI-Assisted Analysis, one step at a time" flow, run in
  // one shot for a Client Brief instead of a click per stop (see
  // routers/analysis.py's /client-brief): Chart Suggestion (applied
  // automatically), AI Summary, Chart Interpretation for what was just
  // applied, and the Formula Agent answering the brief's own question
  // directly -- fanned out into the exact same state every one of those
  // individual buttons below already populates, so the whole page lights
  // up at once instead of needing new UI for this.
  const handleClientBrief = (id: UploadSlotId, brief: string, plannedAnalyses?: PlannedAnalysisItem[]) => {
    const text = brief.trim();
    if (!text) return;
    const sessionId = auditReports[id]!.session_id;
    setAskBusy((prev) => ({ ...prev, [id]: true }));
    setAskError((prev) => ({ ...prev, [id]: undefined }));
    setAskAnswer((prev) => ({ ...prev, [id]: undefined }));
    setBriefRequirements((prev) => ({ ...prev, [id]: undefined }));
    setBriefOutcomes((prev) => ({ ...prev, [id]: undefined }));
    submitAnalysisBrief(sessionId, text, plannedAnalyses)
      .then((res) => {
        setReports((prev) => ({ ...prev, [id]: res.pivot_report }));
        if (res.overall) setOverallReports((prev) => ({ ...prev, [id]: res.overall! }));
        if (res.suggested_pivots.length > 0) {
          setSuggestions((prev) => ({ ...prev, [id]: res.suggested_pivots }));
          const appliedSpecs = res.suggested_pivots.filter((s) => res.applied_pivot_ids.includes(s.id));
          setAccepted((prev) => {
            const current = prev[id] ?? [];
            const existingIds = new Set(current.map((s) => s.id));
            return { ...prev, [id]: [...current, ...appliedSpecs.filter((s) => !existingIds.has(s.id))] };
          });
        }
        if (res.client_requirements.length > 0) {
          setBriefRequirements((prev) => ({ ...prev, [id]: res.client_requirements }));
          setBriefOutcomes((prev) => ({ ...prev, [id]: res.outcomes }));
        }
        if (res.formula_answer) setAskAnswer((prev) => ({ ...prev, [id]: res.formula_answer! }));
        if (res.errors.length > 0) setAskError((prev) => ({ ...prev, [id]: res.errors.join(" ") }));
      })
      .catch((err) =>
        setAskError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the analysis pipeline.",
        }))
      )
      .finally(() => setAskBusy((prev) => ({ ...prev, [id]: false })));
  };

  // The Orchestrator Agent (see UploadPage's Client Brief box) can send the
  // user here with a question already decided -- run the whole pipeline
  // above at the first ready slot as soon as one exists, then clear the
  // navigation state so it doesn't refire on a later visit.
  //
  // `prefillFiredRef` (not just the state-clearing navigate below) is what
  // actually makes this idempotent -- `slotsReady` is a brand-new array
  // every render (computed inline above, not memoized), so it's never
  // reference-equal to its previous value; every one of the several
  // re-renders that happen while feature/pivot/overall-analysis state is
  // still loading re-triggers this effect, and each one saw the SAME
  // not-yet-cleared `location.state.prefillRequest` before the clearing
  // navigate's own re-render could land -- calling handleClientBrief (and
  // so submitting the same 1-2 planned analyses) 3-4x over, which is
  // exactly the duplicate "Client-Requested Analyses" cards this was
  // caught from. Same idempotency-via-ref pattern AuditPage and
  // FeaturesPage already use for their own prefill effects.
  const prefillFiredRef = useRef(false);
  useEffect(() => {
    const state = location.state as {
      prefillRequest?: string;
      prefillDetectedLanguage?: string | null;
      prefillTranslatedText?: string | null;
      prefillPlannedAnalyses?: PlannedAnalysisItem[];
    } | null;
    const prefill = state?.prefillRequest;
    if (!prefill || slotsReady.length === 0 || prefillFiredRef.current) return;
    prefillFiredRef.current = true;
    const id = slotsReady[0];
    if (state?.prefillDetectedLanguage) {
      setBriefLanguage((prev) => ({
        ...prev,
        [id]: { detected: state.prefillDetectedLanguage ?? null, translated: state.prefillTranslatedText ?? null },
      }));
    }
    handleClientBrief(id, prefill, state?.prefillPlannedAnalyses);
    navigate(location.pathname, { replace: true, state: {} });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, slotsReady]);

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

  // Section 1's checkboxes -- toggling one flips its id in/out of the
  // backend's excluded set and recomputes immediately (see
  // routers/analysis.py's /pivot-selection), so the chart itself
  // disappears/reappears rather than just looking unchecked.
  const toggleDefinedPivot = (id: UploadSlotId, pivotId: string, currentlyExcluded: string[]) => {
    const nextExcluded = currentlyExcluded.includes(pivotId)
      ? currentlyExcluded.filter((x) => x !== pivotId)
      : [...currentlyExcluded, pivotId];
    const sessionId = auditReports[id]!.session_id;
    setPivotSelectionBusy((prev) => ({ ...prev, [id]: true }));
    setPivotSelection(sessionId, nextExcluded)
      .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
      .catch((err) =>
        setErrors((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not update the analysis selection.",
        }))
      )
      .finally(() => setPivotSelectionBusy((prev) => ({ ...prev, [id]: false })));
  };

  // "For each one we need drill downs": a drill-down that resolved to a new
  // chart (see PivotModal's onDrillDownAdded) is folded straight into this
  // slot's own pivot list -- it's already persisted server-side
  // (session.drill_down_pivots), this just avoids waiting on a refetch to
  // see it appear.
  const handleDrillDownAdded = (id: UploadSlotId, newPivot: PivotResult) => {
    setReports((prev) => {
      const current = prev[id];
      if (!current) return prev;
      if (current.pivots.some((p) => p.id === newPivot.id)) return prev;
      return { ...prev, [id]: { ...current, pivots: [...current.pivots, newPivot] } };
    });
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="analysis-page">
        <Header subtitle="Analysis" />
        <main className="analysis-page__main">
          <StepIndicator current={4} />
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
          <StepIndicator current={4} />
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
          <StepIndicator current={4} />
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

  return (
    <div className="analysis-page">
      <Header subtitle="Analysis" />
      <main className="analysis-page__main">
        <StepIndicator current={4} />

        <PageHeader
          icon={<IconBarChart />}
          title="Analysis"
          subtitle="Analysis tables and a summary rolled up from the audited + feature-engineered data, or ask the AI agent to suggest more analyses from your data's own columns."
        />

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const slotSuggestions = suggestions[id] ?? [];
          const slotAccepted = accepted[id] ?? [];
          const acceptedIds = new Set(slotAccepted.map((s) => s.id));
          const pendingSuggestionCount = slotSuggestions.filter((s) => !acceptedIds.has(s.id)).length;
          const definedPivots = report
            ? report.pivots.filter(
                (p) =>
                  !p.id.startsWith("ai_pivot_") &&
                  !p.id.startsWith("custom_pivot_") &&
                  !p.id.startsWith("drilldown_") &&
                  !p.id.startsWith("client_pivot_")
              )
            : [];
          const clientPivots = report ? report.pivots.filter((p) => p.id.startsWith("client_pivot_")) : [];
          const aiPivots = report ? report.pivots.filter((p) => p.id.startsWith("ai_pivot_")) : [];
          const userPivots = report ? report.pivots.filter((p) => p.id.startsWith("custom_pivot_")) : [];
          const drillDownPivots = report ? report.pivots.filter((p) => p.id.startsWith("drilldown_")) : [];
          const aiPivotCount = aiPivots.length;
          const customPivotCount = userPivots.length;
          const excludedPivotIds = report?.excluded_pivot_ids ?? [];
          const featureColumns = featureReports[id]?.columns ?? [];

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
                        {savedPivots.length > 0 && ` ${savedPivots.length} saved.`}
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
                    : slotSuggestions.length + savedPivots.length > 0
                      ? `View Suggestions (${slotSuggestions.length + savedPivots.length})`
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

                    {savedError && <p className="analysis-page__error">{savedError}</p>}

                    {savedPivots.length > 0 && (
                      <section className="analysis-page__saved-section">
                        <h4 className="analysis-page__saved-title">Saved by you</h4>
                        <p className="analysis-page__ai-panel-hint">
                          Analyses you created earlier, kept between sessions. A "Regular" one is already
                          computed on every run -- the rest wait here until you add them.
                        </p>
                        <div className="analysis-page__ai-grid">
                          {savedPivots.map((item) => (
                            <SavedDefinitionCard
                              key={item.id}
                              name={item.name}
                              description={item.description}
                              detail={pivotDetail(item.spec)}
                              scope={item.scope}
                              added={acceptedIds.has(item.id)}
                              busy={savedBusyId === item.id || applyingSuggestionId[id] === item.id || !!applyingAll[id]}
                              onAdd={() => acceptSuggestion(id, item.spec)}
                              onToggleScope={() => handleToggleSavedScope(item)}
                              onDelete={() => handleDeleteSaved(item)}
                            />
                          ))}
                        </div>
                      </section>
                    )}

                    <section className="analysis-page__saved-section">
                      <h4 className="analysis-page__saved-title">From the AI agent</h4>
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
                    </section>
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
                  <IconGrid /> Add Custom Analysis
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

          const briefReqs = briefRequirements[id];
          const briefOuts = briefOutcomes[id] ?? [];
          const language = briefLanguage[id];
          const clientBriefSection = ((briefReqs && briefReqs.length > 0) || language?.detected || askAnswer[id] || askError[id] || askBusy[id]) && (
            <div className="analysis-page__client-brief">
              <div className="analysis-page__panel-head-text">
                <span className="analysis-page__panel-icon analysis-page__panel-icon--purple">
                  <IconSparkle />
                </span>
                <div>
                  <h3 className="analysis-page__ai-panel-title">Client Brief</h3>
                  <p className="analysis-page__ai-panel-hint">
                    Every analysis the brief explicitly asked for was computed (or reused from an
                    already-active one) automatically -- see "AI Analysis Suggestions" below for
                    more, if you want them.
                  </p>
                  {language?.detected && (
                    <details className="analysis-page__client-brief-language">
                      <summary>Detected language: {language.detected} -- show translation</summary>
                      <p className="analysis-page__client-brief-translation">{language.translated}</p>
                    </details>
                  )}
                </div>
              </div>
              {briefReqs && briefReqs.length > 0 && (
                <ul className="analysis-page__client-brief-list">
                  {briefReqs.map((item) => {
                    const outcome = briefOuts.find((o) => o.analysis_name === item.analysis_name);
                    const status = outcome?.status ?? "failed";
                    return (
                      <li key={item.analysis_name} className={`analysis-page__client-brief-item analysis-page__client-brief-item--${status}`}>
                        <div className="analysis-page__client-brief-item-head">
                          <span className="analysis-page__client-brief-item-name">{item.analysis_name}</span>
                          <span className={`analysis-page__client-brief-status analysis-page__client-brief-status--${status}`}>
                            {status === "created" ? "Created" : status === "reused" ? "Reused existing" : "Failed"}
                          </span>
                        </div>
                        <p className="analysis-page__client-brief-item-desc">{item.description}</p>
                        {outcome?.status === "failed" && outcome.error && <p className="analysis-page__error">{outcome.error}</p>}
                      </li>
                    );
                  })}
                </ul>
              )}
              {askBusy[id] && <p className="analysis-page__ai-panel-hint">Resolving the brief…</p>}
              {askError[id] && <p className="analysis-page__error">{askError[id]}</p>}
              {askAnswer[id] && (
                <div className="analysis-page__ask-answer">
                  <span className="analysis-page__ask-mode">
                    {askAnswer[id]!.mode === "template" ? "Answered via pivot template" : "Answered via generated Python (sandboxed)"}
                  </span>
                  <p className="analysis-page__ask-explanation">{askAnswer[id]!.explanation}</p>
                  {askAnswer[id]!.pivot && <PivotTableCard pivot={askAnswer[id]!.pivot!} />}
                  {askAnswer[id]!.table && askAnswer[id]!.table!.length > 0 && (
                    <div className="analysis-page__ask-table-wrap">
                      <table className="analysis-page__ask-table">
                        <thead>
                          <tr>
                            {Object.keys(askAnswer[id]!.table![0]).map((k) => (
                              <th key={k}>{k}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {askAnswer[id]!.table!.map((row, i) => (
                            <tr key={i}>
                              {Object.values(row).map((v, j) => (
                                <td key={j}>{String(v)}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {askAnswer[id]!.value != null && <p className="analysis-page__ask-value">{askAnswer[id]!.value}</p>}
                </div>
              )}
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

                  {clientBriefSection}

                  {report.pivots.length === 0 ? (
                    <p className="analysis-page__none">None of the uploaded analysis definitions could be computed against this data.</p>
                  ) : (
                    [
                      {
                        key: "defined",
                        label: "Analysis Profile (Defined)",
                        hint: "Uncheck one to leave it out of this session -- it stays out until you check it again.",
                        items: definedPivots,
                        checkable: true,
                      },
                      {
                        key: "client",
                        label: "Client-Requested Analyses",
                        hint: "Explicitly asked for in a Client Brief -- still checkable, but computed and added automatically regardless.",
                        items: clientPivots,
                        checkable: true,
                      },
                      { key: "ai", label: "AI-Suggested Analyses", hint: "Proposed by the AI -- from a Client Brief, or from Suggest Analyses.", items: aiPivots, checkable: false },
                      { key: "user", label: "User-Requested Analyses", hint: "Answered by the Formula Agent from your own plain-language ask below.", items: userPivots, checkable: false },
                      { key: "drilldown", label: "Drill-Down Analyses", hint: "Added from a chart's own drill-down suggestions.", items: drillDownPivots, checkable: false },
                    ]
                      .filter((group) => group.items.length > 0)
                      .map((group) => (
                        <div className="analysis-page__pivot-section" key={group.key}>
                          <h3 className="analysis-page__section-title">
                            <IconLayers /> {group.label} ({group.items.length})
                          </h3>
                          <p className="analysis-page__ai-panel-hint">{group.hint}</p>
                          <div className="analysis-page__pivot-list">
                            {group.items.map((p, idx) =>
                              group.checkable ? (
                                <div className="analysis-page__defined-row" key={p.id}>
                                  <input
                                    type="checkbox"
                                    className="analysis-page__defined-checkbox"
                                    checked={!excludedPivotIds.includes(p.id)}
                                    disabled={!!pivotSelectionBusy[id]}
                                    onChange={() => toggleDefinedPivot(id, p.id, excludedPivotIds)}
                                    aria-label={`Include ${p.name}`}
                                  />
                                  <PivotCard pivot={p} colorIndex={idx} onOpen={() => setOpenPivot({ slotId: id, pivotId: p.id })} />
                                </div>
                              ) : (
                                <PivotCard key={p.id} pivot={p} colorIndex={idx} onOpen={() => setOpenPivot({ slotId: id, pivotId: p.id })} />
                              )
                            )}
                          </div>
                        </div>
                      ))
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
              sessionId={auditReports[openPivot.slotId]!.session_id}
              filterSelections={filterSelections[openPivot.slotId]?.[openPivot.pivotId] ?? {}}
              onSaveFilters={(next) => handleSaveFilters(openPivot.slotId, openPivot.pivotId, next)}
              savingFilters={!!savingFilters[openPivot.pivotId]}
              onClose={() => setOpenPivot(null)}
              onDrillDownAdded={(newPivot) => handleDrillDownAdded(openPivot.slotId, newPivot)}
            />
          );
        })()}
    </div>
  );
}
