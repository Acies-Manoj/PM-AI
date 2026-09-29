"""AI agent that looks at the audited dataframe's columns/dtypes and
proposes new chart-worthy analyses -- the "ai_suggested" source in the
analysis repository (see analysis_repository.py). It only picks WHICH
columns/aggregations to explore and describes the analysis in plain
English; it never computes a value itself -- the Analysis Agent
(analysis_agent.py) is what actually plans, writes, and executes the code
for whatever gets accepted. Runs on OpenRouter, never Groq. Anything
referencing a column that doesn't exist in the current data (a
hallucination) is dropped rather than surfaced, since a broken suggestion
is worse than a missing one.
"""
import json
import logging
import re
from collections.abc import Iterable

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import OPENROUTER_MODEL
from app.prompts.analysis_suggester import MAX_SUGGESTIONS, SYSTEM_PROMPT
from app.services.analysis.analysis_columns import column_catalog
from app.services.common import token_usage
from app.services.common.entry_repository import normalize_name as _normalize_name
from app.services.common.llm_client import get_client

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 45.0
# One retry covers the common transient failure: the model returning
# truncated or non-JSON output. A second failure means give up quietly.
MAX_ATTEMPTS = 2

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class _Suggestion(BaseModel):
    """Shape one LLM suggestion must satisfy before it reaches the
    repository. Anything that fails validation is dropped, not repaired."""

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    calculation_intent: str = Field(min_length=1)
    input_columns: list[str] = Field(min_length=1)

    @field_validator("name", "calculation_intent", mode="before")
    @classmethod
    def _strip_required(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before")
    @classmethod
    def _strip_optional(cls, value):
        if value is None:
            return ""
        return value.strip() if isinstance(value, str) else value

    @field_validator("input_columns", mode="before")
    @classmethod
    def _dedupe_columns(cls, value):
        # Models sometimes return a lone column as a bare string.
        if isinstance(value, str):
            value = [value]
        if isinstance(value, list) and all(isinstance(c, str) for c in value):
            # Column names are NOT stripped: a real header may carry
            # whitespace, and it must match the dataframe exactly.
            return list(dict.fromkeys(value))
        return value


def _existing_block(existing_entries: Iterable[dict]) -> str:
    lines = [
        f"- {e['name']}: {e.get('calculation_intent') or e.get('description') or ''}".rstrip(": ")
        for e in existing_entries
        if e.get("name")
    ]
    return "\n".join(lines) if lines else "(none yet)"


def _parse_candidates(raw: str) -> list | None:
    """Returns the raw suggestion list, or None if the output is unusable."""
    try:
        payload = json.loads(_CODE_FENCE.sub("", raw))
    except json.JSONDecodeError:
        return None
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("suggestions"), list):
        return payload["suggestions"]
    return None


def _validate(candidates: list, available_columns: set[str], existing_names: set[str]) -> list[dict]:
    """Pure filter from raw LLM output to repository-ready dicts: drops
    malformed specs, hallucinated columns, and names that duplicate an
    existing entry or an earlier suggestion in the same batch."""
    seen = set(existing_names)
    suggestions: list[dict] = []
    dropped = {"malformed": 0, "unknown_column": 0, "duplicate": 0}

    for spec in candidates:
        try:
            suggestion = _Suggestion.model_validate(spec)
        except ValidationError:
            dropped["malformed"] += 1
            continue
        if not set(suggestion.input_columns).issubset(available_columns):
            dropped["unknown_column"] += 1
            continue
        key = _normalize_name(suggestion.name)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        suggestions.append(suggestion.model_dump())
        if len(suggestions) == MAX_SUGGESTIONS:
            break

    if any(dropped.values()):
        logger.info("analysis_suggester kept %d of %d suggestions; dropped %s", len(suggestions), len(candidates), dropped)
    return suggestions


def suggest_analyses(df: pd.DataFrame, existing_entries: Iterable[dict] = ()) -> list[dict]:
    """Returns repository-shaped candidate dicts: name, description,
    calculation_intent, input_columns -- ready to hand to
    analysis_repository.add_ai_suggested_entries. `existing_entries` are the
    repository's current entries, shown to the model so it proposes
    genuinely new ideas and used to filter out any repeats it still makes."""
    existing_entries = list(existing_entries)
    client = get_client().with_options(timeout=REQUEST_TIMEOUT_S)
    user_prompt = (
        f"Columns:\n{column_catalog(df)}\n\n"
        f"Existing analyses (do not repeat these):\n{_existing_block(existing_entries)}\n\n"
        "Propose the analyses now."
    )

    candidates = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            temperature=0.4,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        token_usage.record("analysis_suggester", OPENROUTER_MODEL, response)
        candidates = _parse_candidates(response.choices[0].message.content or "")
        if candidates is not None:
            break
        logger.warning("analysis_suggester got unparseable output (attempt %d/%d)", attempt, MAX_ATTEMPTS)

    if candidates is None:
        return []

    existing_names = {_normalize_name(e["name"]) for e in existing_entries if e.get("name")}
    return _validate(candidates, set(df.columns.astype(str)), existing_names)
