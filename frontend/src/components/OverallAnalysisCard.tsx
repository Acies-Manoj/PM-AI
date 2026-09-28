import type { OverallAnalysisReport } from "../api/audit";
import { IconSparkle } from "./icons";
import "./OverallAnalysisCard.css";

interface OverallAnalysisCardProps {
  report: OverallAnalysisReport | undefined;
  loading: boolean;
  error: string | undefined;
  /** True while some analyses are still queued or running -- the summary
   * generates on its own once they finish. */
  waitingForAnalyses: boolean;
  /** Only offered after a failed attempt -- the summary generates itself. */
  onRetry: () => void;
}

export default function OverallAnalysisCard({ report, loading, error, waitingForAnalyses, onRetry }: OverallAnalysisCardProps) {
  let status: string | null = null;
  if (loading) status = report ? "Updating the summary with the latest analyses…" : "Writing the summary…";
  else if (waitingForAnalyses) status = "The summary will appear once the analyses finish running.";
  else if (!report && !error) status = "The summary will appear once an analysis has run.";

  return (
    <div className="overall-analysis-card">
      <div className="overall-analysis-card__head">
        <h3 className="overall-analysis-card__title">
          <IconSparkle /> Summary
        </h3>
      </div>

      {status && (
        <p className="overall-analysis-card__status" role="status">
          {loading && <span className="overall-analysis-card__spinner" aria-hidden="true" />}
          {status}
        </p>
      )}

      {error && !loading && (
        <div className="overall-analysis-card__error-row">
          <p className="overall-analysis-card__error">{error}</p>
          <button type="button" className="overall-analysis-card__refresh-btn" onClick={onRetry}>
            Try again
          </button>
        </div>
      )}

      {report && (
        <>
          <p className="overall-analysis-card__narrative">{report.narrative}</p>
          <ul className="overall-analysis-card__highlights">
            {report.highlights.map((h, idx) => (
              <li key={idx}>
                <span className="overall-analysis-card__highlight-label">{h.label}</span>
                <span className="overall-analysis-card__highlight-value">{h.value}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
