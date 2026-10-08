"""Audit session store, backed by DynamoDB + S3 (or local files when AWS is not configured).

What changed from the old in-memory dict: sessions now OUTLIVE the process and can be served
by any ECS task. What did NOT change is how callers use a session -- `store.get(id)` still
returns a mutable `AuditSession` and routers still assign to its fields -- with one new rule:
**after changing a session, call `store.save(session)`**. Nothing is written until then.

Where the pieces live (see services/common/session_repo.py and doc_store.py):
  * header  (owner, filename, features, events, ...)           -> doc `SESSIONS` in `DDB_DOCS`
  * issues (one per audit finding)                            -> doc `ISSUE#<issue id>`
  * proposals (drill-down suggestions)                        -> doc `PROPOSAL#<analysis id>#<nnn>`
  * df / pre_feature_df / audit_baseline (DataFrames)         -> S3 `frames/<id>/<name>.parquet`
  * analysis_results (one per entry)                          -> doc `RESULT#<entry id>`
  * overall_analysis                                          -> doc `OVERALL`
  * feature_drafts (one per draft token)                      -> doc `DRAFT#<token>`

The big or rarely-needed parts are LAZY: reading `session.df` loads the frame the first time,
`session.analysis_results` loads the result docs the first time. Assigning marks the part dirty
and `save()` writes only dirty parts. For `df` / `pre_feature_df` / `audit_baseline`, an
IN-PLACE change (`session.df.loc[...] = x`) is NOT detected -- call `session.mark_dirty("df")`.

Per-task cache: `get()` always reads the (tiny) header to check its version, and returns the
cached in-memory object only if the version still matches. Another task's save bumps the
version, so a stale cache is dropped and the session reloaded -- that is what lets several
tasks share sessions safely.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import pandas as pd
from cachetools import TTLCache

from app.schemas import AnalysisResult, AuditIssue, FeatureResult, OverallAnalysisReport
from app.services.common import doc_store, session_repo
from app.services.common.doc_store import VersionConflict

FRAME_NAMES = ("df", "pre_feature_df", "audit_baseline")
RESULT_PREFIX = "RESULT#"
DRAFT_PREFIX = "DRAFT#"
ISSUE_PREFIX = "ISSUE#"
PROPOSAL_PREFIX = "PROPOSAL#"
OVERALL_DOC = "OVERALL"
# A feature draft is only meant to live for one editing sitting.
DRAFT_TTL_DAYS = 2

_UNLOADED = object()


class SessionConflict(Exception):
    """Another task saved this session after we loaded it. The caller should reload and retry
    (the API turns this into HTTP 409)."""


class _TrackedDict(dict):
    """A dict that remembers which keys were set or removed, so save() writes only those."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.changed: set[str] = set()
        self.removed: set[str] = set()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.changed.add(key)
        self.removed.discard(key)

    def __delitem__(self, key):
        super().__delitem__(key)
        self.changed.discard(key)
        self.removed.add(key)

    def pop(self, key, *default):
        if key in self:
            self.changed.discard(key)
            self.removed.add(key)
        return super().pop(key, *default)

    def popitem(self):
        key, value = super().popitem()
        self.changed.discard(key)
        self.removed.add(key)
        return key, value

    def clear(self):
        self.removed.update(self.keys())
        self.changed.clear()
        super().clear()

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def mark_clean(self) -> None:
        self.changed.clear()
        self.removed.clear()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _issue_doc_name(issue_id: str) -> str:
    return f"{ISSUE_PREFIX}{issue_id}"


def _proposal_doc_name(analysis_id: str, index: int) -> str:
    return f"{PROPOSAL_PREFIX}{analysis_id}#{index:03d}"


def _group_proposals(docs: dict[str, Any]) -> dict[str, list[dict]]:
    """{analysis id: [proposal, ...] in order} from the PROPOSAL#<analysis id>#<nnn> documents."""
    grouped: dict[str, list[dict]] = {}
    for name in sorted(docs):
        analysis_id = name[len(PROPOSAL_PREFIX):].rsplit("#", 1)[0]
        grouped.setdefault(analysis_id, []).append(docs[name])
    return grouped


