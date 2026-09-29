import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import AnalysisChart from "../components/AnalysisChart";
import {
  IconChevronDown,
  IconChevronLeft,
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

  const [repositories, setRepositories] = useState<RepositoriesState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  // The PM's own chosen slide order (drag-reorderable) -- frontend-only
  // until download time, when it's sent to the backend so the exported
  // .pptx matches this preview's order exactly.
  const [slideOrder, setSlideOrder] = useState<Partial<Record<UploadSlotId, string[]>>>({});
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // Charts start collapsed -- a slide is mostly checkbox/name/chart-type
  // until the PM asks to actually see the chart.
  const [expandedCharts, setExpandedCharts] = useState<Record<string, boolean>>({});

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
      setTranslations({});
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
      if (repositories[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      fetchAnalysisRepository(sessionId)
        .then((res) => {
          setRepositories((prev) => ({ ...prev, [id]: res.entries }));
          setSelected((prev) => {
            const next = { ...prev };
            for (const entry of res.entries) {
              if (entry.run_status === "done" && !(entry.id in next)) next[entry.id] = true;
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
      const orderedSelectedDoneIds = order.filter((eid) => doneIds.has(eid) && selected[eid]);
      if (orderedSelectedDoneIds.length === 0) continue;
      const signature = orderedSelectedDoneIds.join("|");
      if (summarizedFor.current[id] === signature || summaryLoading[id]) continue;
      summarizedFor.current[id] = signature;
      runReportSummary(id, orderedSelectedDoneIds);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady, slideOrder, selected]);

  const toggleSelected = (entryId: string) => setSelected((prev) => ({ ...prev, [entryId]: !prev[entryId] }));

  const handleDrop = (id: UploadSlotId, targetEntryId: string) => {
    if (!draggingId || draggingId === targetEntryId) {
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
                ? "Checking whether any analyses have been run…"
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
          const orderIndex = new Map(order.map((eid, idx) => [eid, idx]));
          const doneEntries = [...doneEntriesRaw].sort(
            (a, b) => (orderIndex.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (orderIndex.get(b.id) ?? Number.MAX_SAFE_INTEGER)
          );
          const aiSuggestedCount = doneEntries.filter((e) => e.source === "ai_suggested").length;
          const selectedEntries = doneEntries.filter((e) => selected[e.id]);
          const selectedIds = selectedEntries.map((e) => e.id);
          const rowCount = auditReports[id]!.row_count;

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

              <p className="report-page__included-title">This report will include:</p>
              <ul className="report-page__included-list">
                {doneEntries.map((entry, idx) => {
                  const entryTranslation = translations[id]?.[entry.id];
                  const displayName = entryTranslation?.name ?? entry.name;
                  const displayInterpretation = entryTranslation?.interpretation ?? entry.interpretation;
                  return (
                    <li
                      key={entry.id}
                      className={`report-page__slide-thumb${draggingId === entry.id ? " report-page__slide-thumb--dragging" : ""}`}
                      draggable
                      onDragStart={() => setDraggingId(entry.id)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => {
                        e.preventDefault();
                        handleDrop(id, entry.id);
                      }}
                      onDragEnd={() => setDraggingId(null)}
                    >
                      <div className="report-page__slide-thumb-head">
                        <span className="report-page__drag-handle" aria-label="Drag to reorder">
                          <IconGripVertical />
                        </span>
                        <input type="checkbox" checked={!!selected[entry.id]} onChange={() => toggleSelected(entry.id)} />
                        <span className="report-page__slide-label">Slide {idx + 1}</span>
                        <span className="report-page__entry-name">{displayName}</span>
                      </div>
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
                  <p className="report-page__summary-status">Writing the final summary…</p>
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
