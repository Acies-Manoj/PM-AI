import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import { fetchSuggestions, saveDecisions } from "../api/planner";
import type { PlannerRecommendation, PlannerRecommendationType, PlannerSuggestResponse, PmDecisionValue } from "../api/planner";
import PlanText from "../components/PlanText";
import "./PlannerPage.css";

type PlannerTab = "features" | "analyses";

// A "feature_and_analysis" recommendation produces an entry on BOTH the
// Features page and the Analysis page when accepted (see
// feature_repository.py / analysis_repository.py's _planner_entries) --
// so it must be counted and shown in BOTH tabs here too. Showing it under
// only one tab is what let a PM accept it while looking at "Feature
// Suggestions" and then be surprised to see one MORE entry than expected
// show up on the Analysis page later.
function getTabs(type: PlannerRecommendationType): PlannerTab[] {
  if (type === "feature_and_analysis") return ["features", "analyses"];
  if (type === "analysis") return ["analyses"];
  return ["features"]; // "feature" and "configuration"
}

// Mirrors feature_repository.py's `_planner_entries` derivation
// (re.sub(r"\W+", "_", name.strip().lower()).strip("_")) -- the Planner
// never proposes an output-column name of its own for a feature, one is
// always derived from the recommendation's name, so this is the only way
// to tell whether a missing column IS one of the features being suggested
// alongside it, before either has actually been accepted/computed.
function deriveOutputColumn(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

// {derived output column -> recommendation name} for every feature-producing
// recommendation in this batch, so a sibling analysis's missing_fields can
// be resolved to "this needs feature X" instead of a bare column name.
function buildFeatureColumnMap(recs: PlannerRecommendation[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const r of recs) {
    if (r.type === "feature" || r.type === "feature_and_analysis") {
      map.set(deriveOutputColumn(r.name), r.name);
    }
  }
  return map;
}

interface PlannerPageProps {
  sessionId: string | null;
}

type DecisionsMap = Record<number, PmDecisionValue>;

export default function PlannerPage({ sessionId }: PlannerPageProps) {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PlannerSuggestResponse | null>(null);
  const [decisions, setDecisions] = useState<DecisionsMap>({});
  const [activeTab, setActiveTab] = useState<PlannerTab>("features");
  const [moreLoading, setMoreLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const fetched = useRef(false);

  useEffect(() => {
    if (!sessionId || fetched.current) return;
    fetched.current = true;
    setLoading(true);
    setError(null);
    fetchSuggestions(sessionId)
      .then((res) => setResult(res))
      .catch((err) => setError(err.message ?? "Planner failed."))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const setDecision = (index: number, value: PmDecisionValue) => {
    setDecisions((prev) => ({
      ...prev,
      [index]: prev[index] === value ? "pending" : value,
    }));
  };

  const setAllInTab = (tab: PlannerTab, value: PmDecisionValue) => {
    if (!result) return;
    setDecisions((prev) => {
      const next = { ...prev };
      result.recommendations.forEach((r, i) => {
        if (getTabs(r.type).includes(tab)) next[i] = value;
      });
      return next;
    });
  };

  const handleRequestMore = async () => {
    if (!sessionId || !result) return;
    setMoreLoading(true);
    setError(null);
    const existingNames = result.recommendations.map((r) => r.name).join(", ");
    const context = `Generate 4 additional feature suggestions and 4 additional analysis suggestions. These must be DIFFERENT from the ones already shown: ${existingNames}. Do not repeat any of those.`;
    try {
      const res = await fetchSuggestions(sessionId, context);
      setResult((prev) => {
        if (!prev) return res;
        return {
          ...prev,
          recommendations: [...prev.recommendations, ...res.recommendations],
        };
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to get more suggestions.");
    } finally {
      setMoreLoading(false);
    }
  };

  const handleProceed = async () => {
    if (!sessionId || !result) return;
    setSaving(true);
    try {
      const decisionList = result.recommendations.map((_, i) => ({
        recommendation_index: i,
        pm_decision: decisions[i] ?? "pending",
        pm_notes: "",
      }));
      await saveDecisions(sessionId, decisionList);
      navigate("/audit");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not save decisions.");
    } finally {
      setSaving(false);
    }
  };

  if (!sessionId) {
    return (
      <div className="planner-page">
        <Header subtitle="AI Planner" />
        <main className="planner-page__main">
          <StepIndicator current={2} />
          <div className="planner-page__loading">
            No session found. Please go back and upload your files.
          </div>
        </main>
      </div>
    );
  }

  const recs = result?.recommendations ?? [];
  const featureColumnMap = buildFeatureColumnMap(recs);

  return (
    <div className="planner-page">
      <Header subtitle="AI Planner" />
      <main className="planner-page__main">
        <StepIndicator current={2} />

        <PageHeader
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 2L2 7l10 5 10-5-10-5z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M2 17l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          }
          title="AI Planner"
          subtitle="The Planner has read your brief and dataset. Review its suggested features and analyses below, then accept or reject each one before proceeding to the data audit."
        />

        {loading && (
          <div className="planner-page__loading">
            <span className="planner-page__spinner" />
            Planner is reading your brief and dataset…
          </div>
        )}

        {error && <div className="planner-page__error">{error}</div>}

        {result && (
          <>
            <div className="planner-page__tabs">
              <div className="planner-page__tabs-left">
                {(["features", "analyses"] as PlannerTab[]).map((tab) => {
                  const count = recs.filter((r) => getTabs(r.type).includes(tab)).length;
                  const acceptedCount = recs.filter((r, i) => getTabs(r.type).includes(tab) && decisions[i] === "accepted").length;
                  return (
                    <button
                      key={tab}
                      type="button"
                      className={`planner-page__tab${activeTab === tab ? " planner-page__tab--active" : ""}`}
                      onClick={() => setActiveTab(tab)}
                    >
                      {tab === "features" ? "Feature Suggestions" : "Analysis Suggestions"}
                      <span className="planner-page__tab-count">{count}</span>
                      {acceptedCount > 0 && (
                        <span className="planner-page__tab-accepted">{acceptedCount} accepted</span>
                      )}
                    </button>
                  );
                })}
              </div>
              {recs.filter((r) => getTabs(r.type).includes(activeTab)).length > 0 && (
                <div className="planner-page__bulk-btns">
                  <button
                    type="button"
                    className="planner-page__bulk-btn planner-page__bulk-btn--accept"
                    onClick={() => setAllInTab(activeTab, "accepted")}
                  >
                    Accept all
                  </button>
                  <button
                    type="button"
                    className="planner-page__bulk-btn planner-page__bulk-btn--reject"
                    onClick={() => setAllInTab(activeTab, "rejected")}
                  >
                    Reject all
                  </button>
                </div>
              )}
            </div>

            <div className="planner-page__list">
              {recs
                .map((rec, i) => ({ rec, i }))
                .filter(({ rec }) => getTabs(rec.type).includes(activeTab))
                .map(({ rec, i }) => (
                  <RecommendationCard
                    key={i}
                    rec={rec}
                    index={i}
                    decision={decisions[i] ?? "pending"}
                    onDecide={setDecision}
                    featureColumnMap={featureColumnMap}
                  />
                ))}
              {recs.filter((r) => getTabs(r.type).includes(activeTab)).length === 0 && (
                <div className="planner-page__empty-tab">
                  No {activeTab === "features" ? "feature" : "analysis"} suggestions yet.
                </div>
              )}
            </div>

            <div className="planner-page__more-section">
              <div className="planner-page__more-label">Want more options?</div>
              <p className="planner-page__more-hint">
                Ask the Planner to generate 4 more features and 4 more analyses, different from what's already shown.
              </p>
              <button
                type="button"
                className="planner-page__more-btn"
                onClick={handleRequestMore}
                disabled={moreLoading || !result}
              >
                {moreLoading ? (
                  <><span className="planner-page__spinner" />Generating more suggestions…</>
                ) : (
                  "Generate more suggestions"
                )}
              </button>
            </div>
          </>
        )}

        <div className="planner-page__bottom">
          <div className="planner-page__nav-btns">
            <button
              type="button"
              className="planner-page__btn--secondary"
              onClick={() => navigate("/upload")}
            >
              Back to Upload
            </button>
            <button
              type="button"
              className="planner-page__btn--primary"
              disabled={saving || loading || !result}
              onClick={handleProceed}
            >
              {saving ? "Saving…" : "Proceed to Audit"}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}

interface RecCardProps {
  rec: PlannerRecommendation;
  index: number;
  decision: PmDecisionValue;
  onDecide: (index: number, value: PmDecisionValue) => void;
  featureColumnMap: Map<string, string>;
}

interface RequirementNote {
  text: string;
  kind: "ok" | "blocked" | "missing";
}

// Whether this recommendation needs any column it doesn't already have --
// missing_fields is required_fields minus whatever's already in the
// uploaded data (see planner.py's DATA AVAILABILITY guardrail). Resolving a
// missing field to a sibling feature recommendation (by its derived
// output_column) tells the PM WHY it's missing: not absent data, but a
// column that only exists once that feature is accepted and computed.
function requirementNote(rec: PlannerRecommendation, ownName: string, featureColumnMap: Map<string, string>): RequirementNote {
  const missing = rec.missing_fields ?? [];
  if (missing.length === 0) {
    return { text: "No required column", kind: "ok" };
  }
  const neededFeatures = new Set<string>();
  const unresolved: string[] = [];
  for (const field of missing) {
    const featureName = featureColumnMap.get(deriveOutputColumn(field));
    if (featureName && featureName !== ownName) {
      neededFeatures.add(featureName);
    } else {
      unresolved.push(field);
    }
  }
  if (neededFeatures.size > 0 && unresolved.length === 0) {
    return { text: `Can only be done once the feature "${[...neededFeatures].join('", "')}" is computed.`, kind: "blocked" };
  }
  if (neededFeatures.size > 0) {
    return {
      text: `Can only be done once the feature "${[...neededFeatures].join('", "')}" is computed. Still missing: ${unresolved.join(", ")}.`,
      kind: "blocked",
    };
  }
  return { text: `Missing required column${unresolved.length > 1 ? "s" : ""}: ${unresolved.join(", ")}`, kind: "missing" };
}

function typeLabel(type: string): string {
  if (type === "analysis") return "Analysis";
  if (type === "feature_and_analysis") return "Feature + Analysis";
  if (type === "configuration") return "Configuration";
  return "Feature";
}

function typeSlug(type: string): string {
  return type.replace(/_/g, "-");
}

function statusLabel(status: string): string {
  if (status === "existing") return "Existing";
  if (status === "needs_clarification") return "Needs Clarification";
  return "New";
}

function RecommendationCard({ rec, index, decision, onDecide, featureColumnMap }: RecCardProps) {
  // Defensive fallbacks: an older cached suggestion, a dev-server hot-reload
  // that preserved stale state from before this schema changed, or an LLM
  // response that omitted an array field should never blank the whole page.
  const clarifications = rec.clarifications_required ?? [];
  const hasClarifications = clarifications.length > 0;
  const columns = rec.required_fields ?? [];
  const generatedFormula = rec.generated_feature_formula;
  const generatedAnalysisFormula = rec.generated_analysis_formula;
  const requirement = requirementNote(rec, rec.name, featureColumnMap);

  return (
    <div
      className={`planner-page__card${decision === "accepted" ? " planner-page__card--accepted" : ""}${decision === "rejected" ? " planner-page__card--rejected" : ""}`}
    >
      <div className="planner-page__card-head">
        <div className="planner-page__card-meta">
          <div className="planner-page__card-badges">
            <span className={`planner-page__badge planner-page__badge--type-${typeSlug(rec.type)}`}>
              {typeLabel(rec.type)}
            </span>
            <span className={`planner-page__badge planner-page__badge--status-${statusLabel(rec.status).toLowerCase().replace(/\s+/g, "-")}`}>
              {statusLabel(rec.status)}
            </span>
          </div>
          <h3 className="planner-page__card-name">{rec.name}</h3>
          <p className="planner-page__card-desc">{rec.description}</p>
          {rec.feature_formula_expression && (
            <div className="planner-page__spec">
              <span className="planner-page__spec-label">ƒ Feature formula</span>
              <code className="planner-page__spec-code">{rec.feature_formula_expression}</code>
              {rec.feature_output_dtype && (
                <span className="planner-page__spec-meta">Output type: {rec.feature_output_dtype}</span>
              )}
            </div>
          )}
          {generatedFormula && (
            <PlanText plan={generatedFormula} label="Feature computation plan" className="planner-page__formula" />
          )}
          {(rec.analysis_logic || (rec.analysis_group_by?.length ?? 0) > 0 || (rec.analysis_metrics?.length ?? 0) > 0) && (
            <div className="planner-page__spec">
              <span className="planner-page__spec-label">Analysis spec / logic</span>
              {rec.analysis_logic && <code className="planner-page__spec-code">{rec.analysis_logic}</code>}
              <span className="planner-page__spec-meta">
                Group by: {(rec.analysis_group_by?.length ?? 0) > 0 ? rec.analysis_group_by!.join(", ") : "none (overall)"}
              </span>
              {(rec.analysis_metrics?.length ?? 0) > 0 && (
                <span className="planner-page__spec-meta">Metrics: {rec.analysis_metrics!.join("; ")}</span>
              )}
            </div>
          )}
          {generatedAnalysisFormula && (
            <PlanText plan={generatedAnalysisFormula} label="Analysis plan" className="planner-page__formula" />
          )}
          {columns.length > 0 && (
            <div className="planner-page__columns">
              <span className="planner-page__columns-label">Columns used:</span>
              {columns.map((col) => (
                <span key={col} className="planner-page__col-tag">{col}</span>
              ))}
            </div>
          )}
          <div className={`planner-page__requirement planner-page__requirement--${requirement.kind}`}>
            {requirement.text}
          </div>
        </div>
      </div>

      {hasClarifications && (
        <div className="planner-page__clarifications">
          <p>Needs clarification:</p>
          <ul>
            {clarifications.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="planner-page__card-foot">
        <span className="planner-page__reason">{rec.reason}</span>
        <div className="planner-page__actions">
          <button
            type="button"
            className={`planner-page__btn-accept${decision === "accepted" ? " planner-page__btn-accept--active" : ""}`}
            onClick={() => onDecide(index, "accepted")}
          >
            {decision === "accepted" ? "✓ Accepted" : "Accept"}
          </button>
          <button
            type="button"
            className={`planner-page__btn-reject${decision === "rejected" ? " planner-page__btn-reject--active" : ""}`}
            onClick={() => onDecide(index, "rejected")}
          >
            {decision === "rejected" ? "Rejected" : "Reject"}
          </button>
        </div>
      </div>
    </div>
  );
}
