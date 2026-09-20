"""Analysis engine, driven entirely by the Analysis Agent (see
analysis_agent.py). Every repository entry -- predefined, planner-approved,
custom, AI-suggested, or a PM-triggered drilldown -- goes through the same
think -> write code -> execute pipeline, regardless of how it was authored.

Every analysis is computed against the dataframe passed in by the caller,
which is always the CURRENT audited (and feature-engineered) session
dataframe -- this module never reads the original uploaded file.
"""
import pandas as pd

from app.services import ai_code_executor, analysis_agent, analysis_cache


def run_analysis(session_id: str, entry: dict, df: pd.DataFrame) -> analysis_agent.AnalysisComputation:
    """Mirrors feature_engineering._compute_with_cache: replays a previously
    computed plan+code for this entry if one's cached, so re-running an
    analysis that already worked doesn't re-risk Think/Code sampling
    variance. A cache-replay that itself fails (e.g. a column it used got
    dropped since) invalidates the cache and falls through to a fresh
    computation.

    Chart-type/chart-spec/interpretation/drilldowns are NOT cached -- they
    always run fresh against whatever table this call produced, since a
    "Run" click is expected, on-demand cost, not batch overhead the cache
    exists to avoid."""
    cached = analysis_cache.get(session_id, entry)
    if cached:
        try:
            table = ai_code_executor.run_generated_table_code(cached["generated_code"], df)
            plausible, reason = analysis_agent.is_plausible_table(table)
            if plausible:
                plan = {"plan": cached["plan_text"]}
                columns_block = analysis_agent.describe_columns(df)
                return analysis_agent.finish_computation(entry, plan, cached["generated_code"], table, columns_block)
            raise ValueError(reason)
        except Exception:
            analysis_cache.invalidate(session_id, entry["id"])

    computation = analysis_agent.compute_analysis(entry, df)
    if computation.generated_code:
        analysis_cache.set(session_id, entry, computation.plan_text, computation.generated_code)
    return computation
