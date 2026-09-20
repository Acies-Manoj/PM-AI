import type { SegmentOutliersResult } from "../api/audit";
import "./OutlierTabs.css";

interface Props {
  data: SegmentOutliersResult;
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
      <p className="outlier-tab__hint">
        Trips whose own transit duration (Segment Length) falls outside their lane's Tukey fence -- the outliers
        themselves, not the fence numbers.
      </p>

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
              {data.outlier_rows.map((r, idx) => (
                <tr key={`${idx}::${r.serial ?? "?"}::${r.trip_id ?? "?"}`}>
                  <td>{r.serial ?? "—"}</td>
                  <td>{r.trip_id ?? "—"}</td>
                  <td>{r.origin}</td>
                  <td>{r.destination}</td>
                  <td>{r.segment_days ?? "—"}</td>
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
  );
}
