"""In-memory audit session store. Single-process demo scope -- same pattern
as the prior IngestionStore: no persistence, no multi-user isolation, just a
thread-safe dict keyed by session id."""
import threading
import uuid
from dataclasses import dataclass, field

import pandas as pd
from fastapi import HTTPException

from app.schemas import AnalysisResult, AuditIssue, FeatureResult, OverallAnalysisReport


@dataclass
class AuditSession:
    session_id: str
    source: str
    filename: str
    df: pd.DataFrame
    issues: list[AuditIssue] = field(default_factory=list)
    summary: str = ""
    features: list[FeatureResult] = field(default_factory=list)
    feature_skipped_notes: list[str] = field(default_factory=list)
    # Undo support for resolved issues that actually mutated `df` (dropped
    # columns / removed rows). Any of them can be reverted, in any order:
    # `audit_baseline` is the data before the FIRST change and `audit_events`
    # is every change since, in order (audit decisions and the PM's inline
    # value edits). Reverting one drops its event and REPLAYS the rest from the
    # baseline, so every later decision is re-derived as if the reverted one had
    # never happened. `mutation_stack` lists the applied decisions' issue ids,
    # oldest first. "Keep as-is" resolutions never touch `df`.
    mutation_stack: list[str] = field(default_factory=list)
    audit_baseline: pd.DataFrame | None = None
    audit_events: list[dict] = field(default_factory=list)
    # Snapshot of `df` taken the first time features are computed, i.e. the
    # fully-audited data before any feature columns were appended. Every
    # subsequent feature computation (e.g. accepting another AI suggestion)
    # re-runs from this snapshot rather than layering on top of `df`, so
    # re-applying the same definitions twice can't double up or drift.
    pre_feature_df: pd.DataFrame | None = None
    # In-memory run outputs for the Analysis Agent (see analysis_engine.py),
    # keyed by analysis_repository entry id. Populated only once a PM clicks
    # "Run" for that entry -- unlike features, analyses are computed
    # per-entry/on-demand, not as an eager batch, so there's no equivalent of
    # `features` holding every result up front. Definitions (name/
    # calculation_intent/etc) live in analysis_repository.json; this is only
    # the latest computed table/chart/interpretation for entries that have
    # actually been run.
    analysis_results: dict[str, AnalysisResult] = field(default_factory=dict)
    # Last-computed overall analysis (see routers/analysis.py's /overall
    # endpoint) -- kept here so a future report generator can reuse the exact
    # highlights/narrative the user already saw on screen instead of
    # triggering another LLM call at export time.
    overall_analysis: OverallAnalysisReport | None = None
    # Custom-feature drafts the PM is reviewing (see features/feature_designer.py),
    # keyed by draft token: the formula and the already-validated code from
    # the dry run. Saving a draft whose formula is unchanged seeds the feature
    # cache from here, so the validated code is reused instead of regenerated
    # -- the browser never sends code back.
    feature_drafts: dict[str, dict] = field(default_factory=dict)


class AuditStore:
    def __init__(self):
        self._sessions: dict[str, AuditSession] = {}
        self._lock = threading.Lock()

    def create(
        self,
        source: str,
        filename: str,
        df: pd.DataFrame,
        issues: list[AuditIssue] | None = None,
        summary: str = "",
    ) -> AuditSession:
        session = AuditSession(
            session_id=uuid.uuid4().hex,
            source=source,
            filename=filename,
            df=df,
            issues=issues if issues is not None else [],
            summary=summary,
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AuditSession | None:
        with self._lock:
            return self._sessions.get(session_id)


store = AuditStore()


def get_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session
