import { useState } from "react";
import type {
  ConfirmDrilldownBody,
  DrilldownMetric,
  DrilldownOptions,
  DrilldownProposal,
  DrilldownRank,
} from "../api/audit";
import { AuditApiError } from "../api/audit";
import { IconSparkle } from "./icons";
import "./DrilldownPanel.css";

const METRIC_LABELS: Record<DrilldownMetric, string> = { count: "Trips", pct_in_spec: "% in spec" };

/** Compact Top/Bottom + N + rank-by control -- used by the guided panel and,
 * on its own, in a chain level's header to re-rank that level. */
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
  /** True for a drill-down chain level (multi-select focus); level 1 is single-select. */
  multiFocus: boolean;
  onPropose: () => Promise<DrilldownProposal[]>;
  onConfirm: (body: ConfirmDrilldownBody) => Promise<void>;
}

/** The PM's guided drill-down: pick focus values, a child dimension, a metric
 * and a rank, then explicitly Confirm -- nothing runs before that. */
export default function DrilldownPanel({ options, multiFocus, onPropose, onConfirm }: DrilldownPanelProps) {
  const [focus, setFocus] = useState<string[]>(multiFocus ? options.default_focus : options.default_focus.slice(0, 1));
  const [childDim, setChildDim] = useState(options.child_dimension ?? options.candidate_dimensions[0] ?? "");
  const [metric, setMetric] = useState<DrilldownMetric>("count");
  const [rank, setRank] = useState<DrilldownRank>(options.default_rank);
  const [proposals, setProposals] = useState<DrilldownProposal[] | null>(null);
  const [proposing, setProposing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // "One slide per selected value": several siblings (2.1, 2.2, ...) instead of one combined chart.
  const [split, setSplit] = useState(false);
  const pickMany = multiFocus || split;

  const canPct = options.metrics.includes("pct_in_spec");
  const dimensions =
    !childDim || options.candidate_dimensions.includes(childDim) ? options.candidate_dimensions : [childDim, ...options.candidate_dimensions];
  const unit = childDim ? `${childDim}s` : "groups";
  const metricChoices: DrilldownMetric[] = canPct ? ["count", "pct_in_spec"] : ["count"];

  const toggleFocus = (value: string) => {
    setDone(false);
    if (!pickMany) {
      setFocus([value]);
      return;
    }
    setFocus((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]));
  };

  const propose = () => {
    setProposing(true);
    setError(null);
    onPropose()
      .then(setProposals)
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not get drill-down proposals."))
      .finally(() => setProposing(false));
  };

  // Pre-fills the controls only -- the PM still has to press Confirm.
  const applyProposal = (p: DrilldownProposal) => {
    setDone(false);
    setFocus(multiFocus ? p.focus_values : p.focus_values.slice(0, 1));
    setChildDim(p.child_dimension);
    setMetric(canPct || p.metric === "count" ? p.metric : "count");
    setRank(p.rank);
  };

  const confirm = () => {
    setConfirming(true);
    setError(null);
    setDone(false);
    onConfirm({ focus_values: focus, child_dimension: childDim || null, metric, rank, split: split && focus.length > 1 })
      .then(() => setDone(true))
      .catch((err) => setError(err instanceof AuditApiError ? err.message : "Could not run that drill-down."))
      .finally(() => setConfirming(false));
  };

  return (
    <div className="drilldown-panel">
      <div className="drilldown-panel__head">
        <h5 className="drilldown-panel__title">Guided drill-down</h5>
        <button type="button" className="analysis-detail__suggest-more-btn" disabled={proposing} onClick={propose}>
          <IconSparkle />
          {proposing ? "Thinking…" : "Suggest with AI"}
        </button>
      </div>

      {proposals && (
        <div className="drilldown-proposals">
          {proposals.length === 0 && <p className="drilldown-panel__hint">No proposals available.</p>}
          {proposals.map((p, i) => (
            <div className="drilldown-proposal" key={i}>
              <div className="drilldown-proposal__body">
                <span className="drilldown-proposal__title">
                  {p.child_dimension} · {METRIC_LABELS[p.metric]} · {p.rank.mode === "top" ? "Top" : "Bottom"} {p.rank.n}
                  <span className={`drilldown-tag drilldown-tag--${p.source}`}>{p.source === "ai" ? "AI" : "Default"}</span>
                </span>
                {p.focus_values.length > 0 && <span className="drilldown-proposal__focus">{p.focus_values.join(", ")}</span>}
                <p className="drilldown-proposal__reason">{p.reason}</p>
              </div>
              <button type="button" className="drilldown-btn" onClick={() => applyProposal(p)}>
                Use this
              </button>
            </div>
          ))}
        </div>
      )}

      {options.focus_options.length > 0 && (
        <div className="drilldown-panel__group">
          <span className="drilldown-panel__label">
            {options.focus_dimension ? `Focus on ${options.focus_dimension}` : "Focus"}
            {pickMany ? " (select one or more)" : ""}
          </span>
          <div className="drilldown-focus" role={pickMany ? "group" : "radiogroup"}>
            {options.focus_options.map((o) => {
              const on = focus.includes(o.value);
              return (
                <button
                  key={o.value}
                  type="button"
                  role={pickMany ? "checkbox" : "radio"}
                  aria-checked={on}
                  className={`drilldown-focus__item${on ? " drilldown-focus__item--on" : ""}`}
                  onClick={() => toggleFocus(o.value)}
                >
                  <span className="drilldown-focus__value">{o.value}</span>
                  <span className="drilldown-focus__meta">
                    {o.rows.toLocaleString()} trips · {o.child_count} {options.child_dimension ?? "group"}
                    {o.child_count === 1 ? "" : "s"}
                  </span>
                  {o.is_wide && <span className="drilldown-tag drilldown-tag--wide">wide</span>}
                </button>
              );
            })}
          </div>
          {options.focus_options.length > 1 && (
            <label className="drilldown-split">
              <input
                type="checkbox"
                checked={split}
                onChange={(e) => {
                  setDone(false);
                  setSplit(e.target.checked);
                  // Back to single-pick at level 1: keep just the first selected value.
                  if (!e.target.checked && !multiFocus) setFocus((prev) => prev.slice(0, 1));
                }}
              />
              <span>One slide per selected value</span>
            </label>
          )}
          {split && focus.length > 1 && (
            <p className="drilldown-panel__hint">
              Creates {focus.length} separate slides, one each for {focus.join(", ")}.
            </p>
          )}
        </div>
      )}

      <div className="drilldown-panel__controls">
        <label className="drilldown-field">
          <span>Drill into</span>
          <select value={childDim} onChange={(e) => setChildDim(e.target.value)}>
            {dimensions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        <div className="drilldown-field">
          <span>Metric</span>
          <div className="drilldown-seg">
            {metricChoices.map((m) => (
              <button
                key={m}
                type="button"
                className={`drilldown-seg__btn${metric === m ? " drilldown-seg__btn--active" : ""}`}
                onClick={() => setMetric(m)}
              >
                {METRIC_LABELS[m]}
              </button>
            ))}
          </div>
        </div>
        <div className="drilldown-field">
          <span>Show {unit}</span>
          <DrilldownRankControl rank={rank} metrics={options.metrics} onChange={setRank} />
        </div>
      </div>

      {error && <p className="analysis-card__error">{error}</p>}
      {done && !confirming && <p className="drilldown-panel__hint">Drill-down created -- see the levels below.</p>}
      <div className="drilldown-panel__actions">
        <button
          type="button"
          className="drilldown-btn drilldown-btn--primary"
          disabled={confirming || (options.focus_options.length > 0 && focus.length === 0)}
          onClick={confirm}
        >
          {confirming ? "Running drill-down…" : split && focus.length > 1 ? `Confirm (${focus.length} slides)` : "Confirm"}
        </button>
      </div>
    </div>
  );
}