class AuditSession:
    """One uploaded file's audit/feature/analysis state. Same fields as before; the large ones
    are lazy properties (see module docstring)."""

    def __init__(
        self,
        session_id: str,
        source: str,
        filename: str,
        df: pd.DataFrame | None = None,
        issues: list[AuditIssue] | None = None,
        summary: str = "",
        *,
        user_id: str = "local",
        raw_key: str | None = None,
    ):
        self.session_id = session_id
        self.source = source
        self.filename = filename
        self.user_id = user_id
        self.raw_key = raw_key
        self.issues: list[AuditIssue] = issues if issues is not None else []
        self.summary = summary
        # Size of the dataset as uploaded (the Planner reads these; the column profiles are the
        # COLUMN#<name> documents).
        self.row_count = len(df) if df is not None else 0
        self.column_count = len(df.columns) if df is not None else 0
        self.features: list[FeatureResult] = []
        self.feature_skipped_notes: list[str] = []
        # Snapshot of the PM's decisions and final selected features / analyses (see
        # services/common/selections.py). Stored in the header so the Sessions table row alone
        # answers "what did this user decide".
        self.selections: dict = {}
        # Undo support for resolved issues that actually mutated `df` (dropped columns /
        # removed rows). Any of them can be reverted, in any order: `audit_baseline` is the data
        # before the FIRST change and `audit_events` is every change since, in order (audit
        # decisions and the PM's inline value edits). Reverting one drops its event and REPLAYS
        # the rest from the baseline, so every later decision is re-derived as if the reverted
        # one had never happened. `mutation_stack` lists the applied decisions' issue ids,
        # oldest first. "Keep as-is" resolutions never touch `df`.
        self.mutation_stack: list[str] = []
        self.audit_events: list[dict] = []
        self.created_at = _now()
        # Optimistic-concurrency token of the stored header (0 = not stored yet).
        self.version = 0

        # frame name -> DataFrame | None | _UNLOADED; refs say which frames exist in storage.
        self._frames: dict[str, Any] = {n: _UNLOADED for n in FRAME_NAMES}
        self._frame_refs: dict[str, dict] = {}
        self._dirty_frames: set[str] = set()
        if df is not None:
            self._frames["df"] = df
            self._dirty_frames.add("df")
        else:
            self._frames["df"] = _UNLOADED
        self._frames["pre_feature_df"] = None
        self._frames["audit_baseline"] = None

        # What is stored for each ISSUE# / PROPOSAL# document, so save() writes only what changed.
        self._issue_docs: dict[str, dict] = {}
        self._proposal_docs: dict[str, list[dict]] = {}

        self._analysis_results: _TrackedDict | None = None
        self._overall: Any = _UNLOADED
        self._overall_dirty = False
        self._feature_drafts: _TrackedDict | None = None

        self._lock = threading.RLock()

    # ------------------------------------------------------------------ frames
    def _get_frame(self, name: str) -> pd.DataFrame | None:
        value = self._frames[name]
        if value is _UNLOADED:
            with self._lock:
                value = self._frames[name]
                if value is _UNLOADED:
                    ref = self._frame_refs.get(name)
                    value = session_repo.load_frame(self.session_id, name, ref) if ref else None
                    self._frames[name] = value
        return value

    def _set_frame(self, name: str, value: pd.DataFrame | None) -> None:
        self._frames[name] = value
        self._dirty_frames.add(name)

    @property
    def df(self) -> pd.DataFrame:
        return self._get_frame("df")

    @df.setter
    def df(self, value: pd.DataFrame) -> None:
        self._set_frame("df", value)

    @property
    def pre_feature_df(self) -> pd.DataFrame | None:
        return self._get_frame("pre_feature_df")

    @pre_feature_df.setter
    def pre_feature_df(self, value: pd.DataFrame | None) -> None:
        self._set_frame("pre_feature_df", value)

    @property
    def audit_baseline(self) -> pd.DataFrame | None:
        return self._get_frame("audit_baseline")

    @audit_baseline.setter
    def audit_baseline(self, value: pd.DataFrame | None) -> None:
        self._set_frame("audit_baseline", value)

    def mark_dirty(self, *frame_names: str) -> None:
        """Flag frames that were changed IN PLACE (assignments are tracked automatically)."""
        for name in frame_names or FRAME_NAMES:
            if name not in FRAME_NAMES:
                raise ValueError(f"unknown frame {name!r}")
            self._get_frame(name)  # make sure it is loaded before it is written back
            self._dirty_frames.add(name)

    # ------------------------------------------------------------------ analysis results
    @property
    def analysis_results(self) -> _TrackedDict:
        """In-memory run outputs for the Analysis Agent, keyed by analysis_repository entry id.
        Populated only once a PM clicks "Run" for that entry. Assigning/removing a key marks it
        for the next save()."""
        if self._analysis_results is None:
            with self._lock:
                if self._analysis_results is None:
                    loaded = _TrackedDict()
                    # The drill-down proposals of each result are their own PROPOSAL# documents.
                    proposals = _group_proposals(doc_store.list_docs(self.session_id, PROPOSAL_PREFIX))
                    for doc, data in doc_store.list_docs(self.session_id, RESULT_PREFIX).items():
                        key = doc[len(RESULT_PREFIX):]
                        try:
                            if key in proposals:
                                data = {**data, "guided_proposals": proposals[key]}
                            dict.__setitem__(loaded, key, AnalysisResult.model_validate(data))
                        except Exception:  # a result from an older schema: drop it, it can be re-run
                            continue
                        self._proposal_docs[key] = list(proposals.get(key, []))
                    self._analysis_results = loaded
        return self._analysis_results

    @analysis_results.setter
    def analysis_results(self, value: dict[str, AnalysisResult]) -> None:
        current = self.analysis_results
        current.clear()
        current.update(value)

    # ------------------------------------------------------------------ overall analysis
    @property
    def overall_analysis(self) -> OverallAnalysisReport | None:
        """Last-computed overall analysis, kept so a report can reuse exactly what the user saw
        instead of making another LLM call at export time."""
        if self._overall is _UNLOADED:
            data = doc_store.get(self.session_id, OVERALL_DOC)
            try:
                self._overall = OverallAnalysisReport.model_validate(data) if data else None
            except Exception:
                self._overall = None
        return self._overall

    @overall_analysis.setter
    def overall_analysis(self, value: OverallAnalysisReport | None) -> None:
        self._overall = value
        self._overall_dirty = True

    # ------------------------------------------------------------------ feature drafts
    @property
    def feature_drafts(self) -> _TrackedDict:
        """Custom-feature drafts the PM is reviewing (see features/feature_designer.py), keyed by
        draft token: formula and already-validated code from the dry run. Saving a draft whose
        formula is unchanged seeds the feature cache from here, so the validated code is reused
        instead of regenerated -- the browser never sends code back."""
        if self._feature_drafts is None:
            with self._lock:
                if self._feature_drafts is None:
                    loaded = _TrackedDict()
                    for doc, data in doc_store.list_docs(self.session_id, DRAFT_PREFIX).items():
                        dict.__setitem__(loaded, doc[len(DRAFT_PREFIX):], data)
                    self._feature_drafts = loaded
        return self._feature_drafts

    @feature_drafts.setter
    def feature_drafts(self, value: dict[str, dict]) -> None:
        current = self.feature_drafts
        current.clear()
        current.update(value)

    # ------------------------------------------------------------------ (de)serialization
    def _header(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "source": self.source,
            "filename": self.filename,
            "raw_key": self.raw_key,
            "summary": self.summary,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "features": [f.model_dump(mode="json") for f in self.features],
            "feature_skipped_notes": list(self.feature_skipped_notes),
            "selections": self.selections,
            "mutation_stack": list(self.mutation_stack),
            "audit_events": list(self.audit_events),
            "frames": self._frame_refs,
            "created_at": self.created_at,
            "updated_at": _now(),
        }

    def _issue_doc(self, issue: AuditIssue, order: int) -> dict:
        """The ISSUE#<id> document: the finding as shown to the PM (title, options, AI
        recommendation, status, resolution) plus `applied`, the decision that was applied to the
        data (also kept in `audit_events` of the header, which the undo replays)."""
        doc = issue.model_dump(mode="json")
        doc["order"] = order
        applied = None
        if issue.status == "resolved":
            applied = next(
                (
                    {"decision_id": e.get("decision_id"), "selected_items": e.get("selected_items")}
                    for e in self.audit_events
                    if e.get("type") == "decision" and e.get("issue_id") == issue.id
                ),
                None,
            )
        doc["applied"] = applied
        return doc

    @classmethod
    def _from_header(cls, header: dict, version: int) -> "AuditSession":
        session = cls(
            session_id=header["session_id"],
            source=header.get("source", ""),
            filename=header.get("filename", ""),
            user_id=header.get("user_id") or "local",
            raw_key=header.get("raw_key"),
        )
        session.summary = header.get("summary", "")
        session.row_count = int(header.get("row_count", 0) or 0)
        session.column_count = int(header.get("column_count", 0) or 0)
        # Issues are ISSUE#<id> documents; a session saved before that still has them in its header.
        issue_docs = doc_store.list_docs(session.session_id, ISSUE_PREFIX)
        if issue_docs:
            ordered = sorted(issue_docs.values(), key=lambda d: d.get("order", 0))
            session.issues = [AuditIssue.model_validate(d) for d in ordered]
            session._issue_docs = {d["id"]: d for d in ordered}
        else:
            session.issues = [AuditIssue.model_validate(i) for i in header.get("issues", [])]
        session.features = [FeatureResult.model_validate(f) for f in header.get("features", [])]
        session.feature_skipped_notes = list(header.get("feature_skipped_notes", []))
        session.selections = dict(header.get("selections") or {})
        session.mutation_stack = list(header.get("mutation_stack", []))
        session.audit_events = list(header.get("audit_events", []))
        session.created_at = header.get("created_at", session.created_at)
        session._frame_refs = dict(header.get("frames", {}))
        # Frames are fetched on first use; ones that were never stored are simply None.
        session._frames = {n: (_UNLOADED if n in session._frame_refs else None) for n in FRAME_NAMES}
        session._dirty_frames = set()
        session.version = version
        return session


