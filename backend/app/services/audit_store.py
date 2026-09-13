"""In-memory audit session store. Single-process demo scope -- same pattern
as the prior IngestionStore: no persistence, no multi-user isolation, just a
thread-safe dict keyed by session id."""
import threading
import uuid
from dataclasses import dataclass, field

import pandas as pd

from app.schemas import AuditIssue, FeatureResult, ScreeningReport


@dataclass
class AuditSession:
    session_id: str
    source: str
    filename: str
    df: pd.DataFrame
    issues: list[AuditIssue] = field(default_factory=list)
    summary: str = ""
    features: list[FeatureResult] = field(default_factory=list)
    feature_skipped_notes: list[str] = field(default_factory=list)
    screening_report: ScreeningReport | None = None


class AuditStore:
    def __init__(self):
        self._sessions: dict[str, AuditSession] = {}
        self._lock = threading.Lock()

    def create(self, source: str, filename: str, df: pd.DataFrame, issues: list[AuditIssue], summary: str) -> AuditSession:
        session = AuditSession(
            session_id=uuid.uuid4().hex, source=source, filename=filename, df=df, issues=issues, summary=summary
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> AuditSession | None:
        with self._lock:
            return self._sessions.get(session_id)


store = AuditStore()
