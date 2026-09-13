const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface FlaggedTrip {
  trip_id: string;
  product: string;
  mean_temp: number;
  temp_limit: number | null;
  exceedance: number | null;
  segment_days_above: number;
  origin: string | null;
  destination: string | null;
}

export interface ScreeningReport {
  session_id: string;
  total_trips: number;
  flagged_count: number;
  flagged_trips: FlaggedTrip[];
  product_means: Record<string, number>;
  screening_notes: string[];
}

export interface TripTrace {
  trip_id: string;
  timestamps: string[];
  temperatures: (number | null)[];
  light_events: string[];
}

export class ScreeningApiError extends Error {}

async function parseError(res: Response): Promise<string> {
  try {
    const b = await res.json();
    return b.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

export async function runScreening(
  sessionId: string,
  rawdataSessionId?: string,
  customThresholds?: Record<string, number>
): Promise<ScreeningReport> {
  const res = await fetch(`${API_BASE_URL}/api/screening/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      rawdata_session_id: rawdataSessionId ?? null,
      custom_thresholds: customThresholds ?? null,
    }),
  });
  if (!res.ok) throw new ScreeningApiError(await parseError(res));
  return res.json();
}

export async function fetchTripTrace(
  sessionId: string,
  tripId: string,
  rawdataSessionId?: string
): Promise<TripTrace> {
  const params = rawdataSessionId ? `?rawdata_session_id=${rawdataSessionId}` : "";
  const res = await fetch(
    `${API_BASE_URL}/api/screening/${sessionId}/trip/${encodeURIComponent(tripId)}/trace${params}`
  );
  if (!res.ok) throw new ScreeningApiError(await parseError(res));
  return res.json();
}
