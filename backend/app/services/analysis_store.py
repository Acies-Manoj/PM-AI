"""In-memory store for analysis sessions (one per audit session)."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from app.schemas import AnalysisStep


@dataclass
class AnalysisSession:
    analysis_id: str
    session_id: str
    brief: str
    flagged_summary: str
    steps: list[AnalysisStep] = field(default_factory=list)
    validated_results: list[dict] = field(default_factory=list)
    status: str = "in_progress"


class AnalysisStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AnalysisSession] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, brief: str, flagged_summary: str) -> AnalysisSession:
        analysis = AnalysisSession(
            analysis_id=uuid.uuid4().hex,
            session_id=session_id,
            brief=brief,
            flagged_summary=flagged_summary,
        )
        with self._lock:
            self._sessions[analysis.analysis_id] = analysis
        return analysis

    def get(self, analysis_id: str) -> AnalysisSession | None:
        with self._lock:
            return self._sessions.get(analysis_id)


store = AnalysisStore()
