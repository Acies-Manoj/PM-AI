import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DATA_DIR
from app.services import planner as planner_service

router = APIRouter(prefix="/api/planner", tags=["planner"])

_SESSIONS_DIR = DATA_DIR / "sessions"


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
def suggest(req: SuggestRequest):
    try:
        return planner_service.suggest(req.session_id, req.additional_context)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner LLM error: {exc}") from exc


@router.post("/save", response_model=SaveResponse)
def save_decisions(req: SaveRequest):
    session_dir = _SESSIONS_DIR / req.session_id
    suggest_path = session_dir / "planner_suggest.json"

    if not suggest_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No planner suggestions found for this session. Call /suggest first.",
        )

    planner_data = json.loads(suggest_path.read_text(encoding="utf-8"))
    recommendations = planner_data.get("recommendations", [])

    decision_map = {d.recommendation_index: d for d in req.decisions}
    for i, rec in enumerate(recommendations):
        decision = decision_map.get(i)
        rec["pm_decision"] = decision.pm_decision if decision else "pending"
        rec["pm_notes"] = decision.pm_notes if decision else ""

    output = {
        "session_id": req.session_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "interpreted_requirement": planner_data.get("interpreted_requirement", ""),
        "business_objective": planner_data.get("business_objective", ""),
        "recommendations": recommendations,
    }

    (session_dir / "planner_output.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return SaveResponse(session_id=req.session_id, saved=True)
