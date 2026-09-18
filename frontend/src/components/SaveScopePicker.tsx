import type { SavedScope } from "../api/audit";
import "./SaveScopePicker.css";

interface SaveScopePickerProps {
  /** What this thing is called in the copy below -- "KPI" or "analysis". */
  noun: string;
  value: SavedScope;
  onChange: (scope: SavedScope) => void;
  disabled?: boolean;
}

/**
 * The two save options offered whenever a custom KPI or analysis is created.
 * Either way it's saved to the library as JSON and shows up in the saved list
 * on this page next time -- `scope` only decides whether it ALSO gets
 * computed automatically from then on:
 *
 *   regular   -- treated like part of the uploaded profile: merged into every
 *                run, in every session, without being picked again.
 *   suggested -- offered back alongside the AI suggestions; added per session,
 *                when it's wanted.
 *
 * Defaults to "suggested" at every call site: quietly adding something to
 * every future report is the more surprising of the two, so it's the one the
 * user has to actually choose.
 */
export default function SaveScopePicker({ noun, value, onChange, disabled }: SaveScopePickerProps) {
  const options: { scope: SavedScope; title: string; hint: string }[] = [
    {
      scope: "suggested",
      title: "Add to my list",
      hint: `Saved with your other ${noun}s and offered next time -- added only when you pick it.`,
    },
    {
      scope: "regular",
      title: "Keep as my regular",
      hint: `Saved and treated as standard -- computed on every run from now on, like the uploaded profile's own ${noun}s.`,
    },
  ];

  return (
    <div className="save-scope">
      <span className="save-scope__label">Save this {noun} for next time</span>
      <div className="save-scope__options">
        {options.map((option) => (
          <button
            key={option.scope}
            type="button"
            className={`save-scope__option ${value === option.scope ? "save-scope__option--active" : ""}`}
            disabled={disabled}
            aria-pressed={value === option.scope}
            onClick={() => onChange(option.scope)}
          >
            <span className="save-scope__option-title">{option.title}</span>
            <span className="save-scope__option-hint">{option.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
