import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import SourceSelect from "../components/SourceSelect";
import FileUploadCard from "../components/FileUploadCard";
import StepIndicator from "../components/StepIndicator";
import ClientBriefInput from "../components/ClientBriefInput";
import { UPLOAD_SLOTS, AUDITED_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState } from "../App";
import type { BriefState } from "../components/ClientBriefInput";
import { uploadOnly } from "../api/audit";
import { finalizeBrief } from "../api/brief";
import "./UploadPage.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type ErrorsState = Partial<Record<UploadSlotId, string>>;

// Bundled example files (see backend/data/samples/, served statically at
// /samples/* by main.py) for the "Add all samples" button below -- lets
// trying the app end to end skip hunting down real source files each time.
// Not every slot has a sample; coldstream is left for the user to provide
// since there's nothing representative bundled.
const SAMPLE_FILES: { id: UploadSlotId; filename: string; mimeType: string }[] = [
  {
    id: "sensiwatch",
    filename: "sensiwatch_sample.xlsm",
    mimeType: "application/vnd.ms-excel.sheet.macroEnabled.12",
  },
  { id: "customerKpis", filename: "customer_kpi_profile_sample.json", mimeType: "application/json" },
  { id: "analysisProfile", filename: "analysis_profile_sample.json", mimeType: "application/json" },
];

interface UploadPageProps {
  files: FilesState;
  brief: BriefState;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  onClearAll: () => void;
  onBriefChange: (state: BriefState) => void;
  onUploadComplete: (sessionIds: Partial<Record<UploadSlotId, string>>) => void;
}

export default function UploadPage({
  files,
  brief,
  onSelect,
  onRemove,
  onClearAll,
  onBriefChange,
  onUploadComplete,
}: UploadPageProps) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ErrorsState>({});
  const [highlighted, setHighlighted] = useState<UploadSlotId | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [samplesLoading, setSamplesLoading] = useState(false);
  const cardRefs: Partial<Record<UploadSlotId, HTMLDivElement | null>> = {};

  const handleSelect = (id: UploadSlotId, file: File) => {
    onSelect(id, file);
    setErrors((prev) => ({ ...prev, [id]: undefined }));
  };

  const handleAddAllSamples = async () => {
    setSamplesLoading(true);
    setUploadError(null);
    try {
      const files = await Promise.all(
        SAMPLE_FILES.map(async ({ id, filename, mimeType }) => {
          const response = await fetch(`${API_BASE_URL}/samples/${filename}`);
          if (!response.ok) throw new Error(`Could not load sample "${filename}" (${response.status}).`);
          const blob = await response.blob();
          return { id, file: new File([blob], filename, { type: mimeType }) };
        })
      );
      for (const { id, file } of files) handleSelect(id, file);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Could not load the sample files.");
    } finally {
      setSamplesLoading(false);
    }
  };

  const handleContinue = async () => {
    const nextErrors: ErrorsState = {};
    for (const slot of UPLOAD_SLOTS) {
      if (slot.required && !files[slot.id]) {
        nextErrors[slot.id] = `${slot.title} is required.`;
      }
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    setUploading(true);
    setUploadError(null);
    try {
      const sessionIds: Partial<Record<UploadSlotId, string>> = {};
      for (const id of AUDITED_SLOTS) {
        const file = files[id];
        if (!file) continue;
        const result = await uploadOnly(id, file);
        sessionIds[id] = result.session_id;
      }

      const sessionIdsList = Object.values(sessionIds).filter((s): s is string => Boolean(s));
      if (sessionIdsList.length > 0) {
        await finalizeBrief(brief, files, sessionIdsList);
      }

      onUploadComplete(sessionIds);
      navigate("/planner");
    } catch (err: unknown) {
      setUploadError(
        err instanceof Error ? err.message : "Upload failed. Is the backend running?"
      );
    } finally {
      setUploading(false);
    }
  };

  const handleJumpTo = (id: UploadSlotId) => {
    cardRefs[id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlighted(id);
    setTimeout(() => setHighlighted((prev) => (prev === id ? null : prev)), 1600);
  };

  const selectedCount = Object.values(files).filter(Boolean).length;

  return (
    <div className="upload-page">
      <Header />
      <main className="upload-page__main">
        <StepIndicator current={1} />

        <ClientBriefInput value={brief} onChange={onBriefChange} />

        <div className="upload-page__search-row">
          <SourceSelect files={files} onSelect={handleJumpTo} />
        </div>

        <div className="upload-page__intro">
          <h1 className="upload-page__heading">Upload Source Data</h1>
          <p className="upload-page__lede">
            Provide the SensiWatch export to begin. ColdStream data, threshold references, and
            customer KPI documents are optional but improve triage and reporting accuracy. SensiWatch
            and ColdStream files are reviewed by the data audit agent on the next page.
          </p>
        </div>

        {uploadError && (
          <div className="upload-page__error">{uploadError}</div>
        )}

        <div className="upload-page__actions">
          <span className="upload-page__count">{selectedCount} of {UPLOAD_SLOTS.length} files selected</span>
          <div className="upload-page__buttons">
            <button
              type="button"
              className="upload-page__btn upload-page__btn--secondary"
              onClick={handleAddAllSamples}
              disabled={uploading || samplesLoading}
              title="Fills every slot with a bundled example file, so you can skip hunting one down each time you try the app."
            >
              {samplesLoading ? "Loading samples…" : "Add all samples"}
            </button>
            <button type="button" className="upload-page__btn upload-page__btn--secondary" onClick={onClearAll} disabled={uploading}>
              Clear All
            </button>
            <button
              type="button"
              className="upload-page__btn upload-page__btn--primary"
              onClick={handleContinue}
              disabled={uploading}
            >
              {uploading ? "Uploading…" : "Upload & Continue"}
            </button>
          </div>
        </div>

        <div className="upload-page__grid">
          {UPLOAD_SLOTS.map((slot) => (
            <div
              key={slot.id}
              ref={(el) => {
                cardRefs[slot.id] = el;
              }}
            >
              <FileUploadCard
                config={slot}
                file={files[slot.id]}
                error={errors[slot.id]}
                highlighted={highlighted === slot.id}
                onSelect={(file) => handleSelect(slot.id, file)}
                onRemove={() => onRemove(slot.id)}
              />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
