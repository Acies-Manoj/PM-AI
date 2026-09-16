"""
Persistent library of the KPIs and analyses a user built by hand in the app
(the "Add a Custom KPI" / "Add a Custom Analysis" forms), plus any AI
suggestion they chose to keep.

Unlike every other store in this app -- all single-slot and in-memory, alive
only for the current session -- this one writes to a JSON file on disk
(config.CUSTOM_LIBRARY_PATH). That's the whole point: "keep it as my
regular" means nothing if it disappears on the next restart.

Every saved entry carries a `scope`, which is the ONLY thing that
distinguishes the two save options the forms offer:

  "regular"   -- treated as part of the standing definition set. Merged into
                 the uploaded Customer KPI Profile / Analysis Profile on
                 every compute, for every session, without the user picking
                 it again.
  "suggested" -- kept in the library and offered back alongside the AI
                 suggestions, but never applied on its own. The user adds it
                 per session, when they want it.

The stored `spec` is exactly the definition dict the frontend already sends
as an `extra_features` / `extra_pivots` entry, so a saved item can be echoed
straight back into either path with no reshaping -- and, being the same
shape the uploaded profile files use, it validates through those same
validators (see save()).
"""
import json
import threading
from datetime import datetime, timezone
from typing import Literal

from app.config import CUSTOM_LIBRARY_PATH
from app.services import feature_definitions_store, pivot_definitions_store

Kind = Literal["features", "pivots"]
Scope = Literal["regular", "suggested"]

KINDS: tuple[Kind, ...] = ("features", "pivots")
SCOPES: tuple[Scope, ...] = ("regular", "suggested")

# The uploaded-profile validator to run a spec of each kind through, and the
# key that validator expects to find it under.
_VALIDATORS = {
    "features": (feature_definitions_store.validate, "features"),
    "pivots": (pivot_definitions_store.validate, "pivots"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CustomLibraryStore:
    """Thread-safe, file-backed. The whole file is small (a handful of
    definitions), so every mutation rewrites it -- no partial-update
    machinery to get wrong, and the file on disk is always a complete,
    readable snapshot the user could hand-edit or check into their own
    profile file."""

    def __init__(self, path=CUSTOM_LIBRARY_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, list[dict]] = {kind: [] for kind in KINDS}
        self._load()

    # -- disk ---------------------------------------------------------------

    def _load(self) -> None:
        """A missing file is the normal first-run state, not an error. A
        corrupt one is treated the same way -- an unreadable library
        shouldn't stop the app booting; the user just starts a fresh one."""
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(payload, dict):
            return
        for kind in KINDS:
            items = payload.get(kind)
            if isinstance(items, list):
                self._data[kind] = [i for i in items if isinstance(i, dict) and isinstance(i.get("spec"), dict)]

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    # -- reads --------------------------------------------------------------

    def entries(self, kind: Kind) -> list[dict]:
        """Named `entries`, not `list`, purely so the class body's own
        `list[dict]` annotations below still resolve to the builtin."""
        with self._lock:
            return [dict(item) for item in self._data[kind]]

    def regular_specs(self, kind: Kind) -> list[dict]:
        """The specs to merge into the uploaded profile on every compute."""
        with self._lock:
            return [dict(item["spec"]) for item in self._data[kind] if item.get("scope") == "regular"]

    # -- writes -------------------------------------------------------------

    def save(self, kind: Kind, spec: dict, scope: Scope) -> dict:
        """Upserts by the spec's own id, so re-saving an edited definition
        replaces it instead of piling up near-duplicates. Raises ValueError
        (with the profile validator's own message) if the spec isn't
        something the compute step could actually run."""
        if scope not in SCOPES:
            raise ValueError(f"Unknown scope '{scope}'. Expected one of: {', '.join(SCOPES)}.")
        validate, key = _VALIDATORS[kind]
        validate({key: [spec]})

        def_id = spec["id"]
        entry = {
            "id": def_id,
            "name": spec.get("name", def_id),
            "description": spec.get("description", ""),
            "scope": scope,
            "saved_at": _now(),
            "spec": spec,
        }
        with self._lock:
            self._data[kind] = [i for i in self._data[kind] if i.get("id") != def_id]
            self._data[kind].append(entry)
            self._flush()
        return dict(entry)

    def set_scope(self, kind: Kind, def_id: str, scope: Scope) -> dict:
        if scope not in SCOPES:
            raise ValueError(f"Unknown scope '{scope}'. Expected one of: {', '.join(SCOPES)}.")
        with self._lock:
            for item in self._data[kind]:
                if item.get("id") == def_id:
                    item["scope"] = scope
                    self._flush()
                    return dict(item)
        raise KeyError(def_id)

    def delete(self, kind: Kind, def_id: str) -> None:
        with self._lock:
            remaining = [i for i in self._data[kind] if i.get("id") != def_id]
            if len(remaining) == len(self._data[kind]):
                raise KeyError(def_id)
            self._data[kind] = remaining
            self._flush()


store = CustomLibraryStore()


def merge_definitions(profile_defs: list[dict], *extra_groups: list[dict]) -> list[dict]:
    """Concatenates definition lists into the one list a compute step runs,
    de-duplicated by id with LATER groups winning -- so a session's own
    `extra_features`/`extra_pivots` override a saved "regular" definition of
    the same id, which in turn overrides one from the uploaded profile.
    Order is otherwise preserved (first appearance wins the slot), so the
    profile's own definitions stay in the order the user wrote them."""
    order: list[str] = []
    by_id: dict[str, dict] = {}
    for group in (profile_defs, *extra_groups):
        for spec in group:
            def_id = spec.get("id")
            if def_id is None:
                continue
            if def_id not in by_id:
                order.append(def_id)
            by_id[def_id] = spec
    return [by_id[def_id] for def_id in order]
