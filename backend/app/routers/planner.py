from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.routers.deps import User, get_user, require_owned
from app.services.common import audit_log, doc_store, selections
from app.services.planner import planner as planner_service

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
    planner_data = doc_store.get(req.session_id, "PLANNER_SUGGEST")

    if planner_data is None:
        raise HTTPException(
            status_code=404,
            detail="No planner suggestions found for this session. Call /suggest first.",
        )

    recommendations = planner_data.get("recommendations", [])

    decision_map = {d.recommendation_index: d for d in req.decisions}
    for i, rec in enumerate(recommendations):
        decision = decision_map.get(i)
        rec["pm_decision"] = decision.pm_decision if decision else "pending"
        rec["pm_notes"] = decision.pm_notes if decision else ""

    output = {
        "session_id": req.session_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "recommendations": recommendations,
    }

    doc_store.put(req.session_id, "PLANNER_OUTPUT", output)
    audit_log.log_event(
        req.session_id, user.id, "planner_save",
        {"decisions": [d.model_dump() for d in req.decisions]},
    )
    selections.refresh(req.session_id, user.id, "planner_save")

    return SaveResponse(session_id=req.session_id, saved=True)
