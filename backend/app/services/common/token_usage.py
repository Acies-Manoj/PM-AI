"""Tracks input/output token usage for every LLM call in the pipeline.

Each LLM call (Planner, Feature Agent think/write/validate, Feature Suggester, Audit Agent,
Analysis Agent, Overall Analysis, ...) goes through `services/common/llm.py`, which calls
`record()` right after getting its Bedrock response, tagged with a `call_name` identifying
which call it was.

Usage is kept in memory for the life of the process (it backs `GET /token-usage` quickly)
AND written to the audit log as an `llm_call` event, attributed to the current user/session
(see request_context). The audit log is what survives restarts and is shared by every ECS
task, so per-task in-memory totals are only a convenience.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from app.services.common import audit_log, request_context

_lock = threading.Lock()
_records: list["TokenUsage"] = []
# The in-memory list is only a cache; keep it from growing without bound.
_MAX_RECORDS = 5000


@dataclass
class TokenUsage:
    call_name: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    timestamp: float
    user_id: str | None = None


def record(call_name: str, model: str, usage: dict[str, Any] | None) -> TokenUsage | None:
    """Store the usage block of a Bedrock Converse response (`inputTokens`, `outputTokens`,
    `totalTokens`). Returns None if there is no usage block -- callers must not fail on that."""
    if not usage:
        return None

    input_tokens = int(usage.get("inputTokens", 0) or 0)
    output_tokens = int(usage.get("outputTokens", 0) or 0)
    total = int(usage.get("totalTokens", 0) or 0) or (input_tokens + output_tokens)
    user_id = request_context.current_user_id.get()
    entry = TokenUsage(
        call_name=call_name,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
        timestamp=time.time(),
        user_id=user_id,
    )

    with _lock:
        _records.append(entry)
        if len(_records) > _MAX_RECORDS:
            del _records[: len(_records) - _MAX_RECORDS]

    audit_log.log_event(
        request_context.current_session_id.get(),
        user_id,
        "llm_call",
        {
            "call_name": call_name,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total,
        },
    )
    return entry


def get_records(user_id: str | None = None) -> list[TokenUsage]:
    with _lock:
        records = list(_records)
    if user_id is not None:
        records = [r for r in records if r.user_id == user_id]
    return records


def summary_by_call(user_id: str | None = None) -> dict[str, dict[str, int]]:
    """Aggregate call count and token totals per call_name since this process started
    (optionally only for one user)."""
    totals: dict[str, dict[str, int]] = {}
    for r in get_records(user_id):
        bucket = totals.setdefault(
            r.call_name,
            {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += r.input_tokens
        bucket["output_tokens"] += r.output_tokens
        bucket["total_tokens"] += r.total_tokens
    return totals
