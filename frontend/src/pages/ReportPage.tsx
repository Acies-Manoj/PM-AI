import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import StatTile from "../components/StatTile";
import PivotFilterBar from "../components/PivotFilterBar";
import { IconClipboard, IconChevronLeft, IconDoc, IconDownload, IconGrid, IconLayers, IconSparkle, IconWarnTriangle } from "../components/icons";
import {
  downloadReportUrl,
  fetchPivotReport,
  fetchReportFilters,
  fetchReportFilterScope,
  fetchReportTitles,
  saveReportFilters,
  saveReportFilterScope,
  saveReportTitle,
  uploadReportTemplate,
  AuditApiError,
  type PivotFilter,
  type PivotReport,
  type PivotResult,
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

// The raw column the data uses for a shipment's departure -- not one of the
// categorical filterable_columns slicers, so it gets its own date-range
// control alongside them.
const DEPARTURE_COLUMN = "Actual Departure Time CET";
// Mirrors the backend's report_generator.MAX_COMBOS_PER_PIVOT.
const MAX_COMBOS = 12;

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

// Mirrors the backend's report_generator._report_filter_combos + _combo_label
// exactly, so the UI shows one row per ACTUAL output slide instead of
// collapsing them into a single "N slides" summary -- e.g. 2 selected
// Origins -> 2 rows, each labeled with the specific Origin it resolves to.
function pivotSlidePreviews(filters: PivotFilter[], allowed: string[] | undefined): string[] {
  const scoped = allowed === undefined ? filters : filters.filter((f) => allowed.includes(f.column));
  const multipliers = scoped.filter((f) => f.op === "in" && Array.isArray(f.value) && f.value.length > 1);
  if (multipliers.length === 0) return [""];
  let combos: string[][] = [[]];
  for (const f of multipliers) {
    const values = (f.value as unknown[]).map(String);
    combos = combos.flatMap((c) => values.map((v) => [...c, v]));
  }
  return combos.slice(0, MAX_COMBOS).map((c) => c.join(" / "));
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

  const handleSaveTitle = (id: UploadSlotId, pivotId: string, title: string) => {
    const sessionId = auditReports[id]!.session_id;
    setSavingTitle((prev) => ({ ...prev, [pivotId]: true }));
    saveReportTitle(sessionId, pivotId, title)
      .then((res) => setTitles((prev) => ({ ...prev, [id]: res.titles })))
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

  if (slotsReady.length === 0) {
    return (
      <div className="report-page">
        <Header subtitle="Report" />
        <main className="report-page__main">
          <StepIndicator current={6} />
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
        <StepIndicator current={6} />

        <PageHeader
          icon={<IconClipboard />}
          title="Report"
          subtitle="One shared filter for the whole report -- pick 2+ values for a column (e.g. Origin) and every table below gets one slide per value instead of one slide combining them."
        />

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
                <p className="report-page__included-title">This report will include:</p>
                <ul className="report-page__included-list">
                  {report.pivots.flatMap((p, idx) => {
                    const active = activeColumns(filters);
                    const override = filterScope[id]?.[p.id];
                    const applied = override ?? active;
                    const currentTitle = titles[id]?.[p.id] ?? p.name;
                    const previews = pivotSlidePreviews(filters, override);

                    return previews.map((comboLabel, comboIdx) => (
                      <li key={`${p.id}-${comboIdx}`} className="report-page__included-item-wrap">
                        <div className="report-page__included-row">
                          <span className="report-page__slide-label">
                            {previews.length > 1 ? `Slide ${idx + 1}.${comboIdx + 1}` : `Slide ${idx + 1}`}
                          </span>
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
                        {(active.length > 0 || comboLabel) && (
                          <div className="report-page__scope-row">
                            {active.length > 0 && (
                              <>
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
                              </>
                            )}
                            {comboLabel && <span className="report-page__scope-chip report-page__scope-chip--value">→ {comboLabel}</span>}
                          </div>
                        )}
                      </li>
                    ));
                  })}
                  <li className="report-page__included-summary">Overall analysis summary</li>
                </ul>
              </div>

              <a
                className="report-page__download-btn"
                href={downloadReportUrl(auditReports[id]!.session_id)}
                download
              >
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
    </div>
  );
}
