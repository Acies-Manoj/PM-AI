import { useState } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { ProductTemperatureResult, ProductTemperatureTrip, TemperatureOutliersResult } from "../api/audit";
import { IconChevronRight } from "./icons";
import "./OutlierTabs.css";

const Plot = createPlotlyComponent(Plotly);

interface Props {
  data: TemperatureOutliersResult;
}

// Same categorical palette as AnalysisChart.tsx / report_style.py -- a trip's
// bar reads blue when in spec, the shared error red when it's the reason
// the product got flagged.
const COLOR_IN_SPEC = "#152C73";
const COLOR_OUT_OF_RANGE = "#C0392B";
const COLOR_LOW = "#1891F6";
const COLOR_IDEAL = "#10B981";
const COLOR_HIGH = "#C0392B";

function statusLabel(status: ProductTemperatureTrip["status"]): string {
  return status === "too_warm" ? "Too Warm" : status === "too_cold" ? "Too Cold" : "In Spec";
}

function ProductTempChart({ product }: { product: ProductTemperatureResult }) {
  const trips = product.trips;
  const flaggedCount = product.too_warm + product.too_cold;
  const withLimits = trips.find((t) => t.limit_low != null || t.limit_ideal != null || t.limit_high != null);

  const traces: Partial<Plotly.PlotData>[] = [
    {
      type: "bar",
      name: product.product,
      x: trips.map((t) => String(t.trip_id ?? "—")),
      y: trips.map((t) => t.mean_temp),
      hovertemplate: "Trip %{x}<br>Mean Temp: %{y}°<extra></extra>",
      marker: { color: trips.map((t) => (t.status === "in_spec" ? COLOR_IN_SPEC : COLOR_OUT_OF_RANGE)) },
    },
  ];

  const shapes: Partial<Plotly.Shape>[] = [];
  const addLine = (y: number | null | undefined, color: string) => {
    if (y == null) return;
    shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1.5, dash: "dash" } });
  };
  addLine(withLimits?.limit_low, COLOR_LOW);
  addLine(withLimits?.limit_ideal, COLOR_IDEAL);
  addLine(withLimits?.limit_high, COLOR_HIGH);

  return (
    <div className="temp-chart">
      <div className="temp-chart__head">
        <h3 className="temp-chart__title">{product.product}</h3>
        <div className="temp-chart__pills">
          {withLimits?.limit_low != null && (
            <span className="temp-chart__pill temp-chart__pill--low">Low: {withLimits.limit_low}°</span>
          )}
          {withLimits?.limit_ideal != null && (
            <span className="temp-chart__pill temp-chart__pill--ideal">Ideal: {withLimits.limit_ideal}°</span>
          )}
          {withLimits?.limit_high != null && (
            <span className="temp-chart__pill temp-chart__pill--high">High: {withLimits.limit_high}°</span>
          )}
          <span className="temp-chart__pill temp-chart__pill--flagged">
            {flaggedCount} of {trips.length} flagged
          </span>
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
      />
    </div>
  );
}

export default function TemperatureOutlierTab({ data }: Props) {
  const [openProduct, setOpenProduct] = useState<string | null>(null);

  const missingCols = Object.entries(data.columns_found)
    .filter(([, found]) => !found)
    .map(([key]) => ({ mean: "Mean Value_Temperature", limit_low: "Limit Low_Temperature", limit_high: "Limit High_Temperature" }[key] ?? key));

  if (missingCols.length > 0) {
    return (
      <div className="outlier-tab__missing">
        <p>Temperature outlier analysis requires: Mean Value_Temperature, Limit Low_Temperature, Limit High_Temperature.</p>
        <p>Not found in this dataset: {missingCols.join(", ")}.</p>
      </div>
    );
  }

  const totalBreaches = data.too_warm_count + data.too_cold_count;
  const activeProduct = data.by_product.find((p) => p.product === openProduct) ?? null;
  const activeFlaggedTrips = activeProduct?.trips.filter((t) => t.status !== "in_spec") ?? [];

  return (
    <div className="outlier-tab">
      <p className="outlier-tab__hint">
        One card per product -- open one to see its mean-temperature chart and flagged trips.
      </p>

      {totalBreaches === 0 && (
        <p className="outlier-tab__all-clear">No temperature breaches detected. All trips are within their configured limits.</p>
      )}

      <div className="audit-report__issues">
        {data.by_product.map((p) => {
          const flaggedCount = p.too_warm + p.too_cold;
          return (
            <div key={p.product} className={`audit-issue ${flaggedCount > 0 ? "audit-issue--warning" : "audit-issue--info"}`}>
              <button type="button" className="audit-issue__tile" onClick={() => setOpenProduct(p.product)}>
                <div className="audit-issue__tile-head">
                  <h4 className="audit-issue__title">{p.product}</h4>
                  <span className="audit-issue__tile-chevron">
                    <IconChevronRight />
                  </span>
                </div>
                <span className="audit-issue__affected">
                  {flaggedCount > 0
                    ? `${flaggedCount} of ${p.total} trip${p.total === 1 ? "" : "s"} flagged`
                    : `${p.total} trip${p.total === 1 ? "" : "s"} -- none flagged`}
                </span>
              </button>
            </div>
          );
        })}
      </div>

      {activeProduct && (
        <div className="audit-issue__modal-backdrop" onClick={() => setOpenProduct(null)}>
          <div className="audit-issue__modal outlier-tab__product-modal" onClick={(e) => e.stopPropagation()}>
            <div className="audit-issue__modal-head">
              <div className="audit-issue__top">
                <h4 className="audit-issue__title">{activeProduct.product}</h4>
              </div>
              <button type="button" className="audit-issue__modal-close" onClick={() => setOpenProduct(null)} aria-label="Close">
                ✕
              </button>
            </div>
            <div className="audit-issue__modal-body">
              <ProductTempChart product={activeProduct} />

              {activeFlaggedTrips.length > 0 && (
                <div className="temp-chart__table-wrap">
                  <table className="outlier-lane-card__table">
                    <thead>
                      <tr>
                        <th>Serial Number</th>
                        <th>Trip ID</th>
                        <th>Flags</th>
                        <th>Mean Temp</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {activeFlaggedTrips.map((t, idx) => (
                        <tr key={`${idx}::${t.serial ?? "?"}::${t.trip_id ?? "?"}`}>
                          <td>{t.serial ?? "—"}</td>
                          <td>{t.trip_id ?? "—"}</td>
                          <td>{t.flag_count}</td>
                          <td>{t.mean_temp != null ? `${t.mean_temp}°` : "—"}</td>
                          <td>{statusLabel(t.status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
