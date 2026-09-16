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


class ExcludeTripRequest(BaseModel):
    """The Audit page's Outlier Screening tab "Exclude from analysis" action
    -- drops every row for this (Serial Number, Trip ID) from the audit
    session's dataframe, recorded as an already-resolved AuditIssue (category
    "outlier_trip::<serial>::<trip_id>") so it shows up in Overall Checks/
    Summary and can be reverted the same way as any other finding."""
    serial: str
    trip_id: int


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


class FeatureReport(BaseModel):
    session_id: str
    row_count: int
    column_count: int
    columns: list[str]
    features: list[FeatureResult]
    skipped_notes: list[str] = []
    # Ids the user unchecked from the "Customer KPI Profile" (Defined) or
    # "Client-Requested" sections on the Features page.
    excluded_feature_ids: list[str] = []


class FeatureDefinitionsSummary(BaseModel):
    filename: str
    feature_count: int
    feature_names: list[str]


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
    # None (the default) leaves session.extra_feature_defs as it was -- a
    # caller that only wants to change something else (excluded_feature_ids,
    # or nothing at all -- a bare recompute) doesn't have to resend the full
    # accepted[] set to avoid dropping it. An explicit list (even []) replaces
    # it wholesale, same "send the whole current selection" convention as
    # ApplyPivotsRequest.extra_pivots/pivot_filters.
    extra_features: list[dict[str, Any]] | None = None
    # None (the default) leaves the exclusion set as it was; an explicit list
    # replaces it wholesale -- same convention as above.
    excluded_feature_ids: list[str] | None = None


AggType = Literal["sum", "mean", "count", "min", "max", "median", "distinct_count", "pct_of_total"]


class PivotMetricSpec(BaseModel):
    column: str
    agg: AggType
    output_label: str


class PivotFilterSpec(BaseModel):
    column: str
    op: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in"]
    value: Any


class PivotSortSpec(BaseModel):
    metric: str
    direction: Literal["asc", "desc"] = "desc"


class PivotResult(BaseModel):
    id: str
    name: str
    description: str
    group_by: list[str]
    metric_labels: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    # Columns this pivot can be sliced by at runtime, and the distinct
    # values available for each -- lets the frontend render a slicer/filter
    # picker per column instead of baking one fixed value into the JSON spec.
    filterable_columns: list[str] = []
    filter_options: dict[str, list[str]] = {}
    # Deduplicated real combinations of the filterable columns (from the full,
    # unfiltered session data) -- lets the frontend narrow one slicer's
    # options to what actually co-occurs with the OTHER slicers' current
    # selections (e.g. picking Italy narrows Carrier to Italy's carriers)
    # without a round-trip to the backend.
    filter_combinations: list[dict[str, str]] = []


class SetReportFiltersRequest(BaseModel):
    filters: list[PivotFilterSpec] = []


class ReportFiltersResponse(BaseModel):
    session_id: str
    filters: list[PivotFilterSpec]


class SetReportFilterScopeRequest(BaseModel):
    pivot_id: str
    # None clears the override (back to "every active filter column applies,
    # the default"). An explicit list -- even [] -- means "only these columns
    # apply to this pivot; every other active column is ignored for it."
    columns: list[str] | None = None


class ReportFilterScopeResponse(BaseModel):
    session_id: str
    # pivot id -> the columns that apply to it. A pivot id absent here uses
    # the default (every active report_filters column applies to it).
    scope: dict[str, list[str]]


class SetReportTitleRequest(BaseModel):
    pivot_id: str
    # None clears the override (back to the pivot's own name).
    title: str | None = None


class ReportTitlesResponse(BaseModel):
    session_id: str
    # pivot id -> its custom slide title. A pivot id absent here uses its
    # own name (the default).
    titles: dict[str, str]


