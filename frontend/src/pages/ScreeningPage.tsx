import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import { runScreening, fetchTripTrace, ScreeningApiError } from "../api/screening";
import type { FlaggedTrip, ScreeningReport, TripTrace } from "../api/screening";
import type { AuditReportsState, FilesState } from "../App";
import "./ScreeningPage.css";

interface ScreeningPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

function MeanTempChart({ productMeans }: { productMeans: Record<string, number> }) {
  const entries = Object.entries(productMeans);
  if (entries.length === 0) return null;
  const max = Math.max(...entries.map(([, v]) => Math.abs(v)), 1);
  return (
    <div className="screening-page__chart">
      <h3 className="screening-page__chart-title">Mean Temperature by Product Line (°C)</h3>
      {entries.map(([product, mean]) => (
        <div key={product} className="screening-page__bar-row">
          <span className="screening-page__bar-label">{product}</span>
          <div className="screening-page__bar-track">
            <div
              className={`screening-page__bar-fill ${mean > 0 ? "screening-page__bar-fill--warm" : "screening-page__bar-fill--cold"}`}
              style={{ width: `${(Math.abs(mean) / max) * 100}%` }}
            />
          </div>
          <span className="screening-page__bar-value">{mean}°C</span>
        </div>
      ))}
    </div>
  );
}

function TempTrace({ trace }: { trace: TripTrace }) {
  if (trace.temperatures.length === 0)
    return <p className="screening-page__no-trace">No time-series data available for this trip.</p>;

  const valid = trace.temperatures.filter((v): v is number => v !== null);
  const minT = Math.min(...valid);
  const maxT = Math.max(...valid);
  const range = maxT - minT || 1;
  const W = 600;
  const H = 120;
  const pts = trace.temperatures
    .map((t, i) => {
      if (t === null) return null;
      const x = (i / (trace.temperatures.length - 1)) * W;
      const y = H - ((t - minT) / range) * (H - 10) - 5;
      return `${x},${y}`;
    })
    .filter(Boolean)
    .join(" ");

  return (
    <div className="screening-page__trace">
      <div className="screening-page__trace-label">Temperature Trace (°C)</div>
      <svg viewBox={`0 0 ${W} ${H}`} className="screening-page__trace-svg" aria-hidden="true">
        <polyline points={pts} fill="none" stroke="#1891f6" strokeWidth="2" strokeLinejoin="round" />
        {trace.light_events.length > 0 && (
          <text x="4" y="14" fontSize="10" fill="#c62828">
            ● {trace.light_events.length} door-open event(s)
          </text>
        )}
      </svg>
      <div className="screening-page__trace-range">
        <span>Min: {minT.toFixed(1)}°C</span>
        <span>Max: {maxT.toFixed(1)}°C</span>
      </div>
    </div>
  );
}

