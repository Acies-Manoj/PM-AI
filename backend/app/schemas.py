"""Pydantic response models for the data audit API."""
from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["info", "warning", "critical"]
IssueStatus = Literal["pending", "resolved"]
ReportStatus = Literal["pending_review", "reviewed"]


class IssueOption(BaseModel):
    id: str
    label: str


class OutlierChart(BaseModel):
    """Box-plot data for one numeric column -- the standard chart for an
    IQR-based outlier finding, built from the exact same quartiles/fence the
    detector used, plus the real value of every row it flagged."""
    type: Literal["boxplot"] = "boxplot"
    column: str
    min: float
    max: float
    q1: float
    median: float
    q3: float
    lower_bound: float
    upper_bound: float
    outlier_values: list[float]


class AuditIssue(BaseModel):
    id: str
    category: str
    severity: Severity
    title: str
    description: str
    affected_row_count: int
    sample: list[dict[str, Any]] = []
    requires_decision: bool
    options: list[IssueOption] = []
    # Column names the user can individually pick for a "drop_selected"
    # decision (e.g. which of these 10 empty columns to actually drop).
    # Empty for row-level issues, which stay all-or-nothing.
    selectable_items: list[str] = []
    status: IssueStatus = "pending"
    resolution: str | None = None
    # Box-plot data for the underlying numeric column, for findings where a
    # chart says more than the description (currently: statistical_outliers).
    # None for every other category.
    chart: OutlierChart | None = None
    # Agent-written, per-finding recommendation -- set by
    # audit_agent.generate_audit_analysis after the deterministic findings are
    # computed. `recommended_action` is one of this issue's own `options` ids
    # (e.g. "drop_selected", "keep"); `recommendation` is the short why. Both
    # None if the agent didn't return a usable recommendation for this finding.
    recommended_action: str | None = None
    recommendation: str | None = None


class AuditReport(BaseModel):
    session_id: str
    source: str
    filename: str
    row_count: int
    column_count: int
    columns: list[str]
    summary: str
    issues: list[AuditIssue]
    status: ReportStatus
    # Id of the one data-mutating resolution (column drop / row removal) that
    # is currently safe to revert, i.e. the top of the undo stack. "Keep
    # as-is" resolutions aren't subject to this and can always be reverted.
    revertible_issue_id: str | None = None


class ResolveRequest(BaseModel):
    issue_id: str
    decision_id: str
    selected_items: list[str] | None = None


class UpdateTripValueRequest(BaseModel):
    """A PM's inline correction to one trip's Segment Length (Days) or Mean
    Value_Temperature, from the Segment/Temperature Outlier tabs' editable
    columns. `trip_id` is a string on the wire since it's just a lookup key
    here (not computed on), matching whatever the outliers response already
    sent back for that trip."""
    serial: str
    trip_id: str
    field: Literal["segment_days", "mean_temp"]
    value: float


class FeatureResult(BaseModel):
    id: str
    name: str
    description: str
    output_column: str
    non_null_count: int
    null_count: int
    distribution: dict[str, int] = {}
    stats: dict[str, float] = {}
    generated_code: str | None = None
    # Where this feature came from (predefined / planner / custom / ai_suggested).
    source: str = "predefined"
    # The Feature Agent's own plain-English computation plan (its "Think"
    # step output) -- shown in place of a static formula string, since every
    # feature is now agent-computed rather than template-applied.
    plan: str | None = None
    # The agent's own validation verdict on its result (its "Validate" step
    # reason), so a PM can see why a computed column was trusted.
    validation_note: str | None = None


class FeatureReport(BaseModel):
    session_id: str
    row_count: int
    column_count: int
    columns: list[str]
    features: list[FeatureResult]
    skipped_notes: list[str] = []


class FeatureDefinitionsSummary(BaseModel):
    filename: str
    feature_count: int
    feature_names: list[str]


FeatureSource = Literal["predefined", "planner", "custom", "ai_suggested"]
FeatureEntryStatus = Literal["approved", "pending", "rejected"]


class FeatureRepositoryEntry(BaseModel):
    """One candidate feature in a session's repository, regardless of which
    of the four sources proposed it. `calculation_intent` is always a plain-
    English description of what to compute -- the one thing every source
    (a structured KPI-profile spec, a planner recommendation, a PM's typed
    request, an AI suggestion) can be reduced to, and the only input the
    Feature Agent's Think step actually needs."""
    id: str
    source: FeatureSource
    status: FeatureEntryStatus
    name: str
    description: str
    output_column: str
    calculation_intent: str
    input_columns: list[str] = []
    # A precise, agent-thought-through plan already attached to this entry --
    # set when the Planner pre-generated one at suggest time (feature/
    # feature_and_analysis recommendations), or when the uploaded Customer
    # KPI Profile's spec was already fully structured (not "ai_generated").
    # None means the Feature Agent hasn't thought about this one yet and
    # will run its own Think step for it at compute time. Once set here, the
    # Feature Agent will never silently replace it -- only retry writing
    # code against it.
    formula: str | None = None


