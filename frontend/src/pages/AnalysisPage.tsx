import { useEffect, useRef, useState } from "react";
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
import { IconDoc, IconGrid, IconChevronLeft, IconChevronRight, IconBarChart, IconLayers, IconSparkle, IconPlus } from "../components/icons";
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
  confirmDrilldown,
  rerankDrilldown,
  refreshDrilldown,
  runAnalysisEntry,
  applyFeatures,
  selectRequiredFeature,
  suggestAnalysisEntries,
  triggerDrilldown,
  suggestMoreDrilldowns,
  uploadAnalysisDefinitions,
  AuditApiError,
  type AddCustomAnalysisBody,
  type AnalysisFilterSelections,
  type AnalysisRepositoryEntry,
  type AnalysisSource,
  type ConfirmDrilldownBody,
  type DrilldownRank,
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

  const [featureReports, setFeatureReports] = useState<FeatureReportsState>({});
  const [featureCheckLoading, setFeatureCheckLoading] = useState<LoadingState>({});
  const [featureCheckFailed, setFeatureCheckFailed] = useState<LoadingState>({});

  const [repositories, setRepositories] = useState<RepositoryState>({});
  const [repoLoading, setRepoLoading] = useState<LoadingState>({});
  const [repoError, setRepoError] = useState<ErrorsState>({});

  const [runningIds, setRunningIds] = useState<Record<string, boolean>>({});
  const [runFailures, setRunFailures] = useState<Record<string, string | undefined>>({});
  // Entries the auto-runner has already started once -- it never starts the
  // same entry twice; a failed run is retried only from the card.
  const autoStarted = useRef<Set<string>>(new Set());
  // Required-feature actions per analysis entry: what's running, and errors.
  const [featureBusy, setFeatureBusy] = useState<Record<string, string | undefined>>({});
  const [featureErrors, setFeatureErrors] = useState<Record<string, string | undefined>>({});
  // Per slot: the set of finished analyses the last summary was generated
  // for, so the summary regenerates only when that set actually changes.
  const summarizedFor = useRef<Partial<Record<UploadSlotId, string>>>({});
  const [suggestLoading, setSuggestLoading] = useState<LoadingState>({});
  const [suggestError, setSuggestError] = useState<ErrorsState>({});
  const [applyingEntryId, setApplyingEntryId] = useState<BusyIdState>({});
  const [showAddForm, setShowAddForm] = useState<LoadingState>({});
  const [addingAnalysis, setAddingAnalysis] = useState<LoadingState>({});
  const [showSuggestionsModal, setShowSuggestionsModal] = useState<LoadingState>({});
  const [triggeringDrilldownId, setTriggeringDrilldownId] = useState<string | null>(null);
  // Explore / Suggest-more failures. The page-level error line sits behind the
  // open modal, so these are handed to the modal to show next to the list.
  const [drilldownError, setDrilldownError] = useState<string | null>(null);
  const [suggestingMoreFor, setSuggestingMoreFor] = useState<string | null>(null);
  // Which drilldown suggestions the PM has selected for each entry --
  // frontend-only bookkeeping (see AnalysisDetailModal's Selected Drill-downs
  // tab); a missing key means "not seeded yet" (see seedDrilldownSelection).
  const [selectedDrilldowns, setSelectedDrilldowns] = useState<Record<string, Set<string>>>({});

  const [overallReports, setOverallReports] = useState<OverallReportsState>({});
  const [overallLoading, setOverallLoading] = useState<LoadingState>({});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [openEntry, setOpenEntry] = useState<{ slotId: UploadSlotId; entryId: string } | null>(null);

  // Toolbar state -- search/sort/filter/pagination, per audited slot.
  const [search, setSearch] = useState<Partial<Record<UploadSlotId, string>>>({});
  const [sort, setSort] = useState<Partial<Record<UploadSlotId, AnalysisSortKey>>>({});
  const [categoryFilter, setCategoryFilter] = useState<Partial<Record<UploadSlotId, string[]>>>({});
  const [statusFilter, setStatusFilter] = useState<Partial<Record<UploadSlotId, AnalysisStatusFilter[]>>>({});
  const [page, setPage] = useState<Partial<Record<UploadSlotId, number>>>({});

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
  // one), load the repository for each ready slot. Entries then run on
  // their own (see the auto-run effect below).
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

  const handleTriggerDrilldown = (id: UploadSlotId, entryId: string, drilldownId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setTriggeringDrilldownId(drilldownId);
    setDrilldownError(null);
    triggerDrilldown(sessionId, entryId, drilldownId)
      .then((child) => refreshRepository(id, sessionId).then(() => setOpenEntry({ slotId: id, entryId: child.id })))
      .catch((err) =>
        setDrilldownError(err instanceof AuditApiError ? err.message : "Could not run that drill-down. Is the backend still running?")
      )
      .finally(() => setTriggeringDrilldownId(null));
  };

  // Guided drill-down chain. These reject so the modal can show the error
  // next to the control that failed; each refetches the repository so new and
  // stale levels appear.
  const confirmChainDrilldown = (id: UploadSlotId, entryId: string, body: ConfirmDrilldownBody): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    return confirmDrilldown(sessionId, entryId, body).then(() => refreshRepository(id, sessionId));
  };

  const rerankChainLevel = (id: UploadSlotId, entryId: string, rank: DrilldownRank): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    return rerankDrilldown(sessionId, entryId, rank).then(() => refreshRepository(id, sessionId));
  };

  const refreshChainLevel = (id: UploadSlotId, entryId: string): Promise<void> => {
    const sessionId = auditReports[id]!.session_id;
    return refreshDrilldown(sessionId, entryId).then(() => refreshRepository(id, sessionId));
  };

  const handleSuggestMoreDrilldowns = (id: UploadSlotId, entryId: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSuggestingMoreFor(entryId);
    setDrilldownError(null);
    suggestMoreDrilldowns(sessionId, entryId)
      .then(() => refreshRepository(id, sessionId))
      .catch((err) =>
        setDrilldownError(err instanceof AuditApiError ? err.message : "Could not get more drill-down suggestions.")
      )
      .finally(() => setSuggestingMoreFor(null));
  };

  // Frontend-only: which drilldown suggestions are "selected" for an entry.
  // Seeded once per entry (already-triggered ones start selected) and toggled
  // from the modal -- never sent to the backend.
  const seedDrilldownSelection = (entryId: string, drilldownIds: string[]) => {
    setSelectedDrilldowns((prev) => (prev[entryId] ? prev : { ...prev, [entryId]: new Set(drilldownIds) }));
  };

  const toggleDrilldownSelection = (entryId: string, drilldownId: string) => {
    setSelectedDrilldowns((prev) => {
      const current = new Set(prev[entryId] ?? []);
      if (current.has(drilldownId)) current.delete(drilldownId);
      else current.add(drilldownId);
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

  const blockedCount = slotsReady.reduce((n, sid) => n + (repositories[sid] ?? []).filter(isBlocked).length, 0);

  return (
    <div className="analysis-page">
      <Header subtitle="Analysis" />
      <main className="analysis-page__main">
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconBarChart />}
          title="Analysis"
          subtitle="The Analysis Agent drafts a formula, writes the code, picks a chart, and interprets the result for each analysis below -- predefined, planner-approved, custom, and AI-suggested -- automatically, as soon as each one is added."
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

              <div className="analysis-page__cta-row">
                <div className="analysis-page__cta">
                  <span className="analysis-page__cta-icon analysis-page__cta-icon--purple">
                    <IconSparkle />
                  </span>
                  <div className="analysis-page__cta-text">
                    <span className="analysis-page__cta-title">AI Analysis Suggestions</span>
                    <span className="analysis-page__cta-desc">Let the agent propose analysis tables from this data's columns.</span>
                  </div>
                  <button
                    type="button"
                    className="analysis-page__cta-btn analysis-page__cta-btn--primary"
                    disabled={!!suggestLoading[id]}
                    onClick={() => {
                      if (pendingSuggestions.length === 0) runSuggest(id);
                      setShowSuggestionsModal((prev) => ({ ...prev, [id]: true }));
                    }}
                  >
                    {suggestLoading[id]
                      ? "Thinking…"
                      : pendingSuggestions.length > 0
                        ? `View Suggestions (${pendingSuggestions.length})`
                        : "Suggest Analyses"}
                  </button>
                </div>

                <div className="analysis-page__cta">
                  <span className="analysis-page__cta-icon analysis-page__cta-icon--blue">
                    <IconPlus />
                  </span>
                  <div className="analysis-page__cta-text">
                    <span className="analysis-page__cta-title">Add a Custom Analysis</span>
                    <span className="analysis-page__cta-desc">Define your own group-by + aggregation logic from this data's columns.</span>
                  </div>
                  <button
                    type="button"
                    className="analysis-page__cta-btn"
                    onClick={() => setShowAddForm((prev) => ({ ...prev, [id]: true }))}
                  >
                    + Add Custom
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
              selectedIds={selectedDrilldowns[openEntryData.id]}
              onToggleSelect={(drilldownId) => toggleDrilldownSelection(openEntryData.id, drilldownId)}
              onSeedSelection={(ids) => seedDrilldownSelection(openEntryData.id, ids)}
              triggeringDrilldownId={triggeringDrilldownId}
              running={!!runningIds[openEntryData.id]}
              onRetry={() => runEntry(openEntry.slotId, openEntryData)}
              drilldownError={drilldownError}
              suggestingMore={suggestingMoreFor === openEntryData.id}
              onSuggestMore={() => handleSuggestMoreDrilldowns(openEntry.slotId, openEntry.entryId)}
              onClose={() => setOpenEntry(null)}
              onTriggerDrilldown={(drilldownId) => handleTriggerDrilldown(openEntry.slotId, openEntry.entryId, drilldownId)}
              onOpenChild={(childEntryId) => setOpenEntry({ slotId: openEntry.slotId, entryId: childEntryId })}
              trail={ancestorTrail(openRepo, openEntryData)}
              childLevels={buildLevelTree(openRepo, openEntryData.id)}
              onFetchDrilldownOptions={() => fetchDrilldownOptions(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onProposeDrilldowns={() => proposeDrilldowns(auditReports[openEntry.slotId]!.session_id, openEntry.entryId)}
              onConfirmDrilldown={(body) => confirmChainDrilldown(openEntry.slotId, openEntry.entryId, body)}
              onRerankLevel={(rank) => rerankChainLevel(openEntry.slotId, openEntry.entryId, rank)}
              onRefreshLevel={() => refreshChainLevel(openEntry.slotId, openEntry.entryId)}
              onApplyFilters={(filters: AnalysisFilterSelections) =>
                filterAnalysisEntry(auditReports[openEntry.slotId]!.session_id, openEntry.entryId, filters)
              }
            />
          );
        })()}
    </div>
  );
}