class AuditStore:
    def __init__(self):
        self._cache: TTLCache = TTLCache(maxsize=32, ttl=900)
        self._cache_lock = threading.Lock()

    # ------------------------------------------------------------------ create / get
    def create(
        self,
        source: str,
        filename: str,
        df: pd.DataFrame,
        issues: list[AuditIssue] | None = None,
        summary: str = "",
        *,
        user_id: str = "local",
        raw_key: str | None = None,
    ) -> AuditSession:
        session = AuditSession(
            session_id=uuid.uuid4().hex,
            source=source,
            filename=filename,
            df=df,
            issues=issues,
            summary=summary,
            user_id=user_id,
            raw_key=raw_key,
        )
        self.save(session)
        return session

    def get(self, session_id: str) -> AuditSession | None:
        """The session, or None if it does not exist (or the id is malformed)."""
        try:
            header, version = session_repo.load_header(session_id)
        except ValueError:
            return None
        if header is None:
            with self._cache_lock:
                self._cache.pop(session_id, None)
            return None
        with self._cache_lock:
            cached = self._cache.get(session_id)
            if cached is not None and cached.version == version:
                return cached
        session = AuditSession._from_header(header, version or 0)
        with self._cache_lock:
            self._cache[session_id] = session
        return session

    def owner_of(self, session_id: str) -> str | None:
        """The owning user id without loading the session (None if it does not exist)."""
        try:
            header, _ = session_repo.load_header(session_id)
        except ValueError:
            return None
        if header is None:
            return None
        return header.get("user_id") or "local"

    # ------------------------------------------------------------------ save
    def save(self, session: AuditSession, *, frames: Iterable[str] | None = None) -> None:
        """Persist everything that changed on `session`. Raises SessionConflict if another task
        saved it first. `frames` forces those frames to be written even if not flagged dirty."""
        with session._lock:
            force = set(frames or ())
            for name in FRAME_NAMES:
                if name in force:
                    session._get_frame(name)
                    session._dirty_frames.add(name)

            # 1. frames (the header refers to them, so they go first)
            for name in sorted(session._dirty_frames):
                value = session._frames[name]
                if value is _UNLOADED:
                    continue
                if value is None:
                    session_repo.delete_frame(session.session_id, name, session._frame_refs.get(name))
                    session._frame_refs.pop(name, None)
                else:
                    session._frame_refs[name] = session_repo.save_frame(session.session_id, name, value)
            session._dirty_frames.clear()

            # 2. result / draft / overall documents
            results = session._analysis_results
            if results is not None:
                for key in sorted(results.changed):
                    data = results[key].model_dump(mode="json")
                    proposals = data.pop("guided_proposals", None) or []  # stored as PROPOSAL# documents
                    doc_store.put(session.session_id, RESULT_PREFIX + key, data)
                    previous = session._proposal_docs.get(key)
                    if previous != proposals:
                        doc_store.put_many(
                            session.session_id, {_proposal_doc_name(key, i): p for i, p in enumerate(proposals)}
                        )
                        for i in range(len(proposals), len(previous or [])):
                            doc_store.delete(session.session_id, _proposal_doc_name(key, i))
                        session._proposal_docs[key] = proposals
                for key in sorted(results.removed):
                    doc_store.delete(session.session_id, RESULT_PREFIX + key)
                    for i in range(len(session._proposal_docs.pop(key, []))):
                        doc_store.delete(session.session_id, _proposal_doc_name(key, i))
                results.mark_clean()
            # issues: only the ones that changed since they were loaded / last saved
            current_issues = {i.id: session._issue_doc(i, n) for n, i in enumerate(session.issues)}
            changed = {_issue_doc_name(k): d for k, d in current_issues.items() if session._issue_docs.get(k) != d}
            if changed:
                doc_store.put_many(session.session_id, changed)
            for gone in set(session._issue_docs) - set(current_issues):
                doc_store.delete(session.session_id, _issue_doc_name(gone))
            session._issue_docs = current_issues
            drafts = session._feature_drafts
            if drafts is not None:
                for key in sorted(drafts.changed):
                    doc_store.put(session.session_id, DRAFT_PREFIX + key, drafts[key], ttl_days=DRAFT_TTL_DAYS)
                for key in sorted(drafts.removed):
                    doc_store.delete(session.session_id, DRAFT_PREFIX + key)
                drafts.mark_clean()
            if session._overall_dirty:
                if session._overall is None:
                    doc_store.delete(session.session_id, OVERALL_DOC)
                else:
                    doc_store.put(session.session_id, OVERALL_DOC, session._overall.model_dump(mode="json"))
                session._overall_dirty = False

            # 3. header, conditional on the version we loaded
            try:
                session.version = session_repo.save_header(
                    session.session_id, session._header(), expected_version=session.version
                )
            except VersionConflict as exc:
                with self._cache_lock:
                    self._cache.pop(session.session_id, None)
                raise SessionConflict(
                    "This session was changed by another request. Reload and try again."
                ) from exc

        with self._cache_lock:
            self._cache[session.session_id] = session


store = AuditStore()
