import { useState } from "react";
import type { ProductTemperatureResult, TemperatureOutliersResult } from "../api/audit";
import "./OutlierTabs.css";

interface Props {
  data: TemperatureOutliersResult;
}

function TempBarChart({ product }: { product: ProductTemperatureResult }) {
  const max = product.total;
  const pct = (n: number) => (max > 0 ? (n / max) * 100 : 0);

  const rows: { label: string; value: number; cls: string }[] = [
    { label: "In Spec", value: product.in_spec, cls: "in-spec" },
    { label: "Too Warm", value: product.too_warm, cls: "too-warm" },
    { label: "Too Cold", value: product.too_cold, cls: "too-cold" },
  ];

  return (
    <div className="temp-bar-chart">
      <div className="temp-bar-chart__title">{product.product} — {product.total} trips</div>
      <div className="temp-bar-chart__bars">
        {rows.map(({ label, value, cls }) => (
          <div key={cls} className="temp-bar-chart__row">
            <span className="temp-bar-chart__label">{label}</span>
            <div className="temp-bar-chart__track">
              <div
                className={`temp-bar-chart__fill temp-bar-chart__fill--${cls}`}
                style={{ width: `${pct(value)}%` }}
              />
            </div>
            <span className="temp-bar-chart__value">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function TemperatureOutlierTab({ data }: Props) {
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null);

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
  const activeProduct = data.by_product.find((p) => p.product === selectedProduct) ?? null;

  return (
    <div className="outlier-tab">
      <div className="outlier-tab__summary">
        <span className="outlier-tab__summary-stat">
          <strong>{data.total_trips.toLocaleString()}</strong> trips
        </span>
        <span className="outlier-tab__summary-stat outlier-tab__summary-stat--flagged">
          <strong>{data.too_warm_count}</strong> too warm
        </span>
        <span className="outlier-tab__summary-stat outlier-tab__summary-stat--cold">
          <strong>{data.too_cold_count}</strong> too cold
        </span>
        <span className="outlier-tab__summary-stat">
          <strong>{data.by_product.length}</strong> product{data.by_product.length !== 1 ? "s" : ""}
        </span>
      </div>

      {totalBreaches === 0 && (
        <p className="outlier-tab__all-clear">No temperature breaches detected. All trips are within their configured limits.</p>
      )}

      <div className="outlier-tab__products">
        {data.by_product.map((p) => {
          const isActive = selectedProduct === p.product;
          const hasIssues = p.too_warm + p.too_cold > 0;
          return (
            <button
              key={p.product}
              type="button"
              className={`temp-product-card${hasIssues ? " temp-product-card--has-issues" : ""}${isActive ? " temp-product-card--active" : ""}`}
              onClick={() => setSelectedProduct(isActive ? null : p.product)}
            >
              <div className="temp-product-card__name" title={p.product}>{p.product}</div>
              <div className="temp-product-card__counts">
                <span className="temp-product-card__count temp-product-card__count--ok">{p.in_spec} ok</span>
                {p.too_warm > 0 && (
                  <span className="temp-product-card__count temp-product-card__count--warm">+{p.too_warm} warm</span>
                )}
                {p.too_cold > 0 && (
                  <span className="temp-product-card__count temp-product-card__count--cold">+{p.too_cold} cold</span>
                )}
              </div>
              {p.total > 0 && (
                <div className="temp-product-card__bar">
                  <div className="temp-product-card__bar-seg temp-product-card__bar-seg--ok" style={{ width: `${(p.in_spec / p.total) * 100}%` }} />
                  <div className="temp-product-card__bar-seg temp-product-card__bar-seg--warm" style={{ width: `${(p.too_warm / p.total) * 100}%` }} />
                  <div className="temp-product-card__bar-seg temp-product-card__bar-seg--cold" style={{ width: `${(p.too_cold / p.total) * 100}%` }} />
                </div>
              )}
            </button>
          );
        })}
      </div>

      {activeProduct && (
        <div className="outlier-tab__chart-area">
          <TempBarChart product={activeProduct} />
        </div>
      )}
    </div>
  );
}
