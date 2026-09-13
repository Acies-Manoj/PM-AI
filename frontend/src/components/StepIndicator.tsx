import "./StepIndicator.css";

type StepNumber = 1 | 2 | 3 | 4 | 5 | 6;

interface StepIndicatorProps {
  current: StepNumber;
}

const STEPS: { step: StepNumber; label: string }[] = [
  { step: 1, label: "Upload" },
  { step: 2, label: "Audit" },
  { step: 3, label: "Screening" },
  { step: 4, label: "Features" },
  { step: 5, label: "Analysis" },
  { step: 6, label: "Report" },
];

export default function StepIndicator({ current }: StepIndicatorProps) {
  return (
    <ol className="step-indicator" aria-label="Progress">
      {STEPS.map(({ step, label }, idx) => (
        <li
          key={step}
          className={`step-indicator__item ${
            step === current
              ? "step-indicator__item--current"
              : step < current
              ? "step-indicator__item--done"
              : ""
          }`}
        >
          <span className="step-indicator__badge">{step < current ? "✓" : step}</span>
          <span className="step-indicator__label">{label}</span>
          {idx < STEPS.length - 1 && <span className="step-indicator__connector" aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}
