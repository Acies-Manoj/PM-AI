"""Pydantic response models for the data audit API."""
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    # Names of the analyses that depend on this feature -- set means the
    # feature is only here because an analysis needs it (labelled REQUIRED FOR
    # ANALYSIS); empty means the client asked for it in its own right.
    required_for_analysis: list[str] = []


class FeatureRepositoryResponse(BaseModel):
    session_id: str
    entries: list[FeatureRepositoryEntry]


class AddCustomFeatureRequest(BaseModel):
    name: str
    description: str = ""
    calculation_intent: str
    input_columns: list[str] = []
    # From a reviewed FeatureDraft: the formula the PM approved, and the
    # token of the dry run that validated it (lets the server reuse that
    # run's code -- the code itself is never sent by the browser).
    formula: str | None = None
    draft_token: str | None = None


class DraftFeatureRequest(BaseModel):
    name: str
    description: str
    input_columns: list[str] = []
    # Set when the PM edited the formula and asked to re-check it: used
    # verbatim (no Think) and only dry-run again.
    formula: str | None = None


class FeatureDraftSummary(BaseModel):
    non_null_count: int
    null_count: int
    stats: dict[str, float] = {}
    distribution: dict[str, int] = {}


class FeatureDraft(BaseModel):
    """A reviewed-before-adding custom feature (see features/feature_designer.py):
    the formula the Feature Agent wrote, plus a dry run of it on the real data."""
    draft_token: str | None = None
    name: str
    output_column: str
    formula: str
    formula_steps: list[str] = []
    columns_used: list[str] = []
    output_dtype: str | None = None
    status: Literal["ok", "failed"]
    error: str | None = None
    validation_note: str | None = None
    preview_columns: list[str] = []
    preview_rows: list[dict[str, Any]] = []
    summary: FeatureDraftSummary | None = None
    notes: list[str] = []


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
    # Set when this drilldown reuses the parent's own chart type (a rate +
    # volume pair, e.g. "combo") for visual consistency down a drill chain --
    # see analysis_agent.suggest_drilldowns. None lets the normal chart-
    # suggestion step decide when the entry is accepted.
    chart_type_hint: str | None = None
    triggered: bool = False
    child_entry_id: str | None = None


# What a drill-down level shows per group: trips, % in spec, or an aggregation of one measure column.
DrilldownMeasure = Literal["count", "pct_in_spec", "mean", "sum", "median", "max", "min"]


class DrilldownRank(BaseModel):
    """How a guided drill-down step picks its groups: the top or bottom `n`
    by `by` (trip count, or % in spec)."""
    # "all" keeps every group (up to the chart cap); "top"/"bottom" keep only n.
    mode: Literal["all", "top", "bottom"] = "all"
    n: int = Field(default=5, ge=1, le=10)
    by: Literal["count", "pct_in_spec"] = "count"


class DrilldownChain(BaseModel):
    """Marks a repository entry as one level of a guided drill-down chain.
    Level 1 is the original analysis; each confirmed drill-down adds one."""
    chain_id: str
    level: int
    dimension: str
    # Every X-axis column of this level (1-5); `dimension` is the first one.
    dimensions: list[str] = []
    metric: DrilldownMeasure = "count"
    # The numeric column aggregated when metric is mean / sum / median / max / min.
    metric_column: str | None = None
    rank: DrilldownRank = DrilldownRank()
    # Row pre-filter this level inherits from its ancestors plus the focus the
    # PM confirmed, as analysis_templates conditions.
    where: list[dict[str, Any]] = []
    focus_dimension: str | None = None
    focus_values: list[str] = []
    focus_label: str = ""
    # True when this level is one of several sibling slides created from one
    # Confirm ("one slide per selected value"); its focus stays a single value.
    split: bool = False
    # Set when an ancestor's rank/focus changed after this level was built.
    stale: bool = False


class DrilldownFocusOption(BaseModel):
    value: str
    rows: int
    child_count: int
    is_wide: bool


class DrilldownOptions(BaseModel):
    entry_id: str
    level: int
    max_level: int
    can_drill: bool
    reason: str = ""
    focus_dimension: str | None = None
    child_dimension: str | None = None
    # Every column that could be the next level (the hierarchy's next step first).
    candidate_dimensions: list[str] = []
    # Numeric columns (engineered features included) that can be averaged as the metric.
    numeric_columns: list[str] = []
    max_dimensions: int = 5
    # Root analyses: candidate focus values (e.g. products) with how many child
    # groups (origins) each has. Chain levels: their own top/bottom groups.
    focus_options: list[DrilldownFocusOption] = []
    default_focus: list[str] = []
    default_rank: DrilldownRank = DrilldownRank()
    metrics: list[str] = []


