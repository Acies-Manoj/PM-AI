import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import AuditReport from "../components/AuditReport";
import type { Tab } from "../components/AuditReport";
import { IconShieldSearch, IconDownload, IconLayers, IconWarnTriangle, IconChevronRight } from "../components/icons";
import {
  AuditApiError,
  downloadCleansedFileUrl,
  fetchSegmentDays,
  type PlannedAnalysisItem,
  type PlannedFeatureItem,
  type SegmentDaysResponse,
} from "../api/audit";
import { fetchFlags, fetchRca, fetchTripSeries } from "../api/rawData";
import type {
  RawDataFlaggedTrip,
  RawDataRcaResponse,
  RawDataTrip,
  RawDataTripMeanTemp,
  RawDataTripSeriesResponse,
  RawDataUploadResponse,
} from "../api/rawData";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditErrorsState, AuditLoadingState, AuditReportsState, FilesState, ResolvingState } from "../App";
import "./AuditPage.css";

const Plot = createPlotlyComponent(Plotly);

interface AuditPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
  auditLoading: AuditLoadingState;
  auditErrors: AuditErrorsState;
  resolvingIssueId: ResolvingState;
  rawDataResult: RawDataUploadResponse | null;
  onRunAudit: (id: UploadSlotId, file: File) => void;
  onResolveIssue: (id: UploadSlotId, issueId: string, decisionId: string, selectedItems?: string[]) => Promise<void>;
  onRevertIssue: (id: UploadSlotId, issueId: string) => void;
  onExcludeTrip: (id: UploadSlotId, serial: string, tripId: number) => Promise<void>;
}

