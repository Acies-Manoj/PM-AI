import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import DATA_DIR

router = APIRouter(prefix="/api/brief", tags=["brief"])

SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class FileMetadataIn(BaseModel):
    slot: str
    filename: str
    size: int
    mime_type: str


class FinalizeRequest(BaseModel):
    audit_session_ids: list[str]
    raw_brief: str
    final_brief: str
    original_language: str | None = None
    original_language_name: str | None = None
    translated_text: str | None = None
    files: list[FileMetadataIn]


class FinalizeResponse(BaseModel):
    session_id: str


@router.post("/finalize", response_model=FinalizeResponse)
def finalize(req: FinalizeRequest):
    """Merge brief + all uploaded datasets into one metadata.json.

    Uses the first audit session's folder as the canonical session so
    there is exactly one folder and one file per run.
    """
    if not req.audit_session_ids:
        raise HTTPException(status_code=400, detail="At least one audit_session_id is required.")

    primary_sid = req.audit_session_ids[0]
    session_dir = SESSIONS_DIR / primary_sid

    metadata = {
        "session_id": primary_sid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "client_brief": {
            "raw_text": req.raw_brief,
            "final_text": req.final_brief,
            "original_language": req.original_language,
            "original_language_name": req.original_language_name,
            "translated_text": req.translated_text,
        },
        "files": [f.model_dump() for f in req.files],
    }

    (session_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return FinalizeResponse(session_id=primary_sid)
