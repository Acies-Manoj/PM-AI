import { useMemo, useState } from "react";
import type { OutliersResponse, SegmentOutlierRow, SegmentOutliersResult } from "../api/audit";
import { updateTripValue } from "../api/audit";
import { IconSearch } from "./icons";
import EditableNumberCell from "./EditableNumberCell";
import ExcelTable from "./ExcelTable";
import "./OutlierTabs.css";

interface Props {
  data: SegmentOutliersResult;
  sessionId: string;
  onUpdated: (updated: OutliersResponse) => void;
}

// Columns of the flagged-trips table. TRIP_REF carries each row's source record.
const COLUMNS = ["Serial Number", "Trip ID", "Segment Days", "Mode of Transport", "Origin", "Destination", "Lower Fence", "Upper Fence", "Status"];
const TRIP_REF = "__trip";

function statusLabel(row: SegmentOutlierRow): string {
  if (row.status.startsWith("Two Trips")) return "Pair disagrees";
  const days = row.segment_days;
  if (days == null) return "Outlier";
  if (row.lower_fence_days != null && days < row.lower_fence_days) return "Too short";
  if (row.upper_fence_days != null && days > row.upper_fence_days) return "Too long";
  return "Outlier";
}

export default function SegmentOutlierTab({ data, sessionId, onUpdated }: Props) {
  const [query, setQuery] = useState("");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.outlier_rows
      .filter(
        (r) =>
          !q ||
          [r.serial, r.trip_id, r.mode, r.origin, r.destination, r.segment_days, statusLabel(r)].some((v) =>
            String(v ?? "").toLowerCase().includes(q)
          )
      )
      .map((r) => ({
        "Serial Number": r.serial,
        "Trip ID": r.trip_id,
        "Segment Days": r.segment_days,
        "Mode of Transport": r.mode,
        Origin: r.origin,
        Destination: r.destination,
        "Lower Fence": r.lower_fence_days != null ? Math.round(r.lower_fence_days * 100) / 100 : null,
        "Upper Fence": r.upper_fence_days != null ? Math.round(r.upper_fence_days * 100) / 100 : null,
        Status: statusLabel(r),
        [TRIP_REF]: r,
      }));
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
        Trips whose transit duration (Segment Length) falls outside their lane's 5th-95th percentile fence, computed
        only from that exact route's own trips. A lane with 1 trip uses it as the baseline; a lane with 2 trips is
        flagged only if they differ by 3+ days and 1.5x or more. Click a Segment Days value to correct it.
      </p>
      {data.outlier_rows.length > 0 && (
        <div className="outlier-tab__search">
          <span className="outlier-tab__search-icon">
            <IconSearch />
          </span>
          <input
            type="text"
            className="outlier-tab__search-input"
            placeholder="Search serial, trip, origin, destination…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button type="button" className="outlier-tab__search-clear" aria-label="Clear search" onClick={() => setQuery("")}>
              ✕
            </button>
          )}
        </div>
      )}
      </div>

      {data.flagged_trips === 0 ? (
        <p className="outlier-tab__all-clear">No trips fell outside their lane's duration fence.</p>
      ) : (
        <>
          <ExcelTable
            columns={COLUMNS}
            rows={rows}
            frozen={["Serial Number", "Trip ID", "Segment Days"]}
            highlight="Segment Days"
            emptyText={query ? `No trips match "${query}".` : undefined}
            renderCell={(col, row) => {
              if (col !== "Segment Days") return undefined;
              const t = row[TRIP_REF] as SegmentOutlierRow;
              if (t.serial == null || t.trip_id == null) return t.segment_days != null ? String(t.segment_days) : "—";
              return (
                <EditableNumberCell
                  value={t.segment_days}
                  onSave={async (next) => {
                    const updated = await updateTripValue(sessionId, {
                      serial: String(t.serial),
                      tripId: t.trip_id as string | number,
                      field: "segment_days",
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
