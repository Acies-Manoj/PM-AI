"""Pydantic response models for all API stages of the pipeline."""
from typing import Any, Literal

from pydantic import BaseModel

Severity = Literal["info", "warning", "critical"]
IssueStatus = Literal["pending", "resolved"]
ReportStatus = Literal["pending_review", "reviewed"]


class IssueOption(BaseModel):
    id: str
    label: str


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


class ResolveRequest(BaseModel):
    issue_id: str
    decision_id: str
    selected_items: list[str] | None = None


class FeatureResult(BaseModel):
    id: str
    name: str
    description: str
    output_column: str
    non_null_count: int
    null_count: int
    distribution: dict[str, int] = {}
    stats: dict[str, float] = {}


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


# ── Phase 1: Orchestrator ────────────────────────────────────────────────────

class BriefAnalysis(BaseModel):
    key_questions: list[str]
    pipeline_description: str


# ── Phase 2: Screening ───────────────────────────────────────────────────────

class FlaggedTrip(BaseModel):
    trip_id: str
    product: str
    mean_temp: float
    temp_limit: float | None = None
    exceedance: float | None = None
    segment_days_above: int = 0
    origin: str | None = None
    destination: str | None = None


class ScreeningReport(BaseModel):
    session_id: str
    total_trips: int
    flagged_count: int
    flagged_trips: list[FlaggedTrip]
    product_means: dict[str, float]
    screening_notes: list[str]


class TripTrace(BaseModel):
    trip_id: str
    timestamps: list[str]
    temperatures: list[float | None]
    light_events: list[str]


class ScreeningRequest(BaseModel):
    session_id: str
    rawdata_session_id: str | None = None
    custom_thresholds: dict[str, float] | None = None


# ── Phase 3: Feature Agent ───────────────────────────────────────────────────

class FeatureSuggestion(BaseModel):
    name: str
    description: str
    rationale: str
    feature_type: str


class AIFeatureSuggestRequest(BaseModel):
    session_id: str
    brief: str = ""


class AIFeatureGenerateRequest(BaseModel):
    session_id: str
    user_request: str


class AIFeatureCodeResult(BaseModel):
    name: str
    description: str
    output_column: str
    code: str
    success: bool = False
    sample_values: list[Any] = []
    error: str | None = None


# ── Phase 4: Analysis ────────────────────────────────────────────────────────

class AnalysisStep(BaseModel):
    step_number: int
    step_type: str
    content: str
    chart_type: str | None = None
    drill_down_suggestions: list[str] = []
    formula_code: str | None = None
    compute_result: dict[str, Any] | None = None


class StartAnalysisRequest(BaseModel):
    session_id: str
    brief: str


class NextStepRequest(BaseModel):
    user_ask: str | None = None


class ComputeRequest(BaseModel):
    ask: str


class AnalysisState(BaseModel):
    analysis_id: str
    session_id: str
    brief: str
    steps: list[AnalysisStep]
    status: str


# ── Phase 5: Report ──────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    analysis_id: str
    format: Literal["html", "markdown"] = "html"


class ReportOutput(BaseModel):
    report_id: str
    analysis_id: str
    title: str
    format: str
    content: str
