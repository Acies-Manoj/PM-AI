import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import SearchBar from "../components/SearchBar";
import FileUploadCard from "../components/FileUploadCard";
import StepIndicator from "../components/StepIndicator";
import OrchestratorBanner from "../components/OrchestratorBanner";
import { UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { FilesState, BriefState } from "../App";
import { analyzeBrief, translateBrief, BriefApiError } from "../api/brief";
import type { BriefAnalysis, TranslationResult } from "../api/brief";
import "./UploadPage.css";

type ErrorsState = Partial<Record<UploadSlotId, string>>;

interface UploadPageProps {
  files: FilesState;
  brief: BriefState;
  onSelect: (id: UploadSlotId, file: File) => void;
  onRemove: (id: UploadSlotId) => void;
  onClearAll: () => void;
  onBriefChange: (text: string) => void;
  onBriefAnalyzed: (analysis: BriefAnalysis) => void;
}

export default function UploadPage({
  files,
  brief,
  onSelect,
  onRemove,
  onClearAll,
  onBriefChange,
  onBriefAnalyzed,
}: UploadPageProps) {
  const navigate = useNavigate();
  const [errors, setErrors] = useState<ErrorsState>({});
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);

  // Translation state — set when the brief was non-English and needs user confirmation.
  const [translation, setTranslation] = useState<TranslationResult | null>(null);
  const [originalText, setOriginalText] = useState("");
  const [editedTranslation, setEditedTranslation] = useState("");

  const handleSelect = (id: UploadSlotId, file: File) => {
    onSelect(id, file);
    setErrors((prev) => ({ ...prev, [id]: undefined }));
  };

  // Step 1: detect language + translate if needed.
  const handleAnalyzeBrief = async () => {
    if (!brief.text.trim()) return;
    setBriefLoading(true);
    setBriefError(null);
    setTranslation(null);
    try {
      const tr = await translateBrief(brief.text.trim());
      if (!tr.was_translated) {
        // Already English — go straight to orchestrator.
        await runOrchestrator(tr.translated_text);
      } else {
        // Non-English — show the side-by-side translator panel.
        setTranslation(tr);
        setOriginalText(tr.original_text);
        setEditedTranslation(tr.translated_text);
      }
    } catch (err) {
      setBriefError(err instanceof BriefApiError ? err.message : "Translation service unavailable.");
    } finally {
      setBriefLoading(false);
    }
  };

  // Re-run translation after the user edits the original-language text.
  const handleRetranslate = async () => {
    if (!originalText.trim()) return;
    setBriefLoading(true);
    setBriefError(null);
    try {
      const tr = await translateBrief(originalText.trim());
      setTranslation(tr);
      setOriginalText(tr.original_text);
      setEditedTranslation(tr.translated_text);
    } catch (err) {
      setBriefError(err instanceof BriefApiError ? err.message : "Translation service unavailable.");
    } finally {
      setBriefLoading(false);
    }
  };

  // Step 2: run orchestrator with the (possibly edited) English text.
  const handleConfirmTranslation = async () => {
    const textToAnalyse = editedTranslation.trim();
    if (!textToAnalyse) return;
    setBriefLoading(true);
    setBriefError(null);
    try {
      await runOrchestrator(textToAnalyse);
      setTranslation(null);
    } catch {
      // error already set inside runOrchestrator
    } finally {
      setBriefLoading(false);
    }
  };

  const runOrchestrator = async (englishText: string) => {
    try {
      const result = await analyzeBrief(englishText);
      onBriefAnalyzed(result);
    } catch (err) {
      setBriefError(err instanceof BriefApiError ? err.message : "Orchestrator unavailable.");
      throw err;
    }
  };

  const handleBriefChange = (text: string) => {
    onBriefChange(text);
    // Reset translation panel when user edits the original brief.
    if (translation) setTranslation(null);
  };

  const handleContinue = () => {
    const nextErrors: ErrorsState = {};
    for (const slot of UPLOAD_SLOTS) {
      if (slot.required && !files[slot.id]) {
        nextErrors[slot.id] = `${slot.title} is required.`;
      }
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length === 0) {
      navigate("/audit");
    }
  };

  const selectedCount = Object.values(files).filter(Boolean).length;

  return (
    <div className="upload-page">
      <Header />
      <main className="upload-page__main">
        <StepIndicator current={1} />

        <div className="upload-page__search-row">
          <SearchBar onSearch={(q) => console.log("Search:", q)} />
        </div>

        <div className="upload-page__intro">
          <h1 className="upload-page__heading">Upload Source Data</h1>
          <p className="upload-page__lede">
            Provide the SensiWatch export to begin. ColdStream data, threshold references, and
            customer KPI documents are optional but improve triage and reporting accuracy.
          </p>
        </div>

        {/* Client Brief */}
        <div className="upload-page__brief-section">
          <label className="upload-page__brief-label" htmlFor="brief-input">
            Client Brief
            <span className="upload-page__brief-hint"> — describe what you need from this analysis (any language)</span>
          </label>
          {!translation && (
            <>
              <textarea
                id="brief-input"
                className="upload-page__brief-textarea"
                placeholder="e.g. Analyse all Edeka shipments from Q3 and flag any cold-chain excursions…"
                value={brief.text}
                onChange={(e) => handleBriefChange(e.target.value)}
                rows={4}
              />
              <div className="upload-page__brief-actions">
                <button
                  type="button"
                  className="upload-page__btn upload-page__btn--secondary upload-page__btn--sm"
                  onClick={handleAnalyzeBrief}
                  disabled={!brief.text.trim() || briefLoading}
                >
                  {briefLoading ? "Detecting language…" : "Analyse Brief"}
                </button>
                {briefError && <span className="upload-page__brief-error">{briefError}</span>}
              </div>
            </>
          )}

          {/* Side-by-side translator — shown only when the brief was non-English */}
          {translation && (
            <div className="upload-page__translator-block">
              <div className="upload-page__translator">
                <div className="upload-page__translator-pane">
                  <div className="upload-page__translator-pane-header">
                    <span className="upload-page__translator-lang">{translation.language_name} · Detected</span>
                  </div>
                  <textarea
                    className="upload-page__translator-textarea"
                    value={originalText}
                    onChange={(e) => setOriginalText(e.target.value)}
                    rows={7}
                  />
                  <div className="upload-page__translator-pane-footer">
                    <button
                      type="button"
                      className="upload-page__translator-retranslate"
                      onClick={handleRetranslate}
                      disabled={!originalText.trim() || briefLoading}
                    >
                      {briefLoading ? "Translating…" : "Re-translate"}
                    </button>
                  </div>
                </div>

                <div className="upload-page__translator-arrow" aria-hidden="true">→</div>

                <div className="upload-page__translator-pane upload-page__translator-pane--target">
                  <div className="upload-page__translator-pane-header">
                    <span className="upload-page__translator-lang">English</span>
                  </div>
                  <textarea
                    className="upload-page__translator-textarea"
                    value={editedTranslation}
                    onChange={(e) => setEditedTranslation(e.target.value)}
                    rows={7}
                  />
                  <div className="upload-page__translator-pane-footer">
                    <span className="upload-page__translator-hint">Edit if needed before analysing.</span>
                  </div>
                </div>
              </div>

              <div className="upload-page__brief-actions">
                <button
                  type="button"
                  className="upload-page__btn upload-page__btn--primary upload-page__btn--sm"
                  onClick={handleConfirmTranslation}
                  disabled={!editedTranslation.trim() || briefLoading}
                >
                  {briefLoading ? "Analysing…" : "Confirm & Analyse"}
                </button>
                <button
                  type="button"
                  className="upload-page__btn upload-page__btn--secondary upload-page__btn--sm"
                  onClick={() => setTranslation(null)}
                >
                  Cancel
                </button>
                {briefError && <span className="upload-page__brief-error">{briefError}</span>}
              </div>
            </div>
          )}

          {brief.analysis && <OrchestratorBanner analysis={brief.analysis} />}
        </div>

        <div className="upload-page__grid">
          {UPLOAD_SLOTS.map((slot) => (
            <FileUploadCard
              key={slot.id}
              config={slot}
              file={files[slot.id]}
              error={errors[slot.id]}
              onSelect={(file) => handleSelect(slot.id, file)}
              onRemove={() => onRemove(slot.id)}
            />
          ))}
        </div>

        <div className="upload-page__actions">
          <span className="upload-page__count">{selectedCount} of 4 files selected</span>
          <div className="upload-page__buttons">
            <button type="button" className="upload-page__btn upload-page__btn--secondary" onClick={onClearAll}>
              Clear All
            </button>
            <button type="button" className="upload-page__btn upload-page__btn--primary" onClick={handleContinue}>
              Upload &amp; Continue
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
