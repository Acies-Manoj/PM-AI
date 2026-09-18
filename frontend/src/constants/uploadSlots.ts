import type { UploadSlotConfig, UploadSlotId } from "../types/upload";

export const UPLOAD_SLOTS: UploadSlotConfig[] = [
  {
    id: "sensiwatch",
    title: "SensiWatch Export",
    description: "Real-time shipment monitoring data exported from the SensiWatch platform.",
    required: true,
    accept: ".xlsx,.xls,.xlsm,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .xlsm, .csv)",
  },
  {
    id: "coldstream",
    title: "ColdStream Export",
    description: "Trip and sensor data exported from the ColdStream monitoring platform.",
    required: false,
    accept: ".xlsx,.xls,.xlsm,.csv",
    acceptLabel: "Excel or CSV (.xlsx, .xls, .xlsm, .csv)",
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
    description: "JSON pivot definitions for the Analysis step (e.g. carrier reliability).",
    required: false,
    accept: ".json",
    acceptLabel: "JSON",
  },
  {
    id: "reportTemplate",
    title: "Report Template",
    description: "Optional PowerPoint template to use as the base for the downloaded report. Falls back to the built-in layout if not provided.",
    required: false,
    accept: ".pptx",
    acceptLabel: "PowerPoint (.pptx)",
  },
];

// Only the tabular data sources get audited -- duplicate/outlier checks aren't
// meaningful for the reference documents even though their accept lists also
// permit spreadsheet formats.
export const AUDITED_SLOTS: UploadSlotId[] = ["sensiwatch", "coldstream"];

export function isAudited(id: UploadSlotId): boolean {
  return AUDITED_SLOTS.includes(id);
}
