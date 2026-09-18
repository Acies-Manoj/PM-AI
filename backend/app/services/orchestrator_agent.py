"""Two jobs, kept deliberately separate:

  `route_brief` -- translation only (DeepL, not Groq -- see
  translation_service.py). Used by the Upload page's language-review step:
  detect what language the brief is in and show the English translation,
  editable, before anything downstream reads it. Cheap and instant; doesn't
  touch the Groq rate-limit budget at all.

  `generate_recommendations` -- the actual Planner Agent: ONE Groq call
  reads the (already-translated) brief plus a compact catalog of what
  features/analyses already exist, and returns a full recommendation per
  distinct feature/analysis/configuration it identifies -- name,
  description, WHY, a confidence score, and (for a feature or analysis) a
  draft definition -- for the user to review, edit, approve, or reject on
  the new AI Recommendation page. Nothing is created from this alone.

Existing-vs-new is judged by the LLM against the catalog it's given, not a
deterministic token-overlap check like kpi_store.find_equivalent -- that's
fine here because a human reviews every recommendation before anything is
actually created; a wrong "Existing -- Reuse" guess just means the user
corrects it on that page, same as any other field."""
import json
import uuid

from app.schemas import (
    AnalysisDefinitionDraft,
    ClientRequirementSummary,
    ConfigurationDraft,
    DataRequirementsDraft,
    FeatureDefinitionDraft,
    OrchestratorRouteResponse,
    Recommendation,
    RecommendationResponse,
    ValidationDraft,
)
from app.services import feature_definitions_store as feature_defs_store
from app.services import kpi_store
from app.services import pivot_definitions_store as pivot_defs_store
from app.services import translation_service
from app.services.groq_client import chat_json

MAX_CATALOG_ENTRIES = 25

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent for a cold-chain \
shipment analytics tool's "AI Recommendation" page. A business user (not a \
data engineer) has described what they need in plain language. You read \
that brief plus a catalog of features/analyses that ALREADY exist, and \
produce one recommendation per DISTINCT thing the brief is asking for.

First, restate what the brief is asking for:
- "interpreted_requirement": one or two plain-English sentences restating \
what the client wants, in your own words.
- "business_objective": one sentence on the underlying business goal (why \
they want this, not just what it is).

