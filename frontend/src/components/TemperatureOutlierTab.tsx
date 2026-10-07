import { useMemo, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { OutliersResponse, ProductTemperatureResult, ProductTemperatureTrip, TemperatureOutliersResult } from "../api/audit";
import { updateTripValue } from "../api/audit";
import { IconChevronRight, IconSearch } from "./icons";
import EditableNumberCell from "./EditableNumberCell";
import ExcelTable from "./ExcelTable";
import { CHART_COLORS } from "../utils/chartTheme";
import "./OutlierTabs.css";

const Plot = createPlotlyComponent(Plotly);

interface Props {
  data: TemperatureOutliersResult;
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
}

// Same categorical palette as AnalysisChart.tsx / report_style.py -- a trip's
// bar reads blue when in spec, the shared error red when it's the reason
// the product got flagged.
const COLOR_IN_SPEC = CHART_COLORS.primary;
const COLOR_OUT_OF_RANGE = CHART_COLORS.negative;
const COLOR_SELECTED = CHART_COLORS.highlight;
const COLOR_LOW = CHART_COLORS.secondary;
const COLOR_AVG = CHART_COLORS.neutral;
const COLOR_OUTLIER_LINE = CHART_COLORS.highlight;

// Columns of the affected-trips table (the Flags count is no longer shown). TRIP_REF carries each row's trip.
const TRIP_COLUMNS = ["Serial Number", "Trip ID", "Mean Temp", "Low Limit", "Status"];
const TRIP_REF = "__trip";

function statusLabel(status: ProductTemperatureTrip["status"]): string {
  return status === "too_warm" ? "Too Warm" : status === "too_cold" ? "Too Cold" : "In Spec";
}

function tripKey(t: { serial: string | null; trip_id: number | string | null }): string {
  return `${t.serial ?? "?"}::${t.trip_id ?? "?"}`;
}

function ProductTempChart({
  product,
  selectedKey,
  onBarClick,
}: {
  product: ProductTemperatureResult;
  selectedKey: string | null;
  onBarClick: (trip: ProductTemperatureTrip) => void;
}) {
  const trips = product.trips;
  const flaggedCount = product.too_warm + product.too_cold;
  const lowLimit = trips.find((t) => t.limit_low != null)?.limit_low ?? null;
  const selectedTrip = selectedKey ? trips.find((t) => tripKey(t) === selectedKey) ?? null : null;

  const traces: Partial<Plotly.PlotData>[] = [
    {
      type: "bar",
      name: product.product,
      x: trips.map((t) => String(t.trip_id ?? "—")),
      y: trips.map((t) => t.mean_temp),
      customdata: trips.map((t) => tripKey(t)) as unknown as Plotly.Datum[],
      hovertemplate: "Trip %{x}<br>Mean Temp: %{y}°<extra></extra>",
      marker: { color: trips.map((t) => (t.status === "in_spec" ? COLOR_IN_SPEC : COLOR_OUT_OF_RANGE)) },
    },
  ];

  // A marker drawn on top of the selected trip's bar -- clicking a table
  // row highlights the bar this way, regardless of how many bars are on
  // screen (a border tweak on one bar among a thousand is easy to miss).
  if (selectedTrip) {
    traces.push({
      type: "scatter",
      mode: "markers",
      x: [String(selectedTrip.trip_id ?? "—")],
      y: [selectedTrip.mean_temp],
      marker: { color: COLOR_SELECTED, size: 13, symbol: "circle-open", line: { color: COLOR_SELECTED, width: 3 } },
      hoverinfo: "skip",
      showlegend: false,
    });
  }

  const shapes: Partial<Plotly.Shape>[] = [];
  const addLine = (y: number | null | undefined, color: string) => {
    if (y == null) return;
    shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color, width: 1.5, dash: "dash" } });
  };
  addLine(lowLimit, COLOR_LOW);
  addLine(product.avg_temp, COLOR_AVG);
  addLine(product.outlier_line, COLOR_OUTLIER_LINE);

  return (
    <div className="temp-chart">
      <div className="temp-chart__head">
        <h3 className="temp-chart__title">{product.product}</h3>
        <div className="temp-chart__pills">
          {lowLimit != null && <span className="temp-chart__pill temp-chart__pill--low">Low: {lowLimit}°</span>}
          {product.avg_temp != null && (
            <span className="temp-chart__pill temp-chart__pill--avg">Avg: {product.avg_temp}°</span>
          )}
          {product.outlier_line != null && (
            <span className="temp-chart__pill temp-chart__pill--cutoff">Outlier above: {product.outlier_line}°</span>
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
          yaxis: { title: { text: "Mean Temp (°)" }, gridcolor: CHART_COLORS.grid, zeroline: false },
          shapes,
        }}
        config={{ displayModeBar: "hover", displaylogo: false, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
        onClick={(e) => {
          const point = e.points?.[0] as unknown as { curveNumber?: number; customdata?: string } | undefined;
          if (!point || point.curveNumber !== 0 || !point.customdata) return;
          const trip = trips.find((t) => tripKey(t) === point.customdata);
          if (trip) onBarClick(trip);
        }}
      />
    </div>
  );
}

function AffectedTripsPanel({
  flaggedTrips,
  sessionId,
  onUpdated,
  show,
  setShow,
  query,
  setQuery,
  selectedKey,
  onRowClick,
  rowRefs,
}: {
  flaggedTrips: ProductTemperatureTrip[];
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
  show: boolean;
  setShow: (v: boolean | ((s: boolean) => boolean)) => void;
  query: string;
  setQuery: (v: string) => void;
  selectedKey: string | null;
  onRowClick: (trip: ProductTemperatureTrip) => void;
  rowRefs: React.MutableRefObject<Map<string, HTMLTableRowElement>>;
}) {
  const filteredTrips = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return flaggedTrips;
    return flaggedTrips.filter(
      (t) => (t.serial != null && t.serial.toLowerCase().includes(q)) || (t.trip_id != null && String(t.trip_id).toLowerCase().includes(q))
    );
  }, [flaggedTrips, query]);

  if (flaggedTrips.length === 0) return null;

  return (
    <div className="temp-chart__affected">
      <button type="button" className="temp-chart__affected-toggle" onClick={() => setShow((s) => !s)}>
        {show ? "▾" : "▸"} {show ? "Hide" : "Show"} affected trips ({flaggedTrips.length})
      </button>

      {show && (
        <>
          <div className="outlier-tab__search outlier-tab__search--compact">
            <span className="outlier-tab__search-icon">
              <IconSearch />
            </span>
            <input
              type="text"
              className="outlier-tab__search-input"
              placeholder="Filter by serial or trip ID…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button type="button" className="outlier-tab__search-clear" aria-label="Clear filter" onClick={() => setQuery("")}>
                ✕
              </button>
            )}
          </div>

          <ExcelTable
            columns={TRIP_COLUMNS}
            rows={filteredTrips.map((t) => ({
              "Serial Number": t.serial,
              "Trip ID": t.trip_id,
              "Mean Temp": t.mean_temp,
              "Low Limit": t.limit_low,
              Status: statusLabel(t.status),
              [TRIP_REF]: t,
            }))}
            frozen={["Serial Number", "Trip ID", "Mean Temp"]}
            highlight="Mean Temp"
            emptyText={query ? `No trips match "${query}".` : "No trips match the filters."}
            isRowSelected={(row) => tripKey(row[TRIP_REF] as ProductTemperatureTrip) === selectedKey}
            onRowClick={(row) => onRowClick(row[TRIP_REF] as ProductTemperatureTrip)}
            rowRef={(row, el) => {
              const key = tripKey(row[TRIP_REF] as ProductTemperatureTrip);
              if (el) rowRefs.current.set(key, el);
              else rowRefs.current.delete(key);
            }}
            renderCell={(col, row) => {
              if (col !== "Mean Temp") return undefined;
              const t = row[TRIP_REF] as ProductTemperatureTrip;
              if (t.serial == null || t.trip_id == null) return t.mean_temp != null ? `${t.mean_temp}°` : "—";
              return (
                <EditableNumberCell
                  value={t.mean_temp}
                  suffix="°"
                  onSave={async (next) => {
                    const updated = await updateTripValue(sessionId, {
                      serial: t.serial!,
                      tripId: t.trip_id!,
                      field: "mean_temp",
                      value: next,
                    });
                    onUpdated(updated);
                  }}
                />
              );
            }}
          />
        </>
      )}
    </div>
  );
}

