import json

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.schemas import (
    AIFeatureCodeResult,
    AIFeatureGenerateRequest,
    AIFeatureSuggestRequest,
    FeatureDefinitionsSummary,
    FeatureSuggestion,
)
from app.services import feature_agent, sandbox_executor
from app.services import feature_definitions_store as defs_store
from app.services.audit_store import store as audit_store

router = APIRouter(prefix="/api/features", tags=["features"])


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


@router.post("/suggest", response_model=list[FeatureSuggestion])
def suggest_features(body: AIFeatureSuggestRequest) -> list[FeatureSuggestion]:
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    try:
        return feature_agent.suggest_features(session.df, body.brief)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature agent unavailable: {exc}") from exc


@router.post("/generate", response_model=AIFeatureCodeResult)
def generate_and_run_feature(body: AIFeatureGenerateRequest) -> AIFeatureCodeResult:
    session = audit_store.get(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    try:
        result = feature_agent.generate_feature_code(body.user_request, session.df)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feature agent unavailable: {exc}") from exc

    if not result.code:
        return result

    series, error = sandbox_executor.run_feature_code(result.code, session.df)
    if error:
        result.error = error
        return result

    # Attach the new column to the session df for downstream use
    session.df[result.output_column] = series
    result.success = True
    result.sample_values = [
        None if v != v else v  # NaN check
        for v in series.head(10).tolist()
    ]
    return result
