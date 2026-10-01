import ThinkingLoader, { Spinner } from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useEffect, useState } from "react";
import type { ConfirmDrilldownBody, DrilldownMetric, DrilldownOptions, DrilldownProposal } from "../api/audit";
import { AuditApiError } from "../api/audit";
import { IconSparkle } from "./icons";
import { aggLabel } from "../utils/drilldownTree";
import "./DrilldownPanel.css";

const METRIC_LABELS: Record<DrilldownMetric, string> = {
  count: "Trips",
  pct_in_spec: "% in spec",
  mean: "Average",
  sum: "Total",
  median: "Median",
  max: "Max",
  min: "Min",
};
const MODE_LABELS = { all: "All", top: "Top", bottom: "Bottom" } as const;

function proposalTitle(p: DrilldownProposal): string {
  const dims = (p.child_dimensions?.length ? p.child_dimensions : [p.child_dimension]).join(" × ");
  const metric = p.metric_column && !["count", "pct_in_spec"].includes(p.metric) ? aggLabel(p.metric, p.metric_column) : METRIC_LABELS[p.metric];
  const limit = p.rank.mode === "all" ? "All" : `${MODE_LABELS[p.rank.mode]} ${p.rank.n}`;
  return `${dims} · ${metric} · ${limit}`;
}

const MAX_SLIDES = 6;

function proposalKey(p: DrilldownProposal): string {
  const dims = p.child_dimensions?.length ? p.child_dimensions : [p.child_dimension];
  return `${dims.join("|")}~${p.metric}~${p.metric_column ?? ""}`;
}

/** One card per analysis: proposals that differ only in their focus value are merged. */
function mergeProposals(proposals: DrilldownProposal[]): DrilldownProposal[] {
  const seen = new Map<string, DrilldownProposal>();
  for (const p of proposals) if (!seen.has(proposalKey(p))) seen.set(proposalKey(p), p);
  return [...seen.values()];
}

/** A tick-box list of the values from the main chart (e.g. every carrier). */
function FocusChips({
  options,
  selected,
  onToggle,
}: {
  options: DrilldownOptions;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="drilldown-focus">
      {options.focus_options.map((o) => {
        const on = selected.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            role="checkbox"
            aria-checked={on}
            disabled={!on && selected.length >= MAX_SLIDES}
            className={`drilldown-focus__item${on ? " drilldown-focus__item--on" : ""}`}
            onClick={() => onToggle(o.value)}
          >
            <span className="drilldown-focus__value">{o.value}</span>
            <span className="drilldown-focus__meta">{o.rows.toLocaleString()} trips</span>
          </button>
        );
      })}
    </div>
  );
}

function toggleValue(prev: string[], value: string): string[] {
  return prev.includes(value) ? prev.filter((v) => v !== value) : prev.length < MAX_SLIDES ? [...prev, value] : prev;
}

/** One suggested analysis. The values of the main chart are listed right on the
 * card; ticking several runs the same analysis once for each, on separate slides. */
function ProposalCard({
  proposal,
  options,
  busy,
  disabled,
  onRun,
}: {
  proposal: DrilldownProposal;
  options: DrilldownOptions;
  busy: boolean;
  disabled: boolean;
  onRun: (focus: string[]) => void;
}) {
  const [focus, setFocus] = useState<string[]>(proposal.focus_values.slice(0, 1));
  const label = options.focus_dimension ?? "value";
  return (
    <div className="drilldown-proposal drilldown-proposal--stacked">
      <div className="drilldown-proposal__body">
        <span className="drilldown-proposal__title">
          {proposalTitle(proposal)}
          <span className="drilldown-tag drilldown-tag--vars">
            {(proposal.child_dimensions?.length || 1) + 1}-variable chart
          </span>
        </span>
        <p className="drilldown-proposal__reason">{proposal.reason}</p>
        {options.focus_options.length > 0 && (
          <>
            <span className="drilldown-panel__label">Apply to {label} (tick one or more)</span>
            <FocusChips options={options} selected={focus} onToggle={(v) => setFocus((prev) => toggleValue(prev, v))} />
          </>
        )}
      </div>
      <button
        type="button"
        className="drilldown-btn drilldown-btn--primary"
        disabled={disabled || focus.length === 0}
        onClick={() => onRun(focus)}
      >
        {busy ? "Opening…" : focus.length > 1 ? `Drill down (${focus.length} slides)` : "Drill down"}
      </button>
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
  // Already-cached duplicates of one analysis (same columns + measure, different focus) become one card.
  const cards = proposals ? mergeProposals(proposals) : null;

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

  const select = (p: DrilldownProposal, focus: string[], i: number) => {
    setConfirmingIndex(i);
    setError(null);
    onConfirm({
      focus_values: focus,
      child_dimension: p.child_dimension,
      child_dimensions: p.child_dimensions?.length ? p.child_dimensions : [p.child_dimension],
      metric: p.metric,
      metric_column: p.metric_column ?? null,
      rank: p.rank,
      // Several values selected = the same analysis once per value, each on its own slide.
      split: focus.length > 1,
    })
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
          {proposing ? <><Spinner />Thinking…</> : "AI"}
        </button>
      </div>

      {error && <p className="analysis-card__error">{error}</p>}
      {proposing && !proposals && <ThinkingLoader messages={LOADING.proposals} showElapsed />}

      {cards && (
        <div className={`drilldown-proposals${cards.length > 5 ? " drilldown-proposals--scroll" : ""}`}>
          {cards.length === 0 && <p className="drilldown-panel__hint">No drill-downs available.</p>}
          {cards.map((p, i) => (
            <ProposalCard
              key={proposalKey(p)}
              proposal={p}
              options={options}
              busy={confirmingIndex === i}
              disabled={confirmingIndex !== null}
              onRun={(focus) => select(p, focus, i)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
