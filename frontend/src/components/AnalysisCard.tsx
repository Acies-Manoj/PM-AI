import type { AnalysisRepositoryEntry } from "../api/audit";
import { IconBarChart, IconExpand, IconSparkle } from "./icons";
import PlanText from "./PlanText";
import AnalysisChart from "./AnalysisChart";
import "./AnalysisCard.css";

interface AnalysisCardProps {
  entry: AnalysisRepositoryEntry;
  running: boolean;
  onRun: () => void;
  onExpand: () => void;
}

const SOURCE_LABELS: Record<string, string> = {
  predefined: "Predefined",
  planner: "Planner",
  custom: "Custom",
  ai_suggested: "AI",
  drilldown: "Drilldown",
};

export default function AnalysisCard({ entry, running, onRun, onExpand }: AnalysisCardProps) {
  return (
    <div className="analysis-card">
      <div className="analysis-card__header">
        <span className="analysis-card__icon">
          <IconBarChart />
        </span>
        <div className="analysis-card__header-text">
          <h3 className="analysis-card__name">{entry.name}</h3>
          {(entry.formula || entry.plan_text) && (
            <PlanText plan={entry.plan_text ?? entry.formula ?? ""} label="Analysis plan" className="analysis-card__formula" />
          )}
        </div>
        {entry.source !== "predefined" && (
          <span className={entry.source === "ai_suggested" ? "analysis-card__ai-badge" : "analysis-card__custom-badge"}>
            {SOURCE_LABELS[entry.source] ?? entry.source}
          </span>
        )}
      </div>

      <p className="analysis-card__description">{entry.description}</p>

      {entry.run_status === "not_run" && (
        <button type="button" className="analysis-card__run-btn" disabled={running} onClick={onRun}>
          <IconSparkle /> {running ? "Running…" : "Run Analysis"}
        </button>
      )}

      {entry.run_status === "error" && (
        <div className="analysis-card__error-block">
          <p className="analysis-card__error">{entry.error}</p>
          <button type="button" className="analysis-card__run-btn analysis-card__run-btn--retry" disabled={running} onClick={onRun}>
            {running ? "Retrying…" : "Retry"}
          </button>
        </div>
      )}

      {entry.run_status === "done" && (
        <>
          <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} />
          {entry.interpretation && <p className="analysis-card__interpretation">{entry.interpretation}</p>}
          <button type="button" className="analysis-card__expand-btn" onClick={onExpand}>
            <IconExpand /> View details{entry.drilldown_suggestions.length > 0 ? " & drilldowns" : ""}
          </button>
        </>
      )}
    </div>
  );
}
