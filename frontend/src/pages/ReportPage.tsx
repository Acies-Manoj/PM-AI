import ThinkingLoader from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import AnalysisChart from "../components/AnalysisChart";
import ReportEditorModal from "../components/ReportEditorModal";
import type { DeckState, SlideEdit } from "../utils/deck";
import { useStoredRef, useStoredState } from "../state/sessionStore";
import {
  IconChevronDown,
  IconChevronLeft,
  IconClipboard,
  IconDownload,
  IconEye,
  IconGripVertical,
  IconLayers,
  IconSparkle,
} from "../components/icons";
import {
  fetchAnalysisRepository,
  fetchReportSummary,
  fetchReportTranslations,
  fetchSupportedReportLanguages,
  AuditApiError,
  exportReport,
  translateTexts,
  type AnalysisRepositoryEntry,
  type EntryTranslation,
  type LanguageOption,
} from "../api/audit";
import { buildReportTree, drilldownSubtitle, isStaleEntry } from "../utils/reportTree";
import { REPORT_CHART_TYPES, type ReportChartType } from "../utils/reportChartTypes";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type RepositoriesState = Partial<Record<UploadSlotId, AnalysisRepositoryEntry[]>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;

function defaultChartType(entry: AnalysisRepositoryEntry): ReportChartType {
  return (REPORT_CHART_TYPES as readonly string[]).includes(entry.chart_type ?? "")
    ? (entry.chart_type as ReportChartType)
    : "bar";
}

// Strips the LLM's boilerplate "The chart shows..." framing and keeps only
// the first couple of sentences -- the PM wants the gist, not a restatement
// of what they're already looking at.
const CHART_LEAD_IN_RE = /^(the|this)\s+(chart|graph|data|visuali[sz]ation)\s+(shows?|illustrates?|indicates?|reveals?|highlights?)\s*(that\s+)?/i;
const MAX_SUMMARY_CHARS = 220;

