import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import OverallAnalysisCard from "../components/OverallAnalysisCard";
import AnalysisChart from "../components/AnalysisChart";
import { IconChevronLeft, IconClipboard, IconDoc, IconDownload, IconLayers, IconSparkle } from "../components/icons";
import {
  fetchAnalysisRepository,
  fetchOverallAnalysis,
  fetchSupportedReportLanguages,
  AuditApiError,
  downloadReportUrl,
  type AnalysisRepositoryEntry,
  type LanguageOption,
  type OverallAnalysisReport,
} from "../api/audit";
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

const CHART_TYPE_LABELS: Record<string, string> = {
  bar: "Bar chart",
  grouped_bar: "Grouped bar chart",
  line: "Line chart",
  pie: "Pie chart",
  scatter: "Scatter chart",
  heatmap: "Heatmap",
  table: "Table",
};

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [repositories, setRepositories] = useState<RepositoriesState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const [overallReports, setOverallReports] = useState<Partial<Record<UploadSlotId, OverallAnalysisReport>>>({});
  const [overallLoading, setOverallLoading] = useState<LoadingState>({});
  const [overallError, setOverallError] = useState<ErrorsState>({});

  const [languages, setLanguages] = useState<LanguageOption[]>([{ code: "en", name: "English" }]);
  const [language, setLanguage] = useState("en");

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

  // The summary generates on its own once a slot's analyses are loaded (and
  // at least one has run) -- once per visit; "Try again" covers a failure.
  const summaryRequested = useRef<Set<UploadSlotId>>(new Set());
  useEffect(() => {
    for (const id of auditedReady) {
      const hasDone = (repositories[id] ?? []).some((e) => e.run_status === "done");
      if (!hasDone || summaryRequested.current.has(id)) continue;
      summaryRequested.current.add(id);
      runOverallAnalysis(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repositories, auditedReady]);

  const toggleSelected = (entryId: string) => setSelected((prev) => ({ ...prev, [entryId]: !prev[entryId] }));

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
          subtitle="Pick which completed analyses go into the downloadable report, preview each slide, then export it as a .pptx."
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
              Slide headings and footer text are translated -- analysis names, interpretations, and data values are not.
            </span>
          )}
        </div>

        {slotsWithResults.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const doneEntries = (repositories[id] ?? []).filter((e) => e.run_status === "done");
          const aiSuggestedCount = doneEntries.filter((e) => e.source === "ai_suggested").length;
          const selectedIds = doneEntries.filter((e) => selected[e.id]).map((e) => e.id);
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
                {doneEntries.map((entry, idx) => (
                  <li key={entry.id} className="report-page__slide-thumb">
                    <label className="report-page__slide-thumb-head">
                      <input type="checkbox" checked={!!selected[entry.id]} onChange={() => toggleSelected(entry.id)} />
                      <span className="report-page__slide-label">Slide {idx + 1}</span>
                      <span className="report-page__entry-name">{entry.name}</span>
                      {entry.chart_type && (
                        <span className="report-page__chart-type-pill">
                          {CHART_TYPE_LABELS[entry.chart_type] ?? entry.chart_type}
                        </span>
                      )}
                    </label>
                    <div className="report-page__slide-thumb-body">
                      <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} />
                    </div>
                    {entry.interpretation && <p className="report-page__slide-thumb-caption">{entry.interpretation}</p>}
                  </li>
                ))}
                <li className="report-page__included-summary">Overall analysis summary</li>
              </ul>

              <OverallAnalysisCard
                report={overallReports[id]}
                loading={!!overallLoading[id]}
                error={overallError[id]}
                waitingForAnalyses={false}
                onRetry={() => runOverallAnalysis(id)}
              />

              <a
                className={`report-page__download-btn ${selectedIds.length === 0 ? "report-page__download-btn--disabled" : ""}`}
                href={selectedIds.length > 0 ? downloadReportUrl(auditReports[id]!.session_id, selectedIds, language) : undefined}
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
