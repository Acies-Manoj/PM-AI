import { briefInsight } from "../utils/insightText";
import ThinkingLoader, { Spinner } from "./ThinkingLoader";
import { LOADING } from "../utils/loadingMessages";
import { useCallback, useEffect, useState } from "react";
import type { DrilldownPath, DrilldownPathEntry, DrilldownPathStep } from "../api/audit";
import { AuditApiError } from "../api/audit";
import AnalysisChart from "./AnalysisChart";
import { IconSparkle } from "./icons";
import "./DrilldownPaths.css";

interface DrilldownPathsProps {
  onFetch: () => Promise<DrilldownPath[]>;
  onSuggest: () => Promise<DrilldownPath>;
  /** `levels` = the levels to keep (see acceptDrilldownPath). */
  onAccept: (pathId: string, levels: number[]) => Promise<DrilldownPath>;
  onReject: (pathId: string) => Promise<DrilldownPath>;
  /** Jumps to the Selected Drill-downs tab (where an accepted path's levels are listed). */
  onViewSelected: () => void;
}

const errorText = (err: unknown, fallback: string) => (err instanceof AuditApiError ? err.message : fallback);

/** Complete, step-by-step drill-downs the AI designs for this analysis. Each path
 * is shown with every step's chart and insight; the PM accepts or rejects the whole path. */
export default function DrilldownPaths({ onFetch, onSuggest, onAccept, onReject, onViewSelected }: DrilldownPathsProps) {
  const [paths, setPaths] = useState<DrilldownPath[] | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    onFetch()
      .then(setPaths)
      .catch((err) => {
        setPaths([]);
        setError(errorText(err, "Couldn't load the drill-down paths."));
      });
  }, [onFetch]);

  useEffect(() => {
    load();
    // Loaded once when the tab opens for an analysis (the parent re-mounts it per entry).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const suggest = () => {
    setSuggesting(true);
    setError(null);
    onSuggest()
      .then((path) => setPaths((prev) => [path, ...(prev ?? [])]))
      .catch((err) => setError(errorText(err, "Couldn't design a drill-down path.")))
      .finally(() => setSuggesting(false));
  };

  const decide = (path: DrilldownPath, accept: boolean, levels: number[] = []) => {
    setBusyId(path.path_id);
    setError(null);
    (accept ? onAccept(path.path_id, levels) : onReject(path.path_id))
      .then((updated) =>
        setPaths((prev) =>
          (prev ?? []).flatMap((p) => (p.path_id !== updated.path_id ? [p] : updated.status === "rejected" ? [] : [updated]))
        )
      )
      .catch((err) => setError(errorText(err, accept ? "Couldn't accept this path." : "Couldn't reject this path.")))
      .finally(() => setBusyId(null));
  };

  return (
    <div className="drilldown-paths">
      <div className="drilldown-paths__head">
        <div>
          <h5 className="drilldown-paths__title">Drill-down paths</h5>
          <p className="drilldown-paths__hint">
            A complete drill-down designed from your columns and features, with a chart for every step. Accept it to add
            its levels to this analysis, or reject it.
          </p>
        </div>
        <button type="button" className="btn btn--ai btn--sm" disabled={suggesting} onClick={suggest}>
          <IconSparkle />
          {suggesting ? <><Spinner />Planning…</> : paths && paths.length > 0 ? "Suggest another" : "Suggest a path"}
        </button>
      </div>

      {suggesting && (
        <ThinkingLoader
          messages={LOADING.path}
          hint="Designing the path, then running and charting every step. This takes about 30 seconds."
          intervalMs={4500}
          showElapsed
        />
      )}
      {error && <p className="analysis-card__error">{error}</p>}
      {paths === null && !error && <ThinkingLoader variant="inline" messages={LOADING.paths} />}
      {paths !== null && paths.length === 0 && !suggesting && !error && (
        <p className="drilldown-paths__empty">No paths yet. Press "Suggest a path" to get one.</p>
      )}

      {(paths ?? []).map((path) => (
        <PathCard
          key={path.path_id}
          path={path}
          busy={busyId === path.path_id}
          onAccept={(levels) => decide(path, true, levels)}
          onReject={() => decide(path, false)}
          onViewSelected={onViewSelected}
        />
      ))}
    </div>
  );
}