Then, for EACH distinct feature, analysis, or configuration need in the \
brief, produce a recommendation:
- "type": "feature" (a new calculated column, nothing to chart yet), \
"analysis" (a chart/breakdown/question that can be answered ENTIRELY from \
raw columns or features already in the catalog below -- no new column \
needed), "feature_and_analysis" (the chart/breakdown needs a metric or \
dimension that is NOT a raw column and is NOT already in the catalog -- \
e.g. "rank carriers by compliance" needs a compliance metric to exist \
first), or "configuration" (a threshold/business rule setting, not a \
column or chart). Default to "feature_and_analysis" whenever you're not \
sure the needed metric/dimension already exists as a plain column -- it's \
the safer guess, since it's what makes the missing feature actually get \
created and show up on the Features page instead of the analysis silently \
having nothing to compute from.
- "status": "existing" if the catalog below already has something that \
satisfies this (cite it by name in "reason"), "create_new" if nothing in \
the catalog covers it, or "needs_clarification" if the brief is too vague \
to act on (missing a threshold, an ambiguous field reference, etc).
- "name": short, human-readable.
- "description": one sentence, plain English.
- "reason": one sentence on WHY you classified it this way -- cite the \
matching catalog entry's name if status is "existing".
- "confidence": 0-100, how sure you are this recommendation is correct.
- "feature_definition" (only if type includes "feature"): \
{"feature_name": snake_case, "formula": plain-English calculation logic, \
"input_fields": [column names it reads, best guess from the brief's own \
wording], "dimensions": [], "filters": [], "business_rules": [any \
conditions/thresholds mentioned]}.
- "analysis_definition" (only if type includes "analysis"): \
{"analysis_name": Title Case, "objective": one sentence, "metrics": [], \
"dimensions": [], "filters": [], "visualization": one of "bar", "line", \
"pie", "ranking", "scatter", "trend", "group_by": [], "sort_by": []}.
- "configuration" (only if type is "configuration"): {"required": true, \
"parameters": [threshold/setting names mentioned]}.
- "data_requirements": {"required_fields": [best-guess column names this \
needs], "missing_fields": [anything the brief implies but doesn't name]}.
- "validation": {"issues": [anything that would block creating this as-is \
-- empty list if none], "warnings": [non-blocking concerns], \
"clarifications_required": [specific questions to ask the client if status \
is needs_clarification]}.

Do not invent requirements the brief didn't ask for. If the brief is a \
single simple ask, return a single recommendation, not several.

Respond with ONLY a JSON object of this exact shape, no markdown, no \
commentary:
{"interpreted_requirement": "...", "business_objective": "...",
 "recommendations": [
   {"type": "feature|analysis|feature_and_analysis|configuration",
    "status": "existing|create_new|needs_clarification",
    "name": "...", "description": "...", "reason": "...", "confidence": 0,
    "feature_definition": {...} | null,
    "analysis_definition": {...} | null,
    "configuration": {...} | null,
    "data_requirements": {"required_fields": [...], "missing_fields": [...]},
    "validation": {"issues": [...], "warnings": [...], "clarifications_required": [...]}}
 ]}"""


def route_brief(brief: str) -> OrchestratorRouteResponse:
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("The client brief is empty -- nothing to translate.")
    translation = translation_service.translate_to_english(brief)
    was_translated = translation.detected_lang_code not in (None, "EN") and translation.text != brief
    return OrchestratorRouteResponse(
        detected_language=translation.detected_lang_name or translation.detected_lang_code if was_translated else None,
        translated_text=translation.text if was_translated else None,
    )


def _catalog_block() -> str:
    """Best-effort "what already exists" -- Defined feature/analysis
    definitions plus the durable KPI Store (everything ever created via a
    Client Brief or a custom request), name + one-line description only,
    capped so this doesn't become its own token-budget problem. No live
    session/dataframe is available yet at this point in the flow (Audit
    hasn't run), so this is catalog-level only -- real column-level
    validation still happens later, same as before this page existed."""
    lines: list[str] = []
    for store, label in ((feature_defs_store.store.definitions, "feature"), (pivot_defs_store.store.definitions, "analysis")):
        for entry in (store or [])[:MAX_CATALOG_ENTRIES]:
            name = entry.get("name") or entry.get("id", "")
            desc = entry.get("description", "")
            if name:
                lines.append(f"- [{label}] {name}: {desc}")
    for entry in kpi_store.store.all()[:MAX_CATALOG_ENTRIES]:
        name = entry.get("name", "")
        desc = entry.get("description", "")
        if name:
            lines.append(f"- [feature] {name}: {desc}")
    return "\n".join(lines) if lines else "(nothing yet -- this is the first brief for this deployment)"


def _draft(cls, payload: object):
    return cls(**payload) if isinstance(payload, dict) else None


def generate_recommendations(brief: str) -> RecommendationResponse:
    brief = (brief or "").strip()
    if not brief:
        raise ValueError("The client brief is empty -- nothing to recommend.")

    user_prompt = f"Client brief: {brief}\n\nExisting features/analyses:\n{_catalog_block()}\n\nProduce the recommendations now."
    raw = chat_json(PLANNER_SYSTEM_PROMPT, user_prompt)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("The Planner Agent returned something unusable.")

    client_requirement = ClientRequirementSummary(
        original_input=brief,
        interpreted_requirement=str(payload.get("interpreted_requirement") or "").strip(),
        business_objective=str(payload.get("business_objective") or "").strip(),
    )

    recommendations: list[Recommendation] = []
    for item in payload.get("recommendations", []) or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        rtype = item.get("type")
        if rtype not in ("feature", "analysis", "feature_and_analysis", "configuration"):
            rtype = "analysis"
        status = item.get("status")
        if status not in ("existing", "create_new", "needs_clarification"):
            status = "create_new"
        data_req = item.get("data_requirements") or {}
        validation = item.get("validation") or {}
        recommendations.append(
            Recommendation(
                id=f"rec_{uuid.uuid4().hex[:10]}",
                type=rtype,
                status=status,
                name=str(item.get("name", "")).strip(),
                description=str(item.get("description", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
                confidence=int(item.get("confidence") or 0),
                feature_definition=_draft(FeatureDefinitionDraft, item.get("feature_definition")),
                analysis_definition=_draft(AnalysisDefinitionDraft, item.get("analysis_definition")),
                configuration=_draft(ConfigurationDraft, item.get("configuration")),
                data_requirements=DataRequirementsDraft(
                    required_fields=list(data_req.get("required_fields") or []),
                    missing_fields=list(data_req.get("missing_fields") or []),
                ),
                validation=ValidationDraft(
                    issues=list(validation.get("issues") or []),
                    warnings=list(validation.get("warnings") or []),
                    clarifications_required=list(validation.get("clarifications_required") or []),
                ),
            )
        )

    return RecommendationResponse(client_requirement=client_requirement, recommendations=recommendations)