function TripCard({
  trip,
  sessionId,
  rawdataSessionId,
}: {
  trip: FlaggedTrip;
  sessionId: string;
  rawdataSessionId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [trace, setTrace] = useState<TripTrace | null>(null);
  const [loading, setLoading] = useState(false);

  const handleDrillDown = async () => {
    setOpen((prev) => !prev);
    if (!trace && !loading) {
      setLoading(true);
      try {
        const t = await fetchTripTrace(sessionId, trip.trip_id, rawdataSessionId);
        setTrace(t);
      } catch {
        setTrace({ trip_id: trip.trip_id, timestamps: [], temperatures: [], light_events: [] });
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <div className="screening-page__trip-card">
      <div className="screening-page__trip-header">
        <div className="screening-page__trip-meta">
          <span className="screening-page__excursion-badge">EXCURSION</span>
          <span className="screening-page__trip-id">{trip.trip_id || "—"}</span>
          <span className="screening-page__trip-product">{trip.product}</span>
        </div>
        <div className="screening-page__trip-temps">
          <span className="screening-page__trip-mean">{trip.mean_temp}°C</span>
          {trip.temp_limit !== null && (
            <span className="screening-page__trip-limit">limit: {trip.temp_limit}°C</span>
          )}
          {trip.exceedance !== null && (
            <span className="screening-page__trip-exceedance">+{trip.exceedance}°C over</span>
          )}
        </div>
      </div>

      {(trip.origin || trip.destination) && (
        <div className="screening-page__trip-route">
          {trip.origin} → {trip.destination}
        </div>
      )}

      <button type="button" className="screening-page__drill-btn" onClick={handleDrillDown}>
        {open ? "▲ Hide trace" : "▼ View temperature & light trace"}
      </button>

      {open && (
        <div className="screening-page__drill-content">
          {loading ? (
            <div className="screening-page__loading">Loading trace…</div>
          ) : trace ? (
            <TempTrace trace={trace} />
          ) : null}
        </div>
      )}
    </div>
  );
}

export default function ScreeningPage({ files, auditReports }: ScreeningPageProps) {
  const navigate = useNavigate();
  const [report, setReport] = useState<ScreeningReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const primaryReport = auditReports.sensiwatch;
  const rawdataReport = auditReports.coldstream;

  useEffect(() => {
    if (!primaryReport || report || loading) return;
    setLoading(true);
    runScreening(primaryReport.session_id, rawdataReport?.session_id)
      .then(setReport)
      .catch((err) =>
        setError(err instanceof ScreeningApiError ? err.message : "Screening failed.")
      )
      .finally(() => setLoading(false));
  }, [primaryReport]);

  if (!files.sensiwatch || !primaryReport) {
    return (
      <div className="screening-page">
        <Header />
        <main className="screening-page__main">
          <StepIndicator current={3} />
          <div className="screening-page__empty">
            <p>Complete the data audit first.</p>
            <button type="button" className="screening-page__btn screening-page__btn--primary" onClick={() => navigate("/audit")}>
              Go to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="screening-page">
      <Header />
      <main className="screening-page__main">
        <StepIndicator current={3} />

        <div className="screening-page__intro">
          <h1 className="screening-page__heading">Threshold Screening</h1>
          <p className="screening-page__lede">
            Rule-based excursion detection against known product temperature limits. Flagged trips
            exceeded their limit — click any trip to drill into its temperature and light trace.
          </p>
        </div>

        {loading && <div className="screening-page__loading">Running threshold screening…</div>}
        {error && <p className="screening-page__error">{error}</p>}

        {report && (
          <>
            <div className="screening-page__summary-row">
              <div className="screening-page__stat">
                <span className="screening-page__stat-value">{report.total_trips}</span>
                <span className="screening-page__stat-label">Total trips</span>
              </div>
              <div className="screening-page__stat screening-page__stat--flagged">
                <span className="screening-page__stat-value">{report.flagged_count}</span>
                <span className="screening-page__stat-label">Flagged excursions</span>
              </div>
              <div className="screening-page__stat">
                <span className="screening-page__stat-value">
                  {report.total_trips > 0
                    ? `${(((report.total_trips - report.flagged_count) / report.total_trips) * 100).toFixed(0)}%`
                    : "—"}
                </span>
                <span className="screening-page__stat-label">In spec</span>
              </div>
            </div>

            {report.screening_notes.map((note, i) => (
              <p key={i} className="screening-page__note">{note}</p>
            ))}

            <MeanTempChart productMeans={report.product_means} />

            {report.flagged_trips.length > 0 && (
              <section className="screening-page__flagged">
                <h2 className="screening-page__section-title">
                  Flagged Trips ({report.flagged_trips.length})
                </h2>
                {report.flagged_trips.map((trip, i) => (
                  <TripCard
                    key={i}
                    trip={trip}
                    sessionId={primaryReport.session_id}
                    rawdataSessionId={rawdataReport?.session_id}
                  />
                ))}
              </section>
            )}
          </>
        )}

        <div className="screening-page__actions">
          <button type="button" className="screening-page__btn screening-page__btn--secondary" onClick={() => navigate("/audit")}>
            Back to Audit
          </button>
          <button type="button" className="screening-page__btn screening-page__btn--primary" onClick={() => navigate("/features")}>
            Continue to Features
          </button>
        </div>
      </main>
    </div>
  );
}
