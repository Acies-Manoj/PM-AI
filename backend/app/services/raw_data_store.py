"""In-memory session store for the Raw Data Explorer step -- same pattern as
audit_store.py, just keyed separately since a raw-data session isn't an
AuditSession (no issues/features/pivots, just the parsed aggregated table
plus the temperature/light matrices it's joined against)."""
import threading
import uuid
from dataclasses import dataclass

from app.services.raw_data_matrix import AggregatedData, MatrixData, TripRow

DEFAULT_INTERVAL_MINUTES = 15


@dataclass
class RawDataSession:
    session_id: str
    aggregated: AggregatedData
    trips: list[TripRow]
    temperature: MatrixData | None
    light: MatrixData | None
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES


class RawDataStore:
    def __init__(self):
        self._sessions: dict[str, RawDataSession] = {}
        self._lock = threading.Lock()

    def create(
        self, aggregated: AggregatedData, trips: list[TripRow], temperature: MatrixData | None, light: MatrixData | None
    ) -> RawDataSession:
        session = RawDataSession(
            session_id=uuid.uuid4().hex, aggregated=aggregated, trips=trips, temperature=temperature, light=light
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> RawDataSession | None:
        with self._lock:
            return self._sessions.get(session_id)


store = RawDataStore()
