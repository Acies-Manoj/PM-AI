import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.schemas import (
    AddCustomFeatureRequest,
    DraftFeatureRequest,
    FeatureDefinitionsSummary,
    FeatureDraft,
    FeatureRepositoryEntry,
    FeatureRepositoryResponse,
    SuggestFeatureEntriesResponse,
)
from app.routers import deps
from app.routers.deps import User, get_user
from app.services.audit.audit_store import store as audit_store
from app.services.common.audit_log import log_event
from app.services.features import feature_definitions_store as defs_store
from app.services.features import feature_designer, feature_repository, feature_suggester

router = APIRouter(prefix="/api/features", tags=["features"])
logger = logging.getLogger(__name__)


@router.post("/definitions", response_model=FeatureDefinitionsSummary)
async def upload_feature_definitions(file: UploadFile = File(...), user: User = Depends(get_user)) -> FeatureDefinitionsSummary:
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
    defs_store.save(user.id, filename, features)

    return FeatureDefinitionsSummary(
        filename=filename,
        feature_count=len(features),
        feature_names=[f["name"] for f in features],
    )


@router.get("/definitions", response_model=FeatureDefinitionsSummary)
def get_feature_definitions(user: User = Depends(get_user)) -> FeatureDefinitionsSummary:
    filename, definitions = defs_store.load(user.id)
    if definitions is None:
        raise HTTPException(status_code=404, detail="No Customer KPI Profile has been uploaded yet.")
    return FeatureDefinitionsSummary(
        filename=filename,
        feature_count=len(definitions),
        feature_names=[f["name"] for f in definitions],
    )


@router.get("/repository/{session_id}", response_model=FeatureRepositoryResponse)
def get_repository(session_id: str, user: User = Depends(get_user)) -> FeatureRepositoryResponse:
    deps.load_owned_session(session_id, user)
    entries = feature_repository.get_repository(session_id)
    return FeatureRepositoryResponse(session_id=session_id, entries=[FeatureRepositoryEntry(**e) for e in entries])


@router.post("/repository/{session_id}/custom", response_model=FeatureRepositoryEntry)
def add_custom_feature(session_id: str, body: AddCustomFeatureRequest, user: User = Depends(get_user)) -> FeatureRepositoryEntry:
    session = deps.load_owned_session(session_id, user)
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
        audit_store.save(session)  # the used draft is popped from session.feature_drafts
    log_event(session_id, user.id, "feature_custom_added", {"entry_id": entry.get("id"), "name": entry.get("name")})
    return FeatureRepositoryEntry(**entry)


@router.post("/repository/{session_id}/draft", response_model=FeatureDraft)
def draft_custom_feature(session_id: str, body: DraftFeatureRequest, user: User = Depends(get_user)) -> FeatureDraft:
    """Human-in-the-loop step for a user-requested feature: the formula the
    Feature Agent would use, dry-run on the real data. Nothing is saved --
    the PM reviews/edits it and confirms via /custom."""
    session = deps.load_owned_session(session_id, user)
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
    audit_store.save(session)  # draft_feature stores the draft in session.feature_drafts
    log_event(session_id, user.id, "feature_draft", {"name": body.name.strip()})
    return FeatureDraft(**draft)


@router.post("/repository/{session_id}/suggest", response_model=SuggestFeatureEntriesResponse)
def suggest_features(session_id: str, user: User = Depends(get_user)) -> SuggestFeatureEntriesResponse:
    session = deps.load_owned_session(session_id, user)
    base_df = session.pre_feature_df if session.pre_feature_df is not None else session.df
    try:
        suggestions = feature_suggester.suggest_features(base_df, feature_repository.get_repository(session_id))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature suggestion agent (Bedrock) is unavailable: {exc}") from exc
    new_entries = feature_repository.add_ai_suggested_entries(session_id, suggestions)
    audit_store.save(session)
    log_event(session_id, user.id, "feature_suggested", {"count": len(new_entries)})
    return SuggestFeatureEntriesResponse(session_id=session_id, entries=[FeatureRepositoryEntry(**e) for e in new_entries])


@router.post("/repository/{session_id}/entries/{entry_id}/accept", response_model=FeatureRepositoryEntry)
def accept_entry(session_id: str, entry_id: str, user: User = Depends(get_user)) -> FeatureRepositoryEntry:
    deps.load_owned_session(session_id, user)
    entry = feature_repository.set_entry_status(session_id, entry_id, "approved")
    if entry is None:
        raise HTTPException(status_code=404, detail="Feature entry not found in this session's repository.")
    log_event(session_id, user.id, "feature_accepted", {"entry_id": entry_id, "name": entry.get("name")})
    return FeatureRepositoryEntry(**entry)


@router.post("/repository/{session_id}/entries/{entry_id}/reject", response_model=FeatureRepositoryEntry)
def reject_entry(session_id: str, entry_id: str, user: User = Depends(get_user)) -> FeatureRepositoryEntry:
    deps.load_owned_session(session_id, user)
    entry = feature_repository.set_entry_status(session_id, entry_id, "rejected")
    if entry is None:
        raise HTTPException(status_code=404, detail="Feature entry not found in this session's repository.")
    log_event(session_id, user.id, "feature_rejected", {"entry_id": entry_id, "name": entry.get("name")})
    return FeatureRepositoryEntry(**entry)
