"""In-memory audit session store. Single-process demo scope -- same pattern
as the prior IngestionStore: no persistence, no multi-user isolation, just a
thread-safe dict keyed by session id."""
import threading
import uuid
from dataclasses import dataclass, field

import pandas as pd

from app.schemas import AuditIssue, FeatureResult, OverallAnalysisReport, PivotFilterSpec, PivotResult


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
    # Features page: ids the user unchecked from the "Customer KPI Profile"
    # (Defined) or "Client-Requested" lists -- same exclusions-not-inclusions
    # rationale as excluded_pivot_ids below.
    excluded_feature_ids: list[str] = field(default_factory=list)
    # The AI-suggested/custom/client-requested feature specs last applied on
    # top of the uploaded Customer KPI Profile -- remembered so a caller that
    # only wants to change something else (or a fresh page load that never
    # resent the accepted list) can recompute without silently dropping
    # everything this session already added. Same role as extra_pivot_defs
    # below, for features instead of analyses.
    extra_feature_defs: list[dict] = field(default_factory=list)
    # Undo support for resolved issues that actually mutated `df` (dropped
    # columns / removed rows). `mutation_stack` is a LIFO of issue ids -- only
    # the most recent one is safe to revert without re-deriving every
    # decision after it, since row/column removal isn't commutative once a
    # later decision's mask was computed against the mutated frame.
    # "Keep as-is" resolutions never touch `df` so they're excluded and can
    # be reverted in any order.
    mutation_stack: list[str] = field(default_factory=list)
    pre_mutation_snapshots: dict[str, pd.DataFrame] = field(default_factory=dict)
    # Snapshot of `df` taken the first time features are computed, i.e. the
    # fully-audited data before any feature columns were appended. Every
    # subsequent feature computation (e.g. accepting another AI suggestion)
    # re-runs from this snapshot rather than layering on top of `df`, so
    # re-applying the same definitions twice can't double up or drift.
    pre_feature_df: pd.DataFrame | None = None
    # Last-computed pivot tables for the Analysis step (see routers/analysis.py).
    # Pivots only ever READ `df` (post-feature-engineering) -- they never
    # mutate it, so there's no snapshot/undo bookkeeping needed here.
    pivots: list[PivotResult] = field(default_factory=list)
    pivot_skipped_notes: list[str] = field(default_factory=list)
    # Analysis page: ids the user unchecked from the "Analysis Profile"
    # (Defined) list -- stored as exclusions, not inclusions, same rationale
    # as excluded_slide_keys below, so a defined analysis that only becomes
    # computable later (e.g. after a feature it needs is added) is included
    # by default rather than silently missing.
    excluded_pivot_ids: list[str] = field(default_factory=list)
    # Pivots created by clicking "Add" on a per-chart drill-down suggestion
    # (see routers/analysis.py's drill-down/apply) -- kept separately from
    # `pivots` because they're a snapshot of ONE Formula Agent answer, not
    # part of the Analysis Profile/AI-suggestion/custom-KPI definition sets
    # `_combined_pivot_defs` recomputes from scratch on every apply_pivots
    # call, so they'd otherwise be wiped out by the next recompute.
    drill_down_pivots: list[PivotResult] = field(default_factory=list)
    # The AI-suggested/custom pivot definitions last applied on top of the
    # uploaded Analysis Profile -- remembered so a caller that only wants to
    # change slicer filters (e.g. the Report page) can recompute without
    # having to resend every AI/custom pivot the Analysis page already added.
    extra_pivot_defs: list[dict] = field(default_factory=list)
    # Currently-active runtime slicer filters per pivot id (see
    # ApplyPivotsRequest.pivot_filters) -- merged (not replaced) on each
    # apply_pivots call so a caller touching one pivot's filters, or adding
    # a filter shared across several, can't silently wipe filters saved for
    # pivots it didn't mention.
    pivot_filter_state: dict[str, list[dict]] = field(default_factory=dict)
    # The ONE shared filter set for the whole downloaded report -- applied to
    # EVERY pivot at report-build time (see report_generator.build_report).
    # An "in" filter with 2+ selected values becomes a multiplier: the report
    # gets one slide per value (per pivot) instead of one slide combining
    # them. Report-time only, never affects a pivot's own computed rows/table
    # on the Analysis page.
    report_filters: list[PivotFilterSpec] = field(default_factory=list)
    # Per-pivot override of WHICH report_filters columns actually apply to
    # that pivot's slide(s) -- a pivot id absent here uses every active
    # column (the default, i.e. today's "same scope everywhere" behavior).
    # E.g. {"pivot_1": ["Country of Origin"]} means pivot_1 only respects the
    # Country of Origin filter and ignores Origin/Carrier/Product/departure-
    # range even though they're set in the shared report_filters.
    pivot_filter_scope: dict[str, list[str]] = field(default_factory=dict)
    # Per-pivot custom slide title -- a pivot id absent here uses its own
    # name (the default). Report-time only, purely cosmetic.
    report_titles: dict[str, str] = field(default_factory=dict)
    # Keys (see report_generator.slide_key) of the slides the user switched
    # OFF in the Report page's preview. Stored as exclusions, not
    # inclusions, so a slide that only appears later -- because a filter was
    # widened, or another analysis added -- is in the deck by default rather
    # than silently missing from it.
    excluded_slide_keys: list[str] = field(default_factory=list)
    # Last-computed overall analysis (see routers/analysis.py's /overall
    # endpoint) -- kept here so the report generator can reuse the exact
    # highlights/narrative the user already saw on screen instead of
    # triggering another Groq call at export time.
    overall_analysis: OverallAnalysisReport | None = None


class AuditStore:
    def __init__(self):
        self._sessions: dict[str, AuditSession] = {}
        self._lock = threading.Lock()

    def create(self, source: str, filename: str, df: pd.DataFrame, issues: list[AuditIssue], summary: str) -> AuditSession:
        session = AuditSession(
            session_id=uuid.uuid4().hex, source=source, filename=filename, df=df, issues=issues, summary=summary
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AuditSession | None:
        with self._lock:
            return self._sessions.get(session_id)


store = AuditStore()
