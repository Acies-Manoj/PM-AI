import { useState } from "react";
import type { LaneResult, SegmentOutliersResult } from "../api/audit";
import "./OutlierTabs.css";

interface Props {
  data: SegmentOutliersResult;
}

function LaneCard({ lane, columns }: { lane: LaneResult; columns: string[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="outlier-lane-card">
      <button
        type="button"
        className="outlier-lane-card__header"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="outlier-lane-card__route">
          <span>{lane.origin || "—"}</span>
          <span className="outlier-lane-card__arrow">→</span>
          <span>{lane.destination || "—"}</span>
        </div>
        <div className="outlier-lane-card__meta">
          <span className={`outlier-lane-card__status-badge outlier-lane-card__status-badge--${lane.status_type}`}>
            {lane.status_type === "own_lane"
              ? "Own-Lane Fence"
              : lane.status_type === "peer_shrunk"
              ? "Peer-Shrunk"
              : "Insufficient"}
          </span>
          {lane.lower_fence !== null && lane.upper_fence !== null && (
            <span className="outlier-lane-card__fence">
              [{lane.lower_fence.toFixed(1)} – {lane.upper_fence.toFixed(1)} days]
            </span>
          )}
          <span className={`outlier-lane-card__count${lane.n_outliers > 0 ? " outlier-lane-card__count--flagged" : ""}`}>
            {lane.n_outliers} / {lane.n_trips} outlier{lane.n_outliers !== 1 ? "s" : ""}
          </span>
        </div>
        <span className="outlier-lane-card__chevron">{expanded ? "▲" : "▼"}</span>
      </button>

      {expanded && lane.outlier_rows.length > 0 && (
        <div className="outlier-lane-card__trips">
          <table className="outlier-lane-card__table">
            <thead>
              <tr>
                {columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lane.outlier_rows.map((row, idx) => (
                <tr key={idx}>
                  {columns.map((col) => {
                    const val = row[col];
                    return (
                      <td key={col}>
                        {val === null || val === undefined ? "—" : String(val)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded && lane.outlier_rows.length === 0 && lane.n_outliers === 0 && (
        <div className="outlier-lane-card__trips outlier-lane-card__trips--empty">
          No outlier rows in this lane.
        </div>
      )}
    </div>
  );
}

export default function SegmentOutlierTab({ data }: Props) {
  if (!data.column_found) {
    return (
      <div className="outlier-tab__missing">
        <p>Column "Segment Length (Days)" not found in this dataset. Segment outlier analysis is unavailable.</p>
      </div>
    );
  }

  return (
    <div className="outlier-tab">
      <div className="outlier-tab__summary">
        <span className="outlier-tab__summary-stat">
          <strong>{data.total_trips.toLocaleString()}</strong> trips analyzed
        </span>
        <span className="outlier-tab__summary-stat outlier-tab__summary-stat--flagged">
          <strong>{data.flagged_trips}</strong> outlier{data.flagged_trips !== 1 ? "s" : ""} detected
        </span>
        <span className="outlier-tab__summary-stat">
          <strong>{data.lanes.length}</strong> lane{data.lanes.length !== 1 ? "s" : ""}
        </span>
      </div>

      {data.flagged_trips === 0 && (
        <p className="outlier-tab__all-clear">No segment length outliers detected.</p>
      )}

      <div className="outlier-tab__lanes">
        {data.lanes.map((lane) => (
          <LaneCard
            key={`${lane.origin}__${lane.destination}`}
            lane={lane}
            columns={data.columns}
          />
        ))}
      </div>
    </div>
  );
}
