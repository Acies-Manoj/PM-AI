"""Shared FastAPI dependencies used across routers."""
from fastapi import HTTPException

from app.services.audit.audit_store import AuditSession, store


def get_session_or_404(session_id: str) -> AuditSession:
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Audit session not found.")
    return session
