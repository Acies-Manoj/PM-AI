import { useEffect, useMemo, useState } from "react";
import type { LaneResult, OutliersResponse, SegmentOutliersResult } from "../api/audit";
import { updateTripValue } from "../api/audit";
import { IconChevronRight, IconSearch } from "./icons";
import EditableNumberCell from "./EditableNumberCell";
import ExcelTable from "./ExcelTable";
import "./OutlierTabs.css";

interface Props {
  data: SegmentOutliersResult;
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
}

const STATUS_LABELS: Record<LaneResult["status_type"], string> = {
  own_lane: "Own-Lane Fence",
  insufficient: "Insufficient History",
};

// Same fuzzy match backend/app/services/audit/outlier_detectors.py's
// _find_col uses -- finds this lane's own Serial/Trip ID/Segment Length
// columns among the ORIGINAL (non-normalized) column names, so the lane
// detail modal's table can offer the same inline edit the flat table used to.
function findColumn(columns: string[], ...needles: string[]): string | null {
  const lowered = columns.map((c) => c.toLowerCase());
  for (let i = 0; i < lowered.length; i++) {
    if (needles.every((n) => lowered[i].includes(n))) return columns[i];
  }
  return null;
}

function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

export default function SegmentOutlierTab({ data, sessionId, onUpdated }: Props) {
  const [query, setQuery] = useState("");
  const [openLane, setOpenLane] = useState<LaneResult | null>(null);

  // Keep the open lane's rows in sync with freshly recomputed data after an
  // edit -- `openLane` is a snapshot captured at click time, so without this
  // a correction made inside the modal wouldn't be reflected in it.
  useEffect(() => {
    if (!openLane) return;
    const fresh = data.lanes.find((l) => l.origin === openLane.origin && l.destination === openLane.destination);
    setOpenLane(fresh ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const filteredLanes = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return data.lanes;
    return data.lanes.filter(
      (l) => l.origin.toLowerCase().includes(q) || l.destination.toLowerCase().includes(q)
    );
  }, [data.lanes, query]);

  const serialCol = useMemo(() => findColumn(data.columns, "serial"), [data.columns]);
  const tripCol = useMemo(() => findColumn(data.columns, "trip", "id"), [data.columns]);
  const durationCol = useMemo(() => findColumn(data.columns, "segment", "day"), [data.columns]);

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
          Trips whose own transit duration (Segment Length) falls outside their lane's 5th-95th percentile fence --
          computed only from that exact route's own trips. Click a lane below to see its flagged trips.
        </p>
        {data.lanes.length > 0 && (
          <div className="outlier-tab__search">
            <span className="outlier-tab__search-icon">
              <IconSearch />
            </span>
            <input
              type="text"
              className="outlier-tab__search-input"
              placeholder="Filter lanes by origin or destination…"
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

      {data.lanes.length > 0 && (
        <div className="outlier-tab__lanes">
          <h4 className="outlier-tab__lanes-title">Lanes (Origin → Destination)</h4>
          <div className="outlier-tab__lane-list">
            {filteredLanes.map((lane) => (
              <button
                type="button"
                key={`${lane.origin}::${lane.destination}`}
                className="outlier-tab__lane-item"
                disabled={lane.n_outliers === 0}
                onClick={() => setOpenLane(lane)}
              >
                <span className="outlier-tab__lane-route">
                  {lane.origin} → {lane.destination}
                </span>
                <span className={`outlier-tab__lane-badge outlier-tab__lane-badge--${lane.status_type}`}>
                  {STATUS_LABELS[lane.status_type]}
                </span>
                <span className="outlier-tab__lane-fence">
                  {lane.lower_fence != null && lane.upper_fence != null
                    ? `${lane.lower_fence.toFixed(1)} – ${lane.upper_fence.toFixed(1)} days`
                    : "—"}
                </span>
                <span className="outlier-tab__lane-count">
                  {lane.n_outliers > 0 ? `${lane.n_outliers} of ${lane.n_trips} flagged` : `${lane.n_trips} trips`}
                </span>
                {lane.n_outliers > 0 && <IconChevronRight />}
              </button>
            ))}
            {filteredLanes.length === 0 && (
              <p className="outlier-tab__empty">No lanes match "{query}".</p>
            )}
          </div>
        </div>
      )}

      {openLane && (
        <div className="audit-issue__modal-backdrop" onClick={() => setOpenLane(null)}>
          <div className="audit-issue__modal outlier-tab__product-modal" onClick={(e) => e.stopPropagation()}>
            <div className="audit-issue__modal-head">
              <div className="audit-issue__top">
                <h4 className="audit-issue__title">
                  {openLane.origin} → {openLane.destination}
                </h4>
              </div>
              <button type="button" className="audit-issue__modal-close" onClick={() => setOpenLane(null)} aria-label="Close">
                ✕
              </button>
            </div>
            <div className="audit-issue__modal-body">
              <p className="outlier-tab__hint">
                {openLane.n_outliers} of {openLane.n_trips} trip{openLane.n_trips === 1 ? "" : "s"} fell outside this
                lane's fence
                {openLane.lower_fence != null && openLane.upper_fence != null
                  ? ` (${openLane.lower_fence.toFixed(1)} – ${openLane.upper_fence.toFixed(1)} days, ${openLane.status_label}).`
                  : "."}{" "}
                {durationCol && "Click a Segment Days value below to correct it."}
              </p>
              <ExcelTable
                columns={data.columns}
                rows={openLane.outlier_rows}
                frozen={[serialCol, tripCol, durationCol].filter((c): c is string => c != null)}
                highlight={durationCol ?? undefined}
                renderCell={(col, row) => {
                  const serial = serialCol ? row[serialCol] : null;
                  const tripId = tripCol ? row[tripCol] : null;
                  if (col !== durationCol || serial == null || tripId == null) return undefined;
                  return (
                    <EditableNumberCell
                      value={toNumberOrNull(row[col])}
                      onSave={async (next) => {
                        const updated = await updateTripValue(sessionId, {
                          serial: String(serial),
                          tripId: tripId as string | number,
                          field: "segment_days",
                          value: next,
                        });
                        onUpdated(updated);
                      }}
                    />
                  );
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
