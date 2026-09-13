from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.schemas import BriefAnalysis
from app.services import orchestrator
from app.services.translator import detect_and_translate

router = APIRouter(prefix="/api/brief", tags=["brief"])


class BriefRequest(BaseModel):
    text: str


class TranslationResponse(BaseModel):
    original_text: str
    translated_text: str
    detected_language: str
    language_name: str
    was_translated: bool


@router.post("/translate", response_model=TranslationResponse)
def translate_brief(body: BriefRequest) -> TranslationResponse:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Brief text cannot be empty.")
    try:
        result = detect_and_translate(body.text.strip())
        return TranslationResponse(
            original_text=result.original_text,
            translated_text=result.translated_text,
            detected_language=result.detected_language,
            language_name=result.language_name,
            was_translated=result.was_translated,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analyze", response_model=BriefAnalysis)
def analyze_brief(body: BriefRequest) -> BriefAnalysis:
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="Brief text cannot be empty.")
    try:
        return orchestrator.analyze_brief(body.text.strip())
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Orchestrator agent unavailable: {exc}"
        ) from exc