class PivotReport(BaseModel):
    session_id: str
    row_count: int
    column_count: int
    columns: list[str]
    pivots: list[PivotResult]
    skipped_notes: list[str] = []
    # Currently-active runtime slicer filters per pivot id (same shape as
    # ApplyPivotsRequest.pivot_filters) -- lets a caller that didn't set
    # these itself (e.g. the Report page, on first load) know what's already
    # applied, so it can pre-populate its filter UI and merge in new filters
    # without clobbering the ones already saved.
    pivot_filters: dict[str, list[dict[str, Any]]] = {}
    # Ids the user unchecked from the "Analysis Profile" (Defined) list on
    # the Analysis page -- lets the frontend restore checkbox state on
    # reload without tracking it separately from the backend's own record.
    excluded_pivot_ids: list[str] = []


class PivotDefinitionsSummary(BaseModel):
    filename: str
    pivot_count: int
    pivot_names: list[str]


class ReportTemplateSummary(BaseModel):
    """`filename` is None when no template has been uploaded -- report
    generation then falls back to the built-in layout."""
    filename: str | None


class PivotSuggestion(BaseModel):
    """One AI-proposed pivot table -- shaped so the frontend can echo it
    straight back as an `extra_pivots` entry when the user accepts it."""
    id: str
    name: str
    description: str
    group_by: list[str]
    metrics: list[PivotMetricSpec]
    filters: list[PivotFilterSpec] = []
    sort_by: PivotSortSpec | None = None
    top_n: int | None = None


class SuggestPivotsRequest(BaseModel):
    session_id: str


class SuggestPivotsResponse(BaseModel):
    session_id: str
    suggestions: list[PivotSuggestion]


class ApplyPivotsRequest(BaseModel):
    # None means "leave whatever AI/custom pivots were last applied for this
    # session alone" -- a caller that only wants to change slicer filters
    # (e.g. the Report page) can omit this instead of resending the Analysis
    # page's full accepted list. An explicit [] means "no extra pivots".
    extra_pivots: list[dict[str, Any]] | None = None
    # Runtime slicer selections, keyed by pivot id -- each value is a list of
    # filter dicts (same shape as a JSON-defined filter, typically {"column":
    # ..., "op": "in", "value": [...]}) applied IN ADDITION to that pivot's
    # own declared filters, without needing to edit/re-upload the profile.
    pivot_filters: dict[str, list[dict[str, Any]]] = {}


class SetPivotSelectionRequest(BaseModel):
    """Analysis page's "Defined" checkboxes -- replaces the excluded-id set
    wholesale, same "always send the whole current selection" convention as
    SetReportSlidesRequest below."""
    excluded_ids: list[str]


class PivotDrillDownRequest(BaseModel):
    suggestion: str


class OverallHighlight(BaseModel):
    label: str
    value: str


class OverallAnalysisReport(BaseModel):
    session_id: str
    row_count: int
    highlights: list[OverallHighlight]
    narrative: str


# -- Saved custom definitions (the persistent library) ------------------------
# See services/custom_library_store.py. `scope` is the only thing separating
# the two save options the Add-a-KPI / Add-an-Analysis forms offer.

SavedScope = Literal["regular", "suggested"]


class SavedDefinition(BaseModel):
    """One user-created KPI or analysis, as kept on disk. `spec` is the
    definition dict verbatim -- the same shape the frontend already sends as
    an `extra_features` / `extra_pivots` entry, so it can be echoed straight
    back into either path with no reshaping."""
    id: str
    name: str
    description: str = ""
    scope: SavedScope
    saved_at: str
    spec: dict[str, Any]


class SavedDefinitionsResponse(BaseModel):
    items: list[SavedDefinition]


class SaveDefinitionRequest(BaseModel):
    scope: SavedScope
    definition: dict[str, Any]


class SetSavedScopeRequest(BaseModel):
    scope: SavedScope


# -- Report translation -------------------------------------------------------


class LanguageOption(BaseModel):
    code: str
    name: str


class SupportedLanguagesResponse(BaseModel):
    # "en" (English) is always first -- the report's default, no-translation
    # language -- followed by whatever translation_service.SUPPORTED_LANGUAGES
    # currently lists.
    languages: list[LanguageOption]
    # False when translation can't actually run (no DEEPL_API_KEY, or the
    # `deepl` package isn't installed in the environment serving this app).
    # The languages are still listed -- picking one just wouldn't change
    # anything -- so the Report page says so rather than letting the picker
    # look broken.
    available: bool = True


