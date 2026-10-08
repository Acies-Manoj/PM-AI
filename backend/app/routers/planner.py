from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.deps import User, get_user, require_owned
from app.services.common import audit_log, selections
from app.services.planner import planner as planner_service, planner_store

router = APIRouter(prefix="/api/planner", tags=["planner"])


class SuggestRequest(BaseModel):
    session_id: str
    additional_context: str = ""


class PmDecision(BaseModel):
    recommendation_index: int
    pm_decision: str  # "accepted" | "rejected" | "pending"
    pm_notes: str = ""


class SaveRequest(BaseModel):
    session_id: str
    decisions: list[PmDecision]


class SaveResponse(BaseModel):
    session_id: str
    saved: bool


@router.post("/suggest")
def suggest(req: SuggestRequest, user: User = Depends(get_user)):
    require_owned(req.session_id, user)
    try:
        result = planner_service.suggest(req.session_id, req.additional_context)
        audit_log.log_event(req.session_id, user.id, "planner_suggest", {})
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner LLM error: {exc}") from exc


@router.post("/save", response_model=SaveResponse)
def save_decisions(req: SaveRequest, user: User = Depends(get_user)):
    require_owned(req.session_id, user)
    if not planner_store.load(req.session_id):
        raise HTTPException(
            status_code=404,
            detail="No planner suggestions found for this session. Call /suggest first.",
        )

    # The decision lands on the recommendation's own PLAN#<n> document.
    planner_store.apply_decisions(
        req.session_id, {d.recommendation_index: (d.pm_decision, d.pm_notes) for d in req.decisions}
    )
    audit_log.log_event(
        req.session_id, user.id, "planner_save",
        {"decisions": [d.model_dump() for d in req.decisions]},
    )
    selections.refresh(req.session_id, user.id, "planner_save")

    return SaveResponse(session_id=req.session_id, saved=True)