function shortenInterpretation(text: string): string {
  let s = text.trim().replace(CHART_LEAD_IN_RE, "");
  if (s) s = s[0].toUpperCase() + s.slice(1);
  const sentences = s.split(/(?<=[.!?])\s+/).filter(Boolean);
  let result = sentences.slice(0, 2).join(" ");
  if (result.length > MAX_SUMMARY_CHARS) result = `${result.slice(0, MAX_SUMMARY_CHARS - 1).trimEnd()}…`;
  return result || text;
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  // Everything the PM chose (selection, order, language, expanded charts) lives in the
  // shared store so it survives leaving this page; the analysis repository itself is
  // refetched on each visit (stale-while-revalidate) since the Analysis page can change it.
  const [repositories, setRepositories] = useStoredState<RepositoriesState>("report.repositories", {});
  const [loading, setLoading] = useStoredState<LoadingState>("report.loading", {});
  const refreshedThisVisit = useRef<Set<string>>(new Set());
  // Where each source's Preview / Download buttons render: the top bar and the bottom bar of the page.
  const [exportTop, setExportTop] = useState<HTMLDivElement | null>(null);
  const [exportBottom, setExportBottom] = useState<HTMLDivElement | null>(null);
  const [editorSlot, setEditorSlot] = useState<UploadSlotId | null>(null);
  const [exporting, setExporting] = useState<LoadingState>({});
  // What the PM changed in the editor: slide text, cover text, and whether the summary was hand-written.
  const [edits, setEdits] = useStoredState<Record<string, SlideEdit>>("report.edits", {});
  const [cover, setCover] = useStoredState<Partial<Record<UploadSlotId, DeckState["cover"]>>>("report.cover", {});
  const [summaryEdited, setSummaryEdited] = useStoredState<Partial<Record<UploadSlotId, boolean>>>("report.summaryEdited", {});
  // The summary has three sources: what the generator wrote (English), its translation into the picked language,
  // and what the PM typed. The PM's text wins; otherwise the translation when one matches the language.
  const [summaryText, setSummaryText] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.summaryText", {});
  const [summaryTranslated, setSummaryTranslated] = useStoredState<
    Partial<Record<UploadSlotId, { language: string; source: string; bullets: string[] }>>
  >("report.summaryTranslated", {});
  const summaryEditedRef = useRef(summaryEdited);
  summaryEditedRef.current = summaryEdited;
  const [errors, setErrors] = useState<ErrorsState>({});
  const [selected, setSelected] = useStoredState<Record<string, boolean>>("report.selected", {});

  // The PM's own chosen slide order (drag-reorderable) -- frontend-only
  // until download time, when it's sent to the backend so the exported
  // .pptx matches this preview's order exactly.
  const [slideOrder, setSlideOrder] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.slideOrder", {});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // Charts start collapsed -- a slide is mostly checkbox/name/chart-type
  // until the PM asks to actually see the chart.
  const [expandedCharts, setExpandedCharts] = useStoredState<Record<string, boolean>>("report.expandedCharts", {});

  // The Report's own closing-slide bullet points -- synthesized from the
  // included slides' interpretations (see final_summary_agent.py), NOT the
  // Analysis page's KPI-highlights Summary. Bullets, not one paragraph, to
  // match the reference deck's own bullet-point closing slide.
  const [summaryBullets, setSummaryBullets] = useStoredState<Partial<Record<UploadSlotId, string[]>>>("report.summaryBullets", {});
  const [summaryLoading, setSummaryLoading] = useStoredState<LoadingState>("report.summaryLoading", {});
  const [summaryError, setSummaryError] = useState<ErrorsState>({});

  const [languages, setLanguages] = useState<LanguageOption[]>([{ code: "en", name: "English" }]);
  const [language, setLanguage] = useStoredState("report.language", "en");
  // Translated {entryId: {name, interpretation}} per slot, for whichever
  // language is picked -- mirrors what build_report puts on each slide, so
  // this on-screen list matches the .pptx before the PM ever downloads it.
  const [translations, setTranslations] = useStoredState<Partial<Record<UploadSlotId, Record<string, EntryTranslation>>>>("report.translations", {});

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  // The language list only ever needs fetching once -- it's a fixed catalog
  // of what the backend's translation_service currently supports, not
  // per-session. Falling back to English-only (the initial state above) if
  // this fails is fine -- the report always downloads, just without the
  // language picker filled in.
  useEffect(() => {
    fetchSupportedReportLanguages()
      .then((res) => setLanguages(res.languages))
      .catch(() => {});
  }, []);

  // Re-fetches translated names/interpretations whenever the picked
  // language or the set of done entries changes. English needs no fetch --
  // clearing state lets the render fall back to each entry's own English
  // text. A failed fetch (translation service down, etc.) leaves the prior
  // (or no) translations in place rather than blocking the preview.
  useEffect(() => {
    if (language === "en") {
      setTranslations((prev) => (Object.keys(prev).length === 0 ? prev : {}));
      return;
    }
    for (const id of auditedReady) {
      const doneIds = (repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id);
      if (doneIds.length === 0) continue;
      const sessionId = auditReports[id]!.session_id;
      fetchReportTranslations(sessionId, language, doneIds)
        .then((res) => setTranslations((prev) => ({ ...prev, [id]: res.translations })))
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, repositories, auditedReady]);

  useEffect(() => {
    for (const id of auditedReady) {
      if (loading[id] || refreshedThisVisit.current.has(id)) continue;
      refreshedThisVisit.current.add(id);
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      fetchAnalysisRepository(sessionId)
        .then((res) => {
          // Only accepted analyses and drill-downs: a suggested path's pending levels (and rejected
          // ones) are never offered for the report.
          const entries = res.entries.filter((e) => e.status === "approved");
          setRepositories((prev) => ({ ...prev, [id]: entries }));
          const byId = new Map(entries.map((e) => [e.id, e]));
          setSelected((prev) => {
            const next = { ...prev };
            for (const entry of entries) {
              // Stale drill-down levels are never included by default.
              if (entry.run_status === "done" && !(entry.id in next)) next[entry.id] = !isStaleEntry(entry, byId);
            }
            return next;
          });
        })
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not load this session's analyses.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  // Seeds each slot's slide order from its done entries the first time they
  // load, and appends any newly-finished entry ids at the end afterward --
  // never disturbs an order the PM already dragged into place.
  useEffect(() => {
    for (const id of auditedReady) {
      const doneIds = (repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id);
      if (doneIds.length === 0) continue;
      setSlideOrder((prev) => {
        const current = prev[id] ?? [];
        const currentSet = new Set(current);
        const missing = doneIds.filter((eid) => !currentSet.has(eid));
        if (missing.length === 0) return prev;
        return { ...prev, [id]: [...current, ...missing] };
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady]);

  const runReportSummary = (id: UploadSlotId, entryIds: string[]) => {
    const sessionId = auditReports[id]!.session_id;
    setSummaryLoading((prev) => ({ ...prev, [id]: true }));
    setSummaryError((prev) => ({ ...prev, [id]: undefined }));
    fetchReportSummary(sessionId, entryIds)
      .then((res) => {
        // A summary the PM wrote by hand while this was loading must not be overwritten.
        if (!summaryEditedRef.current[id]) setSummaryBullets((prev) => ({ ...prev, [id]: res.bullets }));
      })
      .catch((err) => {
        // Forget the signature so the next visit / selection change retries instead of
        // treating this selection as already summarized.
        summarizedFor.current[id] = undefined;
        setSummaryError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the summary agent.",
        }));
      })
      .finally(() => setSummaryLoading((prev) => ({ ...prev, [id]: false })));
  };

  // The final summary regenerates whenever the ordered, selected, done
  // entry-id list actually changes -- keyed by a signature of that exact
  // list so toggling a checkbox or reordering slides refreshes it, but
  // re-renders for unrelated reasons don't re-request it.
  const summarizedFor = useStoredRef<{ current: Partial<Record<UploadSlotId, string>> }>("report.summarizedFor", () => ({ current: {} }));
  useEffect(() => {
    for (const id of auditedReady) {
      const order = slideOrder[id] ?? [];
      const doneIds = new Set((repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id));
      const byId = new Map((repositories[id] ?? []).map((e) => [e.id, e]));
      const orderedSelectedDoneIds = buildReportTree(
        (repositories[id] ?? []).filter((e) => doneIds.has(e.id) && selected[e.id] && !isStaleEntry(e, byId)),
        order
      ).map((n) => n.entry.id);
      if (orderedSelectedDoneIds.length === 0 || summaryEdited[id]) continue;
      const signature = orderedSelectedDoneIds.join("|");
      if (summarizedFor.current[id] === signature || summaryLoading[id]) continue;
      summarizedFor.current[id] = signature;
      runReportSummary(id, orderedSelectedDoneIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady, slideOrder, selected, summaryEdited]);

  // Hand the summary back to the generator: forgetting its signature makes the effect above rebuild it.
  const regenerateSummary = (id: UploadSlotId) => {
    summarizedFor.current[id] = undefined;
    setSummaryEdited((prev) => ({ ...prev, [id]: false }));
    setSummaryText((prev) => ({ ...prev, [id]: undefined }));
  };

  // Translate the generated summary whenever the language (or the summary) changes. English needs nothing.
  useEffect(() => {
    if (language === "en") return;
    for (const id of auditedReady) {
      const source = summaryBullets[id];
      if (!source || summaryEdited[id]) continue;
      const key = source.join("|");
      const have = summaryTranslated[id];
      if (have && have.language === language && have.source === key) continue;
      translateTexts(language, source)
        .then((map) =>
          setSummaryTranslated((prev) => ({ ...prev, [id]: { language, source: key, bullets: source.map((b) => map[b] ?? b) } }))
        )
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, summaryBullets, summaryEdited]);

  // The summary exactly as it should read now: the PM's own text, else the translation, else the generated English.
  const bulletsFor = (id: UploadSlotId): string[] | null => {
    if (summaryEdited[id]) return summaryText[id] ?? [];
    const generated = summaryBullets[id];
    if (!generated) return null;
    const translated = summaryTranslated[id];
    return language !== "en" && translated?.language === language && translated.source === generated.join("|")
      ? translated.bullets
      : generated;
  };

  const toggleSelected = (entryId: string) => setSelected((prev) => ({ ...prev, [entryId]: !prev[entryId] }));

  const handleDrop = (id: UploadSlotId, targetEntryId: string, parentOf: Map<string, string | null>) => {
    // Reordering only happens among roots or among siblings -- a drill-down
    // can never leave its parent, nor precede it.
    if (!draggingId || draggingId === targetEntryId || parentOf.get(draggingId) !== parentOf.get(targetEntryId)) {
      setDraggingId(null);
      return;
    }
    setSlideOrder((prev) => {
      const current = prev[id] ?? [];
      if (!current.includes(draggingId) || !current.includes(targetEntryId)) return prev;
      const withoutDragged = current.filter((eid) => eid !== draggingId);
      const targetIdx = withoutDragged.indexOf(targetEntryId);
      const next = [...withoutDragged.slice(0, targetIdx), draggingId, ...withoutDragged.slice(targetIdx)];
      return { ...prev, [id]: next };
    });
    setDraggingId(null);
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={6} />
          <div className="report-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (auditedReady.length === 0) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={6} />
          <div className="report-page__empty">
            <p>Finish resolving the data audit before a report can be generated.</p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  const stillChecking = Object.values(loading).some(Boolean);
  const slotsWithResults = auditedReady.filter((id) => (repositories[id] ?? []).some((e) => e.run_status === "done"));

  if (slotsWithResults.length === 0) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={6} />
          <div className="report-page__empty">
            <p>
              {stillChecking
                ? <ThinkingLoader variant="inline" messages={["Checking whether any analyses have been run…"]} />
                : "No analyses have been run yet -- go run some on the Analysis page first, since the report is built from whichever of them finished successfully."}
            </p>
            <button type="button" className="report-page__btn report-page__btn--primary" onClick={() => navigate("/analysis")}>
              Go to Analysis
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="report-page">
      <Header subtitle="Report" />
      <main className="report-page__main">
        <StepIndicator current={6} />

        <PageHeader
          icon={<IconClipboard />}
          title="Report"
          subtitle="Pick which completed analyses go into the downloadable report, drag to reorder, preview each slide, then export it as a .pptx."
          action={
            <button type="button" className="report-page__btn report-page__btn--secondary report-page__nav-btn" onClick={() => navigate("/analysis")}>
              <IconChevronLeft /> Back to Analysis
            </button>
          }
        />

        <div className="report-page__toolbar">
        <div className="report-page__language-picker">
          <label htmlFor="report-language">Report language</label>
          <select id="report-language" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
        </div>
        <div className="report-page__export-host" ref={setExportTop} />
        </div>

        {slotsWithResults.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const doneEntriesRaw = (repositories[id] ?? []).filter((e) => e.run_status === "done");
          const order = slideOrder[id] ?? [];
          const byId = new Map((repositories[id] ?? []).map((e) => [e.id, e]));
          const staleIds = new Set(doneEntriesRaw.filter((e) => isStaleEntry(e, byId)).map((e) => e.id));
          // Display tree: every done level, drill-downs indented under their parent.
          const tree = buildReportTree(doneEntriesRaw, order);
          const doneEntries = tree.map((n) => n.entry);
          const parentOf = new Map(tree.map((n) => [n.entry.id, n.parentId]));
          const aiSuggestedCount = doneEntries.filter((e) => e.source === "ai_suggested").length;
          // What the export will contain: selected, non-stale levels, numbered
          // over that subset exactly as the backend does.
          const includedTree = buildReportTree(
            doneEntriesRaw.filter((e) => selected[e.id] && !staleIds.has(e.id)),
            order
          );
          const slideNumbers = new Map(includedTree.map((n) => [n.entry.id, n.number]));
          const selectedEntries = includedTree.map((n) => n.entry);
          const selectedIds = selectedEntries.map((e) => e.id);
          const deck: DeckState = {
            selected,
            order,
            edits,
            cover: cover[id] ?? {},
            bullets: bulletsFor(id),
            bulletsEdited: !!summaryEdited[id],
          };
          const applyDeck = (next: DeckState) => {
            setSelected(next.selected);
            setSlideOrder((prev) => ({ ...prev, [id]: next.order }));
            setEdits(next.edits);
            setCover((prev) => ({ ...prev, [id]: next.cover }));
            setSummaryEdited((prev) => ({ ...prev, [id]: next.bulletsEdited }));
            // Only text the PM typed is stored; the generated summary stays as the generator wrote it.
            if (next.bulletsEdited) setSummaryText((prev) => ({ ...prev, [id]: next.bullets ?? [] }));
          };
          const download = async () => {
            setExporting((prev) => ({ ...prev, [id]: true }));
            setErrors((prev) => ({ ...prev, [id]: undefined }));
            try {
              const blob = await exportReport(auditReports[id]!.session_id, {
                slides: selectedEntries.map((e) => ({
                  entry_id: e.id,
                  chart_type: defaultChartType(e),
                  heading: edits[e.id]?.heading,
                  explanation: edits[e.id]?.explanation,
                  caption: edits[e.id]?.caption,
                })),
                language,
                cover_title: cover[id]?.title,
                cover_subtitle: cover[id]?.subtitle,
                // The summary exactly as shown (and possibly edited), so the file matches the preview.
                summary_bullets: bulletsFor(id),
              });
              const url = URL.createObjectURL(blob);
              const link = document.createElement("a");
              link.href = url;
              link.download = "Program Manager AI Report.pptx";
              document.body.appendChild(link);
              link.click();
              link.remove();
              URL.revokeObjectURL(url);
            } catch (err) {
              setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not build the report." }));
            } finally {
              setExporting((prev) => ({ ...prev, [id]: false }));
            }
          };

          return (
            <section className="report-page__card" key={id}>
              <div className="report-page__card-head">
                <div className="report-page__card-head-left">
                  <h2 className="report-page__slot-title">{slot.title}</h2>
                  <span className="report-page__pill">REPORT READY</span>
                </div>
                <span className="report-page__filename">{files[id]!.name}</span>
              </div>

              {errors[id] && <p className="report-page__error">{errors[id]}</p>}

              <div className="report-page__stat-row">
                <StatTile icon={<IconLayers />} color="teal" value={doneEntries.length} label="Analyses" />
                {aiSuggestedCount > 0 && (
                  <StatTile icon={<IconSparkle />} color="purple" value={aiSuggestedCount} label="AI Suggested" />
                )}
              </div>

              <div className="report-page__summary-card">
                <h3 className="report-page__summary-title">
                  <IconSparkle /> Final Summary
                </h3>
                {summaryError[id] ? (
                  <div className="report-page__summary-error-row">
                    <p className="report-page__summary-error">{summaryError[id]}</p>
                    <button type="button" className="report-page__summary-retry" onClick={() => runReportSummary(id, selectedIds)}>
                      Try again
                    </button>
                  </div>
                ) : summaryLoading[id] && !bulletsFor(id) ? (
                  <ThinkingLoader messages={LOADING.reportSummary} />
                ) : bulletsFor(id) ? (
                  <ul className="report-page__summary-bullets">
                    {bulletsFor(id)!.map((bullet, i) => (
                      <li key={i}>{bullet}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="report-page__summary-status">Select at least one analysis to generate the final summary.</p>
                )}
              </div>

              <p className="report-page__included-title">This report will include:</p>
              <ul className="report-page__included-list">
                {tree.map(({ entry, depth }) => {
                  const entryTranslation = translations[id]?.[entry.id];
                  const displayName = edits[entry.id]?.heading || (entryTranslation?.name ?? entry.name);
                  const displayInterpretation = entryTranslation?.interpretation ?? entry.interpretation;
                  const stale = staleIds.has(entry.id);
                  const slideNumber = slideNumbers.get(entry.id);
                  return (
                    <li
                      key={entry.id}
                      className={`report-page__slide-thumb${draggingId === entry.id ? " report-page__slide-thumb--dragging" : ""}${stale ? " report-page__slide-thumb--stale" : ""}`}
                      style={depth > 0 ? { marginLeft: depth * 28 } : undefined}
                      draggable
                      onDragStart={() => setDraggingId(entry.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        handleDrop(id, entry.id, parentOf);
                      }}
                      onDragEnd={() => setDraggingId(null)}
                    >
                      <div className="report-page__slide-thumb-head">
                        <span className="report-page__drag-handle" aria-label="Drag to reorder">
                          <IconGripVertical />
                        </span>
                        <input
                          type="checkbox"
                          checked={!stale && !!selected[entry.id]}
                          disabled={stale}
                          onChange={() => toggleSelected(entry.id)}
                        />
                        <span className={`report-page__slide-label${slideNumber ? "" : " report-page__slide-label--off"}`}>
                          {slideNumber ? `Slide ${slideNumber}` : "Not included"}
                        </span>
                        <span className="report-page__entry-name">{displayName}</span>
                        {stale && <span className="report-page__stale-badge">Stale</span>}
                      </div>
                      {entry.chain && <p className="report-page__slide-subtitle">{drilldownSubtitle(entry.chain)}</p>}
                      {stale && (
                        <p className="report-page__stale-note">
                          Stale - an earlier level's filter or ranking changed. Refresh it on the Analysis page to include it.
                        </p>
                      )}
                      <button
                        type="button"
                        className="report-page__chart-toggle"
                        aria-expanded={!!expandedCharts[entry.id]}
                        onClick={() => setExpandedCharts((prev) => ({ ...prev, [entry.id]: !prev[entry.id] }))}
                      >
                        <span className={`report-page__chart-toggle-arrow${expandedCharts[entry.id] ? " report-page__chart-toggle-arrow--open" : ""}`}>
                          <IconChevronDown />
                        </span>
                        {expandedCharts[entry.id] ? "Hide chart" : "Show chart"}
                      </button>
                      {expandedCharts[entry.id] && (
                        <div className="report-page__slide-thumb-body">
                          <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} />
                        </div>
                      )}
                      {displayInterpretation && (
                        <p className="report-page__slide-thumb-caption">{shortenInterpretation(displayInterpretation)}</p>
                      )}
                    </li>
                  );
                })}
                <li className="report-page__included-summary">Final summary</li>
              </ul>

              {(() => {
                const exportRow = (
                  <div className="report-page__export-row">
                    {slotsWithResults.length > 1 && <span className="report-page__export-label">{slot.title}</span>}
                    <button
                      type="button"
                      className="report-page__preview-btn"
                      disabled={doneEntries.length === 0}
                      onClick={() => setEditorSlot(id)}
                    >
                      <IconEye />
                      Preview &amp; edit slides
                    </button>
                    <button
                      type="button"
                      className={`report-page__download-btn ${selectedIds.length === 0 || exporting[id] ? "report-page__download-btn--disabled" : ""}`}
                      disabled={selectedIds.length === 0 || !!exporting[id]}
                      onClick={download}
                    >
                      <IconDownload />
                      {selectedIds.length === 0
                        ? "Select at least one analysis"
                        : exporting[id]
                          ? "Building report…"
                          : "Download Report"}
                    </button>
                  </div>
                );
                return (
                  <>
                    {exportTop && createPortal(exportRow, exportTop)}
                    {exportBottom && createPortal(exportRow, exportBottom)}
                  </>
                );
              })()}

              {editorSlot === id && (
                <ReportEditorModal
                  entries={doneEntriesRaw}
                  staleIds={staleIds}
                  translations={translations[id]}
                  deck={deck}
                  coverDefaults={{ title: "Cold Chain Analysis", subtitle: files[id]!.name.replace(/\.(xlsx|xlsm|xls|csv)$/i, "") }}
                  summaryLoading={!!summaryLoading[id]}
                  summaryError={summaryError[id]}
                  onChange={applyDeck}
                  onRegenerateSummary={() => regenerateSummary(id)}
                  onClose={() => setEditorSlot(null)}
                />
              )}
            </section>
          );
        })}

        <div className="report-page__actions">
          <button type="button" className="report-page__btn report-page__btn--secondary report-page__nav-btn" onClick={() => navigate("/analysis")}>
            <IconChevronLeft /> Back to Analysis
          </button>
          <div className="report-page__export-host" ref={setExportBottom} />
        </div>
      </main>
    </div>
  );
}