# -- Report preview / slide selection -----------------------------------------


class ReportSlide(BaseModel):
    """One slide the downloaded deck WOULD contain, described in enough
    detail for the Report page to draw a faithful preview of it. Produced by
    report_generator.plan_report -- the exact same plan build_report renders
    into PPTX, so the preview can't drift from the file."""
    # Stable across re-plans (it's derived from the pivot id + the filter
    # combo's own label, not a position), so a slide stays deselected while
    # the user keeps editing filters around it.
    key: str
    kind: Literal["cover", "chart", "summary"]
    title: str
    subtitle: str | None = None
    # Only set on a "chart" slide. Shape depends on chart["type"]:
    #   grouped_bar -- groups, y_axis_title, category_axis_title
    #   combo       -- categories, category_axis_title, bar_name/bar_values,
    #                  line_name/line_values
    #   simple      -- categories, category_axis_title, metric_label, values,
    #                  is_trend
    chart: dict[str, Any] | None = None
    # Only set on the "summary" slide.
    narrative: str | None = None
    bullets: list[str] = []
    # Which pivot this slide came from, and which filter-combo of it, so the
    # Report page can group a pivot's slides under its own title/scope
    # controls. Both None for the cover and summary slides.
    pivot_id: str | None = None
    combo_label: str | None = None
    # False when the user has deselected this slide (see /report-slides) --
    # it is then skipped at download time.
    included: bool = True


class ReportPreviewResponse(BaseModel):
    session_id: str
    language: str
    slides: list[ReportSlide]


class SetReportSlidesRequest(BaseModel):
    # The keys of the slides to LEAVE OUT. Sent (and stored) as exclusions
    # rather than inclusions so a slide that appears later -- because the
    # user widened a filter, or added an analysis -- is included by default
    # instead of silently missing from the deck.
    excluded_keys: list[str] = []


class ReportSlidesResponse(BaseModel):
    session_id: str
    excluded_keys: list[str]


# -- Raw Data Explorer (pre-audit step) --------------------------------------
# Aggregated trip summary + up to two "data point matrix" files (temperature
# / light, one column per trip, raw sequential readings). A selected trip's
# own start timestamp (from the aggregated file) anchors point #1; later
# points are spaced by `interval_minutes`. See raw_data_matrix.py.


class RawDataTrip(BaseModel):
    serial: str
    trip_id: int
    label: str
    # ISO 8601 -- kept as a plain string like the rest of this API's row data
    # (see AuditReport.sample / DataPreview.rows, which go through
    # df.to_json rather than a typed datetime field).
    start_time: str


class RawDataUploadResponse(BaseModel):
    session_id: str
    interval_minutes: int
    trips: list[RawDataTrip]
    temperature_uploaded: bool
    temperature_matched: int | None = None
    temperature_total: int | None = None
    light_uploaded: bool
    light_matched: int | None = None
    light_total: int | None = None


class RawDataSeriesPoint(BaseModel):
    t: str
    v: float | None


class RawDataChannel(BaseModel):
    unit: str
    points: list[RawDataSeriesPoint]


class RawDataTripSeriesResponse(BaseModel):
    session_id: str
    serial: str
    trip_id: int
    start_time: str
    interval_minutes: int
    temperature: RawDataChannel | None = None
    light: RawDataChannel | None = None


# -- Step 1 screening: outlier/threshold flags over the raw-data upload ------
# See services/anomaly_detection.py -- run against the same aggregated table
# a Raw Data Explorer session already holds.


class RawDataFlaggedTrip(BaseModel):
    serial: str
    trip_id: int
    label: str
    flag_count: int
    flags: list[str]
    duration_outlier: bool
    mean_temp: float | None = None
    product: str | None = None


