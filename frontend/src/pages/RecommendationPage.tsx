import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import { IconSparkle, IconLayers, IconBarChart, IconClipboard } from "../components/icons";
import { getRecommendations } from "../api/recommendations";
import { AuditApiError } from "../api/audit";
import type {
  Recommendation,
  RecommendationResponse,
  RecommendationType,
  ClientRequirementSummary,
  ValidationDraft,
} from "../api/recommendations";
import type { PlannedAnalysisItem, PlannedFeatureItem } from "../api/orchestrator";
import "./RecommendationPage.css";

const LOADING_STEPS = [
  "Understanding client requirement…",
  "Identifying required features and analyses…",
  "Preparing recommendation for review…",
];

type ApprovalState = "approved" | "rejected";

const TYPE_LABEL: Record<RecommendationType, string> = {
  feature: "NEW FEATURE",
  analysis: "NEW ANALYSIS",
  feature_and_analysis: "FEATURE + ANALYSIS",
  configuration: "CONFIGURATION",
};

// Rule-based (not another Groq call) -- re-run on every edit so correcting a
// recommendation doesn't cost a round-trip, let alone another slice of the
// Groq rate-limit budget per keystroke.
function revalidate(rec: Recommendation): ValidationDraft {
  const issues: string[] = [];
  const warnings: string[] = [];
  if (!rec.name.trim()) issues.push("Name is required.");
  if (!rec.description.trim()) warnings.push("A description helps explain this to reviewers later.");
  if (rec.type === "feature" || rec.type === "feature_and_analysis") {
    if (!rec.feature_definition?.formula?.trim()) issues.push("Feature formula/logic is required.");
    if (!rec.feature_definition?.feature_name?.trim()) issues.push("Feature name is required.");
  }
  if (rec.type === "analysis" || rec.type === "feature_and_analysis") {
    if (!rec.analysis_definition?.metrics?.length) issues.push("At least one metric is required.");
    if (!rec.analysis_definition?.analysis_name?.trim()) issues.push("Analysis name is required.");
  }
  return { issues, warnings, clarifications_required: rec.validation.clarifications_required };
}

