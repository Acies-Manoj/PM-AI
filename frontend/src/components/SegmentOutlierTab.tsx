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
const COLUMNS = ["Serial Number", "Trip ID", "Segment Days", "Origin", "Destination", "Lower Fence", "Upper Fence", "Status"];
const TRIP_REF = "__trip";

type ModeGroup = "Road" | "Ocean" | "Others";
const MODE_GROUPS: ModeGroup[] = ["Road", "Ocean", "Others"];

// Anything that isn't Road or Ocean (Rail, blank, ...) is bucketed under "Others".
function modeGroup(mode: string | null): ModeGroup {
  const m = (mode ?? "").trim().toLowerCase();
  return m === "road" ? "Road" : m === "ocean" ? "Ocean" : "Others";
}

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
  // Mode groups switched OFF (everything is shown by default).
  const [hiddenGroups, setHiddenGroups] = useState<Set<ModeGroup>>(new Set());

  const groupCounts = useMemo(() => {
    const out: Record<ModeGroup, number> = { Road: 0, Ocean: 0, Others: 0 };
    for (const r of data.outlier_rows) out[modeGroup(r.mode)] += 1;
    return out;
  }, [data.outlier_rows]);

  const toggleGroup = (g: ModeGroup) =>
    setHiddenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.outlier_rows
      .filter((r) => !hiddenGroups.has(modeGroup(r.mode)))
      .filter(
        (r) =>
          !q ||
          [r.serial, r.trip_id, r.origin, r.destination, r.segment_days, statusLabel(r)].some((v) =>
            String(v ?? "").toLowerCase().includes(q)
          )
      )
      .map((r) => ({
        "Serial Number": r.serial,
        "Trip ID": r.trip_id,
        "Segment Days": r.segment_days,
        Origin: r.origin,
        Destination: r.destination,
        "Lower Fence": r.lower_fence_days != null ? Math.round(r.lower_fence_days * 100) / 100 : null,
        "Upper Fence": r.upper_fence_days != null ? Math.round(r.upper_fence_days * 100) / 100 : null,
        Status: statusLabel(r),
        [TRIP_REF]: r,
      }));
  }, [data.outlier_rows, query, hiddenGroups]);

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
        Trips outside their lane's normal duration range (5th–95th percentile) by more than 15%. Click a Segment Days value to correct it.
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

      {data.outlier_rows.length > 0 && (
        <div className="outlier-tab__modes" role="group" aria-labelledby="seg-mode-title">
          <span id="seg-mode-title" className="outlier-tab__modes-title">Mode of transport</span>
          <div className="outlier-tab__modes-pills">
          {MODE_GROUPS.map((g) => {
            const on = !hiddenGroups.has(g);
            return (
              <button
                key={g}
                type="button"
                aria-pressed={on}
                className={`outlier-tab__mode${on ? " is-on" : ""}`}
                onClick={() => toggleGroup(g)}
              >
                {g} <span className="outlier-tab__mode-n">({groupCounts[g]})</span>
              </button>
            );
          })}
          </div>
        </div>
      )}

      {data.flagged_trips === 0 ? (
        <p className="outlier-tab__all-clear">No trips fell outside their lane's duration fence.</p>
      ) : (
        <>
          <ExcelTable
            columns={COLUMNS}
            rows={rows}
            frozen={["Serial Number", "Trip ID", "Segment Days"]}
            highlight="Segment Days"
            emptyText={query || hiddenGroups.size > 0 ? "No trips match the current search or mode selection." : undefined}
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
