import "./PlanText.css";

// Matches the Feature Agent's own numbering convention ("1. ... 2. ...") --
// see backend/app/services/feature_agent.py's _plan_text(). Splits into
// clean step strings; returns [] (caller falls back to plain prose) if the
// text isn't actually numbered, e.g. an older un-numbered plan/formula.
export function splitPlanSteps(plan: string): string[] {
  const trimmed = plan.trim();
  if (!/^1\.\s/.test(trimmed)) return [];
  // Splits only at a real step boundary -- a newline immediately followed
  // by "N. " (see _plan_text()'s "\n".join(f"{i+1}. {s}" ...) format).
  // A lookahead with no newline requirement (the previous version's
  // `/(?=\d+\.\s)/`) also matches a plain number ending a sentence mid-step,
  // e.g. "...dividing by 3600. Assign the result..." -- "3600. " satisfies
  // \d+\.\s from EVERY digit inside it (matching "3600. ", "600. ", "00. ",
  // "0. " all separately), shredding that one step into spurious one-digit
  // "steps" instead of treating it as prose inside the real step.
  const steps = trimmed
    .split(/\r?\n(?=\d+\.\s)/)
    .map((s) => s.replace(/^\d+\.\s*/, "").trim())
    .filter(Boolean);
  return steps.length > 1 ? steps : [];
}

interface PlanTextProps {
  plan: string;
  className?: string;
  label?: string;
}

/** Renders a Feature Agent plan as a readable numbered list when it's in the
 * expected "1. ... 2. ..." shape, falling back to plain text otherwise. */
export default function PlanText({ plan, className, label = "Computation plan" }: PlanTextProps) {
  const steps = splitPlanSteps(plan);

  if (steps.length === 0) {
    return <p className={`plan-text plan-text--prose ${className ?? ""}`}>ƒ {plan}</p>;
  }

  return (
    <div className={`plan-text ${className ?? ""}`}>
      <span className="plan-text__label">ƒ {label}</span>
      <ol className="plan-text__list">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </div>
  );
}
