"""Per-attempt record of every generated-code run (Feature Agent and Analysis Agent).

The agents retry code generation against validator / executor feedback; without a trace the
only evidence of that is the final winning code. Each attempt is written to the audit log as a
`code_attempt` event (attempt number, which path, ok/failed, the stage that failed -- no code or
error text; the winning code is kept in the analysis cache doc), and each finished run as a
`code_run` event (total attempts, final status).

Session and user come from `request_context`, so the agents need no extra parameters. Logging
never raises (see audit_log.log_event).
"""
from __future__ import annotations

from typing import Any

from app.services.common import audit_log, request_context

_MAX_CODE_CHARS = 20_000
_MAX_TEXT_CHARS = 4_000


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def attempt(
    kind: str,
    entry: dict,
    *,
    path: str,
    attempt_no: int,
    status: str,
    stage: str | None = None,
    code: str | None = None,
    error: str | None = None,
    validation: str | None = None,
) -> None:
    """One generation attempt. `kind` is "feature" or "analysis"; `path` is "fixed_formula" or
    "generated_plan"; `status` is "ok" or "failed"; `stage` is where it failed: "generate",
    "execute", "validate" or "plausibility"."""
    audit_log.log_event(
        request_context.current_session_id.get(),
        request_context.current_user_id.get(),
        "code_attempt",
        {
            "kind": kind,
            "entry_id": entry.get("id"),
            "entry_name": entry.get("name"),
            "path": path,
            "attempt": attempt_no,
            "status": status,
            "stage": stage,
        },
    )


def fallback(kind: str, entry: dict, *, reason: str, detail: str | None = None) -> None:
    """A non-attempt event worth tracing: a cached computation that no longer fits
    ("cache_replay_failed"), a template that stopped matching ("template_failed"), or a
    template that computed the table with no generated code ("template_ok")."""
    audit_log.log_event(
        request_context.current_session_id.get(),
        request_context.current_user_id.get(),
        "code_fallback",
        {"kind": kind, "entry_id": entry.get("id"), "entry_name": entry.get("name"),
         "reason": reason, "detail": _clip(detail, _MAX_TEXT_CHARS)},
    )


def outcome(kind: str, entry: dict, *, attempts: int, status: str, error: str | None = None, extra: dict[str, Any] | None = None) -> None:
    """The finished run: total attempts (across both paths) and whether it succeeded."""
    audit_log.log_event(
        request_context.current_session_id.get(),
        request_context.current_user_id.get(),
        "code_run",
        {
            "kind": kind,
            "entry_id": entry.get("id"),
            "entry_name": entry.get("name"),
            "attempts": attempts,
            "retries": max(0, attempts - 1),
            "status": status,
            "error": _clip(error, _MAX_TEXT_CHARS),
            **(extra or {}),
        },
    )