class DrilldownProposal(BaseModel):
    """One suggested next drill-down, ready to confirm as-is."""
    child_dimension: str
    # All X-axis columns of the proposal (1-3); child_dimension is the first.
    child_dimensions: list[str] = []
    metric: DrilldownMeasure = "count"
    metric_column: str | None = None
    rank: DrilldownRank = DrilldownRank()
    focus_values: list[str]
    reason: str = ""
    source: Literal["ai", "default"] = "ai"


class ConfirmDrilldownRequest(BaseModel):
    focus_values: list[str] = Field(min_length=1, max_length=30)
    child_dimension: str | None = None
    # 1-5 X-axis columns; wins over child_dimension when given.
    child_dimensions: list[str] | None = Field(default=None, max_length=5)
    metric: DrilldownMeasure = "count"
    metric_column: str | None = None
    rank: DrilldownRank = DrilldownRank()
    # One slide (sibling level) per focus value instead of one combined level.
    split: bool = False


AnalysisChartType = Literal["bar", "grouped_bar", "line", "pie", "scatter", "heatmap", "combo", "table"]
AnalysisFilterKind = Literal["categorical", "numeric_range", "date_range"]
AnalysisComputationMode = Literal["template", "code"]


class AnalysisChartAlternative(BaseModel):
    chart_type: AnalysisChartType
    reason: str = ""


class AnalysisChartRecommendation(BaseModel):
    """The chart the Analysis Designer recommended (or the PM picked from
    its alternatives) for this analysis's result table."""
    chart_type: AnalysisChartType
    reason: str = ""
    alternatives: list[AnalysisChartAlternative] = []


class AnalysisFilter(BaseModel):
    """One interactive filter declared for an analysis, plus the values /
    range the current data offers for it (see analysis_filters.options)."""
    column: str
    kind: AnalysisFilterKind
    reason: str = ""
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    start: str | None = None
    end: str | None = None


class AnalysisFilterSelection(BaseModel):
    """What the PM picked for one filter. Which fields apply depends on the
    filter's kind; unset fields mean "no restriction on that side"."""
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None
    start: str | None = None
    end: str | None = None


RequiredFeatureState = Literal["satisfied", "not_approved", "not_computed", "missing"]


class RequiredFeatureStatus(BaseModel):
    """One feature an analysis consumes, and whether it is ready to use."""
    feature_id: str | None = None
    name: str
    output_column: str
    definition: str = ""
    state: RequiredFeatureState
    satisfied: bool
    message: str = ""


class SelectRequiredFeatureRequest(BaseModel):
    feature_id: str


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
    # Set when this entry is one level of a guided drill-down chain.
    chain: DrilldownChain | None = None
    # Features this analysis requires (it consumes their columns instead of
    # recomputing them) and whether all of them are approved and computed.
    # The analysis cannot run until `dependencies_satisfied` is true.
    required_features: list[RequiredFeatureStatus] = []
    dependencies_satisfied: bool = True
    dependency_message: str | None = None
    # Customer KPIs (customer_kpi.json) this analysis reuses the definition of.
    kpi_dependencies: list[dict[str, Any]] = []
    # Deterministic template spec (analysis_templates.py) fitted by the
    # Analysis Designer -- None means the entry is computed by generated code.
    template: dict[str, Any] | None = None
    template_summary: str | None = None
    chart_recommendation: AnalysisChartRecommendation | None = None
    filters: list[AnalysisFilter] = []

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
    # Cached guided drill-down proposals (see analysis_drilldown_agent.propose)
    # -- generated once, the first time the PM opens this entry's drill-down
    # section, and reused on every later open. "Suggest with AI" appends a
    # fresh batch on top rather than replacing it. Cleared on every re-run,
    # same as drilldown_suggestions, since a changed result can change what's
    # worth drilling into.
    guided_proposals: list[DrilldownProposal] = []
    computation_mode: AnalysisComputationMode | None = None
    notes: list[str] = []
    # Set only on a filtered view (POST .../filter): the selections applied.
    # The stored run result is always the unfiltered one.
    applied_filters: dict[str, dict[str, Any]] | None = None


class AnalysisRepositoryResponse(BaseModel):
    session_id: str
    entries: list[AnalysisRepositoryEntry]


class DrilldownPathEntry(BaseModel):
    """One chart of a path step. A step that splits has one per picked value
    (e.g. one carrier chart per origin); otherwise it has a single chart."""
    entry_id: str
    # The values followed to get here, e.g. "Table Grapes › Giacovelli Srl".
    path: str = ""
    # How the values were chosen from the previous chart, e.g. "Top 3 Origin by Trips: A, B, C".
    pick_text: str = ""
    picked_values: list[str] = []
    # False when an identical, already-accepted level was reused instead of created.
    created: bool = True
    entry: AnalysisRepositoryEntry | None = None