function ProductDetail({
  product,
  sessionId,
  onUpdated,
}: {
  product: ProductTemperatureResult;
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [show, setShow] = useState(false);
  const [query, setQuery] = useState("");
  const rowRefs = useRef<Map<string, HTMLTableRowElement>>(new Map());

  const flaggedTrips = useMemo(() => product.trips.filter((t) => t.status !== "in_spec"), [product.trips]);
  const flaggedKeySet = useMemo(() => new Set(flaggedTrips.map(tripKey)), [flaggedTrips]);

  const handleBarClick = (trip: ProductTemperatureTrip) => {
    const key = tripKey(trip);
    // Only a flagged trip has a row to jump to -- an in-spec (blue) bar
    // isn't in the affected-trips table at all.
    if (!flaggedKeySet.has(key)) return;
    setSelectedKey(key);
    setShow(true);
    setQuery("");
    requestAnimationFrame(() => {
      rowRefs.current.get(key)?.scrollIntoView({ block: "center", behavior: "smooth" });
    });
  };

  const handleRowClick = (trip: ProductTemperatureTrip) => {
    setSelectedKey(tripKey(trip));
  };

  return (
    <>
      <ProductTempChart product={product} selectedKey={selectedKey} onBarClick={handleBarClick} />
      <AffectedTripsPanel
        flaggedTrips={flaggedTrips}
        sessionId={sessionId}
        onUpdated={onUpdated}
        show={show}
        setShow={setShow}
        query={query}
        setQuery={setQuery}
        selectedKey={selectedKey}
        onRowClick={handleRowClick}
        rowRefs={rowRefs}
      />
    </>
  );
}

export default function TemperatureOutlierTab({ data, sessionId, onUpdated }: Props) {
  const [openProduct, setOpenProduct] = useState<string | null>(null);
  const [productQuery, setProductQuery] = useState("");

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

  const filteredProducts = data.by_product.filter((p) => p.product.toLowerCase().includes(productQuery.trim().toLowerCase()));

  return (
    <div className="outlier-tab">
      <div className="outlier-tab__toolbar-row">
        <p className="outlier-tab__hint">
          One card per product. Open one to see its mean-temperature chart and flagged trips. Too warm = far above the product's average (more than 2 standard deviations); too cold = below the Low limit.
        </p>
        {data.by_product.length > 0 && (
          <div className="outlier-tab__search">
            <span className="outlier-tab__search-icon">
              <IconSearch />
            </span>
            <input
              type="text"
              className="outlier-tab__search-input"
              placeholder="Filter products…"
              value={productQuery}
              onChange={(e) => setProductQuery(e.target.value)}
            />
            {productQuery && (
              <button type="button" className="outlier-tab__search-clear" aria-label="Clear filter" onClick={() => setProductQuery("")}>
                ✕
              </button>
            )}
          </div>
        )}
      </div>

      {totalBreaches === 0 && (
        <p className="outlier-tab__all-clear">No temperature outliers detected: no trip is far above its product's average or below its Low limit.</p>
      )}

      <div className="audit-report__issues">
        {filteredProducts.map((p) => {
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
                    : `${p.total} trip${p.total === 1 ? "" : "s"}, none flagged`}
                </span>
              </button>
            </div>
          );
        })}
        {filteredProducts.length === 0 && (
          <p className="outlier-tab__empty">No products match "{productQuery}".</p>
        )}
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
              <ProductDetail key={activeProduct.product} product={activeProduct} sessionId={sessionId} onUpdated={onUpdated} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
