"""Planner recommendations: one `PLAN#<nnn>` document per recommendation.

A document holds the AI's proposal (name, type, description, formula, required fields ...) AND
the PM's decision on it (`pm_decision` = accepted | rejected | pending, `pm_notes`), so "what did
the Planner propose and what did the PM decide" is one read. `<nnn>` is the recommendation's
position, zero-padded so DynamoDB's sort order is the list order (PLAN#002 before PLAN#010);
the position is what the rest of the app calls the recommendation's index (`planner_<index>`).

  suggest (first call)      replaces the list; a decision already made on a recommendation with
                            the same name is kept, so reopening the Planner never un-approves it
  suggest (more, with a     appends after the existing recommendations
  request in the text box)
  save decisions            writes the PM's decision onto each recommendation by index
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.common import doc_store

PREFIX = "PLAN#"


def doc_name(index: int) -> str:
    return f"{PREFIX}{index:03d}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(session_id: str) -> list[dict]:
    """Every recommendation of the session, in list order (empty if none)."""
    docs = doc_store.list_docs(session_id, PREFIX)
    return [docs[name] for name in sorted(docs)]


def save_suggestions(session_id: str, recommendations: list[dict], *, append: bool) -> list[dict]:
    """Store the Planner's new recommendations as pending PLAN documents. Returns the stored list
    (the whole list when appending)."""
    existing = load(session_id)
    if append:
        base = len(existing)
        stored = list(existing)
        previous: dict[str, dict] = {}
    else:
        base = 0
        stored = []
        previous = {str(r.get("name", "")).strip().lower(): r for r in existing}

    for offset, rec in enumerate(recommendations):
        index = base + offset
        doc = dict(rec)
        kept = previous.get(str(rec.get("name", "")).strip().lower())
        doc["pm_decision"] = kept.get("pm_decision", "pending") if kept else "pending"
        doc["pm_notes"] = kept.get("pm_notes", "") if kept else ""
        doc["index"] = index
        doc["proposed_at"] = _now()
        doc_store.put(session_id, doc_name(index), doc)
        stored.append(doc)

    if not append:
        # A shorter list than before: drop the leftover documents.
        for index in range(len(recommendations), len(existing)):
            doc_store.delete(session_id, doc_name(index))
    return stored


def apply_decisions(session_id: str, decisions: dict[int, tuple[str, str]]) -> list[dict]:
    """Write the PM's decisions ({index: (decision, notes)}); a recommendation with no entry goes
    back to pending. Returns the updated list."""
    recs = load(session_id)
    for i, rec in enumerate(recs):
        decision, notes = decisions.get(i, ("pending", ""))
        rec["pm_decision"] = decision
        rec["pm_notes"] = notes
        rec["decided_at"] = _now()
        doc_store.put(session_id, doc_name(i), rec)
    return recs


def accept(session_id: str, index: int, allowed_types: tuple[str, ...]) -> bool:
    """Mark one recommendation accepted (used when an analysis needs the feature it proposes).
    False if there is no such recommendation or it is not one of `allowed_types`."""
    result = {"ok": False}

    def _accept(rec: Any) -> Any:
        if not isinstance(rec, dict) or rec.get("type") not in allowed_types:
            return rec
        rec["pm_decision"] = "accepted"
        rec["decided_at"] = _now()
        result["ok"] = True
        return rec

    if doc_store.get(session_id, doc_name(index)) is None:
        return False
    doc_store.update(session_id, doc_name(index), _accept)
    return result["ok"]
