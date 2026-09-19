export type UploadSlotId = "sensiwatch" | "coldstream" | "thresholds" | "customerKpis" | "analysisProfile" | "reportTemplate" | "rawLight" | "rawTemperature";

export interface UploadSlotConfig {
  id: UploadSlotId;
  title: string;
  description: string;
  required: boolean;
  accept: string;
  acceptLabel: string;
}

export type UploadStatus = "empty" | "selected" | "error";
