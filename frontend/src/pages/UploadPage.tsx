import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import FileUploadCard from "../components/FileUploadCard";
import type { FileUploadCardConfig } from "../components/FileUploadCard";
import StatTile from "../components/StatTile";
import { IconGrid, IconSnowflake, IconZap, IconSearch, IconChevronDown } from "../components/icons";
import { AuditApiError, uploadFeatureDefinitions, uploadPivotDefinitions } from "../api/audit";
import { uploadRawData } from "../api/rawData";
import type { RawDataUploadResponse } from "../api/rawData";
import { routeClientBrief } from "../api/orchestrator";
import { fetchAllSamples } from "../api/samples";
import { UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState } from "../App";
import "./UploadPage.css";

interface UploadPageProps {
  files: FilesState;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  rawDataResult: RawDataUploadResponse | null;
  onRawDataProcessed: (result: RawDataUploadResponse) => void;
}

type MatrixSlotId = "temperatureMatrix" | "lightMatrix";
type MatrixFilesState = Record<MatrixSlotId, File | null>;
// The 6 canonical UPLOAD_SLOTS ids, plus the 2 raw sensor-matrix ids -- one
// unified space for the "jump to a data source" search bar and the card
// grid below, even though the matrix files live in this page's own local
// state rather than the lifted FilesState the other 6 share.
type CardId = UploadSlotId | MatrixSlotId;

const MATRIX_SLOTS: { id: MatrixSlotId; config: FileUploadCardConfig }[] = [
  {
    id: "temperatureMatrix",
    config: {
      title: "Temperature Data",
      description: "One column per trip (Serial Number / Trip ID / unit header), raw sequential readings.",
      required: false,
      accept: ".xlsx,.xls,.xlsm",
      acceptLabel: "Excel (.xlsx, .xls, .xlsm)",
    },
  },
  {
    id: "lightMatrix",
    config: {
      title: "Light Data",
      description: "Same layout as the temperature matrix, for light readings.",
      required: false,
      accept: ".xlsx,.xls,.xlsm",
      acceptLabel: "Excel (.xlsx, .xls, .xlsm)",
    },
  },
];

const EMPTY_MATRIX_FILES: MatrixFilesState = { temperatureMatrix: null, lightMatrix: null };

