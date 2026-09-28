"""Shared single-slot, thread-safe store for the most recently uploaded
"definitions" file (a Customer KPI Profile or an Analysis Profile), used
by both feature_definitions_store.py and analysis_definitions_store.py.
Each module's own `validate()` stays local since the schemas differ
(per-type required fields for features vs. one flat schema for analyses).
"""
import threading


class DefinitionsStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.filename: str | None = None
        self.definitions: list[dict] | None = None

    def set(self, filename: str, definitions: list[dict]) -> None:
        with self._lock:
            self.filename = filename
            self.definitions = definitions

    def clear(self) -> None:
        with self._lock:
            self.filename = None
            self.definitions = None
