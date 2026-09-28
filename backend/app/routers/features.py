import json
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    AddCustomFeatureRequest,
    DraftFeatureRequest,
    FeatureDefinitionsSummary,
    FeatureDraft,
    FeatureRepositoryEntry,
    FeatureRepositoryResponse,
    SuggestFeatureEntriesResponse,
)
from app.services.audit.audit_store import store as audit_store
from app.services.features import feature_definitions_store as defs_store
from app.services.features import feature_designer, feature_repository, feature_suggester

router = APIRouter(prefix="/api/features", tags=["features"])
logger = logging.getLogger(__name__)


@router.post("/definitions", response_model=FeatureDefinitionsSummary)
async def upload_feature_definitions(file: UploadFile = File(...)) -> FeatureDefinitionsSummary:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"Not valid JSON: {exc}") from exc

    try:
        features = defs_store.validate(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    filename = file.filename or "customer_kpi_profile.json"
    defs_store.store.set(filename, features)

    return FeatureDefinitionsSummary(
        filename=filename,
        feature_count=len(features),
        feature_names=[f["name"] for f in features],
    )


@router.get("/definitions", response_model=FeatureDefinitionsSummary)
def get_feature_definitions() -> FeatureDefinitionsSummary:
    if defs_store.store.definitions is None:
        raise HTTPException(status_code=404, detail="No Customer KPI Profile has been uploaded yet.")
    return FeatureDefinitionsSummary(
        filename=defs_store.store.filename,
        feature_count=len(defs_store.store.definitions),
        feature_names=[f["name"] for f in defs_store.store.definitions],
    )


def _get_session_or_404(session_id: str):
    session = audit_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session


@router.get("/repository/{session_id}", response_model=FeatureRepositoryResponse)
def get_repository(session_id: str) -> FeatureRepositoryResponse:
    _get_session_or_404(session_id)
    entries = feature_repository.get_repository(session_id)
    return FeatureRepositoryResponse(session_id=session_id, entries=[FeatureRepositoryEntry(**e) for e in entries])


@router.post("/repository/{session_id}/custom", response_model=FeatureRepositoryEntry)
def add_custom_feature(session_id: str, body: AddCustomFeatureRequest) -> FeatureRepositoryEntry:
    session = _get_session_or_404(session_id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Give the KPI a name.")
    if not body.calculation_intent.strip():
        raise HTTPException(status_code=422, detail="Describe what this feature should calculate.")
    formula = body.formula.strip() if body.formula and body.formula.strip() else None
    entry = feature_repository.add_custom_entry(
        session_id, body.name.strip(), body.description.strip(), body.calculation_intent.strip(), body.input_columns,
        formula=formula,
    )
    if formula:
        feature_designer.seed_cache_from_draft(session_id, session.feature_drafts, body.draft_token, entry)
    return FeatureRepositoryEntry(**entry)


@router.post("/repository/{session_id}/draft", response_model=FeatureDraft)
def draft_custom_feature(session_id: str, body: DraftFeatureRequest) -> FeatureDraft:
    """Human-in-the-loop step for a user-requested feature: the formula the
    Feature Agent would use, dry-run on the real data. Nothing is saved --
    the PM reviews/edits it and confirms via /custom."""
    session = _get_session_or_404(session_id)
    if not body.name.strip():
        raise HTTPException(status_code=422, detail="Give the KPI a name.")
    if not body.description.strip():
        raise HTTPException(status_code=422, detail="Describe what this feature should calculate.")
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df
    try:
        draft = feature_designer.draft_feature(
            session.feature_drafts, body.name.strip(), body.description.strip(), body.input_columns, base_df, body.formula,
        )
    except Exception as exc:
        logger.exception("Feature designer failed for session %s", session_id)
        raise HTTPException(status_code=502, detail="Couldn't draft the feature formula right now. Please try again.") from exc
    return FeatureDraft(**draft)


@router.post("/repository/{session_id}/suggest", response_model=SuggestFeatureEntriesResponse)
def suggest_features(session_id: str) -> SuggestFeatureEntriesResponse:
    session = _get_session_or_404(session_id)
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df
    try:
        suggestions = feature_suggester.suggest_features(base_df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature suggestion agent (OpenRouter) is unavailable: {exc}") from exc
    new_entries = feature_repository.add_ai_suggested_entries(session_id, suggestions)
    return SuggestFeatureEntriesResponse(session_id=session_id, entries=[FeatureRepositoryEntry(**e) for e in new_entries])


@router.post("/repository/{session_id}/entries/{entry_id}/accept", response_model=FeatureRepositoryEntry)
def accept_entry(session_id: str, entry_id: str) -> FeatureRepositoryEntry:
    _get_session_or_404(session_id)
    entry = feature_repository.set_entry_status(session_id, entry_id, "approved")
    if entry is None:
        raise HTTPException(status_code=404, detail="Feature entry not found in this session's repository.")
    return FeatureRepositoryEntry(**entry)


@router.post("/repository/{session_id}/entries/{entry_id}/reject", response_model=FeatureRepositoryEntry)
def reject_entry(session_id: str, entry_id: str) -> FeatureRepositoryEntry:
    _get_session_or_404(session_id)
    entry = feature_repository.set_entry_status(session_id, entry_id, "rejected")
    if entry is None:
        raise HTTPException(status_code=404, detail="Feature entry not found in this session's repository.")
    return FeatureRepositoryEntry(**entry)
