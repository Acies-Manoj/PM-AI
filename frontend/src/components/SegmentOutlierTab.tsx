import { useMemo, useState } from "react";
import type { OutliersResponse, SegmentOutliersResult } from "../api/audit";
import { updateTripValue } from "../api/audit";
import { IconSearch } from "./icons";
import EditableNumberCell from "./EditableNumberCell";
import "./OutlierTabs.css";

interface Props {
  data: SegmentOutliersResult;
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
}

export default function SegmentOutlierTab({ data, sessionId, onUpdated }: Props) {
  const [query, setQuery] = useState("");

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data.outlier_rows;
    return data.outlier_rows.filter((r) =>
      [r.serial, r.trip_id, r.origin, r.destination, r.status].some(
        (v) => v != null && String(v).toLowerCase().includes(q)
      )
    );
  }, [data.outlier_rows, query]);

  if (!data.column_found) {
    return (
      <div className="outlier-tab__missing">
        <p>Column "Segment Length (Days)" not found in this dataset. Segment outlier analysis is unavailable.</p>
      </div>
    );
  }

  return (
    <div className="outlier-tab">
      <div className="outlier-tab__toolbar-row">
        <p className="outlier-tab__hint">
          Trips whose own transit duration (Segment Length) falls outside their lane's Tukey fence -- the outliers
          themselves, not the fence numbers. Click a Segment Days value to correct it.
        </p>
        {data.flagged_trips > 0 && (
          <div className="outlier-tab__search">
            <span className="outlier-tab__search-icon">
              <IconSearch />
            </span>
            <input
              type="text"
              className="outlier-tab__search-input"
              placeholder="Filter by serial, trip ID, origin, destination…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query && (
              <button type="button" className="outlier-tab__search-clear" aria-label="Clear filter" onClick={() => setQuery("")}>
                ✕
              </button>
            )}
          </div>
        )}
      </div>

      {data.flagged_trips === 0 && (
        <p className="outlier-tab__all-clear">No trips fell outside their lane's duration fence.</p>
      )}

      {data.flagged_trips > 0 && (
        <div className="outlier-tab__table-wrap">
          <table className="outlier-tab__table">
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
              {filteredRows.map((r, idx) => (
                <tr key={`${idx}::${r.serial ?? "?"}::${r.trip_id ?? "?"}`}>
                  <td>{r.serial ?? "—"}</td>
                  <td>{r.trip_id ?? "—"}</td>
                  <td>{r.origin}</td>
                  <td>{r.destination}</td>
                  <td>
                    {r.serial != null && r.trip_id != null ? (
                      <EditableNumberCell
                        value={r.segment_days}
                        onSave={async (next) => {
                          const updated = await updateTripValue(sessionId, {
                            serial: r.serial!,
                            tripId: r.trip_id!,
                            field: "segment_days",
                            value: next,
                          });
                          onUpdated(updated);
                        }}
                      />
                    ) : (
                      r.segment_days ?? "—"
                    )}
                  </td>
                  <td>
                    {r.lower_fence_days != null && r.upper_fence_days != null
                      ? `${r.lower_fence_days} – ${r.upper_fence_days}`
                      : "—"}
                  </td>
                  <td>{r.status}</td>
                </tr>
              ))}
              {filteredRows.length === 0 && (
                <tr>
                  <td colSpan={7} className="outlier-tab__table-empty">
                    No outliers match "{query}".
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
