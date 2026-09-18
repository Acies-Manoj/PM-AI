import { AuditApiError } from "./audit";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface RawDataTrip {
  serial: string;
  trip_id: number;
  label: string;
  start_time: string;
}

export interface RawDataUploadResponse {
  session_id: string;
  interval_minutes: number;
  trips: RawDataTrip[];
  temperature_uploaded: boolean;
  temperature_matched: number | null;
  temperature_total: number | null;
  light_uploaded: boolean;
  light_matched: number | null;
  light_total: number | null;
}

export interface RawDataSeriesPoint {
  t: string;
  v: number | null;
}

export interface RawDataChannel {
  unit: string;
  points: RawDataSeriesPoint[];
}

export interface RawDataTripSeriesResponse {
  session_id: string;
  serial: string;
  trip_id: number;
  start_time: string;
  interval_minutes: number;
  temperature: RawDataChannel | null;
  light: RawDataChannel | null;
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.detail ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

export async function uploadRawData(
  aggregatedFile: File,
  temperatureMatrixFile: File | null,
  lightMatrixFile: File | null
): Promise<RawDataUploadResponse> {
  const formData = new FormData();
  formData.append("aggregated", aggregatedFile);
  if (temperatureMatrixFile) formData.append("temperature_matrix", temperatureMatrixFile);
  if (lightMatrixFile) formData.append("light_matrix", lightMatrixFile);

  const response = await fetch(`${API_BASE_URL}/api/raw-data/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchTripSeries(sessionId: string, serial: string, tripId: number): Promise<RawDataTripSeriesResponse> {
  const params = new URLSearchParams({ serial, trip_id: String(tripId) });
  const response = await fetch(`${API_BASE_URL}/api/raw-data/${sessionId}/trip?${params.toString()}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

// -- Step 1 screening: outlier/threshold flags (see anomaly_detection.py) --

export interface RawDataFlaggedTrip {
  serial: string;
  trip_id: number;
  label: string;
  flag_count: number;
  flags: string[];
  duration_outlier: boolean;
  mean_temp: number | null;
  product: string | null;
}

export interface RawDataTripMeanTemp {
  serial: string;
  trip_id: number;
  label: string;
  start_time: string;
  product: string | null;
  mean_temp: number | null;
  limit_low: number | null;
  limit_ideal: number | null;
  limit_high: number | null;
  flagged: boolean;
}

export interface RawDataFlagsResponse {
  session_id: string;
  total_trips: number;
  all_trips: RawDataTripMeanTemp[];
  flagged_trips: RawDataFlaggedTrip[];
}

export interface RcaHypothesis {
  hypothesis: string;
  score: number;
  confidence: string;
  rationale: string[];
}

export interface RawDataRcaResponse {
  session_id: string;
  serial: string;
  trip_id: number;
  hypotheses: RcaHypothesis[];
}

export async function fetchFlags(sessionId: string): Promise<RawDataFlagsResponse> {
  const response = await fetch(`${API_BASE_URL}/api/raw-data/${sessionId}/flags`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}

export async function fetchRca(sessionId: string, serial: string, tripId: number): Promise<RawDataRcaResponse> {
  const params = new URLSearchParams({ serial, trip_id: String(tripId) });
  const response = await fetch(`${API_BASE_URL}/api/raw-data/${sessionId}/rca?${params.toString()}`);
  if (!response.ok) {
    throw new AuditApiError(await parseErrorDetail(response));
  }
  return response.json();
}
