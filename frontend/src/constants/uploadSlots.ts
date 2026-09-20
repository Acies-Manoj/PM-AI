import type { UploadSlotConfig, UploadSlotId } from "../types/upload";

export const UPLOAD_SLOTS: UploadSlotConfig[] = [
  {
    id: "sensiwatch",
    title: "SensiWatch Export",
    description: "Real-time shipment monitoring data exported from the SensiWatch platform.",
    required: true,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
  {
    id: "coldstream",
    title: "ColdStream Export",
    description: "Trip and sensor data exported from the ColdStream monitoring platform.",
    required: false,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
  {
    id: "thresholds",
    title: "Threshold & Compliance Reference",
    description: "Temperature/humidity thresholds and other compliance reference documentation.",
    required: false,
    accept: ".pdf,.doc,.docx,.xlsx,.csv,.md",
    acceptLabel: "PDF, Word, Excel, CSV, or Markdown",
  },
  {
    id: "customerKpis",
    title: "Customer KPI Profile",
    description: "JSON feature definitions for the Features step (e.g. % In Spec formula).",
    required: false,
    accept: ".json",
    acceptLabel: "JSON",
  },
  {
    id: "analysisProfile",
    title: "Analysis Profile",
    description: "JSON analysis definitions for the Analysis Agent -- plain-English calculation intents (e.g. carrier reliability trend), not fixed pivot specs.",
    required: false,
    accept: ".json",
    acceptLabel: "JSON",
  },
  {
    id: "rawLight",
    title: "Raw Light Data",
    description: "Raw ambient light sensor readings exported from the monitoring device (e.g. lux or on/off log).",
    required: false,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
  {
    id: "rawTemperature",
    title: "Raw Temperature Data",
    description: "Raw temperature sensor readings from the monitoring device, at full recording resolution.",
    required: false,
    accept: ".xlsx,.xls,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .csv)",
  },
];

// Only the tabular data sources get audited -- duplicate/outlier checks aren't
// meaningful for the reference documents even though their accept lists also
// permit spreadsheet formats.
export const AUDITED_SLOTS: UploadSlotId[] = ["sensiwatch", "coldstream"];

export function isAudited(id: UploadSlotId): boolean {
  return AUDITED_SLOTS.includes(id);
}