function listFromText(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export default function RecommendationPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as {
    brief?: string;
    detectedLanguage?: string | null;
    translatedText?: string | null;
  } | null;
  const brief = state?.brief ?? "";

  const [loading, setLoading] = useState(true);
  const [loadingStep, setLoadingStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [clientRequirement, setClientRequirement] = useState<ClientRequirementSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [approvals, setApprovals] = useState<Record<string, ApprovalState>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const fetchedRef = useRef(false);

  useEffect(() => {
    if (!brief) {
      navigate("/upload", { replace: true });
      return;
    }
    if (fetchedRef.current) return;
    fetchedRef.current = true;

    const stepTimer = window.setInterval(() => {
      setLoadingStep((prev) => Math.min(prev + 1, LOADING_STEPS.length - 1));
    }, 1100);

    getRecommendations(brief)
      .then((res: RecommendationResponse) => {
        setClientRequirement(res.client_requirement);
        setRecommendations(res.recommendations);
        // Default: approved, ready to create -- EXCEPT anything that needs
        // clarification or already has a blocking issue, which starts
        // rejected so the user has to look at it and fix/approve explicitly
        // (see the spec's "don't create anything with unresolved critical
        // errors").
        const initialApprovals: Record<string, ApprovalState> = {};
        for (const rec of res.recommendations) {
          const validated = revalidate(rec);
          initialApprovals[rec.id] = rec.status === "needs_clarification" || validated.issues.length > 0 ? "rejected" : "approved";
        }
        setApprovals(initialApprovals);
        if (res.errors.length > 0) setError(res.errors.join(" "));
      })
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not reach the Planner Agent."))
      .finally(() => {
        window.clearInterval(stepTimer);
        setLoading(false);
      });

    return () => window.clearInterval(stepTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brief]);

  const counts = useMemo(() => {
    const features = recommendations.filter((r) => r.type === "feature" || r.type === "feature_and_analysis").length;
    const analyses = recommendations.filter((r) => r.type === "analysis" || r.type === "feature_and_analysis").length;
    const configurations = recommendations.filter((r) => r.type === "configuration").length;
    const issues = recommendations.reduce((n, r) => n + r.validation.issues.length, 0);
    const warnings = recommendations.reduce((n, r) => n + r.validation.warnings.length, 0);
    const clarifications = recommendations.reduce((n, r) => n + r.validation.clarifications_required.length, 0);
    return { features, analyses, configurations, issues, warnings, clarifications };
  }, [recommendations]);

  const updateRecommendation = (id: string, updater: (rec: Recommendation) => Recommendation) => {
    setRecommendations((prev) =>
      prev.map((r) => {
        if (r.id !== id) return r;
        const updated = updater(r);
        return { ...updated, validation: revalidate(updated) };
      })
    );
  };

  const handleApprove = (id: string) => setApprovals((prev) => ({ ...prev, [id]: "approved" }));
  const handleReject = (id: string) => setApprovals((prev) => ({ ...prev, [id]: "rejected" }));
  const handleApproveAll = () => {
    setApprovals((prev) => {
      const next = { ...prev };
      for (const rec of recommendations) {
        if (rec.validation.issues.length === 0) next[rec.id] = "approved";
      }
      return next;
    });
  };

  // Both buttons carry the SAME approved lists forward -- Features always
  // chains on to Analysis once it's done (see FeaturesPage's own
  // prefillClientBrief effect), so nothing approved is lost regardless of
  // which one the user happens to click; the two labels just match what the
  // spec asks for, not two different underlying actions.
  const handleContinue = () => {
    const approved = recommendations.filter((r) => approvals[r.id] === "approved" && r.validation.issues.length === 0);
    const plannedFeatures: PlannedFeatureItem[] = approved
      .filter((r) => r.type === "feature" || r.type === "feature_and_analysis")
      .map((r) => ({
        feature_name: r.feature_definition?.feature_name || r.name,
        description: r.feature_definition?.formula ? `${r.description} (${r.feature_definition.formula})` : r.description,
      }));
    const plannedAnalyses: PlannedAnalysisItem[] = approved
      .filter((r) => r.type === "analysis" || r.type === "feature_and_analysis")
      .map((r) => ({
        analysis_name: r.analysis_definition?.analysis_name || r.name,
        description: r.analysis_definition?.objective || r.description,
      }));
    navigate("/audit", {
      state: {
        pendingBrief: brief,
        pendingBriefTarget: "/features",
        pendingBriefDetectedLanguage: state?.detectedLanguage,
        pendingBriefTranslatedText: state?.translatedText,
        pendingPlannedFeatures: plannedFeatures,
        pendingPlannedAnalyses: plannedAnalyses,
      },
    });
  };

  const anyApprovedBlocked = recommendations.some(
    (r) => approvals[r.id] === "approved" && r.validation.issues.length > 0
  );

  return (
    <div className="recommendation-page">
      <Header />
      <main className="recommendation-page__main">
        <StepIndicator current={1} />

        {loading && (
          <div className="recommendation-page__loading">
            <IconSparkle />
            <p>{LOADING_STEPS[loadingStep]}</p>
          </div>
        )}

        {!loading && error && recommendations.length === 0 && (
          <div className="recommendation-page__error-block">
            <p className="recommendation-page__error">{error}</p>
            <button type="button" className="recommendation-page__btn recommendation-page__btn--secondary" onClick={() => navigate("/upload")}>
              Back to Upload
            </button>
          </div>
        )}

        {!loading && clientRequirement && (
          <>
            <section className="recommendation-page__summary">
              <h1 className="recommendation-page__heading">AI Requirement Interpretation</h1>
              <div className="recommendation-page__summary-row">
                <span className="recommendation-page__summary-label">Original requirement</span>
                <p className="recommendation-page__summary-text">{clientRequirement.original_input}</p>
              </div>
              <div className="recommendation-page__summary-row">
                <span className="recommendation-page__summary-label">AI interpretation</span>
                <p className="recommendation-page__summary-text">{clientRequirement.interpreted_requirement}</p>
              </div>
              <div className="recommendation-page__summary-row">
                <span className="recommendation-page__summary-label">Business objective</span>
                <p className="recommendation-page__summary-text">{clientRequirement.business_objective}</p>
              </div>
              <div className="recommendation-page__summary-stats">
                <span>{counts.features} feature{counts.features === 1 ? "" : "s"} identified</span>
                <span>{counts.analyses} analys{counts.analyses === 1 ? "is" : "es"} identified</span>
                <span>{counts.configurations} configuration{counts.configurations === 1 ? "" : "s"} identified</span>
                {counts.issues > 0 && <span className="recommendation-page__summary-stat--issue">{counts.issues} issue{counts.issues === 1 ? "" : "s"}</span>}
                {counts.warnings > 0 && <span className="recommendation-page__summary-stat--warning">{counts.warnings} warning{counts.warnings === 1 ? "" : "s"}</span>}
                {counts.clarifications > 0 && (
                  <span className="recommendation-page__summary-stat--warning">{counts.clarifications} clarification{counts.clarifications === 1 ? "" : "s"} needed</span>
                )}
              </div>
              {error && <p className="recommendation-page__error">{error}</p>}
            </section>

            <div className="recommendation-page__cards">
              {recommendations.map((rec) => (
                <RecommendationCard
                  key={rec.id}
                  rec={rec}
                  approval={approvals[rec.id] ?? "approved"}
                  editing={editingId === rec.id}
                  onEditToggle={() => setEditingId(editingId === rec.id ? null : rec.id)}
                  onChange={(updater) => updateRecommendation(rec.id, updater)}
                  onApprove={() => handleApprove(rec.id)}
                  onReject={() => handleReject(rec.id)}
                />
              ))}
            </div>

            {anyApprovedBlocked && (
              <p className="recommendation-page__error">
                One or more approved items still has an unresolved error -- fix it (or reject it) before continuing.
              </p>
            )}

            <div className="recommendation-page__actions">
              <button type="button" className="recommendation-page__btn recommendation-page__btn--secondary" onClick={() => navigate("/upload")}>
                Back to Upload
              </button>
              <button type="button" className="recommendation-page__btn recommendation-page__btn--secondary" onClick={handleApproveAll}>
                Approve All
              </button>
              <button
                type="button"
                className="recommendation-page__btn recommendation-page__btn--primary"
                disabled={anyApprovedBlocked}
                onClick={handleContinue}
              >
                Go to Feature
              </button>
              <button
                type="button"
                className="recommendation-page__btn recommendation-page__btn--primary"
                disabled={anyApprovedBlocked}
                onClick={handleContinue}
              >
                Go to Analysis
              </button>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function RecommendationCard({
  rec,
  approval,
  editing,
  onEditToggle,
  onChange,
  onApprove,
  onReject,
}: {
  rec: Recommendation;
  approval: ApprovalState;
  editing: boolean;
  onEditToggle: () => void;
  onChange: (updater: (rec: Recommendation) => Recommendation) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const statusIcon = rec.validation.issues.length > 0 ? "✕" : rec.validation.warnings.length > 0 ? "⚠" : "✓";
  const statusClass =
    rec.validation.issues.length > 0
      ? "recommendation-card__status--error"
      : rec.validation.warnings.length > 0
        ? "recommendation-card__status--warning"
        : "recommendation-card__status--valid";
  const icon = rec.type === "configuration" ? <IconClipboard /> : rec.type === "feature" ? <IconLayers /> : <IconBarChart />;

  return (
    <div className={`recommendation-card recommendation-card--${approval}`}>
      <div className="recommendation-card__head">
        <span className="recommendation-card__badge">
          {icon}
          {TYPE_LABEL[rec.type]}
        </span>
        <span className="recommendation-card__reuse">
          {rec.status === "existing" ? "Existing — Reuse" : rec.status === "needs_clarification" ? "Clarification Required" : "New"}
        </span>
        <span className={`recommendation-card__status ${statusClass}`}>{statusIcon}</span>
      </div>

      {!editing ? (
        <>
          <h3 className="recommendation-card__name">{rec.name}</h3>
          <p className="recommendation-card__description">{rec.description}</p>
          <p className="recommendation-card__reason">
            <strong>Why:</strong> {rec.reason}
          </p>
          <div className="recommendation-card__confidence">
            <span>AI confidence</span>
            <div className="recommendation-card__confidence-bar">
              <div className="recommendation-card__confidence-fill" style={{ width: `${rec.confidence}%` }} />
            </div>
            <span>{rec.confidence}%</span>
          </div>

          {(rec.type === "feature" || rec.type === "feature_and_analysis") && rec.feature_definition && (
            <div className="recommendation-card__section">
              <p><strong>Formula:</strong> {rec.feature_definition.formula || "—"}</p>
              {rec.feature_definition.input_fields.length > 0 && <p><strong>Data required:</strong> {rec.feature_definition.input_fields.join(", ")}</p>}
              {rec.feature_definition.dimensions.length > 0 && <p><strong>Dimensions:</strong> {rec.feature_definition.dimensions.join(", ")}</p>}
              {rec.feature_definition.filters.length > 0 && <p><strong>Filters:</strong> {rec.feature_definition.filters.join(", ")}</p>}
              {rec.feature_definition.business_rules.length > 0 && <p><strong>Business rules:</strong> {rec.feature_definition.business_rules.join("; ")}</p>}
            </div>
          )}

          {(rec.type === "analysis" || rec.type === "feature_and_analysis") && rec.analysis_definition && (
            <div className="recommendation-card__section">
              <p><strong>Objective:</strong> {rec.analysis_definition.objective || "—"}</p>
              {rec.analysis_definition.metrics.length > 0 && <p><strong>Metrics:</strong> {rec.analysis_definition.metrics.join(", ")}</p>}
              {rec.analysis_definition.dimensions.length > 0 && <p><strong>Dimensions:</strong> {rec.analysis_definition.dimensions.join(", ")}</p>}
              {rec.analysis_definition.filters.length > 0 && <p><strong>Filters:</strong> {rec.analysis_definition.filters.join(", ")}</p>}
              {rec.analysis_definition.visualization && <p><strong>Visualization:</strong> {rec.analysis_definition.visualization}</p>}
            </div>
          )}

          {rec.type === "configuration" && rec.configuration && rec.configuration.parameters.length > 0 && (
            <div className="recommendation-card__section">
              <p><strong>Parameters:</strong> {rec.configuration.parameters.join(", ")}</p>
            </div>
          )}

          {rec.data_requirements.missing_fields.length > 0 && (
            <p className="recommendation-card__warning-text">Missing data: {rec.data_requirements.missing_fields.join(", ")}</p>
          )}
          {rec.validation.issues.map((issue, i) => (
            <p key={i} className="recommendation-card__issue-text">{issue}</p>
          ))}
          {rec.validation.clarifications_required.map((q, i) => (
            <p key={i} className="recommendation-card__warning-text">{q}</p>
          ))}
        </>
      ) : (
        <div className="recommendation-card__edit-form">
          <label>
            Name
            <input value={rec.name} onChange={(e) => onChange((r) => ({ ...r, name: e.target.value }))} />
          </label>
          <label>
            Description
            <textarea rows={2} value={rec.description} onChange={(e) => onChange((r) => ({ ...r, description: e.target.value }))} />
          </label>
          {(rec.type === "feature" || rec.type === "feature_and_analysis") && rec.feature_definition && (
            <>
              <label>
                Formula / logic
                <textarea
                  rows={2}
                  value={rec.feature_definition.formula}
                  onChange={(e) => onChange((r) => ({ ...r, feature_definition: r.feature_definition && { ...r.feature_definition, formula: e.target.value } }))}
                />
              </label>
              <label>
                Data fields (comma-separated)
                <input
                  value={rec.feature_definition.input_fields.join(", ")}
                  onChange={(e) => onChange((r) => ({ ...r, feature_definition: r.feature_definition && { ...r.feature_definition, input_fields: listFromText(e.target.value) } }))}
                />
              </label>
              <label>
                Business rules (comma-separated)
                <input
                  value={rec.feature_definition.business_rules.join(", ")}
                  onChange={(e) => onChange((r) => ({ ...r, feature_definition: r.feature_definition && { ...r.feature_definition, business_rules: listFromText(e.target.value) } }))}
                />
              </label>
            </>
          )}
          {(rec.type === "analysis" || rec.type === "feature_and_analysis") && rec.analysis_definition && (
            <>
              <label>
                Metrics (comma-separated)
                <input
                  value={rec.analysis_definition.metrics.join(", ")}
                  onChange={(e) => onChange((r) => ({ ...r, analysis_definition: r.analysis_definition && { ...r.analysis_definition, metrics: listFromText(e.target.value) } }))}
                />
              </label>
              <label>
                Dimensions (comma-separated)
                <input
                  value={rec.analysis_definition.dimensions.join(", ")}
                  onChange={(e) => onChange((r) => ({ ...r, analysis_definition: r.analysis_definition && { ...r.analysis_definition, dimensions: listFromText(e.target.value) } }))}
                />
              </label>
              <label>
                Visualization
                <input
                  value={rec.analysis_definition.visualization}
                  onChange={(e) => onChange((r) => ({ ...r, analysis_definition: r.analysis_definition && { ...r.analysis_definition, visualization: e.target.value } }))}
                />
              </label>
            </>
          )}
        </div>
      )}

      <div className="recommendation-card__actions">
        <button type="button" className="recommendation-card__btn" onClick={onEditToggle}>
          {editing ? "Done" : "Edit"}
        </button>
        <button type="button" className={`recommendation-card__btn ${approval === "approved" ? "recommendation-card__btn--active-approve" : ""}`} onClick={onApprove}>
          Approve
        </button>
        <button type="button" className={`recommendation-card__btn ${approval === "rejected" ? "recommendation-card__btn--active-reject" : ""}`} onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}
