from fastapi import APIRouter, HTTPException

from app.schemas import OrchestratorRouteRequest, OrchestratorRouteResponse
from app.services import orchestrator_agent

router = APIRouter(prefix="/api/orchestrator", tags=["orchestrator"])


@router.post("/route", response_model=OrchestratorRouteResponse)
def route_brief(body: OrchestratorRouteRequest) -> OrchestratorRouteResponse:
    """Reads the client's free-text brief and decides which entry point it
    belongs to -- "feature_request" (features.py's /request) or
    "analysis_question" (analysis.py's /ask). This is the ONE routing
    decision the orchestrator makes; everything downstream of it (Step 1's
    screening, Step 2's deterministic feature derivation, etc.) runs on its
    own regardless of the brief."""
    try:
        return orchestrator_agent.route_brief(body.brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