class RawDataTripMeanTemp(BaseModel):
    """One point for the Step 1 mean-temperature-by-product chart -- every
    trip, not just the flagged ones, so the chart can show where the
    flagged points sit relative to the rest of their product's trips."""
    serial: str
    trip_id: int
    label: str
    start_time: str
    product: str | None = None
    mean_temp: float | None = None
    limit_low: float | None = None
    limit_ideal: float | None = None
    limit_high: float | None = None
    flagged: bool


class RawDataFlagsResponse(BaseModel):
    session_id: str
    total_trips: int
    all_trips: list[RawDataTripMeanTemp] = []
    flagged_trips: list[RawDataFlaggedTrip]


class RcaHypothesisModel(BaseModel):
    hypothesis: str
    score: int
    confidence: str
    rationale: list[str]


class RawDataRcaResponse(BaseModel):
    session_id: str
    serial: str
    trip_id: int
    hypotheses: list[RcaHypothesisModel]


# -- Orchestrator Agent -------------------------------------------------------
# Reads the free-text client brief and decides which of the two entry points
# it belongs to -- see services/orchestrator_agent.py.


class OrchestratorRouteRequest(BaseModel):
    brief: str


class OrchestratorRouteResponse(BaseModel):
    path: Literal["feature_request", "analysis_question"]
    cleaned_request: str
    rationale: str
    # Both None when the brief was already English (or DeepL couldn't be
    # reached) -- nothing to show the user in that case.
    detected_language: str | None = None
    translated_text: str | None = None


# -- Step 2: user-requested feature (plain language) -------------------------
# See services/feature_request_agent.py. Response is a FeatureSuggestion so
# the frontend can accept/apply/save it exactly like an AI-suggested one.


class RequestFeatureRequest(BaseModel):
    session_id: str
    request_text: str


# -- Client Brief -> multi-feature creation pipeline (Feature Engineering) ---
# See services/feature_orchestrator.py (extraction + orchestration) and
# services/kpi_store.py (the durable provenance registry). Distinct from the
# single free-text "User Requests a Feature" flow above -- a brief can name
# several features at once, and the AI may add a few more of its own.

FeatureSource = Literal["CLIENT_REQUESTED", "AI_SUGGESTED", "USER_REQUESTED"]


class ClientRequirement(BaseModel):
    """One feature extracted from a natural-language Client Brief (or one
    the AI additionally proposed to help satisfy it) -- structured JSON per
    feature_orchestrator.py's extraction prompt. Not yet a computable spec;
    that's what the Feature Agent (feature_request_agent.py) drafts next."""
    feature_name: str
    description: str
    type: str = "derived_feature"
    source: FeatureSource


class ClientBriefFeatureRequest(BaseModel):
    session_id: str
    brief: str


class KpiFeatureOutcome(BaseModel):
    """What happened to one ClientRequirement: reused an existing KPI Store
    entry, created a new one, or -- after retrying across every dependency
    pass -- failed, with why."""
    feature_name: str
    description: str
    source: FeatureSource
    status: Literal["reused", "created", "failed"]
    kpi_id: str | None = None
    output_column: str | None = None
    error: str | None = None


class ClientBriefFeatureResponse(BaseModel):
    session_id: str
    client_requirements: list[ClientRequirement]
    ai_suggested: list[ClientRequirement]
    outcomes: list[KpiFeatureOutcome]
    accepted_specs: list[FeatureSuggestion]
    feature_report: FeatureReport


class KpiStoreEntry(BaseModel):
    """One entry in kpi_store.json, as returned by the transparency endpoint
    (GET /api/features/kpi-store) -- the durable registry's own record
    shape, kept separate from FeatureSuggestion (the ephemeral, per-request
    draft shape) since it carries provenance/version metadata a draft
    doesn't have yet."""
    id: str
    name: str
    description: str
    source: FeatureSource
    output_column: str
    type: str
    source_columns: list[str] = []
    formula: str = ""
    python_code: str | None = None
    data_type: str
    dependencies: list[str] = []
    version: int
    created_at: str
    updated_at: str
    spec: dict[str, Any]


class KpiStoreListResponse(BaseModel):
    features: list[KpiStoreEntry]


