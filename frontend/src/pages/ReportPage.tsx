import ThinkingLoader from "../components/ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import AnalysisChart from "../components/AnalysisChart";
import { ContentSlidePreview, CoverSlidePreview, SummarySlidePreview, ThumbScaler } from "../components/SlidePreview";
import { loadJson, saveJson } from "../utils/sessionPersistence";
import { shortExplanation } from "../utils/slideText";
import {
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconClipboard,
  IconDoc,
  IconDownload,
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
  downloadReportUrl,
  type AnalysisRepositoryEntry,
  type EntryTranslation,
  type LanguageOption,
} from "../api/audit";
import { buildReportTree, drilldownSubtitle, isStaleEntry } from "../utils/reportTree";
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

// The entry's own chart type goes to the export as it is: the backend renders bar/line/combo/pie natively,
// turns a heatmap into grouped columns and anything else (table) into a data table. (Forcing unsupported types
// to "bar" used to draw a heatmap as a row of zeros.)
function defaultChartType(entry: AnalysisRepositoryEntry): string {
  return entry.chart_type ?? "bar";
}

// What the PM ticked, the slide order and the language survive leaving this page (to run
// another drill-down on the Analysis page, say) and coming back: they are keyed by the
// backend session ids, so a new session starts clean.
interface SavedReportState {
  selected: Record<string, boolean>;
  slideOrder: Partial<Record<UploadSlotId, string[]>>;
  language: string;
}

