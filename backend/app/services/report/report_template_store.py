"""
Holds whatever PPTX template was most recently uploaded to use as the base
for the downloaded report. Same single-slot, thread-safe scope as
pivot_definitions_store.py / feature_definitions_store.py -- no bundled
backend default; if nothing has been uploaded, `store.content` is None and
report_generator.build_report falls back to its own built-in layout.
"""
import threading


class ReportTemplateStore:
    def __init__(self):
        self._lock = threading.Lock()
        self.filename: str | None = None
        self.content: bytes | None = None

    def set(self, filename: str, content: bytes) -> None:
        with self._lock:
            self.filename = filename
            self.content = content

    def clear(self) -> None:
        with self._lock:
            self.filename = None
            self.content = None


store = ReportTemplateStore()
