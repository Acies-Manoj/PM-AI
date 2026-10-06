import ThinkingLoader, { Spinner } from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef, useState } from "react";
import { useStoredRef, useStoredState } from "../state/sessionStore";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import AnalysisCard from "../components/AnalysisCard";
import AnalysisToolbar, { type AnalysisSortKey, type AnalysisStatusFilter } from "../components/AnalysisToolbar";
import AnalysisDetailModal from "../components/AnalysisDetailModal";
import Modal from "../components/Modal";
import AnalysisSuggestionCard from "../components/AnalysisSuggestionCard";
import AddAnalysisForm from "../components/AddAnalysisForm";
import OverallAnalysisCard from "../components/OverallAnalysisCard";
import { ancestorTrail, buildLevelTree } from "../utils/drilldownTree";
import { sourceTag } from "../utils/analysisSourceTag";
import { IconDoc, IconGrid, IconChevronLeft, IconChevronRight, IconBarChart, IconLayers, IconSparkle, IconClipboard } from "../components/icons";
import {
  acceptAnalysisEntry,
  addCustomAnalysis,
  draftAnalysis,
  fetchAnalysisRepository,
  fetchFeatureReport,
  fetchOverallAnalysis,
  filterAnalysisEntry,
  fetchDrilldownOptions,
  proposeDrilldowns,
  acceptDrilldownPath,
  confirmDrilldown,
  fetchDrilldownPaths,
  refreshDrilldown,
  rejectDrilldownPath,
  suggestDrilldownPath,
  runAnalysisEntry,
  applyFeatures,
  selectRequiredFeature,
  suggestAnalysisEntries,
  uploadAnalysisDefinitions,
  AuditApiError,
  type AddCustomAnalysisBody,
  type AnalysisFilterSelections,
  type AnalysisRepositoryEntry,
  type AnalysisSource,
  type ConfirmDrilldownBody,
  type FeatureReport,
  type OverallAnalysisReport,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./AnalysisPage.css";

// Stable empty Set reference for entries with nothing dismissed yet.
const EMPTY_ID_SET: Set<string> = new Set();

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

// Each analysis run is several LLM calls, so only this many run at once.
const MAX_CONCURRENT_RUNS = 2;
const PAGE_SIZE = 12;
// Start of the 422 detail when a run is refused for unmet required features.
const REQUIRED_FEATURES_PREFIX = "Select all required features";
// Approved, not yet run, and waiting on required features.
const isBlocked = (e: AnalysisRepositoryEntry) =>
  e.status === "approved" && e.run_status === "not_run" && e.dependencies_satisfied === false;
const STATUS_ORDER: Record<AnalysisRepositoryEntry["run_status"], number> = { not_run: 0, error: 1, done: 2 };
// Predefined analyses lead, mirroring the Feature page's PREDEFINED-first grouping --
// not alphabetical, since "ai_suggested" would otherwise sort before "predefined".
const SOURCE_ORDER: Record<AnalysisSource, number> = { predefined: 0, planner: 1, custom: 2, ai_suggested: 3, drilldown: 4 };
// Same grouping the Feature page uses for its "N features added in total" summary
// (FeaturesPage.tsx's SOURCE_GROUP_LABELS) -- kept in sync for a consistent pattern.
const SOURCE_GROUP_LABELS: { source: AnalysisSource; label: string }[] = [
  { source: "predefined", label: "Predefined (Customer KPI Profile)" },
  { source: "planner", label: "Planner-Approved" },
  { source: "ai_suggested", label: "AI Suggested" },
  { source: "custom", label: "User Added" },
];

export default function AnalysisPage({ files, auditReports }: AnalysisPageProps) {
  const navigate = useNavigate();

  const [featureReports, setFeatureReports] = useStoredState<FeatureReportsState>("analysis.featureReports", {});
  const [featureCheckLoading, setFeatureCheckLoading] = useState<LoadingState>({});
  const [featureCheckFailed, setFeatureCheckFailed] = useState<LoadingState>({});

  const [repositories, setRepositories] = useStoredState<RepositoryState>("analysis.repositories", {});
  const [repoLoading, setRepoLoading] = useStoredState<LoadingState>("analysis.repoLoading", {});
  const [repoError, setRepoError] = useState<ErrorsState>({});

  const [runningIds, setRunningIds] = useStoredState<Record<string, boolean>>("analysis.runningIds", {});
  const [runFailures, setRunFailures] = useStoredState<Record<string, string | undefined>>("analysis.runFailures", {});
  // Entries the auto-runner has already started once -- it never starts the
  // same entry twice; a failed run is retried only from the card.
  const autoStarted = useStoredRef<{ current: Set<string> }>("analysis.autoStarted", () => ({ current: new Set<string>() }));
  // Required-feature actions per analysis entry: what's running, and errors.
  const [featureBusy, setFeatureBusy] = useStoredState<Record<string, string | undefined>>("analysis.featureBusy", {});
  const [featureErrors, setFeatureErrors] = useState<Record<string, string | undefined>>({});
  // Per slot: the set of finished analyses the last summary was generated
  // for, so the summary regenerates only when that set actually changes.
  const summarizedFor = useStoredRef<{ current: Partial<Record<UploadSlotId, string>> }>("analysis.summarizedFor", () => ({ current: {} }));
  const [suggestLoading, setSuggestLoading] = useStoredState<LoadingState>("analysis.suggestLoading", {});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useStoredState<BusyIdState>("analysis.applyingEntryId", {});
  const [showAddForm, setShowAddForm] = useState<LoadingState>({});
  const [addingAnalysis, setAddingAnalysis] = useStoredState<LoadingState>("analysis.addingAnalysis", {});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});
  // Ids the PM has explicitly hidden from an entry's Selected Drill-downs
  // list -- frontend-only. "Selected" itself is derived straight from real
  // repository data (triggered suggestions + existing chain levels), never
  // hand-tracked, so it can't fall out of sync with what actually exists.
  const [dismissedDrilldowns, setDismissedDrilldowns] = useStoredState<Record<string, Set<string>>>("analysis.dismissedDrilldowns", {});

  const [overallReports, setOverallReports] = useStoredState<OverallReportsState>("analysis.overallReports", {});
  const [overallLoading, setOverallLoading] = useStoredState<LoadingState>("analysis.overallLoading", {});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [openEntry, setOpenEntry] = useState<{ slotId: UploadSlotId; entryId: string } | null>(null);
  // Bumped after each guided Confirm so the open modal switches to its Selected Drill-downs tab.
  const [openSelectedSignal, setOpenSelectedSignal] = useState(0);

  // Toolbar state -- search/sort/filter/pagination, per audited slot.
  const [search, setSearch] = useStoredState<Partial<Record<UploadSlotId, string>>>("analysis.search", {});
  const [sort, setSort] = useStoredState<Partial<Record<UploadSlotId, AnalysisSortKey>>>("analysis.sort", {});
  const [categoryFilter, setCategoryFilter] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("analysis.categoryFilter", {});
  const [statusFilter, setStatusFilter] = useStoredState<Partial<Record<UploadSlotId, AnalysisStatusFilter[]>>>("analysis.statusFilter", {});
  const [page, setPage] = useStoredState<Partial<Record<UploadSlotId, number>>>("analysis.page", {});

  const [defsError, setDefsError] = useState<string | null>(null);
  const [defsLoading, setDefsLoading] = useStoredState("analysis.defsLoading", false);
  // True once we've either attempted the Analysis Profile upload (success or
  // failure) or confirmed there isn't one -- gates the first repository fetch
  // so predefined analyses are included when available, without ever
  // requiring the file to exist.
  const [defsAttempted, setDefsAttempted] = useStoredState("analysis.defsAttempted", false);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasAnalysisProfileFile = !!files.analysisProfile;

  // Step 0: confirm feature engineering has actually run for each audited
  // slot -- an analysis can group by engineered columns, so it needs that
  // step done first.
  // Server-derived data (the feature report, the analysis repository) can be
  // changed by the Features page between visits, so each visit refetches it once
  // while the cached copy stays on screen -- no flash of an empty page.
  const refreshedThisVisit = useRef<Set<string>>(new Set());

  useEffect(() => {
    for (const id of auditedReady) {
      if (featureCheckLoading[id] || featureCheckFailed[id] || refreshedThisVisit.current.has(`feature:${id}`)) continue;
      refreshedThisVisit.current.add(`feature:${id}`);
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
  // one), load the repository for each ready slot. Entries then run on
  // their own (see the auto-run effect below).
  useEffect(() => {
    if (!defsAttempted) return;
    for (const id of slotsReady) {
      if (repoLoading[id] || repoError[id] || refreshedThisVisit.current.has(`repo:${id}`)) continue;
      refreshedThisVisit.current.add(`repo:${id}`);
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
    setRunFailures((prev) => ({ ...prev, [entry.id]: undefined }));
    setRunningIds((prev) => ({ ...prev, [entry.id]: true }));
    runAnalysisEntry(sessionId, entry.id)
      .then((updated) => updateEntry(id, updated))
      .catch((err) => {
        const message = err instanceof AuditApiError ? err.message : "Could not run this analysis.";
        if (message.startsWith(REQUIRED_FEATURES_PREFIX)) {
          // The backend refused because a required feature isn't ready.
          // Show the detail on the card, refresh the entry's dependency
          // status, and let the auto-runner pick it up once satisfied.
          autoStarted.current.delete(entry.id);
          setFeatureErrors((prev) => ({ ...prev, [entry.id]: message }));
          refreshRepository(id, sessionId).catch(() => undefined);
          return;
        }
        // Recorded per entry (not as a page-level error) so the card can say
        // what went wrong -- the auto-runner never retries a failed entry on
        // its own, which would loop on a persistent failure.
        setRunFailures((prev) => ({ ...prev, [entry.id]: message }));
      })
      .finally(() => setRunningIds((prev) => ({ ...prev, [entry.id]: false })));
  };

  // Computes features (the existing Feature step) so an approved required
  // feature becomes usable, then refetches so dependency status updates.
  const computeRequiredFeatures = (id: UploadSlotId, entryId: string): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setFeatureBusy((prev) => ({ ...prev, [entryId]: "compute" }));
    return applyFeatures(sessionId)
      .then((report) => {
        setFeatureReports((prev) => ({ ...prev, [id]: report }));
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setFeatureErrors((prev) => ({
          ...prev,
          [entryId]: err instanceof AuditApiError ? err.message : "Could not compute features.",
        }))
      )
      .finally(() => setFeatureBusy((prev) => ({ ...prev, [entryId]: undefined })));
  };

  const selectFeature = (id: UploadSlotId, entry: AnalysisRepositoryEntry, featureId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setFeatureErrors((prev) => ({ ...prev, [entry.id]: undefined }));
    setFeatureBusy((prev) => ({ ...prev, [entry.id]: `select:${featureId}` }));
    selectRequiredFeature(sessionId, entry.id, featureId)
      .then((updated) => {
        updateEntry(id, updated);
        // Approved but not computed yet -> compute it now.
        if ((updated.required_features ?? []).some((f) => f.state === "not_computed")) {
          return computeRequiredFeatures(id, entry.id);
        }
        return refreshRepository(id, sessionId);
      })
      .catch((err) =>
        setFeatureErrors((prev) => ({
          ...prev,
          [entry.id]: err instanceof AuditApiError ? err.message : "Could not select that feature.",
        }))
      )
      .finally(() => setFeatureBusy((prev) => ({ ...prev, [entry.id]: prev[entry.id]?.startsWith("select:") ? undefined : prev[entry.id] })));
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

  // Rejects on failure so the Add Analysis form (a modal) can show the error
  // itself -- the page-level error line is hidden behind the modal.
  const addAnalysis = (id: UploadSlotId, analysis: AddCustomAnalysisBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    setAddingAnalysis((prev) => ({ ...prev, [id]: true }));
    return addCustomAnalysis(sessionId, analysis)
      .then(() => refreshRepository(id, sessionId))
      .then(() => setShowAddForm((prev) => ({ ...prev, [id]: false })))
      .finally(() => setAddingAnalysis((prev) => ({ ...prev, [id]: false })));
  };

  // Guided drill-down chain. These reject so the modal can show the error
  // next to the control that failed; each refetches the repository so new and
  // stale levels appear. Confirming also navigates straight into the new
  // level, so its own suggestions (about drilling further from THIS level)
  // are what the PM sees next, not the parent's.
  const confirmChainDrilldown = (id: UploadSlotId, entryId: string, body: ConfirmDrilldownBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    // Stay on the analysis being drilled and show its Selected Drill-downs tab, where
    // every level just created (one per value, when several were ticked) is listed.
    return confirmDrilldown(sessionId, entryId, body)
      .then(() => refreshRepository(id, sessionId))
      .then(() => setOpenSelectedSignal((n) => n + 1));
  };

  // Suggested drill-down paths. Accepting or rejecting refetches the repository so the
  // accepted levels show up under Selected Drill-downs (and the report) straight away.
  const decidePath = (id: UploadSlotId, pathId: string, accept: boolean) => {
    const sessionId = auditReports[id]!.session_id;
    return (accept ? acceptDrilldownPath : rejectDrilldownPath)(sessionId, pathId).then((path) =>
      refreshRepository(id, sessionId).then(() => path)
    );
  };

  const refreshChainLevel = (id: UploadSlotId, entryId: string): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    return refreshDrilldown(sessionId, entryId).then(() => refreshRepository(id, sessionId));
  };

  const proposeDrilldownsFor = (id: UploadSlotId, entryId: string, more: boolean) => {
    const sessionId = auditReports[id]!.session_id;
    return proposeDrilldowns(sessionId, entryId, more);
  };

  // Frontend-only: hide one drilldown from an entry's Selected list without
  // deleting it -- never sent to the backend.
  const dismissDrilldown = (entryId: string, id: string) => {
    setDismissedDrilldowns((prev) => {
      const current = new Set(prev[entryId] ?? []);
      current.add(id);
      return { ...prev, [entryId]: current };
    });
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

  // Auto-run: every approved analysis that hasn't been computed yet starts
  // on its own -- predefined and planner entries on page load, custom and
  // accepted AI suggestions as soon as they're added. Capped at
  // MAX_CONCURRENT_RUNS because each run is several LLM calls.
  useEffect(() => {
    let slots = MAX_CONCURRENT_RUNS - Object.values(runningIds).filter(Boolean).length;
    for (const id of slotsReady) {
      for (const entry of repositories[id] ?? []) {
        if (slots <= 0) return;
        if (entry.status !== "approved" || entry.run_status !== "not_run") continue;
        // Blocked on required features: running would just return a 422.
        if (entry.dependencies_satisfied === false) continue;
        if (autoStarted.current.has(entry.id) || runningIds[entry.id]) continue;
        autoStarted.current.add(entry.id);
        runEntry(id, entry);
        slots -= 1;
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, runningIds, slotsReady]);

  // Auto-summary: once no analysis in a slot is still waiting or running,
  // generate the summary -- and regenerate it whenever the set of finished
  // analyses changes (a new analysis ran, a drilldown was explored).
  useEffect(() => {
    for (const id of slotsReady) {
      const approved = (repositories[id] ?? []).filter((e) => e.status === "approved");
      const pending = approved.some(
        (e) => runningIds[e.id] || (e.run_status === "not_run" && !runFailures[e.id] && !isBlocked(e))
      );
      const done = approved.filter((e) => e.run_status === "done").map((e) => e.id).sort().join("|");
      if (pending || !done || overallLoading[id] || summarizedFor.current[id] === done) continue;
      summarizedFor.current[id] = done;
      runOverallAnalysis(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, runningIds, runFailures, slotsReady, overallLoading]);

  const toggleCategory = (id: UploadSlotId, label: string) => {
    setPage((prev) => ({ ...prev, [id]: 1 }));
    setCategoryFilter((prev) => {
      const current = prev[id] ?? [];
      const next = current.includes(label) ? current.filter((c) => c !== label) : [...current, label];
      return { ...prev, [id]: next };
    });
  };

  const toggleStatus = (id: UploadSlotId, status: AnalysisStatusFilter) => {
    setPage((prev) => ({ ...prev, [id]: 1 }));
    setStatusFilter((prev) => {
      const current = prev[id] ?? [];
      const next = current.includes(status) ? current.filter((s) => s !== status) : [...current, status];
      return { ...prev, [id]: next };
    });
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
                ? <ThinkingLoader variant="inline" messages={["Checking whether feature engineering has run…"]} />
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

  const blockedCount = slotsReady.reduce((n, sid) => n + (repositories[sid] ?? []).filter(isBlocked).length, 0);

  return (
    <div className="analysis-page">
      <Header subtitle="Analysis" />
      <main className="analysis-page__main">
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconBarChart />}
          title="Analysis"
          subtitle="Each analysis below is computed automatically as soon as it is added, with a chart and a plain-language interpretation of the result. They come from your Analysis Profile, the Planner, AI suggestions, or ones you add yourself."
        />

        {defsLoading && <ThinkingLoader variant="inline" messages={[`Reading ${files.analysisProfile!.name}…`]} />}
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

          const categorized = topLevelEntries.map((entry) => ({ entry, category: sourceTag(entry.source) }));
          const presentSources = new Set(topLevelEntries.map((e) => e.source));
          const availableCategories = (Object.keys(SOURCE_ORDER) as AnalysisSource[])
            .sort((a, b) => SOURCE_ORDER[a] - SOURCE_ORDER[b])
            .filter((s) => presentSources.has(s))
            .map((s) => sourceTag(s).label);

          const searchText = (search[id] ?? "").trim().toLowerCase();
          const sortKey = sort[id] ?? "source";
          const selectedCategories = categoryFilter[id] ?? [];
          const selectedStatuses = statusFilter[id] ?? [];

          let filtered = categorized;
          if (searchText) {
            filtered = filtered.filter(
              ({ entry }) => entry.name.toLowerCase().includes(searchText) || entry.description.toLowerCase().includes(searchText)
            );
          }
          if (selectedCategories.length > 0) {
            filtered = filtered.filter(({ category }) => selectedCategories.includes(category.label));
          }
          if (selectedStatuses.length > 0) {
            filtered = filtered.filter(({ entry }) => selectedStatuses.includes(entry.run_status));
          }
          const sorted = [...filtered].sort((a, b) => {
            if (sortKey === "name") return a.entry.name.localeCompare(b.entry.name);
            if (sortKey === "source") {
              return SOURCE_ORDER[a.entry.source] - SOURCE_ORDER[b.entry.source] || a.entry.name.localeCompare(b.entry.name);
            }
            return STATUS_ORDER[a.entry.run_status] - STATUS_ORDER[b.entry.run_status] || a.entry.name.localeCompare(b.entry.name);
          });

          const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
          const currentPage = Math.min(page[id] ?? 1, totalPages);
          const pageStart = (currentPage - 1) * PAGE_SIZE;
          const pageItems = sorted.slice(pageStart, pageStart + PAGE_SIZE);
          const activeFilterCount = selectedCategories.length + selectedStatuses.length;

          return (
            <section className="analysis-page__card" key={id}>
              <div className="analysis-page__card-head">
                <div className="analysis-page__card-head-left">
                  <h2 className="analysis-page__slot-title">{slot.title}</h2>
                </div>
                <span className="analysis-page__filename">{files[id]!.name}</span>
              </div>

              {repoLoading[id] && !repositories[id] && <ThinkingLoader messages={LOADING.analysisRepository} />}
              {repoError[id] && <p className="analysis-page__error">{repoError[id]}</p>}

              <div className="analysis-page__stat-row">
                <StatTile icon={<IconDoc />} color="blue" value={(featureReports[id]?.row_count ?? 0).toLocaleString()} label="Rows" />
                <StatTile icon={<IconGrid />} color="teal" value={featureReports[id]?.column_count ?? 0} label="Columns" />
                <StatTile icon={<IconLayers />} color="purple" value={topLevelEntries.length} label="Analyses" />
                {drilldownEntries.length > 0 && <StatTile icon={<IconBarChart />} color="amber" value={drilldownEntries.length} label="Drilldowns" />}
              </div>

              {topLevelEntries.length > 0 && (
                <div className="analysis-page__summary">
                  <p className="analysis-page__summary-title">
                    ✓ {topLevelEntries.length} analys{topLevelEntries.length === 1 ? "is" : "es"} added in total
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
                          {group.items.map((entry) => (
                            <li key={entry.id}>
                              <button
                                type="button"
                                className="analysis-page__summary-item"
                                onClick={() => setOpenEntry({ slotId: id, entryId: entry.id })}
                              >
                                <span className="analysis-page__summary-name">{entry.name}</span>
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
                  <AnalysisToolbar
                    search={search[id] ?? ""}
                    onSearchChange={(value) => {
                      setPage((prev) => ({ ...prev, [id]: 1 }));
                      setSearch((prev) => ({ ...prev, [id]: value }));
                    }}
                    sort={sortKey}
                    onSortChange={(value) => setSort((prev) => ({ ...prev, [id]: value }))}
                    categories={availableCategories}
                    selectedCategories={selectedCategories}
                    onToggleCategory={(label) => toggleCategory(id, label)}
                    selectedStatuses={selectedStatuses}
                    onToggleStatus={(status) => toggleStatus(id, status)}
                    activeFilterCount={activeFilterCount}
                    onClearFilters={() => {
                      setCategoryFilter((prev) => ({ ...prev, [id]: [] }));
                      setStatusFilter((prev) => ({ ...prev, [id]: [] }));
                    }}
                  />
                  {suggestError[id] && <p className="analysis-page__error">{suggestError[id]}</p>}

                  {pageItems.length === 0 ? (
                    <p className="analysis-page__none">No analyses match your search or filters.</p>
                  ) : (
                    <div className="analysis-page__grid">
                      {pageItems.map(({ entry }) => (
                        <AnalysisCard
                          key={entry.id}
                          entry={entry}
                          running={!!runningIds[entry.id]}
                          runFailure={runFailures[entry.id]}
                          onRun={() => runEntry(id, entry)}
                          onExpand={() => setOpenEntry({ slotId: id, entryId: entry.id })}
                          levels={buildLevelTree(visibleEntries, entry.id)}
                          onOpenLevel={(entryId) => setOpenEntry({ slotId: id, entryId })}
                          onSelectFeature={(featureId) => selectFeature(id, entry, featureId)}
                          onComputeFeatures={() => {
                            setFeatureErrors((prev) => ({ ...prev, [entry.id]: undefined }));
                            computeRequiredFeatures(id, entry.id);
                          }}
                          featureBusy={featureBusy[entry.id]}
                          featureError={featureErrors[entry.id]}
                        />
                      ))}
                    </div>
                  )}

                  {sorted.length > 0 && (
                    <div className="analysis-page__pagination">
                      <span className="analysis-page__pagination-count">
                        {pageStart + 1}-{Math.min(pageStart + PAGE_SIZE, sorted.length)} of {sorted.length}{" "}
                        {sorted.length === 1 ? "analysis" : "analyses"}
                      </span>
                      <div className="analysis-page__pagination-nav">
                        <button
                          type="button"
                          className="analysis-page__pagination-btn"
                          disabled={currentPage <= 1}
                          onClick={() => setPage((prev) => ({ ...prev, [id]: currentPage - 1 }))}
                          aria-label="Previous page"
                        >
                          <IconChevronLeft />
                        </button>
                        <span className="analysis-page__pagination-page">
                          {currentPage} / {totalPages}
                        </span>
                        <button
                          type="button"
                          className="analysis-page__pagination-btn"
                          disabled={currentPage >= totalPages}
                          onClick={() => setPage((prev) => ({ ...prev, [id]: currentPage + 1 }))}
                          aria-label="Next page"
                        >
                          <IconChevronRight />
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}

              <OverallAnalysisCard
                report={overallReports[id]}
                loading={!!overallLoading[id]}
                error={overallError[id]}
                waitingForAnalyses={visibleEntries.some(
                  (e) => runningIds[e.id] || (e.run_status === "not_run" && !runFailures[e.id] && !isBlocked(e))
                )}
                onRetry={() => runOverallAnalysis(id)}
              />

              <div className="analysis-page__panels-grid">
                <div className="analysis-page__ai-panel">
                  <div className="analysis-page__panel-head-text">
                    <span className="analysis-page__panel-icon analysis-page__panel-icon--purple">
                      <IconSparkle />
                    </span>
                    <div>
                      <h3 className="analysis-page__ai-panel-title">AI Analysis Suggestions</h3>
                      <p className="analysis-page__ai-panel-hint">
                        The agent looks at this data's columns and proposes analysis tables it can
                        compute -- you choose which ones to add.
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="analysis-page__btn analysis-page__btn--primary analysis-page__panel-btn"
                    disabled={!!suggestLoading[id]}
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
                        : "Suggest Analyses"}
                  </button>
                  {suggestError[id] && <p className="analysis-page__error analysis-page__panel-error">{suggestError[id]}</p>}
                </div>

                <div className="analysis-page__custom-panel">
                  <div className="analysis-page__panel-head-text">
                    <span className="analysis-page__panel-icon analysis-page__panel-icon--blue">
                      <IconClipboard />
                    </span>
                    <div>
                      <h3 className="analysis-page__custom-panel-title">Add a Custom Analysis</h3>
                      <p className="analysis-page__custom-panel-hint">
                        Define your own group-by + aggregation logic straight from this data's
                        columns -- no need to edit and re-upload the Analysis Profile file.
                      </p>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="analysis-page__btn analysis-page__btn--secondary analysis-page__panel-btn"
                    onClick={() => setShowAddForm((prev) => ({ ...prev, [id]: true }))}
                  >
                    + Add Custom Analysis
                  </button>
                </div>
              </div>

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
                      {suggestLoading[id] ? <><Spinner />Thinking…</> : "Suggest More"}
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

              {showAddForm[id] && (
                <Modal title="Add a Custom Analysis" onClose={() => setShowAddForm((prev) => ({ ...prev, [id]: false }))}>
                  <AddAnalysisForm
                    columns={featureColumns}
                    busy={!!addingAnalysis[id]}
                    onDraft={(request) => draftAnalysis(auditReports[id]!.session_id, request)}
                    onAdd={(analysis) => addAnalysis(id, analysis)}
                    onCancel={() => setShowAddForm((prev) => ({ ...prev, [id]: false }))}
                  />
                </Modal>
              )}
            </section>
          );
        })}

        {blockedCount > 0 && (
          <p className="analysis-page__blocked-notice" role="status">
            {blockedCount} {blockedCount === 1 ? "analysis is" : "analyses are"} waiting on required features.
          </p>
        )}

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
          const openRepo = repositories[openEntry.slotId] ?? [];
          const openEntryData = openRepo.find((e) => e.id === openEntry.entryId);
          if (!openEntryData) return null;
          const parentName = openEntryData.parent_id
            ? openRepo.find((e) => e.id === openEntryData.parent_id)?.name
            : undefined;
          return (
            <AnalysisDetailModal
              entry={openEntryData}
              parentName={parentName}
              dismissedIds={dismissedDrilldowns[openEntryData.id] ?? EMPTY_ID_SET}
              onDismiss={(id) => dismissDrilldown(openEntryData.id, id)}
              running={!!runningIds[openEntryData.id]}
              onRetry={() => runEntry(openEntry.slotId, openEntryData)}
              onClose={() => setOpenEntry(null)}
              onOpenChild={(childEntryId) => setOpenEntry({ slotId: openEntry.slotId, entryId: childEntryId })}
              trail={ancestorTrail(openRepo, openEntryData)}
              childLevels={buildLevelTree(openRepo, openEntryData.id)}
              onFetchDrilldownOptions={() => fetchDrilldownOptions(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onProposeDrilldowns={(more) => proposeDrilldownsFor(openEntry.slotId, openEntry.entryId, more)}
              onConfirmDrilldown={(body) => confirmChainDrilldown(openEntry.slotId, openEntry.entryId, body)}
              onRefreshLevel={() => refreshChainLevel(openEntry.slotId, openEntry.entryId)}
              openSelectedSignal={openSelectedSignal}
              onFetchPaths={() => fetchDrilldownPaths(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onSuggestPath={() => suggestDrilldownPath(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onAcceptPath={(pathId) => decidePath(openEntry.slotId, pathId, true)}
              onRejectPath={(pathId) => decidePath(openEntry.slotId, pathId, false)}
              onApplyFilters={(filters: AnalysisFilterSelections) =>
                filterAnalysisEntry(auditReports[openEntry.slotId]!.session_id, openEntry.entryId, filters)
              }
            />
          );
        })()}
    </div>
  );
}
