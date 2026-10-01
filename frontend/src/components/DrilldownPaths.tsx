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
  onAccept: (pathId: string) => Promise<DrilldownPath>;
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

  const decide = (path: DrilldownPath, accept: boolean) => {
    setBusyId(path.path_id);
    setError(null);
    (accept ? onAccept(path.path_id) : onReject(path.path_id))
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
        <button type="button" className="analysis-detail__suggest-more-btn" disabled={suggesting} onClick={suggest}>
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
          onAccept={() => decide(path, true)}
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
  onAccept: () => void;
  onReject: () => void;
  onViewSelected: () => void;
}) {
  const pending = path.status === "pending";
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
          <StepView key={step.level} step={step} />
        ))}
      </ol>

      {!path.ready && (
        <p className="analysis-card__error">
          The results for this path are no longer in memory (the backend restarted). Reject it and suggest a new one.
        </p>
      )}

      <footer className="drilldown-path__actions">
        {pending ? (
          <>
            <button type="button" className="drilldown-btn" disabled={busy} onClick={onReject}>
              Reject
            </button>
            <button type="button" className="drilldown-btn drilldown-btn--primary" disabled={busy || !path.ready} onClick={onAccept}>
              {busy ? <><Spinner />Working…</> : "Accept this path"}
            </button>
          </>
        ) : (
          <button type="button" className="drilldown-btn" onClick={onViewSelected}>
            View in Selected Drill-downs
          </button>
        )}
      </footer>
    </section>
  );
}

function StepView({ step }: { step: DrilldownPathStep }) {
  const first = step.entries[0];
  return (
    <li className="drilldown-step">
      <div className="drilldown-step__pick">
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
          {entry.interpretation && <p className="drilldown-step__insight">{entry.interpretation}</p>}
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