function PathCard({
  path,
  busy,
  onAccept,
  onReject,
  onViewSelected,
}: {
  path: DrilldownPath;
  busy: boolean;
  onAccept: (levels: number[]) => void;
  onReject: () => void;
  onViewSelected: () => void;
}) {
  const pending = path.status === "pending";
  // Which levels to keep. Every level starts ticked.
  const allLevels = path.steps.map((st) => st.level);
  const [keep, setKeep] = useState<number[]>(allLevels);
  const kept = allLevels.filter((l) => keep.includes(l));
  const deepest = kept.length > 0 ? Math.max(...kept) : 0;
  const dropped = allLevels.filter((l) => l > deepest);
  const skipped = allLevels.filter((l) => l < deepest && !keep.includes(l));
  const toggle = (level: number) => setKeep((prev) => (prev.includes(level) ? prev.filter((l) => l !== level) : [...prev, level]));
  return (
    <section className={`drilldown-path drilldown-path--${path.status}`}>
      <header className="drilldown-path__head">
        <div className="drilldown-path__heading">
          <h6 className="drilldown-path__name">{path.name}</h6>
          <span className={`drilldown-tag drilldown-tag--${path.source === "ai" ? "ai" : "default"}`}>
            {path.source === "ai" ? "AI" : "From your data"}
          </span>
          <span className={`drilldown-path__status drilldown-path__status--${path.status}`}>
            {pending ? "Pending your decision" : "Accepted"}
          </span>
        </div>
        {path.rationale && <p className="drilldown-path__rationale">{path.rationale}</p>}
      </header>

      <ol className="drilldown-path__steps">
        {path.steps.map((step) => (
          <StepView
            key={step.level}
            step={step}
            choose={pending ? { checked: keep.includes(step.level), onToggle: () => toggle(step.level) } : undefined}
          />
        ))}
      </ol>

      {pending && path.steps.length > 1 && (
        <div className="drilldown-path__choice" role="status">
          <strong>
            Keeping {kept.length === 0 ? "no levels" : `${kept.length} of ${allLevels.length} level${allLevels.length === 1 ? "" : "s"}`}
          </strong>
          {kept.length === 0 && <span>Tick at least one level to accept this path.</span>}
          {dropped.length > 0 && kept.length > 0 && (
            <span>
              {dropped.map((l) => `Level ${l}`).join(", ")} {dropped.length === 1 ? "is" : "are"} dropped, so the path stops at level {deepest}.
            </span>
          )}
          {skipped.length > 0 && (
            <span>
              {skipped.map((l) => `Level ${l}`).join(", ")} {skipped.length === 1 ? "is" : "are"} still calculated, because the next level builds on{" "}
              {skipped.length === 1 ? "it" : "them"}, but {skipped.length === 1 ? "is" : "are"} left out of the report.
            </span>
          )}
        </div>
      )}

      {!pending && (path.skipped_levels?.length ?? 0) > 0 && (
        <p className="drilldown-path__choice">
          Skipped: {path.skipped_levels!.map((l) => `Level ${l}`).join(", ")}. Still calculated, but not in the report.
        </p>
      )}

      {!path.ready && (
        <p className="analysis-card__error">
          The results for this path are no longer in memory (the backend restarted). Reject it and suggest a new one.
        </p>
      )}

      <footer className="drilldown-path__actions">
        {pending ? (
          <>
            <button type="button" className="btn btn--secondary btn--sm" disabled={busy} onClick={onReject}>
              Reject
            </button>
            <button type="button" className="btn btn--primary btn--sm" disabled={busy || !path.ready || kept.length === 0} onClick={() => onAccept(kept)}>
              {busy ? <><Spinner />Working…</> : kept.length === allLevels.length ? "Accept this path" : `Accept ${kept.length} level${kept.length === 1 ? "" : "s"}`}
            </button>
          </>
        ) : (
          <button type="button" className="btn btn--secondary btn--sm" onClick={onViewSelected}>
            View in Selected Drill-downs
          </button>
        )}
      </footer>
    </section>
  );
}

function StepView({ step, choose }: { step: DrilldownPathStep; choose?: { checked: boolean; onToggle: () => void } }) {
  const first = step.entries[0];
  return (
    <li className={`drilldown-step${choose && !choose.checked ? " drilldown-step--off" : ""}`}>
      <div className="drilldown-step__pick">
        {choose && (
          <label className="drilldown-step__keep">
            <input type="checkbox" checked={choose.checked} onChange={choose.onToggle} aria-label={`Keep level ${step.level}`} />
            Keep
          </label>
        )}
        <span className="drilldown-step__level">Level {step.level}</span>
        <span className="drilldown-step__pick-text">
          {step.split && step.entries.length > 1 ? `${step.entries.length} charts, one for each: ` : ""}
          {first?.pick_text}
        </span>
      </div>
      <h6 className="drilldown-step__title">{step.title}</h6>
      <p className="drilldown-step__axes">
        <span>X axis: {step.columns.join(" × ")}</span> · <span>{step.measure_label}</span>
      </p>
      {step.reason && <p className="drilldown-step__reason">{step.reason}</p>}
      <div className={`drilldown-step__charts${step.entries.length > 1 ? " drilldown-step__charts--multi" : ""}`}>
        {step.entries.map((e) => (
          <ChartCard key={e.entry_id} item={e} showPath={step.entries.length > 1 || step.level > 2} />
        ))}
      </div>
    </li>
  );
}

function ChartCard({ item, showPath }: { item: DrilldownPathEntry; showPath: boolean }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const entry = item.entry;
  return (
    <div className="drilldown-chartcard">
      {showPath && item.path && <p className="drilldown-chartcard__path">{item.path}</p>}
      {entry?.run_status === "done" ? (
        <>
          {entry.interpretation && <p className="drilldown-step__insight">{briefInsight(entry.interpretation)}</p>}
          <div className="drilldown-step__toggle" role="tablist">
            {(["chart", "table"] as const).map((v) => (
              <button
                key={v}
                type="button"
                role="tab"
                aria-selected={view === v}
                className={view === v ? "drilldown-step__toggle-btn drilldown-step__toggle-btn--active" : "drilldown-step__toggle-btn"}
                onClick={() => setView(v)}
              >
                {v === "chart" ? "Chart" : "Table"}
              </button>
            ))}
          </div>
          {view === "chart" ? (
            <AnalysisChart chartSpec={entry.chart_spec} chartType={entry.chart_type} resultTable={entry.result_table} />
          ) : (
            <AnalysisChart chartSpec={null} chartType="table" resultTable={entry.result_table} maxTableRows={200} />
          )}
        </>
      ) : (
        <p className="analysis-detail__empty-drilldown">{entry?.error || "This chart has no results."}</p>
      )}
    </div>
  );
}
