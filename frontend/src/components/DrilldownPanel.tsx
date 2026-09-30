import { useEffect, useState } from "react";
import type { ConfirmDrilldownBody, DrilldownMetric, DrilldownOptions, DrilldownProposal, DrilldownRank } from "../api/audit";
import { AuditApiError } from "../api/audit";
import { IconSparkle } from "./icons";
import "./DrilldownPanel.css";

const METRIC_LABELS: Record<DrilldownMetric, string> = { count: "Trips", pct_in_spec: "% in spec" };

/** Compact Top/Bottom + N + rank-by control -- used on its own in a chain
 * level's header to re-rank that level. */
export function DrilldownRankControl({
  rank,
  metrics,
  disabled,
  onChange,
}: {
  rank: DrilldownRank;
  metrics: DrilldownMetric[];
  disabled?: boolean;
  onChange: (rank: DrilldownRank) => void;
}) {
  const byOptions: DrilldownMetric[] = metrics.includes("pct_in_spec") ? ["count", "pct_in_spec"] : ["count"];
  return (
    <div className="drilldown-rank" role="group" aria-label="Rank">
      <div className="drilldown-seg">
        {(["top", "bottom"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            disabled={disabled}
            className={`drilldown-seg__btn${rank.mode === mode ? " drilldown-seg__btn--active" : ""}`}
            onClick={() => rank.mode !== mode && onChange({ ...rank, mode })}
          >
            {mode === "top" ? "Top" : "Bottom"}
          </button>
        ))}
      </div>
      <div className="drilldown-stepper">
        <button
          type="button"
          aria-label="Fewer"
          disabled={disabled || rank.n <= 1}
          onClick={() => onChange({ ...rank, n: rank.n - 1 })}
        >
          -
        </button>
        <span className="drilldown-stepper__value">{rank.n}</span>
        <button
          type="button"
          aria-label="More"
          disabled={disabled || rank.n >= 10}
          onClick={() => onChange({ ...rank, n: rank.n + 1 })}
        >
          +
        </button>
      </div>
      <label className="drilldown-field drilldown-field--inline">
        <span>by</span>
        <select
          value={rank.by}
          disabled={disabled}
          onChange={(e) => onChange({ ...rank, by: e.target.value as DrilldownMetric })}
        >
          {byOptions.map((m) => (
            <option key={m} value={m}>
              {METRIC_LABELS[m]}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

interface DrilldownPanelProps {
  options: DrilldownOptions;
  /** `more: true` asks for an additional, non-repeating batch on top of
   * whatever's cached; `false` (the initial, automatic load) just returns
   * the cached batch, generating it once if this is the first time. */
  onPropose: (more: boolean) => Promise<DrilldownProposal[]>;
  /** Runs the picked proposal exactly as suggested and navigates into the
   * new level -- there's no separate review/edit step. */
  onConfirm: (body: ConfirmDrilldownBody) => Promise<void>;
}

/** 10-15 AI-suggested drill-downs, auto-loaded (and cached) the moment this
 * analysis is opened. Picking one runs it immediately and opens the result --
 * there's no manual dimension/metric/rank picker here. */
export default function DrilldownPanel({ options, onPropose, onConfirm }: DrilldownPanelProps) {
  const [proposals, setProposals] = useState<DrilldownProposal[] | null>(null);
  const [proposing, setProposing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingIndex, setConfirmingIndex] = useState<number | null>(null);

  const propose = (more: boolean) => {
    setProposing(true);
    setError(null);
    onPropose(more)
      .then(setProposals)
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not get drill-down suggestions."))
      .finally(() => setProposing(false));
  };

  // Auto-load the (possibly cached) suggestions the moment this analysis is
  // opened -- no click needed. Re-fires when the caller passes a new
  // `key={entry.id}`, i.e. a fresh mount for a different entry.
  useEffect(() => {
    propose(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = (p: DrilldownProposal, i: number) => {
    setConfirmingIndex(i);
    setError(null);
    onConfirm({ focus_values: p.focus_values, child_dimension: p.child_dimension, metric: p.metric, rank: p.rank, split: false })
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not run that drill-down."))
      .finally(() => setConfirmingIndex(null));
  };

  return (
    <div className="drilldown-panel">
      <div className="drilldown-panel__head">
        <h5 className="drilldown-panel__title">
          Suggested Drill-downs{proposals && proposals.length > 0 ? ` (${proposals.length})` : ""}
        </h5>
        <button type="button" className="analysis-detail__suggest-more-btn" disabled={proposing} onClick={() => propose(true)}>
          <IconSparkle />
          {proposing ? "Thinking…" : "AI"}
        </button>
      </div>

      {error && <p className="analysis-card__error">{error}</p>}
      {proposing && !proposals && <p className="drilldown-panel__hint">Finding drill-downs…</p>}

      {proposals && (
        <div className={`drilldown-proposals${proposals.length > 5 ? " drilldown-proposals--scroll" : ""}`}>
          {proposals.length === 0 && <p className="drilldown-panel__hint">No drill-downs available.</p>}
          {proposals.map((p, i) => (
            <div className="drilldown-proposal" key={i}>
              <div className="drilldown-proposal__body">
                <span className="drilldown-proposal__title">
                  {p.child_dimension} · {METRIC_LABELS[p.metric]} · {p.rank.mode === "top" ? "Top" : "Bottom"} {p.rank.n}
                </span>
                {p.focus_values.length > 0 && (
                  <span className="drilldown-proposal__focus">
                    {options.focus_dimension ? `${options.focus_dimension}: ` : ""}
                    {p.focus_values.join(", ")}
                  </span>
                )}
                <p className="drilldown-proposal__reason">{p.reason}</p>
              </div>
              <button
                type="button"
                className="drilldown-btn drilldown-btn--primary"
                disabled={confirmingIndex !== null}
                onClick={() => select(p, i)}
              >
                {confirmingIndex === i ? "Opening…" : "Drill down"}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
