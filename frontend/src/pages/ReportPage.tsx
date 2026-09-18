import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import Modal from "../components/Modal";
import PivotFilterBar from "../components/PivotFilterBar";
import ReportSlidePreview from "../components/ReportSlidePreview";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconLayers, IconSparkle, IconWarnTriangle } from "../components/icons";
import {
  downloadReportUrl,
  fetchPivotReport,
  fetchReportFilters,
  fetchReportFilterScope,
  fetchReportPreview,
  fetchReportSlides,
  fetchReportTitles,
  fetchSupportedLanguages,
  saveReportFilters,
  saveReportFilterScope,
  saveReportSlides,
  saveReportTitle,
  uploadReportTemplate,
  AuditApiError,
  type LanguageOption,
  type PivotFilter,
  type PivotReport,
  type PivotResult,
  type ReportSlide,
  type ReportTemplateSummary,
} from "../api/audit";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./ReportPage.css";

interface ReportPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type PivotReportsState = Partial<Record<UploadSlotId, PivotReport>>;
type ReportFiltersState = Partial<Record<UploadSlotId, PivotFilter[]>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type SlidePlansState = Partial<Record<UploadSlotId, ReportSlide[]>>;

// The raw column the data uses for a shipment's departure -- not one of the
// categorical filterable_columns slicers, so it gets its own date-range
// control alongside them.
const DEPARTURE_COLUMN = "Actual Departure Time CET";

function selectionsFromFilters(filters: PivotFilter[], filterableColumns: string[]): Record<string, string[] | undefined> {
  const selections: Record<string, string[] | undefined> = {};
  for (const f of filters) {
    if (f.op === "in" && filterableColumns.includes(f.column)) {
      selections[f.column] = (Array.isArray(f.value) ? f.value : [f.value]).map(String);
    }
  }
  return selections;
}

function globalColumnsFor(pivots: PivotResult[]): string[] {
  const columns = new Set<string>();
  for (const p of pivots) for (const c of p.filterable_columns) columns.add(c);
  return [...columns];
}

function globalOptionsFor(pivots: PivotResult[], columns: string[]): Record<string, string[]> {
  const options: Record<string, string[]> = {};
  for (const column of columns) {
    const values = new Set<string>();
    for (const p of pivots) for (const v of p.filter_options[column] ?? []) values.add(v);
    options[column] = [...values].sort();
  }
  return options;
}

function globalCombinationsFor(pivots: PivotResult[]): Record<string, string>[] {
  return pivots.flatMap((p) => p.filter_combinations);
}

function rangeFromFilters(filters: PivotFilter[]): { start: string; end: string } {
  const gte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "gte");
  const lte = filters.find((f) => f.column === DEPARTURE_COLUMN && f.op === "lte");
  return {
    start: typeof gte?.value === "string" ? gte.value.slice(0, 10) : "",
    end: typeof lte?.value === "string" ? lte.value.slice(0, 10) : "",
  };
}

// Which columns the shared filter is actually constraining right now --
// only these are worth a per-pivot "apply this to me?" toggle.
function activeColumns(filters: PivotFilter[]): string[] {
  return [...new Set(filters.map((f) => f.column))];
}

function columnLabel(column: string): string {
  return column === DEPARTURE_COLUMN ? "Departure time" : column;
}

/** Deck position of each included slide, so the numbering the user sees
 * matches the exported file rather than counting slides they switched off. */
function slideNumbers(slides: ReportSlide[]): Map<string, number> {
  const numbers = new Map<string, number>();
  let n = 0;
  for (const slide of slides) {
    if (slide.included) numbers.set(slide.key, ++n);
  }
  return numbers;
}

