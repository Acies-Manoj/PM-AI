"""
Deterministic dataset-wide summary. Rolls up the already-computed feature
stats/distributions and analysis-agent results into a short list of
headline highlights -- no LLM involved, same rule as feature_engineering.py:
the numbers a PM puts in a report need to be reliable, not a
plausible-sounding guess. overall_analysis_agent.py turns this list into
prose; it never adds a number that isn't already here.
"""
from app.schemas import FeatureResult, OverallHighlight

MAX_FEATURE_HIGHLIGHTS = 6


def _feature_highlights(features: list[FeatureResult]) -> list[OverallHighlight]:
    highlights: list[OverallHighlight] = []
    for f in features:
        if f.stats:
            mean = f.stats.get("mean")
            if mean is not None:
                highlights.append(OverallHighlight(label=f"Avg {f.name}", value=str(mean)))
        elif f.distribution:
            top_value, top_count = next(iter(f.distribution.items()), (None, None))
            if top_value is None:
                continue
            total = f.non_null_count or 1
            share = (top_count / total) * 100
            highlights.append(OverallHighlight(
                label=f"Most common {f.name}", value=f"{top_value} ({top_count} rows, {share:.0f}%)"
            ))
    return highlights[:MAX_FEATURE_HIGHLIGHTS]


def _analysis_highlights(entries: list[dict]) -> list[OverallHighlight]:
    """`entries` are merged analysis_repository entries (dicts shaped like
    AnalysisRepositoryEntry) filtered to run_status == "done" by the
    caller. The first result_column is treated as the group label(s), and
    the first NUMERIC result_column as the metric to find the best/worst
    row of -- same best/worst-row logic the old pivot version used against
    PivotResult.rows/group_by/metric_labels, just against whatever shape
    the Analysis Agent's own table came out as."""
    highlights: list[OverallHighlight] = []
    for e in entries:
        table = e.get("result_table")
        columns = e.get("result_columns")
        if not table or not columns:
            continue

        metric = next((c for c in columns if any(isinstance(r.get(c), (int, float)) for r in table)), None)
        if metric is None:
            continue
        label_columns = [c for c in columns if c != metric]
        scored = [r for r in table if isinstance(r.get(metric), (int, float))]
        if not scored:
            continue

        best = max(scored, key=lambda r: r[metric])
        best_label = " / ".join(str(best.get(c)) for c in label_columns) or str(best.get(metric))
        highlights.append(OverallHighlight(
            label=f"Highest {metric} ({e['name']})", value=f"{best_label}: {best[metric]}"
        ))

        if len(scored) > 1:
            worst = min(scored, key=lambda r: r[metric])
            if worst is not best:
                worst_label = " / ".join(str(worst.get(c)) for c in label_columns) or str(worst.get(metric))
                highlights.append(OverallHighlight(
                    label=f"Lowest {metric} ({e['name']})", value=f"{worst_label}: {worst[metric]}"
                ))
    return highlights


def build_highlights(row_count: int, features: list[FeatureResult], analysis_entries: list[dict]) -> list[OverallHighlight]:
    highlights = [OverallHighlight(label="Total Rows Analyzed", value=f"{row_count:,}")]
    highlights += _feature_highlights(features)
    highlights += _analysis_highlights(analysis_entries)
    return highlights