export default function UploadPage({ files, onSelect, onRemove, rawDataResult, onRawDataProcessed }: UploadPageProps) {
  const navigate = useNavigate();
  const [matrixFiles, setMatrixFiles] = useState<MatrixFilesState>(EMPTY_MATRIX_FILES);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [loadingSamples, setLoadingSamples] = useState(false);

  // "Jump to a data source" -- scrolls to and briefly pulses the matching
  // card (see FileUploadCard's own `highlighted` prop/animation), rather
  // than a real filter, since every card is already on screen at once.
  const cardRefs = useRef<Partial<Record<CardId, HTMLDivElement | null>>>({});
  const [highlighted, setHighlighted] = useState<CardId | null>(null);
  const jumpTargets = useMemo(
    () => [
      ...UPLOAD_SLOTS.map((s) => ({ id: s.id as CardId, title: s.title })),
      ...MATRIX_SLOTS.map((s) => ({ id: s.id as CardId, title: s.config.title })),
    ],
    []
  );
  const handleJump = (id: string) => {
    if (!id) return;
    cardRefs.current[id as CardId]?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlighted(id as CardId);
    window.setTimeout(() => setHighlighted((prev) => (prev === id ? null : prev)), 900);
  };

  // Client Brief -> Orchestrator Agent (see api/orchestrator.ts). Translated
  // to English server-side before it's classified, so this box accepts any
  // language. Submitting routes AND continues in one step (see
  // handleSubmitBrief below) -- Audit, then Features/Analysis, pick it up
  // from there and show what actually happened.
  const [brief, setBrief] = useState("");
  const [briefSubmitting, setBriefSubmitting] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  // Set only when the brief wasn't already English -- shows what language
  // was detected and DeepL's English translation, editable, so a mistake in
  // the auto-translation can be fixed before it's what Features/Analysis
  // actually read. Nothing to review (and nothing shown) for an English
  // brief -- it goes straight through, same as before.
  const [briefReview, setBriefReview] = useState<{
    detectedLanguage: string;
    translatedText: string;
  } | null>(null);

  const aggregatedFile = files.sensiwatch;
  const selectedCount = UPLOAD_SLOTS.filter((s) => files[s.id]).length + MATRIX_SLOTS.filter((s) => matrixFiles[s.id]).length;
  const totalCount = UPLOAD_SLOTS.length + MATRIX_SLOTS.length;

  const handleClearAll = () => {
    for (const slot of UPLOAD_SLOTS) {
      if (files[slot.id]) onRemove(slot.id);
    }
    setMatrixFiles(EMPTY_MATRIX_FILES);
  };

  // Dev convenience: fetches the bundled sample files (see backend/data/raw/
  // and api/samples.ts) and drops them into the exact same slots a manual
  // file pick would -- so testing doesn't require re-browsing to the same
  // Desktop files every time. Still requires clicking "Upload & Continue"
  // (or "Submit requirement") afterward, same as any other selection.
  const handleAddAllSamples = async () => {
    setLoadingSamples(true);
    setUploadError(null);
    try {
      const samples = await fetchAllSamples();
      onSelect("sensiwatch", samples.sensiwatch);
      onSelect("customerKpis", samples.customerKpis);
      onSelect("analysisProfile", samples.analysisProfile);
      setMatrixFiles({ temperatureMatrix: samples.temperatureMatrix, lightMatrix: samples.lightMatrix });
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Could not load the sample files.");
    } finally {
      setLoadingSamples(false);
    }
  };

  const handleProcess = async () => {
    if (!aggregatedFile) return;
    setUploading(true);
    setUploadError(null);
    try {
      await uploadSelectedFiles(aggregatedFile);
      navigate("/audit");
    } catch (err) {
      setUploadError(err instanceof AuditApiError ? err.message : "Could not reach the backend. Is it running?");
    } finally {
      setUploading(false);
    }
  };

  // Shared by both "Upload & Continue" and "Submit requirement" below --
  // sending a Client Requirement without having pressed "Upload & Continue"
  // first used to leave the aggregated/matrix files and any optional
  // Customer KPI/Analysis Profile documents never actually sent to the
  // backend, even though the file picker showed them as selected. Both
  // entry points now do this same upload step before moving on, so which
  // button the user happens to click first doesn't matter.
  const uploadSelectedFiles = async (aggregated: File) => {
    // The outlier/threshold screening this used to run right here now lives
    // on the Audit page's own "Outlier Screening" tab -- this just creates
    // the raw-data session and hands its result up to App so that tab can
    // find it. The SAME aggregated file was already handed to the Audit
    // pipeline via onSelect below (as the "sensiwatch" source), so
    // Audit/Features/Analysis/Report pick up from here without a second upload.
    const response = await uploadRawData(aggregated, matrixFiles.temperatureMatrix, matrixFiles.lightMatrix);
    onRawDataProcessed(response);

    // Optional reference documents -- sent now (rather than lazily on
    // Features'/Analysis' own mount, the way Report's template upload still
    // works) so the very first Feature/Pivot compute those pages run
    // already reads the uploaded definitions instead of the bundled
    // default. Best-effort: a failed upload here just means that page falls
    // back to its default, same as if the file had never been provided --
    // it doesn't block continuing.
    const optional = await Promise.allSettled([
      files.customerKpis ? uploadFeatureDefinitions(files.customerKpis) : Promise.resolve(),
      files.analysisProfile ? uploadPivotDefinitions(files.analysisProfile) : Promise.resolve(),
    ]);
    const optionalFailure = optional.find((r) => r.status === "rejected") as PromiseRejectedResult | undefined;
    if (optionalFailure) {
      const reason = optionalFailure.reason;
      setUploadError(
        `Uploaded, but one optional reference document couldn't be processed: ${
          reason instanceof AuditApiError ? reason.message : "unknown error"
        } -- continuing with the bundled default instead.`
      );
    }
  };

  // Uploads the files, then translates/classifies the brief. A brief that
  // was already English (or that DeepL couldn't reach) has nothing to
  // review, so it continues straight on to Audit -- no second click. One
  // that WAS translated stops here instead: the user sees what language was
  // detected and the English translation, and can correct it (see
  // handleConfirmBriefReview) before it's what Features/Analysis actually
  // read -- a wrong auto-translation shouldn't silently become the brief
  // every downstream agent works from.
  //
  // Lands on the new AI Recommendation page next -- the Planner Agent there
  // reads this same brief (once, in a single richer call) and identifies
  // every feature/analysis/configuration it needs, for the user to review/
  // edit/approve/reject BEFORE anything is created. This page's own job
  // stops at "upload the files, translate the brief, let the user fix a bad
  // auto-translation" -- it doesn't pre-extract anything itself anymore.
  const handleSubmitBrief = async () => {
    if (!brief.trim() || !aggregatedFile) return;
    setBriefSubmitting(true);
    setBriefError(null);
    try {
      await uploadSelectedFiles(aggregatedFile);
      const routed = await routeClientBrief(brief.trim());
      if (routed.detected_language && routed.translated_text) {
        setBriefReview({ detectedLanguage: routed.detected_language, translatedText: routed.translated_text });
        return;
      }
      navigate("/recommendation", { state: { brief: routed.translated_text ?? brief.trim() } });
    } catch (err) {
      setBriefError(err instanceof AuditApiError ? err.message : "Could not reach the orchestrator agent.");
    } finally {
      setBriefSubmitting(false);
    }
  };

  const handleConfirmBriefReview = () => {
    if (!briefReview) return;
    navigate("/recommendation", {
      state: {
        brief: briefReview.translatedText.trim(),
        detectedLanguage: briefReview.detectedLanguage,
        translatedText: briefReview.translatedText.trim(),
      },
    });
  };

  const handleEditOriginalBrief = () => setBriefReview(null);

  return (
    <div className="raw-data-page">
      <Header />
      <main className="raw-data-page__main">
        <StepIndicator current={1} />

        <label className="raw-data-page__jump">
          <IconSearch />
          <select
            className="raw-data-page__jump-select"
            value=""
            onChange={(e) => handleJump(e.target.value)}
            aria-label="Jump to a data source"
          >
            <option value="">Jump to a data source…</option>
            {jumpTargets.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
          <IconChevronDown />
        </label>

        <div className="raw-data-page__intro">
          <h1 className="raw-data-page__heading">Upload Source Data</h1>
          <p className="raw-data-page__lede">
            Provide the SensiWatch export to begin, plus the raw temperature/light data-point matrices if you have
            them. ColdStream data, threshold references, and customer KPI/analysis/report documents are optional but
            improve triage and reporting accuracy. SensiWatch and ColdStream files are reviewed by the data audit
            agent on the next page; tell the Orchestrator Agent what you need below and it feeds straight into
            feature engineering and analysis once the audit is clean.
          </p>
        </div>

        <div className="raw-data-page__count-row">
          <span className="raw-data-page__count">
            {selectedCount} of {totalCount} files selected
          </span>
          <div className="raw-data-page__count-actions">
            <button
              type="button"
              className="raw-data-page__btn raw-data-page__btn--secondary"
              onClick={handleAddAllSamples}
              disabled={loadingSamples}
              title="Dev convenience: fills every slot with the bundled sample files."
            >
              {loadingSamples ? "Loading samples…" : "Add all samples"}
            </button>
            <button
              type="button"
              className="raw-data-page__btn raw-data-page__btn--secondary"
              onClick={handleClearAll}
              disabled={selectedCount === 0}
            >
              Clear All
            </button>
            <button
              type="button"
              className="raw-data-page__btn raw-data-page__btn--primary"
              disabled={!aggregatedFile || uploading}
              onClick={handleProcess}
            >
              {uploading ? "Uploading…" : "Upload & Continue"}
            </button>
          </div>
        </div>
        {uploadError && <p className="raw-data-page__error">{uploadError}</p>}

        <div className="raw-data-page__grid">
          {UPLOAD_SLOTS.map((slot) => (
            <div key={slot.id} ref={(el) => { cardRefs.current[slot.id] = el; }}>
              <FileUploadCard
                config={slot}
                file={files[slot.id]}
                highlighted={highlighted === slot.id}
                onSelect={(file) => onSelect(slot.id, file)}
                onRemove={() => onRemove(slot.id)}
              />
            </div>
          ))}
          {MATRIX_SLOTS.map((slot) => (
            <div key={slot.id} ref={(el) => { cardRefs.current[slot.id] = el; }}>
              <FileUploadCard
                config={slot.config}
                file={matrixFiles[slot.id]}
                highlighted={highlighted === slot.id}
                onSelect={(file) => setMatrixFiles((prev) => ({ ...prev, [slot.id]: file }))}
                onRemove={() => setMatrixFiles((prev) => ({ ...prev, [slot.id]: null }))}
              />
            </div>
          ))}
        </div>

        <div className="raw-data-page__brief">
          {briefReview ? (
            <>
              <label className="raw-data-page__brief-label">Detected language: {briefReview.detectedLanguage}</label>
              <p className="raw-data-page__muted">
                Your original text and its English translation are both below -- check the translation against what
                you actually wrote and fix anything DeepL got wrong before continuing. The (editable) English version
                is what the Feature/Analysis agents will actually read.
              </p>
              <p className="raw-data-page__brief-original-label">Original ({briefReview.detectedLanguage})</p>
              <p className="raw-data-page__brief-original">{brief}</p>
              <p className="raw-data-page__brief-original-label">Translated to English (edit if needed)</p>
              <textarea
                className="raw-data-page__brief-input"
                rows={2}
                value={briefReview.translatedText}
                onChange={(e) => setBriefReview((prev) => (prev ? { ...prev, translatedText: e.target.value } : prev))}
              />
              <div className="raw-data-page__actions">
                <button
                  type="button"
                  className="raw-data-page__btn raw-data-page__btn--secondary"
                  onClick={handleEditOriginalBrief}
                >
                  Back
                </button>
                <button
                  type="button"
                  className="raw-data-page__btn raw-data-page__btn--primary"
                  disabled={!briefReview.translatedText.trim()}
                  onClick={handleConfirmBriefReview}
                >
                  Continue
                </button>
              </div>
            </>
          ) : (
            <>
              <label className="raw-data-page__brief-label" htmlFor="client-brief">
                Client requirement
              </label>
              <p className="raw-data-page__muted">
                Tell the Orchestrator Agent what you need — a new column ("add country of origin") or a question about
                the data ("average excursion time by supplier"), in any language. Submitting uploads your selected
                files (if you haven't already) and takes you straight to Data Audit.
              </p>
              <textarea
                id="client-brief"
                className="raw-data-page__brief-input"
                rows={2}
                placeholder="e.g. Flag trips where the sensor unit was swapped mid-trip"
                value={brief}
                onChange={(e) => setBrief(e.target.value)}
              />
              <div className="raw-data-page__actions">
                <button
                  type="button"
                  className="raw-data-page__btn raw-data-page__btn--primary"
                  disabled={!brief.trim() || !aggregatedFile || briefSubmitting}
                  onClick={handleSubmitBrief}
                >
                  {briefSubmitting ? "Uploading…" : "Submit requirement"}
                </button>
              </div>
              {!aggregatedFile && <p className="raw-data-page__muted">Select the SensiWatch export above first.</p>}
            </>
          )}
          {briefError && <p className="raw-data-page__error">{briefError}</p>}
        </div>

        {rawDataResult && (
          <div className="raw-data-page__stats">
            <StatTile icon={<IconGrid />} color="blue" label="Trips in aggregated data" value={String(rawDataResult.trips.length)} />
            {rawDataResult.temperature_uploaded && (
              <StatTile
                icon={<IconSnowflake />}
                color="teal"
                label="Temperature matrix trips matched"
                value={`${rawDataResult.temperature_matched} / ${rawDataResult.temperature_total}`}
              />
            )}
            {rawDataResult.light_uploaded && (
              <StatTile
                icon={<IconZap />}
                color="amber"
                label="Light matrix trips matched"
                value={`${rawDataResult.light_matched} / ${rawDataResult.light_total}`}
              />
            )}
          </div>
        )}

        {rawDataResult && (
          <p className="raw-data-page__muted">
            Outlier &amp; threshold screening for this data now runs on the{" "}
            <button type="button" className="raw-data-page__link-btn" onClick={() => navigate("/audit")}>
              Data Audit
            </button>{" "}
            page's "Outlier Screening" tab.
          </p>
        )}
      </main>
    </div>
  );
}