const reportStateKey = (sessionKey: string) => `pmai.report.${sessionKey}`;

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [repositories, setRepositories] = useState<RepositoriesState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  // The PM's own chosen slide order (drag-reorderable) -- frontend-only
  // until download time, when it's sent to the backend so the exported
  // .pptx matches this preview's order exactly.
  const [slideOrder, setSlideOrder] = useState<Partial<Record<UploadSlotId, string[]>>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // The page shown large in the stage (cover, an analysis id, or "summary"), per slot.
  // Charts inside the "This report will include" rows start collapsed.
  const [expandedCharts, setExpandedCharts] = useState<Record<string, boolean>>({});
  // Which slot's "Select pages" dropdown is open (it closes on an outside click or Escape).
  const [pagesOpen, setPagesOpen] = useState<UploadSlotId | null>(null);
  const [activeSlide, setActiveSlide] = useState<Partial<Record<UploadSlotId, string>>>({});
  // The Report's own closing-slide bullet points -- synthesized from the
  // included slides' interpretations (see final_summary_agent.py), NOT the
  // Analysis page's KPI-highlights Summary. Bullets, not one paragraph, to
  // match the reference deck's own bullet-point closing slide.
  const [summaryBullets, setSummaryBullets] = useState<Partial<Record<UploadSlotId, string[]>>>({});
  const [summaryLoading, setSummaryLoading] = useState<LoadingState>({});
  const [summaryError, setSummaryError] = useState<ErrorsState>({});

  const [languages, setLanguages] = useState<LanguageOption[]>([{ code: "en", name: "English" }]);
  const [language, setLanguage] = useState("en");
  // Translated {entryId: {name, interpretation}} per slot, for whichever
  // language is picked -- mirrors what build_report puts on each slide, so
  // this on-screen list matches the .pptx before the PM ever downloads it.
  const [translations, setTranslations] = useState<Partial<Record<UploadSlotId, Record<string, EntryTranslation>>>>({});

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  // Restore the PM's selection/order/language for these sessions, then save every change.
  // `hydratedFor` keeps the save effect from writing the empty initial state over the
  // saved one before the restore has landed.
  const sessionKey = auditedReady.map((id) => auditReports[id]!.session_id).join("|");
  const [hydratedFor, setHydratedFor] = useState("");
  useEffect(() => {
    if (!sessionKey) return;
    const saved = loadJson<SavedReportState>(reportStateKey(sessionKey));
    if (saved) {
      setSelected(saved.selected ?? {});
      setSlideOrder(saved.slideOrder ?? {});
      setLanguage(saved.language ?? "en");
    }
    setHydratedFor(sessionKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionKey]);
  useEffect(() => {
    if (!sessionKey || hydratedFor !== sessionKey) return;
    saveJson(reportStateKey(sessionKey), { selected, slideOrder, language } satisfies SavedReportState);
  }, [sessionKey, hydratedFor, selected, slideOrder, language]);

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
  // `auditedReady` is a fresh array on every render, so it must not be a dependency
  // itself: with the old `[.., auditedReady]` and an unconditional `setTranslations({})`
  // this effect re-fired after every render, forever ("Maximum update depth exceeded"),
  // which froze the page -- the Report page then ignored "Back to Analysis". The effect
  // now depends on a stable key, and only clears state that actually has something in it.
  const auditedKey = auditedReady.join("|");
  useEffect(() => {
    if (language === "en") {
      setTranslations((prev) => (Object.keys(prev).length > 0 ? {} : prev));
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
  }, [language, repositories, auditedKey]);

  useEffect(() => {
    for (const id of auditedReady) {
      if (repositories[id] || loading[id]) continue;
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
      .then((res) => setSummaryBullets((prev) => ({ ...prev, [id]: res.bullets })))
      .catch((err) =>
        setSummaryError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not reach the summary agent.",
        }))
      )
      .finally(() => setSummaryLoading((prev) => ({ ...prev, [id]: false })));
  };

  // The final summary regenerates whenever the ordered, selected, done
  // entry-id list actually changes -- keyed by a signature of that exact
  // list so toggling a checkbox or reordering slides refreshes it, but
  // re-renders for unrelated reasons don't re-request it.
  const summarizedFor = useRef<Partial<Record<UploadSlotId, string>>>({});
  useEffect(() => {
    for (const id of auditedReady) {
      const order = slideOrder[id] ?? [];
      const doneIds = new Set((repositories[id] ?? []).filter((e) => e.run_status === "done").map((e) => e.id));
      const byId = new Map((repositories[id] ?? []).map((e) => [e.id, e]));
      const orderedSelectedDoneIds = buildReportTree(
        (repositories[id] ?? []).filter((e) => doneIds.has(e.id) && selected[e.id] && !isStaleEntry(e, byId)),
        order
      ).map((n) => n.entry.id);
      if (orderedSelectedDoneIds.length === 0) continue;
      const signature = orderedSelectedDoneIds.join("|");
      if (summarizedFor.current[id] === signature || summaryLoading[id]) continue;
      summarizedFor.current[id] = signature;
      runReportSummary(id, orderedSelectedDoneIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady, slideOrder, selected]);

  useEffect(() => {
    if (!pagesOpen) return;
    const onDown = (e: MouseEvent) => {
      if (!(e.target as HTMLElement | null)?.closest("[data-pages-menu]")) setPagesOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPagesOpen(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [pagesOpen]);

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
          subtitle="Every slide below is a preview of the exported .pptx. Tick the ones you want, drag to reorder, then download. Need another drill-down? Go back to Analysis -- your choices here are kept."
          action={
            <button type="button" className="report-page__btn report-page__btn--secondary report-page__nav-btn" onClick={() => navigate("/analysis")}>
              <IconChevronLeft /> Back to Analysis
            </button>
          }
        />

        <div className="report-page__language-picker">
          <label htmlFor="report-language">Report language</label>
          <select id="report-language" value={language} onChange={(e) => setLanguage(e.target.value)}>
            {languages.map((l) => (
              <option key={l.code} value={l.code}>
                {l.name}
              </option>
            ))}
          </select>
          {language !== "en" && (
            <span className="report-page__language-hint">
              Slide headings, interpretations, and footer text are translated -- chart data and column/category values are not.
            </span>
          )}
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
          const rowCount = auditReports[id]!.row_count;

          // -- studio: one large preview of the open page, and a panel of page thumbnails beside it
          // (select / deselect / reorder / jump), like a print dialog's page picker.
          const coverName = files[id]!.name.replace(/\.(xlsx|xlsm|xls|csv)$/i, "");
          type PageItem = { key: string; kind: "cover" | "entry" | "summary"; entry?: AnalysisRepositoryEntry };
          const pages: PageItem[] = [
            { key: "cover", kind: "cover" },
            ...tree.map(({ entry }) => ({ key: entry.id, kind: "entry" as const, entry })),
            { key: "summary", kind: "summary" },
          ];
          const isIncluded = (page: PageItem) =>
            page.kind !== "entry" || (!staleIds.has(page.key) && !!selected[page.key]);
          const pageNumbers = new Map<string, number>();
          pages.forEach((page) => {
            if (isIncluded(page)) pageNumbers.set(page.key, pageNumbers.size + 1);
          });
          const activeKey = pages.some((pg) => pg.key === activeSlide[id]) ? activeSlide[id]! : "cover";
          const activeIdx = pages.findIndex((pg) => pg.key === activeKey);
          const openPage = (key: string) => setActiveSlide((prev) => ({ ...prev, [id]: key }));
          const step = (delta: number) => openPage(pages[Math.min(pages.length - 1, Math.max(0, activeIdx + delta))].key);
          const pageName = (page: PageItem) =>
            page.kind === "cover" ? "Cover" : page.kind === "summary" ? "Summary" : (translations[id]?.[page.key]?.name ?? page.entry!.name);

          const renderPage = (page: PageItem, thumbnail: boolean) => {
            if (page.kind === "cover") return <CoverSlidePreview title="Cold Chain Analysis" subtitle={coverName} />;
            if (page.kind === "summary") {
              return summaryBullets[id] ? (
                <SummarySlidePreview bullets={summaryBullets[id]!} />
              ) : (
                <div className="report-studio__pending">{summaryLoading[id] ? "Writing the summary…" : "Select at least one analysis to generate the summary."}</div>
              );
            }
            const entry = page.entry!;
            const text = translations[id]?.[entry.id];
            const number = slideNumbers.get(entry.id);
            const heading = `${number ? `${number}  ` : ""}${text?.name ?? entry.name}`;
            return (
              <ContentSlidePreview
                heading={heading}
                explanation={shortExplanation(text?.interpretation ?? entry.interpretation)}
                caption={entry.chain ? drilldownSubtitle(entry.chain) : null}
              >
                <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} fill thumbnail={thumbnail} />
              </ContentSlidePreview>
            );
          };

          const selectableIds = doneEntriesRaw.filter((e) => !staleIds.has(e.id)).map((e) => e.id);
          const allSelected = selectableIds.length > 0 && selectableIds.every((eid) => selected[eid]);
          const onlyThis = selectedIds.length === 1 && selectedIds[0] === activeKey;
          const selectAll = () => setSelected((prev) => ({ ...prev, ...Object.fromEntries(selectableIds.map((eid) => [eid, true])) }));
          const selectOnlyThis = () => {
            if (!selectableIds.includes(activeKey)) return;
            setSelected((prev) => ({ ...prev, ...Object.fromEntries(doneEntriesRaw.map((e) => [e.id, e.id === activeKey && !staleIds.has(e.id)])) }));
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
                <StatTile icon={<IconDoc />} color="blue" value={rowCount.toLocaleString()} label="Rows" />
                <StatTile icon={<IconLayers />} color="teal" value={doneEntries.length} label="Analysis Tables" />
                {aiSuggestedCount > 0 && (
                  <StatTile icon={<IconSparkle />} color="purple" value={aiSuggestedCount} label="AI Suggested" />
                )}
              </div>

              <div className="report-toolbar">
                <p className="report-page__included-title">
                  Report preview &mdash; {selectedIds.length} of {doneEntries.length} analyses selected
                </p>
                <div className="pages-menu" data-pages-menu>
                  <button
                    type="button"
                    className={`pages-menu__trigger${pagesOpen === id ? " is-open" : ""}`}
                    aria-haspopup="dialog"
                    aria-expanded={pagesOpen === id}
                    onClick={() => setPagesOpen((cur) => (cur === id ? null : id))}
                  >
                    Select pages
                    <span className="pages-menu__count">{pageNumbers.size} of {pages.length}</span>
                    <IconChevronDown />
                  </button>
                  {pagesOpen === id && (
                    <div className="pages-menu__panel" role="dialog" aria-label="Select pages">
                  <div className="report-studio__modes" role="group" aria-label="Quick selection">
                    <button type="button" className={allSelected ? "is-on" : ""} onClick={selectAll}>All</button>
                    <button type="button" className={onlyThis ? "is-on" : ""} onClick={selectOnlyThis} disabled={!selectableIds.includes(activeKey)}>
                      This page
                    </button>
                    <button type="button" className={!allSelected && !onlyThis ? "is-on" : ""} onClick={() => undefined}>
                      Custom <IconChevronDown />
                    </button>
                  </div>

                  <ul className="report-studio__thumbs">
                    {pages.map((page) => {
                      const included = isIncluded(page);
                      const stale = page.kind === "entry" && staleIds.has(page.key);
                      return (
                        <li
                          key={page.key}
                          className={`report-studio__thumb${page.key === activeKey ? " is-active" : ""}${included ? "" : " is-off"}${draggingId === page.key ? " is-dragging" : ""}`}
                          draggable={page.kind === "entry"}
                          onDragStart={() => page.kind === "entry" && setDraggingId(page.key)}
                          onDragOver={(e) => e.preventDefault()}
                          onDrop={(e) => {
                            e.preventDefault();
                            if (page.kind === "entry") handleDrop(id, page.key, parentOf);
                          }}
                          onDragEnd={() => setDraggingId(null)}
                        >
                          <button type="button" className="report-studio__thumb-art" onClick={() => openPage(page.key)} aria-label={`Open ${pageName(page)}`}>
                            <ThumbScaler>{renderPage(page, true)}</ThumbScaler>
                          </button>
                          {page.kind === "entry" ? (
                            <input
                              type="checkbox"
                              className="report-studio__thumb-check"
                              checked={included}
                              disabled={stale}
                              onChange={() => toggleSelected(page.key)}
                              aria-label={`Include ${pageName(page)}`}
                            />
                          ) : (
                            <span className="report-studio__thumb-lock" title="Always included">✓</span>
                          )}
                          <span className="report-studio__thumb-num">{pageNumbers.get(page.key) ?? "–"}</span>
                          <span className="report-studio__thumb-name">{stale ? "Stale · " : ""}{pageName(page)}</span>
                        </li>
                      );
                    })}
                  </ul>
                    </div>
                  )}
                </div>
              </div>

              <div className="report-studio__stage" id={`report-stage-${id}`}>
                <div className="report-studio__stage-head">
                  <div className="report-studio__stage-title">
                    <span className={`report-studio__badge${pageNumbers.has(activeKey) ? "" : " report-studio__badge--off"}`}>
                      {pageNumbers.has(activeKey) ? `Page ${pageNumbers.get(activeKey)}` : "Not in report"}
                    </span>
                    <strong>{pageName(pages[activeIdx])}</strong>
                  </div>
                  <div className="report-studio__stage-actions">
                    {pages[activeIdx].kind === "entry" &&
                      (staleIds.has(activeKey) ? (
                        <span className="report-page__stale-badge">Stale</span>
                      ) : (
                        <label className="report-studio__include">
                          <input type="checkbox" checked={!!selected[activeKey]} onChange={() => toggleSelected(activeKey)} />
                          Include in report
                        </label>
                      ))}
                    <button type="button" className="report-studio__nav" onClick={() => step(-1)} disabled={activeIdx === 0} aria-label="Previous page">
                      <IconChevronLeft />
                    </button>
                    <button type="button" className="report-studio__nav" onClick={() => step(1)} disabled={activeIdx === pages.length - 1} aria-label="Next page">
                      <IconChevronRight />
                    </button>
                  </div>
                </div>
                {staleIds.has(activeKey) && (
                  <p className="report-page__stale-note">
                    Stale - an earlier level's filter or ranking changed. Refresh it on the Analysis page to include it.
                  </p>
                )}
                <div className="report-studio__frame">{renderPage(pages[activeIdx], false)}</div>
                {summaryError[id] && (
                  <div className="report-page__summary-error-row">
                    <p className="report-page__summary-error">{summaryError[id]}</p>
                    <button type="button" className="report-page__summary-retry" onClick={() => runReportSummary(id, selectedIds)}>
                      Try again
                    </button>
                  </div>
                )}
              </div>

              <p className="report-page__included-title">This report will include:</p>
              <ul className="report-page__included-list">
                {tree.map(({ entry, depth }) => {
                  const entryTranslation = translations[id]?.[entry.id];
                  const displayName = entryTranslation?.name ?? entry.name;
                  const displayInterpretation = entryTranslation?.interpretation ?? entry.interpretation;
                  const stale = staleIds.has(entry.id);
                  const slideNumber = slideNumbers.get(entry.id);
                  return (
                    <li
                      key={entry.id}
                      className={`report-page__slide-thumb${draggingId === entry.id ? " report-page__slide-thumb--dragging" : ""}${stale ? " report-page__slide-thumb--stale" : ""}${activeKey === entry.id ? " report-page__slide-thumb--current" : ""}`}
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
                        <button
                          type="button"
                          className="report-page__entry-name report-page__entry-name--link"
                          title="Show this page in the preview above"
                          onClick={() => {
                            openPage(entry.id);
                            document.getElementById(`report-stage-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                          }}
                        >
                          {displayName}
                        </button>
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
                        <p className="report-page__slide-thumb-caption">{shortExplanation(displayInterpretation)}</p>
                      )}
                    </li>
                  );
                })}
                <li className="report-page__included-summary">Final summary</li>
              </ul>

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
                ) : summaryLoading[id] && !summaryBullets[id] ? (
                  <ThinkingLoader messages={LOADING.reportSummary} />
                ) : summaryBullets[id] ? (
                  <ul className="report-page__summary-bullets">
                    {summaryBullets[id]!.map((bullet, i) => (
                      <li key={i}>{bullet}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="report-page__summary-status">Select at least one analysis to generate the final summary.</p>
                )}
              </div>

              <a
              className={`report-page__download-btn ${selectedIds.length === 0 ? "report-page__download-btn--disabled" : ""}`}
              href={
                selectedIds.length > 0
                  ? downloadReportUrl(
                      auditReports[id]!.session_id,
                      selectedEntries.map((e) => ({ entryId: e.id, chartType: defaultChartType(e) })),
                      language
                    )
                  : undefined
              }
              aria-disabled={selectedIds.length === 0}
              onClick={(e) => {
                if (selectedIds.length === 0) e.preventDefault();
              }}
              download
            >
              <IconDownload />
              {selectedIds.length === 0 ? "Select at least one analysis" : `Download Report (${selectedIds.length} slides + summary)`}
            </a>
            </section>
          );
        })}

        <div className="report-page__actions">
          <button type="button" className="report-page__btn report-page__btn--secondary report-page__nav-btn" onClick={() => navigate("/analysis")}>
            <IconChevronLeft /> Back to Analysis
          </button>
        </div>
      </main>
    </div>
  );
}
