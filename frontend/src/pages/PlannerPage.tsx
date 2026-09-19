import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import PageHeader from "../components/PageHeader";
import { fetchSuggestions, saveDecisions } from "../api/planner";
import type { PlannerRecommendation, PlannerRecommendationType, PlannerSuggestResponse, PmDecisionValue } from "../api/planner";
import "./PlannerPage.css";

type PlannerTab = "features" | "analyses";

function getTab(type: PlannerRecommendationType): PlannerTab {
  return type === "analysis" ? "analyses" : "features";
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
        if (getTab(r.type) === tab) next[i] = value;
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
  const hasAnyDecision = recs.some((_, i) => decisions[i] && decisions[i] !== "pending");

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
            <div className="planner-page__context">
              <div className="planner-page__context-label">What the Planner understood</div>
              <p className="planner-page__context-text">{result.interpreted_requirement}</p>
              <p className="planner-page__objective">Objective: {result.business_objective}</p>
            </div>

            <div className="planner-page__tabs">
              <div className="planner-page__tabs-left">
                {(["features", "analyses"] as PlannerTab[]).map((tab) => {
                  const count = recs.filter((r) => getTab(r.type) === tab).length;
                  const acceptedCount = recs.filter((r, i) => getTab(r.type) === tab && decisions[i] === "accepted").length;
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
              {recs.filter((r) => getTab(r.type) === activeTab).length > 0 && (
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
                .filter(({ rec }) => getTab(rec.type) === activeTab)
                .map(({ rec, i }) => (
                  <RecommendationCard
                    key={i}
                    rec={rec}
                    index={i}
                    decision={decisions[i] ?? "pending"}
                    onDecide={setDecision}
                  />
                ))}
              {recs.filter((r) => getTab(r.type) === activeTab).length === 0 && (
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
}

function typeLabel(type: string): string {
  return type === "analysis" ? "Analysis" : "Feature";
}

function statusLabel(status: string): string {
  return status === "existing" ? "Existing" : "New";
}

function RecommendationCard({ rec, index, decision, onDecide }: RecCardProps) {
  const hasWarnings = rec.validation.warnings.length > 0;
  const hasClarifications = rec.validation.clarifications_required.length > 0;
  const columns = rec.data_requirements.required_fields;

  return (
    <div
      className={`planner-page__card${decision === "accepted" ? " planner-page__card--accepted" : ""}${decision === "rejected" ? " planner-page__card--rejected" : ""}`}
    >
      <div className="planner-page__card-head">
        <div className="planner-page__card-meta">
          <div className="planner-page__card-badges">
            <span className={`planner-page__badge planner-page__badge--type-${typeLabel(rec.type).toLowerCase()}`}>
              {typeLabel(rec.type)}
            </span>
            <span className={`planner-page__badge planner-page__badge--status-${statusLabel(rec.status).toLowerCase()}`}>
              {statusLabel(rec.status)}
            </span>
          </div>
          <h3 className="planner-page__card-name">{rec.name}</h3>
          <p className="planner-page__card-desc">{rec.description}</p>
          {columns.length > 0 && (
            <div className="planner-page__columns">
              <span className="planner-page__columns-label">Columns used:</span>
              {columns.map((col) => (
                <span key={col} className="planner-page__col-tag">{col}</span>
              ))}
            </div>
          )}
        </div>
        <div className="planner-page__confidence">
          <span className="planner-page__confidence-num">{rec.confidence}%</span>
          <div className="planner-page__confidence-bar">
            <div
              className="planner-page__confidence-fill"
              style={{ width: `${rec.confidence}%` }}
            />
          </div>
          <span className="planner-page__confidence-label">confidence</span>
        </div>
      </div>

      {hasWarnings && (
        <div className="planner-page__warnings">
          {rec.validation.warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </div>
      )}

      {hasClarifications && (
        <div className="planner-page__clarifications">
          <p>Needs clarification:</p>
          <ul>
            {rec.validation.clarifications_required.map((q, i) => (
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