class FeatureRepositoryResponse(BaseModel):
    session_id: str
    entries: list[FeatureRepositoryEntry]


class AddCustomFeatureRequest(BaseModel):
    name: str
    description: str = ""
    calculation_intent: str
    input_columns: list[str] = []


class SuggestFeatureEntriesResponse(BaseModel):
    session_id: str
    entries: list[FeatureRepositoryEntry]


class FeatureSuggestion(BaseModel):
    """One AI-proposed feature -- shaped so the frontend can echo it straight
    back as an `extra_features` entry when the user accepts it, no
    reshaping needed. Only the fields relevant to `type` are populated."""
    id: str
    name: str
    description: str
    output_column: str
    type: str
    formula: str
    summary: str
    start_column: str | None = None
    end_column: str | None = None
    unit: str | None = None
    numerator_columns: list[str] | None = None
    denominator_columns: list[str] | None = None
    source_columns: list[str] | None = None
    calculation_prompt: str | None = None
    generated_code: str | None = None


class SuggestFeaturesRequest(BaseModel):
    session_id: str


class FeatureSuggestionsResponse(BaseModel):
    session_id: str
    suggestions: list[FeatureSuggestion]


class ApplyFeaturesRequest(BaseModel):
    extra_features: list[dict[str, Any]] = []


AnalysisSource = Literal["predefined", "planner", "custom", "ai_suggested", "drilldown"]
AnalysisEntryStatus = Literal["approved", "pending", "rejected"]
AnalysisRunStatus = Literal["not_run", "done", "error"]


class AnalysisDrilldownSuggestion(BaseModel):
    id: str
    name: str
    description: str
    calculation_intent: str
    triggered: bool = False
    child_entry_id: str | None = None


class AnalysisRepositoryEntry(BaseModel):
    """One candidate analysis in a session's repository, regardless of which
    of the five sources proposed it. `calculation_intent` is always a plain-
    English description of what to aggregate -- the one thing every source
    can be reduced to, and the only input the Analysis Agent's Think step
    actually needs. The definitional fields (id..parent_id) are always
    present; the run-result fields (run_status..drilldown_suggestions) are
    only populated once the PM has clicked "Run" for this entry."""
    id: str
    source: AnalysisSource
    status: AnalysisEntryStatus
    name: str
    description: str
    calculation_intent: str
    input_columns: list[str] = []
    # A precise, agent-thought-through plan already attached to this entry --
    # set when the Planner pre-generated one at suggest time, or when the
    # uploaded Analysis Profile's spec shipped with its own formula. None
    # means the Analysis Agent hasn't thought about this one yet and will
    # run its own Think step for it at run time.
    formula: str | None = None
    # Set only for source == "drilldown": the entry id this one was spawned
    # from by a PM clicking "Explore this" on a suggested follow-up.
    parent_id: str | None = None

    run_status: AnalysisRunStatus = "not_run"
    plan_text: str | None = None
    generated_code: str | None = None
    result_table: list[dict[str, Any]] | None = None
    result_columns: list[str] | None = None
    chart_type: str | None = None
    chart_spec: dict[str, Any] | None = None
    interpretation: str | None = None
    error: str | None = None
    drilldown_suggestions: list[AnalysisDrilldownSuggestion] = []


class AnalysisRepositoryResponse(BaseModel):
    session_id: str
    entries: list[AnalysisRepositoryEntry]


class AddCustomAnalysisRequest(BaseModel):
    name: str
    description: str = ""
    calculation_intent: str
    input_columns: list[str] = []


class SuggestAnalysisEntriesResponse(BaseModel):
    session_id: str
    entries: list[AnalysisRepositoryEntry]


class AnalysisDefinitionsSummary(BaseModel):
    filename: str
    analysis_count: int
    analysis_names: list[str]


class AnalysisResult(BaseModel):
    """In-memory-only run output, held on AuditSession.analysis_results
    keyed by entry id -- mirrors FeatureResult's role for the feature
    system. Merged with the definitional AnalysisRepositoryEntry by the
    router at read time; never persisted to analysis_repository.json."""
    id: str
    run_status: AnalysisRunStatus = "done"
    plan_text: str | None = None
    generated_code: str | None = None
    result_table: list[dict[str, Any]] | None = None
    result_columns: list[str] | None = None
    chart_type: str | None = None
    chart_spec: dict[str, Any] | None = None
    interpretation: str | None = None
    error: str | None = None
    drilldown_suggestions: list[AnalysisDrilldownSuggestion] = []


class OverallHighlight(BaseModel):
    label: str
    value: str


class OverallAnalysisReport(BaseModel):
    session_id: str
    row_count: int
    highlights: list[OverallHighlight]
    narrative: str
