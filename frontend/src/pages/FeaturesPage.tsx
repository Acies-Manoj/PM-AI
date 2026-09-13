import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import FeatureCard from "../components/FeatureCard";
import DataPreviewTable from "../components/DataPreviewTable";
import {
  applyFeatures,
  downloadCleansedFileUrl,
  fetchPreview,
  uploadFeatureDefinitions,
  AuditApiError,
  type DataPreview,
  type FeatureDefinitionsSummary,
  type FeatureReport,
} from "../api/audit";
import { suggestFeatures } from "../api/analysis";
import { AUDITED_SLOTS, UPLOAD_SLOTS } from "../constants/uploadSlots";
import type { UploadSlotId } from "../types/upload";
import type { AuditReportsState, FilesState } from "../App";
import "./FeaturesPage.css";

interface FeaturesPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
}

type FeatureReportsState = Partial<Record<UploadSlotId, FeatureReport>>;
type LoadingState = Partial<Record<UploadSlotId, boolean>>;
type ErrorsState = Partial<Record<UploadSlotId, string>>;
type PreviewsState = Partial<Record<UploadSlotId, DataPreview>>;
type PreviewOpenState = Partial<Record<UploadSlotId, boolean>>;

export default function FeaturesPage({ files, auditReports }: FeaturesPageProps) {
  const navigate = useNavigate();
  const [reports, setReports] = useState<FeatureReportsState>({});
  const [loading, setLoading] = useState<LoadingState>({});
  const [errors, setErrors] = useState<ErrorsState>({});
  const [previews, setPreviews] = useState<PreviewsState>({});
  const [previewOpen, setPreviewOpen] = useState<PreviewOpenState>({});
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggestionDraft, setSuggestionDraft] = useState("");
  const [aiSuggestions, setAiSuggestions] = useState<import("../api/analysis").FeatureSuggestion[]>([]);
  const [aiSuggestLoading, setAiSuggestLoading] = useState(false);

  const [defsSummary, setDefsSummary] = useState<FeatureDefinitionsSummary | null>(null);
  const [defsLoading, setDefsLoading] = useState(false);
  const [defsError, setDefsError] = useState<string | null>(null);

  const slotsReady = AUDITED_SLOTS.filter((id) => files[id] && auditReports[id]?.status === "reviewed");
  const hasKpiFile = !!files.customerKpis;

  // Step 1: upload the Customer KPI Profile file itself (the feature
  // definitions + COO mapping live INSIDE it -- nothing is bundled/default).
  useEffect(() => {
    if (!hasKpiFile || defsSummary || defsLoading || defsError) return;
    setDefsLoading(true);
    uploadFeatureDefinitions(files.customerKpis!)
      .then(setDefsSummary)
      .catch((err) => setDefsError(err instanceof AuditApiError ? err.message : "Could not upload the Customer KPI Profile."))
      .finally(() => setDefsLoading(false));
  }, [hasKpiFile, files.customerKpis, defsSummary, defsLoading, defsError]);

  // Step 2: once definitions are uploaded, compute features for each audited slot.
  useEffect(() => {
    if (!defsSummary) return;
    for (const id of slotsReady) {
      if (reports[id] || loading[id]) continue;
      const sessionId = auditReports[id]!.session_id;
      setLoading((prev) => ({ ...prev, [id]: true }));
      applyFeatures(sessionId)
        .then((report) => setReports((prev) => ({ ...prev, [id]: report })))
        .catch((err) =>
          setErrors((prev) => ({
            ...prev,
            [id]: err instanceof AuditApiError ? err.message : "Could not compute features.",
          }))
        )
        .finally(() => setLoading((prev) => ({ ...prev, [id]: false })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [defsSummary, files, auditReports]);

  const togglePreview = (id: UploadSlotId) => {
    const willOpen = !previewOpen[id];
    setPreviewOpen((prev) => ({ ...prev, [id]: willOpen }));
    if (willOpen && !previews[id]) {
      const sessionId = auditReports[id]!.session_id;
      fetchPreview(sessionId, 30).then((preview) => setPreviews((prev) => ({ ...prev, [id]: preview })));
    }
  };

  const addSuggestion = () => {
    const trimmed = suggestionDraft.trim();
    if (!trimmed) return;
    setSuggestions((prev) => [...prev, trimmed]);
    setSuggestionDraft("");
  };

  const handleAiSuggest = async () => {
    const sessionId = slotsReady[0] ? auditReports[slotsReady[0]]!.session_id : null;
    if (!sessionId) return;
    setAiSuggestLoading(true);
    try {
      const suggestions = await suggestFeatures(sessionId, "");
      setAiSuggestions(suggestions);
    } catch {
      // silently fail
    } finally {
      setAiSuggestLoading(false);
    }
  };

  if (AUDITED_SLOTS.every((id) => !files[id])) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={4} />
          <div className="features-page__empty">
            <p>No audited data yet.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (slotsReady.length === 0) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={4} />
          <div className="features-page__empty">
            <p>Finish resolving the data audit before features can be computed.</p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/audit")}>
              Back to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  if (!hasKpiFile) {
    return (
      <div className="features-page">
        <Header />
        <main className="features-page__main">
          <StepIndicator current={4} />
          <div className="features-page__empty">
            <p>
              No Customer KPI Profile has been uploaded. Feature definitions (what to compute, and any
              lookup tables like Country of Origin) live entirely in that file -- there's no default, so
              nothing is computed until it's uploaded.
            </p>
            <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/upload")}>
              Go to Upload
            </button>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="features-page">
      <Header />
      <main className="features-page__main">
        <StepIndicator current={4} />

        <div className="features-page__intro">
          <h1 className="features-page__heading">Feature Engineering</h1>
          <p className="features-page__lede">
            These features were added deterministically on top of your audited data, driven entirely by
            your uploaded Customer KPI Profile ({files.customerKpis!.name}) -- computed from whatever
            survived the audit review, not the original upload. If a source column was dropped during
            audit, that feature is skipped rather than silently pulling the removed data back in.
          </p>
        </div>

        {defsLoading && <div className="features-page__loading">Reading feature definitions from {files.customerKpis!.name}…</div>}
        {defsError && <p className="features-page__error">{defsError}</p>}
        {defsSummary && (
          <p className="features-page__defs-summary">
            Loaded {defsSummary.feature_count} feature definition(s) from <strong>{defsSummary.filename}</strong>:{" "}
            {defsSummary.feature_names.join(", ")}.
          </p>
        )}

        {slotsReady.map((id) => {
          const slot = UPLOAD_SLOTS.find((s) => s.id === id)!;
          const report = reports[id];
          const preview = previews[id];

          return (
            <section className="features-page__slot" key={id}>
              <div className="features-page__slot-header">
                <h2 className="features-page__slot-title">{slot.title}</h2>
                <span className="features-page__filename">{files[id]!.name}</span>
              </div>

              {loading[id] && <div className="features-page__loading">Computing features…</div>}
              {errors[id] && <p className="features-page__error">{errors[id]}</p>}

              {report && (
                <>
                  {report.features.length === 0 ? (
                    <p className="features-page__none">
                      None of the uploaded feature definitions could be computed against this data.
                    </p>
                  ) : (
                    <div className="features-page__grid">
                      {report.features.map((f) => (
                        <FeatureCard key={f.id} feature={f} />
                      ))}
                    </div>
                  )}

                  {report.skipped_notes.length > 0 && (
                    <ul className="features-page__skipped">
                      {report.skipped_notes.map((note, idx) => (
                        <li key={idx}>{note}</li>
                      ))}
                    </ul>
                  )}

                  <div className="features-page__row-actions">
                    <button type="button" className="features-page__link-btn" onClick={() => togglePreview(id)}>
                      {previewOpen[id] ? "Hide" : "View"} audited + engineered data ({report.row_count.toLocaleString()} rows, {report.column_count} columns)
                    </button>
                    <a className="features-page__download-link" href={downloadCleansedFileUrl(report.session_id)} download>
                      Download engineered file
                    </a>
                  </div>

                  {previewOpen[id] && (preview ? <DataPreviewTable preview={preview} /> : <div className="features-page__loading">Loading preview…</div>)}
                </>
              )}
            </section>
          );
        })}

        <section className="features-page__slot">
          <h2 className="features-page__slot-title">Want more features?</h2>

          <div className="features-page__ai-suggest-row">
            <button
              type="button"
              className="features-page__btn features-page__btn--secondary"
              onClick={handleAiSuggest}
              disabled={aiSuggestLoading || slotsReady.length === 0}
            >
              {aiSuggestLoading ? "Thinking…" : "✦ AI Suggest Features"}
            </button>
            <span className="features-page__suggest-hint">
              Let the Feature Agent propose cold-chain features based on your data columns.
            </span>
          </div>

          {aiSuggestions.length > 0 && (
            <ul className="features-page__ai-list">
              {aiSuggestions.map((s, idx) => (
                <li key={idx} className="features-page__ai-item">
                  <strong>{s.name}</strong> <span className="features-page__ai-type">({s.feature_type})</span>
                  <br />
                  <span>{s.description}</span>
                  <br />
                  <em className="features-page__ai-rationale">{s.rationale}</em>
                </li>
              ))}
            </ul>
          )}

          <p className="features-page__suggest-hint" style={{ marginTop: "16px" }}>
            Add a new entry to your Customer KPI Profile JSON and re-upload it on the Upload page to compute
            it. Note anything you'd want here in the meantime.
          </p>
          <div className="features-page__suggest-input-row">
            <input
              type="text"
              className="features-page__suggest-input"
              placeholder="e.g. days in transit, carrier reliability score..."
              value={suggestionDraft}
              onChange={(e) => setSuggestionDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addSuggestion();
              }}
            />
            <button type="button" className="features-page__btn features-page__btn--secondary" onClick={addSuggestion}>
              Add
            </button>
          </div>
          {suggestions.length > 0 && (
            <ul className="features-page__suggest-list">
              {suggestions.map((s, idx) => (
                <li key={idx}>{s}</li>
              ))}
            </ul>
          )}
        </section>

        <div className="features-page__actions">
          <button type="button" className="features-page__btn features-page__btn--secondary" onClick={() => navigate("/screening")}>
            Back to Screening
          </button>
          <button type="button" className="features-page__btn features-page__btn--primary" onClick={() => navigate("/analysis")}>
            Continue to Analysis
          </button>
        </div>
      </main>
    </div>
  );
}
