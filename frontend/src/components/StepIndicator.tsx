import { useNavigate } from "react-router-dom";
import "./StepIndicator.css";

interface StepIndicatorProps {
  current: 1 | 2 | 3 | 4 | 5 | 6;
}

const STEPS = [
  { step: 1, label: "Upload", path: "/upload" },
  { step: 2, label: "Planner", path: "/planner" },
  { step: 3, label: "Audit", path: "/audit" },
  { step: 4, label: "Features", path: "/features" },
  { step: 5, label: "Analysis", path: "/analysis" },
  { step: 6, label: "Report", path: "/report" },
] as const;

export default function StepIndicator({ current }: StepIndicatorProps) {
  const navigate = useNavigate();

  return (
    <ol className="step-indicator" aria-label="Progress">
      {STEPS.map(({ step, label, path }, idx) => {
        const isDone = step < current;
        const isCurrent = step === current;
        return (
          <li
            key={step}
            className={`step-indicator__item ${
              isCurrent ? "step-indicator__item--current" : isDone ? "step-indicator__item--done" : ""
            }`}
          >
            {isDone ? (
              <button
                type="button"
                className="step-indicator__link"
                onClick={() => navigate(path)}
                aria-label={`Back to ${label}`}
              >
                <span className="step-indicator__badge">✓</span>
                <span className="step-indicator__label">{label}</span>
              </button>
            ) : (
              <>
                <span className="step-indicator__badge">{step}</span>
                <span className="step-indicator__label">{label}</span>
              </>
            )}
            {idx < STEPS.length - 1 && <span className="step-indicator__connector" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
