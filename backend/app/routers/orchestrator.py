from fastapi import APIRouter, HTTPException

from app.schemas import (
    OrchestratorRouteRequest,
    OrchestratorRouteResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services import orchestrator_agent

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/route", response_model=OrchestratorRouteResponse)
def route_brief(body: OrchestratorRouteRequest) -> OrchestratorRouteResponse:
    """Translation only -- see orchestrator_agent.py. Used by the Upload
    page's language-review step (detect + show the English translation,
    editable) before the brief goes anywhere near the richer /recommend
    call below."""
    try:
        return orchestrator_agent.route_brief(body.brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/recommend", response_model=RecommendationResponse)
def recommend(body: RecommendationRequest) -> RecommendationResponse:
    """The AI Recommendation page's own endpoint: reads the (already-
    translated) brief and returns one recommendation per distinct feature/
    analysis/configuration it identifies, each with a confidence score, a
    draft definition, and a reuse-vs-new judgment against the existing
    catalog -- see orchestrator_agent.generate_recommendations. Nothing is
    created here; the user reviews/edits/approves/rejects on that page
    first, and only the approved ones carry on to Audit."""
    try:
        return orchestrator_agent.generate_recommendations(body.brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner Agent (Groq) is unavailable: {exc}") from exc