export default function AuditPage({
  files,
  auditReports,
  auditLoading,
  auditErrors,
  resolvingIssueId,
  rawDataResult,
  onRunAudit,
  onResolveIssue,
  onRevertIssue,
  onExcludeTrip,
}: AuditPageProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [activeTabs, setActiveTabs] = useState<Partial<Record<UploadSlotId, Tab>>>({});
  const cardRefs = useRef<Partial<Record<UploadSlotId, HTMLElement | null>>>({});

  // Column Checks vs. Segment Days vs. Outlier Screening -- three different
  // views of the same session, not sub-tabs of the audit report itself (see
  // AuditReport.tsx's own quality/suggestions/summary tabs, which stay untouched).
  const [auditView, setAuditView] = useState<Partial<Record<UploadSlotId, "checks" | "segment_days" | "screening">>>({});
  const [segmentDays, setSegmentDays] = useState<Partial<Record<UploadSlotId, SegmentDaysResponse>>>({});
  const [segmentDaysLoading, setSegmentDaysLoading] = useState<AuditLoadingState>({});
  const [segmentDaysError, setSegmentDaysError] = useState<AuditErrorsState>({});

  const showSegmentDays = (id: UploadSlotId) => {
    setAuditView((prev) => ({ ...prev, [id]: "segment_days" }));
    if (segmentDays[id] || segmentDaysLoading[id]) return;
    const sessionId = auditReports[id]!.session_id;
    setSegmentDaysLoading((prev) => ({ ...prev, [id]: true }));
    setSegmentDaysError((prev) => ({ ...prev, [id]: undefined }));
    fetchSegmentDays(sessionId)
      .then((res) => setSegmentDays((prev) => ({ ...prev, [id]: res })))
      .catch((err) =>
        setSegmentDaysError((prev) => ({
          ...prev,
          [id]: err instanceof AuditApiError ? err.message : "Could not compute Segment Days.",
        }))
      )
      .finally(() => setSegmentDaysLoading((prev) => ({ ...prev, [id]: false })));
  };

  // Outlier Screening tab (see anomaly_detection.py via /flags, /rca) --
  // moved here from the old Upload/Raw Data page. Keyed off the raw-data
  // session (see App.tsx's rawDataResult), which is a separate session id
  // from the audit report above but tied 1:1 to the "sensiwatch" file, so
  // this view only ever applies to that slot's card.
  const [flaggedTrips, setFlaggedTrips] = useState<RawDataFlaggedTrip[] | null>(null);
  const [allTrips, setAllTrips] = useState<RawDataTripMeanTemp[] | null>(null);
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [flagsError, setFlagsError] = useState<string | null>(null);
  const [openProduct, setOpenProduct] = useState<string | null>(null);
  const [selectedTrip, setSelectedTrip] = useState<RawDataTrip | null>(null);
  const [series, setSeries] = useState<RawDataTripSeriesResponse | null>(null);
  const [seriesLoading, setSeriesLoading] = useState(false);
  const [seriesError, setSeriesError] = useState<string | null>(null);
  const [rca, setRca] = useState<RawDataRcaResponse | null>(null);
  const [rcaLoading, setRcaLoading] = useState(false);
  const [rcaError, setRcaError] = useState<string | null>(null);

  const showScreening = (id: UploadSlotId) => {
    setAuditView((prev) => ({ ...prev, [id]: "screening" }));
    if (!rawDataResult || flaggedTrips || allTrips || flagsLoading) return;
    setFlagsLoading(true);
    setFlagsError(null);
    fetchFlags(rawDataResult.session_id)
      .then((flags) => {
        setFlaggedTrips(flags.flagged_trips);
        setAllTrips(flags.all_trips);
      })
      .catch((err) => setFlagsError(err instanceof AuditApiError ? err.message : "Could not run outlier/threshold screening."))
      .finally(() => setFlagsLoading(false));
  };

  const chartProducts = allTrips
    ? Array.from(new Set(allTrips.map((t) => t.product).filter((p): p is string => !!p))).sort()
    : [];

  const closeProductModal = () => {
    setOpenProduct(null);
    setSelectedTrip(null);
    setSeries(null);
    setRca(null);
  };

  const handleSelectTrip = async (trip: RawDataTrip) => {
    if (!rawDataResult) return;
    setSelectedTrip(trip);
    setSeries(null);
    setSeriesError(null);
    setSeriesLoading(true);
    setRca(null);
    setRcaError(null);
    try {
      const data = await fetchTripSeries(rawDataResult.session_id, trip.serial, trip.trip_id);
      setSeries(data);
    } catch (err) {
      setSeriesError(err instanceof AuditApiError ? err.message : "Could not load raw readings for this trip.");
    } finally {
      setSeriesLoading(false);
    }
  };

  const handleViewRca = async () => {
    if (!rawDataResult || !selectedTrip) return;
    setRcaLoading(true);
    setRcaError(null);
    try {
      const data = await fetchRca(rawDataResult.session_id, selectedTrip.serial, selectedTrip.trip_id);
      setRca(data);
    } catch (err) {
      setRcaError(err instanceof AuditApiError ? err.message : "Could not compute root-cause hypotheses for this trip.");
    } finally {
      setRcaLoading(false);
    }
  };

  const hasSeriesChart = !!series && ((series.temperature?.points.length ?? 0) > 0 || (series.light?.points.length ?? 0) > 0);
  const selectedTripFlag = selectedTrip
    ? flaggedTrips?.find((f) => f.serial === selectedTrip.serial && f.trip_id === selectedTrip.trip_id)
    : undefined;
  const selectedTripMeanTemp = selectedTrip
    ? allTrips?.find((t) => t.serial === selectedTrip.serial && t.trip_id === selectedTrip.trip_id)
    : undefined;
  const tripDetailVisible = !!selectedTrip && !!openProduct && selectedTripMeanTemp?.product === openProduct;

  useEffect(() => {
    for (const id of AUDITED_SLOTS) {
      const file = files[id];
      if (!file) continue;
      if (auditReports[id] || auditLoading[id] || auditErrors[id]) continue;
      onRunAudit(id, file);
    }
    // Only re-scan when the selected files change -- audit state itself is
    // checked fresh above so this stays idempotent without needing it as a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  const auditedSlotsWithFiles = AUDITED_SLOTS.filter((id) => files[id]);
  const hasAnyFile = UPLOAD_SLOTS.some((s) => files[s.id]);

  const anyLoading = auditedSlotsWithFiles.some((id) => auditLoading[id]);
  // Every audited slot with a file must have an actual REVIEWED report --
  // not just "isn't currently flagged pending", which was also (wrongly)
  // true for the one render before its audit has even started (before
  // auditReports[id] exists at all, `?.status === "pending_review"` is
  // false simply because there's no report yet, not because it's clean).
  // That one-render gap used to let canContinue go true for an instant
  // right as this page mounted with a pending Client Brief, firing the
  // auto-continue effect below before the audit had actually run.
  const allReviewed = auditedSlotsWithFiles.every((id) => auditReports[id]?.status === "reviewed");
  const canContinue = !!files.sensiwatch && !anyLoading && allReviewed;

  // A Client Brief submitted from Upload's own box (see UploadPage's
  // "Client requirement") lands here first, same as clicking "Continue to
  // Features" by hand -- the audit still has to run and any outstanding
  // questions still have to be resolved before continuing. Once this slot
  // is clean, the brief is READY to carry on to wherever the Orchestrator
  // Agent decided it belongs (Features or Analysis) -- it no longer jumps
  // there automatically, so the user actually sees this page (and its own
  // audit findings) rather than being swept straight past it; "Continue to
  // Features" below carries the pending brief forward when clicked.
  const pendingBriefFiredRef = useRef(false);
  const [pendingBriefHandoff, setPendingBriefHandoff] = useState<{
    target: string;
    brief: string;
    detectedLanguage?: string | null;
    translatedText?: string | null;
    plannedFeatures?: PlannedFeatureItem[];
    plannedAnalyses?: PlannedAnalysisItem[];
  } | null>(null);
  useEffect(() => {
    const state = location.state as {
      pendingBrief?: string;
      pendingBriefTarget?: string;
      pendingBriefDetectedLanguage?: string | null;
      pendingBriefTranslatedText?: string | null;
      pendingPlannedFeatures?: PlannedFeatureItem[];
      pendingPlannedAnalyses?: PlannedAnalysisItem[];
    } | null;
    if (!state?.pendingBrief || !state?.pendingBriefTarget || !canContinue || pendingBriefFiredRef.current) return;
    pendingBriefFiredRef.current = true;
    setPendingBriefHandoff({
      target: state.pendingBriefTarget,
      brief: state.pendingBrief,
      detectedLanguage: state.pendingBriefDetectedLanguage,
      translatedText: state.pendingBriefTranslatedText,
      plannedFeatures: state.pendingPlannedFeatures,
      plannedAnalyses: state.pendingPlannedAnalyses,
    });
  }, [canContinue, location.state]);

  const handleContinueToFeatures = () => {
    if (!pendingBriefHandoff) {
      navigate("/features");
      return;
    }
    const prefillKey = pendingBriefHandoff.target === "/features" ? "prefillClientBrief" : "prefillRequest";
    navigate(pendingBriefHandoff.target, {
      state: {
        [prefillKey]: pendingBriefHandoff.brief,
        prefillDetectedLanguage: pendingBriefHandoff.detectedLanguage,
        prefillTranslatedText: pendingBriefHandoff.translatedText,
        // The Planner Agent's plan, carried straight through -- Features
        // computes exactly this, it doesn't re-derive it from the brief
        // text again (and hands the analysis half onward itself once the
        // user clicks its own "Continue to Analysis").
        prefillPlannedFeatures: pendingBriefHandoff.plannedFeatures,
        prefillPlannedAnalyses: pendingBriefHandoff.plannedAnalyses,
      },
    });
  };

  if (!hasAnyFile) {
    return (
      <div className="audit-page">
        <Header subtitle="Data Audit" />
        <main className="audit-page__main">
          <StepIndicator current={2} />
          <div className="audit-page__empty">
            <p>No files have been uploaded yet.</p>
            <button type="button" className="audit-page__btn audit-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="audit-page">
      <Header subtitle="Data Audit" />
      <main className="audit-page__main">
        <StepIndicator current={2} />

        <PageHeader
          icon={<IconShieldSearch />}
          title="Data Audit"
          subtitle="The data audit agent has reviewed your tabular uploads below. Resolve any outstanding questions before continuing."
        />

        {auditedSlotsWithFiles.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = auditReports[id];
          const activeTab = activeTabs[id] ?? "quality";
          return (
            <section className="audit-page__card" key={id} ref={(el) => { cardRefs.current[id] = el; }}>
              <div className="audit-page__card-head">
                <div className="audit-page__card-head-left">
                  <h2 className="audit-page__slot-title">{slot.title}</h2>
                  <span className="audit-page__pill">DATA AUDIT SUMMARY</span>
                  {report && (
                    <span
                      className={`audit-page__status audit-page__status--${
                        report.status === "reviewed" ? "reviewed" : "pending"
                      }`}
                    >
                      {report.status === "reviewed"
                        ? "Reviewed"
                        : `${report.issues.filter((i) => i.requires_decision && i.status === "pending").length} decision(s) needed`}
                    </span>
                  )}
                </div>
                <span className="audit-page__filename">{files[id]!.name}</span>
              </div>

              {auditLoading[id] && (
                <div className="audit-page__audit-loading">Data audit agent is reviewing this file…</div>
              )}

              {auditErrors[id] && (
                <div className="audit-page__audit-error-row">
                  <p className="audit-page__audit-error">{auditErrors[id]}</p>
                  <button
                    type="button"
                    className="audit-page__retry-btn"
                    onClick={() => onRunAudit(id, files[id]!)}
                  >
                    Retry
                  </button>
                </div>
              )}

              {report && (
                <>
                  <div className="audit-page__view-tabs" role="tablist">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={(auditView[id] ?? "checks") === "checks"}
                      className={`audit-page__view-tab ${(auditView[id] ?? "checks") === "checks" ? "audit-page__view-tab--active" : ""}`}
                      onClick={() => setAuditView((prev) => ({ ...prev, [id]: "checks" }))}
                    >
                      Column Checks
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={auditView[id] === "segment_days"}
                      className={`audit-page__view-tab ${auditView[id] === "segment_days" ? "audit-page__view-tab--active" : ""}`}
                      onClick={() => showSegmentDays(id)}
                    >
                      <IconLayers /> Segment Days
                    </button>
                    {id === "sensiwatch" && rawDataResult && (
                      <button
                        type="button"
                        role="tab"
                        aria-selected={auditView[id] === "screening"}
                        className={`audit-page__view-tab ${auditView[id] === "screening" ? "audit-page__view-tab--active" : ""}`}
                        onClick={() => showScreening(id)}
                      >
                        <IconWarnTriangle /> Outlier Screening
                      </button>
                    )}
                  </div>

                  {(auditView[id] ?? "checks") === "checks" && (
                    <>
                      <AuditReport
                        report={report}
                        onResolve={(issueId, decisionId, selectedItems) =>
                          onResolveIssue(id, issueId, decisionId, selectedItems)
                        }
                        onRevert={(issueId) => onRevertIssue(id, issueId)}
                        resolvingIssueId={resolvingIssueId[id] ?? null}
                        activeTab={activeTab}
                        onTabChange={(tab) => setActiveTabs((prev) => ({ ...prev, [id]: tab }))}
                      />
                      <div className="audit-page__row-actions">
                        <a className="audit-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                          <IconDownload />
                          Download cleansed file
                        </a>
                      </div>
                    </>
                  )}

                  {auditView[id] === "segment_days" && (
                    <div className="audit-page__segment-days">
                      <p className="audit-page__segment-days-hint">
                        Trips whose own transit duration (Segment Length) falls outside their lane's Tukey fence --
                        the outliers themselves, not the fence numbers.
                      </p>
                      {segmentDaysLoading[id] && <div className="audit-page__audit-loading">Computing Segment Days…</div>}
                      {segmentDaysError[id] && <p className="audit-page__audit-error">{segmentDaysError[id]}</p>}
                      {segmentDays[id] && segmentDays[id]!.rows.length === 0 && (
                        <p className="audit-page__segment-days-hint">No trips fell outside their lane's duration fence.</p>
                      )}
                      {segmentDays[id] && segmentDays[id]!.rows.length > 0 && (
                        <div className="audit-page__segment-days-table-wrap">
                          <table className="audit-page__segment-days-table">
                            <thead>
                              <tr>
                                <th>Serial Number</th>
                                <th>Trip ID</th>
                                <th>Origin</th>
                                <th>Destination</th>
                                <th>Segment Days</th>
                                <th>Lane Fence (Days)</th>
                                <th>Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {segmentDays[id]!.rows.map((r) => (
                                <tr key={`${r.serial ?? "?"}::${r.trip_id ?? "?"}`}>
                                  <td>{r.serial ?? "—"}</td>
                                  <td>{r.trip_id ?? "—"}</td>
                                  <td>{r.origin}</td>
                                  <td>{r.destination}</td>
                                  <td>{r.segment_days}</td>
                                  <td>
                                    {r.lower_fence_days != null && r.upper_fence_days != null
                                      ? `${r.lower_fence_days} – ${r.upper_fence_days}`
                                      : "—"}
                                  </td>
                                  <td>{r.status}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}

                  {auditView[id] === "screening" && rawDataResult && (
                    <div className="audit-page__screening">
                      <p className="audit-page__segment-days-hint">
                        One card per product -- open one to see its mean-temperature chart, flagged trips, and any
                        trip's own raw sensor curve.
                      </p>
                      {flagsLoading && <div className="audit-page__audit-loading">Running outlier/threshold screening…</div>}
                      {flagsError && <p className="audit-page__audit-error">{flagsError}</p>}

                      {allTrips && chartProducts.length === 0 && (
                        <p className="audit-page__segment-days-hint">No products found in this data.</p>
                      )}

                      {allTrips && chartProducts.length > 0 && (
                        <div className="audit-report__issues">
                          {chartProducts.map((product) => {
                            const productTrips = allTrips.filter((t) => t.product === product);
                            const flaggedCount = productTrips.filter((t) => t.flagged).length;
                            return (
                              <div
                                key={product}
                                className={`audit-issue ${flaggedCount > 0 ? "audit-issue--warning" : "audit-issue--info"}`}
                              >
                                <button type="button" className="audit-issue__tile" onClick={() => setOpenProduct(product)}>
                                  <div className="audit-issue__tile-head">
                                    <h4 className="audit-issue__title">{product}</h4>
                                    <span className="audit-issue__tile-chevron">
                                      <IconChevronRight />
                                    </span>
                                  </div>
                                  <span className="audit-issue__affected">
                                    {flaggedCount > 0
                                      ? `${flaggedCount} of ${productTrips.length} trip${productTrips.length === 1 ? "" : "s"} flagged`
                                      : `${productTrips.length} trip${productTrips.length === 1 ? "" : "s"} -- none flagged`}
                                  </span>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {openProduct && allTrips && (
                        <div className="audit-issue__modal-backdrop" onClick={closeProductModal}>
                          <div className="audit-issue__modal" onClick={(e) => e.stopPropagation()}>
                            <div className="audit-issue__modal-head">
                              <div className="audit-issue__top">
                                <h4 className="audit-issue__title">{openProduct}</h4>
                              </div>
                              <button type="button" className="audit-issue__modal-close" onClick={closeProductModal} aria-label="Close">
                                ✕
                              </button>
                            </div>
                            <div className="audit-issue__modal-body">
                              <div className="audit-issue__chart-panel">
                                <ProductMeanTempChart
                                  product={openProduct}
                                  trips={allTrips.filter((t) => t.product === openProduct)}
                                  onSelectTrip={(t) => {
                                    const trip = rawDataResult.trips.find((rt) => rt.serial === t.serial && rt.trip_id === t.trip_id);
                                    if (trip) handleSelectTrip(trip);
                                  }}
                                />
                              </div>

                              {flaggedTrips && flaggedTrips.filter((f) => f.product === openProduct).length > 0 && (
                                <div className="audit-page__screening-outlier-table-wrap">
                                  <table className="audit-page__screening-outlier-table">
                                    <thead>
                                      <tr>
                                        <th>Serial Number</th>
                                        <th>Trip ID</th>
                                        <th>Flags</th>
                                        <th>Mean Temp</th>
                                        <th>Status</th>
                                        <th></th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {flaggedTrips
                                        .filter((f) => f.product === openProduct)
                                        .map((f) => {
                                          const excluded = report.issues.some(
                                            (i) => i.category === `outlier_trip::${f.serial}::${f.trip_id}` && i.status === "resolved"
                                          );
                                          const isOpen = selectedTrip?.serial === f.serial && selectedTrip?.trip_id === f.trip_id;
                                          return (
                                            <tr
                                              key={`${f.serial}::${f.trip_id}`}
                                              className={isOpen ? "audit-page__screening-outlier-row--open" : ""}
                                            >
                                              <td>{f.serial}</td>
                                              <td>{f.trip_id}</td>
                                              <td>{f.flag_count}</td>
                                              <td>{f.mean_temp != null ? `${f.mean_temp}°` : "—"}</td>
                                              <td>{excluded ? "Excluded" : "Flagged"}</td>
                                              <td>
                                                <button
                                                  type="button"
                                                  className="audit-page__btn audit-page__btn--secondary"
                                                  onClick={() => {
                                                    const trip = rawDataResult.trips.find(
                                                      (t) => t.serial === f.serial && t.trip_id === f.trip_id
                                                    );
                                                    if (trip) handleSelectTrip(trip);
                                                  }}
                                                >
                                                  {isOpen ? "Inspecting…" : "Inspect"}
                                                </button>
                                              </td>
                                            </tr>
                                          );
                                        })}
                                    </tbody>
                                  </table>
                                </div>
                              )}

                              {seriesLoading && <p className="audit-page__segment-days-hint">Loading raw readings…</p>}
                              {seriesError && <p className="audit-page__audit-error">{seriesError}</p>}

                              {tripDetailVisible && series && !seriesLoading && (
                                <div className="audit-page__screening-trip-detail">
                                  <p className="audit-page__segment-days-hint">
                                    <strong>
                                      Trip {selectedTrip!.trip_id} ({selectedTrip!.serial}) -- start timestamp (point #1):
                                    </strong>{" "}
                                    {new Date(series.start_time).toLocaleString()}
                                  </p>
                                  {hasSeriesChart ? (
                                    <RawDataChart
                                      series={series}
                                      limits={
                                        selectedTripMeanTemp
                                          ? {
                                              low: selectedTripMeanTemp.limit_low,
                                              ideal: selectedTripMeanTemp.limit_ideal,
                                              high: selectedTripMeanTemp.limit_high,
                                            }
                                          : null
                                      }
                                    />
                                  ) : (
                                    <p className="audit-page__segment-days-hint">
                                      No raw data points were found for this trip in the uploaded matrix file(s).
                                    </p>
                                  )}

                                  {(() => {
                                    const key = `${selectedTrip!.serial}::${selectedTrip!.trip_id}`;
                                    const excludedIssue = report.issues.find(
                                      (i) => i.category === `outlier_trip::${key}` && i.status === "resolved"
                                    );
                                    const busy = resolvingIssueId[id] === `trip::${key}`;
                                    return (
                                      <div className="audit-issue__actions">
                                        {excludedIssue ? (
                                          <button
                                            type="button"
                                            className="audit-issue__btn audit-issue__btn--secondary"
                                            disabled={busy}
                                            onClick={() => onRevertIssue(id, excludedIssue.id)}
                                          >
                                            {busy ? "Reverting…" : "Revert exclusion"}
                                          </button>
                                        ) : (
                                          <button
                                            type="button"
                                            className="audit-issue__btn audit-issue__btn--primary"
                                            disabled={busy}
                                            onClick={() => onExcludeTrip(id, selectedTrip!.serial, selectedTrip!.trip_id)}
                                          >
                                            {busy ? "Excluding…" : "Exclude from analysis"}
                                          </button>
                                        )}
                                        {selectedTripFlag && (
                                          <button
                                            type="button"
                                            className="audit-issue__btn audit-issue__btn--secondary"
                                            disabled={rcaLoading}
                                            onClick={handleViewRca}
                                          >
                                            {rcaLoading ? "Scoring hypotheses…" : "View root-cause hypotheses"}
                                          </button>
                                        )}
                                      </div>
                                    );
                                  })()}

                                  {rcaError && <p className="audit-page__audit-error">{rcaError}</p>}
                                  {rca && (
                                    <ul className="audit-page__screening-rca-list">
                                      {rca.hypotheses.map((h) => (
                                        <li key={h.hypothesis}>
                                          <strong>
                                            [{h.confidence} · score {h.score}] {h.hypothesis}
                                          </strong>
                                          <ul>
                                            {h.rationale.map((r) => (
                                              <li key={r}>{r}</li>
                                            ))}
                                          </ul>
                                        </li>
                                      ))}
                                    </ul>
                                  )}
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </section>
          );
        })}

        <div className="audit-page__actions">
          <button type="button" className="audit-page__btn audit-page__btn--secondary" onClick={() => navigate("/upload")}>
            Back to Upload
          </button>
          <button
            type="button"
            className="audit-page__btn audit-page__btn--primary"
            disabled={!canContinue}
            onClick={handleContinueToFeatures}
          >
            Continue to Features
          </button>
        </div>

        {!canContinue && !anyLoading && (
          <p className="audit-page__hint">
            Resolve the outstanding data audit questions above before continuing.
            {(location.state as { pendingBrief?: string } | null)?.pendingBrief &&
              " Your client requirement will be ready to continue once these are resolved."}
          </p>
        )}
        {canContinue && pendingBriefHandoff && (
          <p className="audit-page__hint">Your client requirement is ready -- click "Continue to Features" to carry it forward.</p>
        )}
      </main>
    </div>
  );
}

interface TripPointRef {
  serial: string;
  trip_id: number;
}

/** One chart per product -- every trip for that product as a bar (one bar
 * per trip id) plotted by mean temperature, bars outside that product's own
 * Limit Low/High colored red, Low/Ideal/High drawn as dashed reference
 * lines. "Out of range" is judged directly against THIS chart's own
 * limit_low/limit_high (not the backend's general `flagged`, which can be
 * true for an unrelated reason, like a duration outlier) -- above the high
 * line or below the low line, nothing else. */
function isOutOfMeanTempRange(t: RawDataTripMeanTemp): boolean {
  if (t.mean_temp == null) return false;
  if (t.limit_high != null && t.mean_temp > t.limit_high) return true;
  if (t.limit_low != null && t.mean_temp < t.limit_low) return true;
  return false;
}

function ProductMeanTempChart({
  product,
  trips,
  onSelectTrip,
}: {
  product: string;
  trips: RawDataTripMeanTemp[];
  onSelectTrip: (trip: TripPointRef) => void;
}) {
  const sorted = [...trips].sort((a, b) => a.start_time.localeCompare(b.start_time));
  const flaggedCount = sorted.filter(isOutOfMeanTempRange).length;
  const withLimits = sorted.find((t) => t.limit_low != null || t.limit_ideal != null || t.limit_high != null);

  const traces: Partial<Plotly.PlotData>[] = [
    {
      type: "bar",
      name: product,
      x: sorted.map((t) => String(t.trip_id)),
      y: sorted.map((t) => t.mean_temp),
      customdata: sorted.map((t) => ({ serial: t.serial, trip_id: t.trip_id })) as unknown as Plotly.Datum[],
      hovertext: sorted.map((t) => t.label),
      hovertemplate: "%{hovertext}<br>Mean Temp: %{y}°<extra></extra>",
      marker: { color: sorted.map((t) => (isOutOfMeanTempRange(t) ? "#C0392B" : "#152C73")) },
    },
  ];

  const shapes: Partial<Plotly.Shape>[] = [];
  const addLine = (y: number | null | undefined, color: string) => {
    if (y == null) return;
    shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1.5, dash: "dash" } });
  };
  addLine(withLimits?.limit_low, "#1891F6");
  addLine(withLimits?.limit_ideal, "#10B981");
  addLine(withLimits?.limit_high, "#C0392B");

  return (
    <div className="audit-page__screening-product-chart">
      <div className="audit-page__screening-product-chart-head">
        <h3 className="audit-page__screening-product-chart-title">{product}</h3>
        <div className="audit-page__screening-limit-tiles">
          {withLimits?.limit_low != null && (
            <span className="audit-page__screening-limit-tile audit-page__screening-limit-tile--low">Low: {withLimits.limit_low}°</span>
          )}
          {withLimits?.limit_ideal != null && (
            <span className="audit-page__screening-limit-tile audit-page__screening-limit-tile--ideal">
              Ideal: {withLimits.limit_ideal}°
            </span>
          )}
          {withLimits?.limit_high != null && (
            <span className="audit-page__screening-limit-tile audit-page__screening-limit-tile--high">High: {withLimits.limit_high}°</span>
          )}
          {flaggedCount > 0 && (
            <span className="audit-page__screening-flag-count">
              {flaggedCount} of {sorted.length} flagged
            </span>
          )}
        </div>
      </div>
      <Plot
        data={traces}
        layout={{
          margin: { l: 56, r: 24, t: 8, b: 50 },
          height: 280,
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          showlegend: false,
          xaxis: { title: { text: "Trip ID" }, type: "category", tickangle: -40 },
          yaxis: { title: { text: "Mean Temp (°)" }, gridcolor: "#EEF1F6", zeroline: false },
          shapes,
        }}
        config={{ displayModeBar: true, displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
        onClick={(e) => {
          const point = e.points?.[0] as unknown as { customdata?: TripPointRef } | undefined;
          if (point?.customdata) onSelectTrip(point.customdata);
        }}
      />
    </div>
  );
}

interface TripLimits {
  low: number | null;
  ideal: number | null;
  high: number | null;
}

function RawDataChart({ series, limits }: { series: RawDataTripSeriesResponse; limits?: TripLimits | null }) {
  const [showTemperature, setShowTemperature] = useState(true);
  const [showLight, setShowLight] = useState(true);

  const hasTemp = !!series.temperature && series.temperature.points.length > 0;
  const hasLight = !!series.light && series.light.points.length > 0;

  const traces: Partial<Plotly.PlotData>[] = [];
  if (hasTemp && showTemperature) {
    traces.push({
      type: "scatter",
      mode: "lines+markers",
      name: `Temperature (${series.temperature!.unit || "raw"})`,
      x: series.temperature!.points.map((p) => p.t),
      y: series.temperature!.points.map((p) => p.v),
      yaxis: "y1",
      line: { color: "#C0392B", width: 2 },
      marker: { color: "#C0392B", size: 4 },
    });
  }
  if (hasLight && showLight) {
    traces.push({
      type: "scatter",
      mode: "lines+markers",
      name: `Light (${series.light!.unit || "raw"})`,
      x: series.light!.points.map((p) => p.t),
      y: series.light!.points.map((p) => p.v),
      yaxis: "y2",
      line: { color: "#0EA5A5", width: 2 },
      marker: { color: "#0EA5A5", size: 4 },
    });
  }

  const shapes: Partial<Plotly.Shape>[] = [];
  if (showTemperature && limits) {
    const addLine = (y: number | null, color: string) => {
      if (y == null) return;
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, yref: "y", line: { color, width: 1.5, dash: "dash" } });
    };
    addLine(limits.low, "#1891F6");
    addLine(limits.ideal, "#10B981");
    addLine(limits.high, "#C0392B");
  }

  return (
    <div className="audit-page__screening-chart">
      <div className="audit-page__screening-chart-toolbar">
        {hasTemp && (
          <button
            type="button"
            className={`audit-page__screening-chip audit-page__screening-chip--temp ${showTemperature ? "audit-page__screening-chip--active" : ""}`}
            onClick={() => setShowTemperature((v) => !v)}
          >
            Temperature
          </button>
        )}
        {hasLight && (
          <button
            type="button"
            className={`audit-page__screening-chip audit-page__screening-chip--light ${showLight ? "audit-page__screening-chip--active" : ""}`}
            onClick={() => setShowLight((v) => !v)}
          >
            Light
          </button>
        )}
        <button
          type="button"
          className="audit-page__screening-chip audit-page__screening-chip--clear"
          onClick={() => {
            setShowTemperature(true);
            setShowLight(true);
          }}
        >
          Clear
        </button>
      </div>
      <Plot
        data={traces}
        layout={{
          margin: { l: 56, r: 56, t: 16, b: 60 },
          height: 420,
          paper_bgcolor: "transparent",
          plot_bgcolor: "transparent",
          legend: { orientation: "h", y: -0.2 },
          xaxis: { title: { text: "Timestamp" } },
          yaxis: { title: { text: "Temperature" }, gridcolor: "#EEF1F6", zeroline: false },
          yaxis2: { title: { text: "Light" }, overlaying: "y", side: "right", showgrid: false, zeroline: false },
          shapes,
        }}
        config={{ displayModeBar: true, displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}