class DrilldownPathStep(BaseModel):
    """One level of a suggested drill-down path, already run."""
    level: int
    title: str
    reason: str = ""
    columns: list[str]
    measure_label: str
    # True = a separate chart for each picked value; False = one combined chart.
    split: bool = False
    entries: list[DrilldownPathEntry]


class DrilldownPath(BaseModel):
    """A complete suggested drill-down for one analysis. Its levels are created
    as pending (hidden from Selected Drill-downs and the report) until accepted."""
    path_id: str
    root_id: str
    name: str
    rationale: str = ""
    source: Literal["ai", "default"] = "ai"
    status: Literal["pending", "accepted", "rejected"] = "pending"
    created_at: str = ""
    # False when a step's results are no longer in memory (e.g. after a backend restart).
    ready: bool = True
    steps: list[DrilldownPathStep]


class AddCustomAnalysisRequest(BaseModel):
    name: str
    description: str = ""
    calculation_intent: str
    input_columns: list[str] = []
    # Everything below comes from a reviewed AnalysisDraft and is re-validated
    # server-side on save -- the browser's copy is never trusted.
    formula: str | None = None
    template: dict[str, Any] | None = None
    chart_type: AnalysisChartType | None = None
    chart_reason: str = ""
    chart_alternatives: list[AnalysisChartAlternative] = []
    # [{"column": ..., "reason": ...}] -- the filter kind is recomputed from the data.
    filters: list[dict[str, Any]] = []


class DraftAnalysisRequest(BaseModel):
    name: str
    description: str
    # Set when the PM edited the computation logic and asked to re-check it:
    # used verbatim instead of generating new logic.
    formula: str | None = None


class AnalysisDraft(BaseModel):
    """A fully specified, not-yet-saved analysis for the PM to review in the
    Add Analysis form (see analysis_designer.draft_analysis)."""
    name: str
    description: str
    formula: str
    formula_steps: list[str] = []
    group_by: list[str] = []
    metrics: list[str] = []
    computation_mode: AnalysisComputationMode
    template: dict[str, Any] | None = None
    template_name: str | None = None
    template_summary: str | None = None
    template_reason: str = ""
    chart: AnalysisChartRecommendation
    filters: list[AnalysisFilter] = []
    preview_columns: list[str] = []
    preview_rows: list[dict[str, Any]] = []
    preview_chart_spec: dict[str, Any] | None = None
    notes: list[str] = []


class FilterAnalysisRequest(BaseModel):
    filters: dict[str, AnalysisFilterSelection] = {}


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
    guided_proposals: list[DrilldownProposal] = []
    computation_mode: AnalysisComputationMode | None = None
    notes: list[str] = []
    # The chart picked from the computation logic before this run computed
    # anything -- set for entries that didn't already carry the PM's choice.
    chart_recommendation: AnalysisChartRecommendation | None = None
    # The analysis_templates spec this run was computed with (any source), or
    # None when it used generated code.
    template: dict[str, Any] | None = None
    # Validated filter-column defs ({"column","kind","reason"}) discovered
    # alongside the chart -- for every source now, not just a hand-drafted
    # custom entry. Plain dicts, not AnalysisFilter: the values/min/max the
    # UI needs are always computed fresh from the current data at read time
    # (see routers/analysis.py's _merge_entry), never stored here.
    filters: list[dict[str, Any]] | None = None


class OverallHighlight(BaseModel):
    label: str
    value: str


class OverallAnalysisReport(BaseModel):
    session_id: str
    row_count: int
    highlights: list[OverallHighlight]
    narrative: str


class ReportSummaryResponse(BaseModel):
    """The Report page's own closing-slide bullet points -- synthesized from
    the included analyses' interpretations, distinct from
    OverallAnalysisReport's KPI-highlights narrative (see
    final_summary_agent.py). Bullets, not one prose narrative, to match the
    reference deck's own bullet-point closing slide."""

    session_id: str
    bullets: list[str]


class LanguageOption(BaseModel):
    code: str
    name: str


class SupportedLanguagesResponse(BaseModel):
    languages: list[LanguageOption]


class EntryTranslation(BaseModel):
    """One analysis entry's name (its slide heading) and interpretation
    (its caption), translated into the Report page's picked language --
    mirrors exactly what report_generator.build_report writes onto that
    entry's slide, so the on-screen preview matches the .pptx download."""

    name: str
    interpretation: str | None = None


class ReportTranslationsResponse(BaseModel):
    translations: dict[str, EntryTranslation]