export default function ReportPage({ files, auditReports }: ReportPageProps) {
  const navigate = useNavigate();

  const [reports, setReports] = useState<PivotReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});

  const [reportFilters, setReportFilters] = useState<ReportFiltersState>({});
  const [filtersLoading, setFiltersLoading] = useState<LoadingState>({});
  const [savingFilters, setSavingFilters] = useState<LoadingState>({});
  const [rangeDraft, setRangeDraft] = useState<Partial<Record<UploadSlotId, { start: string; end: string }>>>({});

  const [filterScope, setFilterScope] = useState<Partial<Record<UploadSlotId, Record<string, string[]>>>>({});
  const [scopeLoading, setScopeLoading] = useState<LoadingState>({});
  const [savingScope, setSavingScope] = useState<Record<string, boolean>>({});

  const [titles, setTitles] = useState<Partial<Record<UploadSlotId, Record<string, string>>>>({});
  const [titlesLoading, setTitlesLoading] = useState<LoadingState>({});
  const [savingTitle, setSavingTitle] = useState<Record<string, boolean>>({});

  const [templateSummary, setTemplateSummary] = useState<ReportTemplateSummary | null>(null);
  const [templateLoading, setTemplateLoading] = useState(false);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const hasTemplateFile = !!files.reportTemplate;

  const [languages, setLanguages] = useState<LanguageOption[]>([{ code: "en", name: "English" }]);
  const [language, setLanguage] = useState("en");
  const [translationAvailable, setTranslationAvailable] = useState(true);

  // The planned deck itself, straight from the backend (see
  // report_generator.plan_report) -- the same plan the .pptx is built from,
  // so the slide list and the preview below can't drift from the file.
  const [plans, setPlans] = useState<SlidePlansState>({});
  const [planLoading, setPlanLoading] = useState<LoadingState>({});
  const [savingSlides, setSavingSlides] = useState<LoadingState>({});
  const [previewOpen, setPreviewOpen] = useState<UploadSlotId | null>(null);
  // Bumped whenever something the plan depends on is saved (a filter, a
  // scope toggle, a slide title), to trigger a re-plan.
  const [planVersion, setPlanVersion] = useState(0);
  const bumpPlan = () => setPlanVersion((v) => v + 1);

  // The language list only ever needs fetching once -- unlike everything
  // else on this page it isn't per-session/per-slot, just a fixed catalog of
  // what the backend's translation_service currently supports. Falling back
  // to English-only (the initial state above) if this fails is fine -- the
  // report always downloads, just without the picker filled in.
  useEffect(() => {
    fetchSupportedLanguages()
      .then((res) => {
        setLanguages(res.languages);
        setTranslationAvailable(res.available);
      })
      .catch(() => {});
  }, []);

  // Optional -- when a Report Template file was selected on the Upload page,
  // send it once so every download for the rest of this session uses it as
  // the base deck instead of the built-in layout (see report_generator.py's
  // build_report / TemplateReportBuilder).
  useEffect(() => {
    if (!hasTemplateFile || templateSummary || templateLoading || templateError) return;
    setTemplateLoading(true);
    uploadReportTemplate(files.reportTemplate!)
      .then(setTemplateSummary)
      .catch((err) => setTemplateError(err instanceof AuditApiError ? err.message : "Could not upload the Report Template."))
      .finally(() => setTemplateLoading(false));
  }, [hasTemplateFile, files.reportTemplate, templateSummary, templateLoading, templateError]);

  const auditedReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");

  useEffect(() => {
    for (const id of auditedReady) {
      if (reports[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      fetchPivotReport(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not check the analysis for this source.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auditedReady, auditReports]);

  const slotsReady = auditedReady.filter((id) => (reports[id]?.pivots.length ?? 0) > 0);

  useEffect(() => {
    for (const id of slotsReady) {
      if (reportFilters[id] || filtersLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setFiltersLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportFilters(sessionId)
        .then((res) => setReportFilters((prev) => ({ ...prev, [id]: res.filters })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load report filters." }))
        )
        .finally(() => setFiltersLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (filterScope[id] || scopeLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setScopeLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportFilterScope(sessionId)
        .then((res) => setFilterScope((prev) => ({ ...prev, [id]: res.scope })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load filter scope." }))
        )
        .finally(() => setScopeLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  useEffect(() => {
    for (const id of slotsReady) {
      if (titles[id] || titlesLoading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setTitlesLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportTitles(sessionId)
        .then((res) => setTitles((prev) => ({ ...prev, [id]: res.titles })))
        .catch((err) =>
          setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not load slide titles." }))
        )
        .finally(() => setTitlesLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady, auditReports]);

  // Re-planning re-runs every pivot on the backend, so it deliberately keys
  // off an explicit `planVersion` bump rather than every filter/title state
  // change -- one plan per actual save, not one per keystroke.
  //
  // A re-plan is never skipped just because one is already in flight: the
  // first plan for a slot takes seconds (every pivot is recomputed), and
  // switching language inside that window is exactly when a user does it.
  // Instead each request carries a token, and only the newest one for a slot
  // is allowed to write -- so an earlier, slower response can't land on top
  // of a newer language's plan.
  const planToken = useRef<Partial<Record<UploadSlotId, number>>>({});
  const planSeq = useRef(0);

  const loadPlan = useCallback(
    (id: UploadSlotId) => {
      const sessionId = auditReports[id]!.session_id;
      const token = ++planSeq.current;
      planToken.current[id] = token;
      const isCurrent = () => planToken.current[id] === token;

      setPlanLoading((prev) => ({ ...prev, [id]: true }));
      fetchReportPreview(sessionId, language)
        .then((res) => {
          if (isCurrent()) setPlans((prev) => ({ ...prev, [id]: res.slides }));
        })
        .catch((err) => {
          if (isCurrent()) {
            setErrors((prev) => ({
              ...prev,
              [id]: err instanceof AuditApiError ? err.message : "Could not build the report preview.",
            }));
          }
        })
        .finally(() => {
          // Leave the spinner up if a newer request is still running -- it
          // owns the loading state now.
          if (isCurrent()) setPlanLoading((prev) => ({ ...prev, [id]: false }));
        });
    },
    [auditReports, language]
  );

  useEffect(() => {
    for (const id of slotsReady) loadPlan(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slotsReady.join(","), planVersion, language]);

  // The saved deselections are read once per slot, purely to reconcile:
  // /report-preview already applies them to the plan it returns, so this is
  // only here to catch a key for a slide that no longer exists and clear it.
  // Keyed on the slide keys themselves rather than `plans`, since only a
  // change to the SET of slides can strand one -- ticking a checkbox
  // rewrites `plans` too, and re-reading the server on every tick would be
  // pure noise.
  const planKeySignature = slotsReady.map((id) => `${id}:${(plans[id] ?? []).map((s) => s.key).join("|")}`).join(";;");

  useEffect(() => {
    for (const id of slotsReady) {
      const plan = plans[id];
      if (!plan) continue;
      const sessionId = auditReports[id]!.session_id;
      fetchReportSlides(sessionId)
        .then((res) => {
          const live = new Set(plan.map((s) => s.key));
          const stale = res.excluded_keys.filter((key) => !live.has(key));
          if (stale.length > 0) {
            saveReportSlides(sessionId, res.excluded_keys.filter((key) => live.has(key))).catch(() => {});
          }
        })
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [planKeySignature]);

  const handleToggleSlide = (id: UploadSlotId, key: string) => {
    const plan = plans[id];
    if (!plan) return;
    // Flip it locally first -- re-planning from the backend just to learn
    // the answer to a checkbox would re-run every pivot for no new
    // information. A failed save re-plans and puts it back.
    const nextPlan = plan.map((s) => (s.key === key ? { ...s, included: !s.included } : s));
    setPlans((prev) => ({ ...prev, [id]: nextPlan }));

    const sessionId = auditReports[id]!.session_id;
    setSavingSlides((prev) => ({ ...prev, [id]: true }));
    saveReportSlides(sessionId, nextPlan.filter((s) => !s.included).map((s) => s.key))
      .catch((err) => {
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save the slide selection." }));
        loadPlan(id);
      })
      .finally(() => setSavingSlides((prev) => ({ ...prev, [id]: false })));
  };

  const handleSaveTitle = (id: UploadSlotId, pivotId: string, title: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingTitle((prev) => ({ ...prev, [pivotId]: true }));
    saveReportTitle(sessionId, pivotId, title)
      .then((res) => setTitles((prev) => ({ ...prev, [id]: res.titles })))
      .then(bumpPlan)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not rename the slide." }))
      )
      .finally(() => setSavingTitle((prev) => ({ ...prev, [pivotId]: false })));
  };

  // Toggles ONE column on/off for ONE pivot -- starts from the full active
  // set if this pivot has no override yet. Always saves the resulting list
  // explicitly, even when it happens to equal every active column: some
  // pivots default to a narrower scope than "everything" (see the backend's
  // DEFAULT_SCOPE_EXCLUSIONS), so clearing back to an implicit "no override"
  // here would silently revert the user's own explicit choice back to that
  // narrower default the next time this page loads, instead of keeping
  // whatever they last set as a static, sticky selection.
  const handleToggleScope = (id: UploadSlotId, pivotId: string, column: string, allActive: string[]) => {
    const sessionId = auditReports[id]!.session_id;
    const baseline = filterScope[id]?.[pivotId] ?? allActive;
    const next = baseline.includes(column) ? baseline.filter((c) => c !== column) : [...baseline, column];
    setSavingScope((prev) => ({ ...prev, [pivotId]: true }));
    saveReportFilterScope(sessionId, pivotId, next)
      .then((res) => setFilterScope((prev) => ({ ...prev, [id]: res.scope })))
      .then(bumpPlan)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save filter scope." }))
      )
      .finally(() => setSavingScope((prev) => ({ ...prev, [pivotId]: false })));
  };

  const saveFilters = (id: UploadSlotId, filters: PivotFilter[]) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingFilters((prev) => ({ ...prev, [id]: true }));
    saveReportFilters(sessionId, filters)
      .then((res) => setReportFilters((prev) => ({ ...prev, [id]: res.filters })))
      .then(bumpPlan)
      .catch((err) =>
        setErrors((prev) => ({ ...prev, [id]: err instanceof AuditApiError ? err.message : "Could not save filters." }))
      )
      .finally(() => setSavingFilters((prev) => ({ ...prev, [id]: false })));
  };

  const handleSaveCategorical = (id: UploadSlotId, nextSelections: Record<string, string[] | undefined>) => {
    const current = reportFilters[id] ?? [];
    const inFilters: PivotFilter[] = [];
    for (const [column, values] of Object.entries(nextSelections)) {
      if (values !== undefined) inFilters.push({ column, op: "in", value: values });
    }
    const preservedRange = current.filter((f) => f.column === DEPARTURE_COLUMN);
    saveFilters(id, [...inFilters, ...preservedRange]);
  };

  const handleApplyRange = (id: UploadSlotId, start: string, end: string) => {
    const current = reportFilters[id] ?? [];
    const rangeFilters: PivotFilter[] =
      start && end
        ? [
            { column: DEPARTURE_COLUMN, op: "gte", value: `${start} 00:00:00` },
            { column: DEPARTURE_COLUMN, op: "lte", value: `${end} 23:59:59` },
          ]
        : [];
    const preservedIn = current.filter((f) => f.column !== DEPARTURE_COLUMN);
    saveFilters(id, [...preservedIn, ...rangeFilters]);
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={5} />
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
          <StepIndicator current={5} />
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

  if (slotsReady.length === 0) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={5} />
          <div className="report-page__empty">
            <p>
              {stillChecking
                ? "Checking whether analysis tables have been computed…"
                : "No analysis tables have been computed yet -- run the Analysis step first, since the report is built from whatever analyses (and slicer filters) are currently in place there."}
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
        <StepIndicator current={5} />

        <PageHeader
          icon={<IconClipboard />}
          title="Report"
          subtitle="One shared filter for the whole report -- pick 2+ values for a column (e.g. Origin) and every table below gets one slide per value instead of one slide combining them. Preview the deck and untick anything you don't want before downloading."
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
          {language !== "en" &&
            (translationAvailable ? (
              <span className="report-page__language-hint">
                Slide headings, captions and the summary are translated -- data values (names, categories) are not.
              </span>
            ) : (
              <span className="report-page__language-warn">
                Translation is switched off on the server, so the report will download in English. It needs
                DEEPL_API_KEY set and the <code>deepl</code> package installed in the environment running the API.
              </span>
            ))}
        </div>

        {hasTemplateFile && (
          <p className="report-page__template-status">
            {templateLoading && <>Uploading report template ({files.reportTemplate!.name})…</>}
            {templateSummary?.filename && <>Using your uploaded template ({templateSummary.filename}) as the report's base design.</>}
            {templateError && <span className="report-page__error">{templateError}</span>}
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id]!;
          const aiPivotCount = report.pivots.filter((p) => p.id.startsWith("ai_pivot_")).length;
          const customPivotCount = report.pivots.filter((p) => p.id.startsWith("custom_pivot_")).length;
          const globalColumns = globalColumnsFor(report.pivots);
          const filters = reportFilters[id] ?? [];
          const plan = plans[id] ?? [];
          const numbers = slideNumbers(plan);
          const includedCount = plan.filter((s) => s.included).length;
          const summarySlide = plan.find((s) => s.kind === "summary");

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
                <StatTile icon={<IconDoc />} color="blue" value={report.row_count.toLocaleString()} label="Rows" />
                <StatTile icon={<IconLayers />} color="teal" value={report.pivots.length} label="Analysis Tables" />
                {aiPivotCount > 0 && <StatTile icon={<IconSparkle />} color="amber" value={aiPivotCount} label="AI Suggested" />}
                {customPivotCount > 0 && <StatTile icon={<IconGrid />} color="purple" value={customPivotCount} label="Custom Analyses" />}
                {report.skipped_notes.length > 0 && (
                  <StatTile icon={<IconWarnTriangle />} color="error" value={report.skipped_notes.length} label="Skipped" />
                )}
              </div>

              {globalColumns.length > 0 && (
                <div className="report-page__global-filters">
                  <span className="report-page__range-label">Filters (applied to every table below)</span>
                  <PivotFilterBar
                    filterableColumns={globalColumns}
                    filterOptions={globalOptionsFor(report.pivots, globalColumns)}
                    combinations={globalCombinationsFor(report.pivots)}
                    selected={selectionsFromFilters(filters, globalColumns)}
                    onSave={(next) => handleSaveCategorical(id, next)}
                    saving={!!savingFilters[id]}
                  />
                </div>
              )}

              {(() => {
                const range = rangeDraft[id] ?? rangeFromFilters(filters);
                const setField = (field: "start" | "end", value: string) =>
                  setRangeDraft((prev) => ({ ...prev, [id]: { ...range, [field]: value } }));
                return (
                  <div className="report-page__range">
                    <span className="report-page__range-label">Departure time (applies to every table above)</span>
                    <div className="report-page__range-row">
                      <input type="date" value={range.start} onChange={(e) => setField("start", e.target.value)} aria-label="Departure start date" />
                      <span className="report-page__range-sep">to</span>
                      <input type="date" value={range.end} onChange={(e) => setField("end", e.target.value)} aria-label="Departure end date" />
                      <button
                        type="button"
                        className="report-page__btn report-page__btn--secondary report-page__range-btn"
                        disabled={!!savingFilters[id] || !range.start || !range.end}
                        onClick={() => handleApplyRange(id, range.start, range.end)}
                      >
                        {savingFilters[id] ? "Saving…" : "Apply Range"}
                      </button>
                      {(range.start || range.end) && (
                        <button
                          type="button"
                          className="report-page__btn report-page__btn--secondary report-page__range-btn"
                          disabled={!!savingFilters[id]}
                          onClick={() => {
                            setRangeDraft((prev) => ({ ...prev, [id]: { start: "", end: "" } }));
                            handleApplyRange(id, "", "");
                          }}
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>
                );
              })()}

              <div className="report-page__included">
                <div className="report-page__included-head">
                  <p className="report-page__included-title">
                    This report will include {includedCount} slide{includedCount === 1 ? "" : "s"}
                    {planLoading[id] && <span className="report-page__included-busy"> · rebuilding…</span>}
                  </p>
                  <button
                    type="button"
                    className="report-page__btn report-page__btn--secondary"
                    disabled={plan.length === 0}
                    onClick={() => setPreviewOpen(id)}
                  >
                    Preview Report
                  </button>
                </div>

                {plan.length === 0 && !planLoading[id] && (
                  <p className="report-page__included-empty">Nothing chartable for the current filters.</p>
                )}

                <ul className="report-page__included-list">
                  {report.pivots.map((p) => {
                    const active = activeColumns(filters);
                    const override = filterScope[id]?.[p.id];
                    const applied = override ?? active;
                    const currentTitle = titles[id]?.[p.id] ?? p.name;
                    const pivotSlides = plan.filter((s) => s.pivot_id === p.id);

                    return (
                      <li key={p.id} className="report-page__included-item-wrap">
                        <div className="report-page__included-row">
                          <input
                            key={currentTitle}
                            className="report-page__slide-title"
                            defaultValue={currentTitle}
                            disabled={!!savingTitle[p.id]}
                            aria-label={`Title for ${p.name}`}
                            onBlur={(e) => {
                              const next = e.target.value.trim();
                              if (next && next !== currentTitle) handleSaveTitle(id, p.id, next);
                            }}
                          />
                          <span className="report-page__included-metrics">{p.metric_labels.join(", ")}</span>
                        </div>

                        {active.length > 0 && (
                          <div className="report-page__scope-row">
                            <span className="report-page__scope-label">Filters applied:</span>
                            {active.map((column) => (
                              <button
                                key={column}
                                type="button"
                                className={`report-page__scope-chip ${applied.includes(column) ? "report-page__scope-chip--on" : ""}`}
                                disabled={!!savingScope[p.id]}
                                onClick={() => handleToggleScope(id, p.id, column, active)}
                              >
                                {columnLabel(column)}
                              </button>
                            ))}
                          </div>
                        )}

                        {pivotSlides.length === 0 ? (
                          <p className="report-page__slide-none">
                            {planLoading[id] ? "Checking…" : "No slide -- nothing chartable for the current filters."}
                          </p>
                        ) : (
                          <ul className="report-page__slide-list">
                            {pivotSlides.map((slide) => (
                              <li key={slide.key}>
                                <label className={`report-page__slide-pick ${slide.included ? "" : "report-page__slide-pick--off"}`}>
                                  <input
                                    type="checkbox"
                                    checked={slide.included}
                                    disabled={!!savingSlides[id]}
                                    onChange={() => handleToggleSlide(id, slide.key)}
                                  />
                                  <span className="report-page__slide-label">
                                    {slide.included ? `Slide ${numbers.get(slide.key)}` : "Left out"}
                                  </span>
                                  <span className="report-page__slide-name">{slide.title}</span>
                                </label>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    );
                  })}

                  {summarySlide && (
                    <li className="report-page__included-item-wrap">
                      <label className={`report-page__slide-pick ${summarySlide.included ? "" : "report-page__slide-pick--off"}`}>
                        <input
                          type="checkbox"
                          checked={summarySlide.included}
                          disabled={!!savingSlides[id]}
                          onChange={() => handleToggleSlide(id, summarySlide.key)}
                        />
                        <span className="report-page__slide-label">
                          {summarySlide.included ? `Slide ${numbers.get(summarySlide.key)}` : "Left out"}
                        </span>
                        <span className="report-page__slide-name">{summarySlide.title}</span>
                      </label>
                    </li>
                  )}
                </ul>
              </div>

              <a className="report-page__download-btn" href={downloadReportUrl(auditReports[id]!.session_id, language)} download>
                <IconDownload />
                Download Report (.pptx)
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

      {previewOpen &&
        (() => {
          const plan = plans[previewOpen] ?? [];
          const numbers = slideNumbers(plan);
          const included = plan.filter((s) => s.included).length;
          return (
            <Modal
              title={`Report Preview — ${included} slide${included === 1 ? "" : "s"}`}
              onClose={() => setPreviewOpen(null)}
              headerExtra={
                <a
                  className="report-page__btn report-page__btn--primary"
                  href={downloadReportUrl(auditReports[previewOpen]!.session_id, language)}
                  download
                >
                  Download
                </a>
              }
            >
              <p className="report-page__preview-hint">
                Every slide the .pptx would contain right now, drawn from the same plan the file is built
                from. Untick one to leave it out -- the choice sticks until you change it.
              </p>
              <div className="report-page__preview-grid">
                {plan.map((slide) => (
                  <ReportSlidePreview
                    key={slide.key}
                    slide={slide}
                    number={numbers.get(slide.key) ?? null}
                    busy={!!savingSlides[previewOpen]}
                    onToggle={slide.kind === "cover" ? undefined : () => handleToggleSlide(previewOpen, slide.key)}
                  />
                ))}
              </div>
            </Modal>
          );
        })()}
    </div>
  );
}