# -- Step 3: chart interpretation, drill-down suggestions, ask-a-question ----
# See services/chart_interpretation_agent.py, drill_down_agent.py,
# formula_agent.py.


class ChartInterpretationResponse(BaseModel):
    session_id: str
    pivot_id: str
    interpretation: str


class DrillDownSuggestionsResponse(BaseModel):
    session_id: str
    suggestions: list[str]


class AskQuestionRequest(BaseModel):
    session_id: str
    question: str


class FormulaAnswerResponse(BaseModel):
    session_id: str
    question: str
    mode: Literal["template", "custom_python"]
    pivot: PivotResult | None = None
    table: list[dict[str, Any]] | None = None
    value: str | None = None
    explanation: str


# -- Client Brief -> Step 3's AI-Assisted Analysis, run in one shot ----------
# See routers/analysis.py's /client-brief. Every piece here is an existing
# agent (pivot_suggester, overall_analysis(_agent), chart_interpretation_
# agent, drill_down_agent, formula_agent) -- this just sequences them for a
# brief instead of requiring a click per step.


class AnalysisRequirement(BaseModel):
    """One specific analysis/chart/breakdown the client explicitly asked for
    in a natural-language Client Brief -- structured JSON per
    analysis_orchestrator.py's extraction prompt. Not yet computed; that's
    what the Formula Agent (formula_agent.answer_question) resolves next --
    a pivot template first, sandboxed Python otherwise -- the SAME engine
    "Request an Analysis"/a chart's own drill-down "Add" already run
    through, so an explicit client ask is guaranteed the same treatment as
    every other analysis in this app, not a second execution path."""
    analysis_name: str
    description: str


class AnalysisRequirementOutcome(BaseModel):
    """What happened to one AnalysisRequirement: reused an already-active
    pivot with the same group-by/metric shape, computed and added a new
    one, or failed, with why."""
    analysis_name: str
    description: str
    status: Literal["reused", "created", "failed"]
    pivot_id: str | None = None
    error: str | None = None


class AnalysisBriefRequest(BaseModel):
    session_id: str
    brief: str


class AnalysisBriefResponse(BaseModel):
    session_id: str
    overall: OverallAnalysisReport | None = None
    suggested_pivots: list[PivotSuggestion] = []
    applied_pivot_ids: list[str] = []
    interpretations: dict[str, str] = {}
    formula_answer: FormulaAnswerResponse | None = None
    # Every analysis the brief explicitly asked for -- one outcome per
    # requirement, always attempted regardless of what Chart Suggestion
    # (suggested_pivots, above) came up with on its own.
    client_requirements: list[AnalysisRequirement] = []
    outcomes: list[AnalysisRequirementOutcome] = []
    pivot_report: PivotReport
    # Soft-fail notes -- one agent being unavailable (Groq down/rate-limited)
    # doesn't abort the rest of the pipeline; whatever succeeded still comes
    # back, and this says what didn't.
    errors: list[str] = []


# -- Analysis Store ------------------------------------------------------------
# See services/analysis_store.py -- everything Step 3's agents have already
# produced for a session, kept for reuse.


class AnalysisStoreEntry(BaseModel):
    id: str
    kind: Literal["summary", "chart_interpretation", "drill_down", "formula_result"]
    label: str
    content: Any
    created_at: str


class AnalysisStoreResponse(BaseModel):
    session_id: str
    entries: list[AnalysisStoreEntry]


# -- Audit page: Segment Days (per-trip transit-duration outliers) ---------
# See services/anomaly_detection.py's compute_lane_duration_outliers. Each
# row here is one trip whose own lane fence flagged it, not the fence/rule
# numbers themselves -- those still ride along per row for reference.


class SegmentDaysRow(BaseModel):
    serial: str | None
    trip_id: int | None
    origin: str
    destination: str
    segment_days: float
    lower_fence_days: float | None
    upper_fence_days: float | None
    status: str


class SegmentDaysResponse(BaseModel):
    session_id: str
    total_trips: int
    rows: list[SegmentDaysRow]
