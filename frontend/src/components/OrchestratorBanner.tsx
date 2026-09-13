import type { BriefAnalysis } from "../api/brief";
import "./OrchestratorBanner.css";

interface OrchestratorBannerProps {
  analysis: BriefAnalysis;
}

export default function OrchestratorBanner({ analysis }: OrchestratorBannerProps) {
  return (
    <div className="orch-banner orch-banner--full">
      <p className="orch-banner__description">{analysis.pipeline_description}</p>

      {analysis.key_questions.length > 0 && (
        <div className="orch-banner__questions">
          <span className="orch-banner__questions-label">Key questions this analysis will answer:</span>
          <ol className="orch-banner__questions-list">
            {analysis.key_questions.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
