import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Header from "../components/Header";
import StepIndicator from "../components/StepIndicator";
import {
  startAnalysis,
  nextAnalysisStep,
  computeFormula,
  AnalysisApiError,
} from "../api/analysis";
import type { AnalysisState, AnalysisStep } from "../api/analysis";
import type { AuditReportsState, FilesState, BriefState } from "../App";
import "./AnalysisPage.css";

interface AnalysisPageProps {
  files: FilesState;
  auditReports: AuditReportsState;
  brief: BriefState;
  onAnalysisStarted?: (analysisId: string) => void;
}

const STEP_LABELS: Record<string, string> = {
  summary: "Executive Summary",
  chart_suggestion: "Chart Recommendation",
  chart_interpretation: "Chart Interpretation",
  drill_down: "Drill-Down Suggestions",
  formula_spec: "Analytical Formula",
};

function StepCard({ step }: { step: AnalysisStep }) {
  const label = STEP_LABELS[step.step_type] ?? step.step_type.replace(/_/g, " ");
  return (
    <div className="analysis-page__step-card">
      <div className="analysis-page__step-badge">Step {step.step_number} · {label}</div>
      <div className="analysis-page__step-content">{step.content}</div>
      {step.formula_code && (
        <details className="analysis-page__code-details">
          <summary>View generated code</summary>
          <pre className="analysis-page__code">{step.formula_code}</pre>
        </details>
      )}
    </div>
  );
}

export default function AnalysisPage({ files, auditReports, brief, onAnalysisStarted }: AnalysisPageProps) {
  const navigate = useNavigate();
  const [state, setState] = useState<AnalysisState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userAsk, setUserAsk] = useState("");
  const [computeAsk, setComputeAsk] = useState("");

  const primaryReport = auditReports.sensiwatch;

  const handleStart = async () => {
    if (!primaryReport) return;
    setLoading(true);
    setError(null);
    try {
      const s = await startAnalysis(primaryReport.session_id, brief.text || "Analyse the cold-chain data.");
      setState(s);
      onAnalysisStarted?.(s.analysis_id);
    } catch (err) {
      setError(err instanceof AnalysisApiError ? err.message : "Analysis could not start.");
    } finally {
      setLoading(false);
    }
  };

  const handleNext = async () => {
    if (!state) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await nextAnalysisStep(state.analysis_id, userAsk.trim() || undefined);
      setState(updated);
      setUserAsk("");
    } catch (err) {
      setError(err instanceof AnalysisApiError ? err.message : "Step failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleCompute = async () => {
    if (!state || !computeAsk.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const updated = await computeFormula(state.analysis_id, computeAsk.trim());
      setState(updated);
      setComputeAsk("");
    } catch (err) {
      setError(err instanceof AnalysisApiError ? err.message : "Computation failed.");
    } finally {
      setLoading(false);
    }
  };

  if (!files.sensiwatch || !primaryReport) {
    return (
      <div className="analysis-page">
        <Header />
        <main className="analysis-page__main">
          <StepIndicator current={5} />
          <div className="analysis-page__empty">
            <p>Complete the data audit before running analysis.</p>
            <button type="button" className="analysis-page__btn analysis-page__btn--primary" onClick={() => navigate("/audit")}>
              Go to Audit
            </button>
          </div>
        </main>
      </div>
    );
  }

  const stepsDone = state?.steps.length ?? 0;
  const totalSteps = 5;
  const isComplete = state?.status === "complete";
  const canAdvance = state && stepsDone < totalSteps && !isComplete;

  return (
    <div className="analysis-page">
      <Header />
      <main className="analysis-page__main">
        <StepIndicator current={5} />

        <div className="analysis-page__intro">
          <h1 className="analysis-page__heading">AI-Assisted Analysis</h1>
          <p className="analysis-page__lede">
            The Insight Agent works through five sequential micro-steps: summarise → suggest
            chart → interpret → drill-down → formula. You can steer it at any step with a
            specific question, or compute a custom metric directly.
          </p>
        </div>

        {brief.text && (
          <div className="analysis-page__brief-box">
            <span className="analysis-page__brief-label">Brief</span>
            <p className="analysis-page__brief-text">{brief.text}</p>
          </div>
        )}

        {!state && !loading && (
          <div className="analysis-page__start">
            <button type="button" className="analysis-page__btn analysis-page__btn--primary analysis-page__btn--lg" onClick={handleStart}>
              Start Analysis
            </button>
          </div>
        )}

        {loading && <div className="analysis-page__spinner">Insight agent is thinking…</div>}
        {error && <p className="analysis-page__error">{error}</p>}

        {state && (
          <>
            <div className="analysis-page__steps">
              {state.steps.map((step) => (
                <StepCard key={step.step_number} step={step} />
              ))}
            </div>

            {canAdvance && (
              <div className="analysis-page__advance">
                <input
                  type="text"
                  className="analysis-page__ask-input"
                  placeholder="Steer this step with a specific question (optional)…"
                  value={userAsk}
                  onChange={(e) => setUserAsk(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleNext(); }}
                />
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--primary"
                  onClick={handleNext}
                  disabled={loading}
                >
                  Next Step ({stepsDone + 1}/{totalSteps})
                </button>
              </div>
            )}

            {isComplete && (
              <p className="analysis-page__complete">All 5 analysis steps complete.</p>
            )}

            <div className="analysis-page__compute-section">
              <h2 className="analysis-page__compute-title">Compute a custom metric</h2>
              <p className="analysis-page__compute-hint">
                Ask in plain English — the Formula Agent writes Python, the Sandbox runs it, and the
                result is added to your analysis and report.
              </p>
              <div className="analysis-page__compute-row">
                <input
                  type="text"
                  className="analysis-page__ask-input"
                  placeholder="e.g. Average excursion duration by supplier…"
                  value={computeAsk}
                  onChange={(e) => setComputeAsk(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") handleCompute(); }}
                />
                <button
                  type="button"
                  className="analysis-page__btn analysis-page__btn--secondary"
                  onClick={handleCompute}
                  disabled={loading || !computeAsk.trim()}
                >
                  Compute
                </button>
              </div>
            </div>
          </>
        )}

        <div className="analysis-page__actions">
          <button type="button" className="analysis-page__btn analysis-page__btn--secondary" onClick={() => navigate("/features")}>
            Back to Features
          </button>
          {state && (
            <button
              type="button"
              className="analysis-page__btn analysis-page__btn--primary"
              onClick={() => navigate("/report")}
            >
              Generate Report
            </button>
          )}
        </div>
      </main>
    </div>
  );
}
