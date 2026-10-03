"""The one LLM client: Amazon Bedrock, via the Converse API.

Every LLM call in the app -- Planner, Feature Agent, Analysis Agent, Drilldown, Audit,
Overall Analysis, Report summary -- goes through `chat_text` / `chat_json` here. Converse
gives one request/response shape for every Bedrock model, so swapping a model is just
changing the id in config.MODEL_BY_CALL (or a `MODEL_<CALL_NAME>` env var).

Compared with the OpenAI-style client this replaces:
  * there is no `response_format=json_object` mode, so JSON-returning prompts rely on the
    prompt text plus `strip_json_fence` (models often wrap JSON in ```json fences);
  * usage comes back as `usage.inputTokens / outputTokens / totalTokens`.

Prompts: `system_prompt(name, fallback, **vars)` returns the Bedrock Prompt Management text
for `name` when one is configured (BEDROCK_PROMPT_IDS), else `fallback` -- the text that
lives in the source. Any lookup failure also falls back, so a Prompt Management outage can
never take the app down.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

from app.config import (
    BEDROCK_PROMPT_IDS,
    DEFAULT_MAX_TOKENS,
    LLM_MODEL,
    PROMPT_CACHE_SECONDS,
    model_for,
)
from app.services.common import aws_clients, token_usage

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- fences
_JSON_FENCE = re.compile(r"^```[a-zA-Z]*\s*(.*?)\s*```$", re.DOTALL)
_CODE_FENCE = re.compile(r"^```[a-zA-Z0-9_+-]*\s*\n?(.*?)\n?```\s*$", re.DOTALL)


_ANY_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*(.*?)```", re.DOTALL)


def strip_json_fence(text: str) -> str:
    """Models such as Claude often wrap JSON in ```json fences -- and sometimes add a sentence
    before or after it ("Here is the plan: ..."). Return the bare JSON in all of those cases;
    text that is not recognisably JSON is returned unchanged (the caller's json.loads reports it)."""
    t = (text or "").strip()
    m = _JSON_FENCE.match(t)
    if m:
        return m.group(1).strip()
    if t[:1] in ("{", "["):
        try:
            json.loads(t)
            return t
        except ValueError:
            pass
    for block in _ANY_FENCE.findall(t):  # a fenced block with prose around it
        block = block.strip()
        if block[:1] in ("{", "["):
            return block
    starts = [i for i in (t.find("{"), t.find("[")) if i >= 0]
    if starts:  # unfenced JSON with prose around it: first opener .. last matching closer
        start = min(starts)
        end = t.rfind("}" if t[start] == "{" else "]")
        if end > start:
            candidate = t[start : end + 1]
            try:
                json.loads(candidate)
                return candidate
            except ValueError:
                pass
    return t


def strip_code_fence(text: str) -> str:
    """Same for code answers (```python ... ```), including a fenced block surrounded by prose."""
    t = (text or "").strip()
    m = _CODE_FENCE.match(t)
    if m:
        return m.group(1).strip()
    m = _ANY_FENCE.search(t)
    return m.group(1).strip() if m else t


# --------------------------------------------------------------------------- Converse
class LLMError(RuntimeError):
    """The model call succeeded at the API level but its answer is unusable (blocked by a
    content filter / guardrail, or cut off mid-JSON)."""


def _converse(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    call_name: str,
) -> tuple[str, str | None]:
    """One Converse call. Returns (text, stopReason)."""
    client = aws_clients.bedrock_runtime()
    response = client.converse(
        modelId=model,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    token_usage.record(call_name, model, response.get("usage"))
    stop = response.get("stopReason")
    if stop in ("content_filtered", "guardrail_intervened"):
        raise LLMError(f"{call_name}: the model's answer was blocked ({stop}).")
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(b.get("text", "") for b in blocks if "text" in b), stop


def chat_text(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.3,
    call_name: str = "unnamed_chat_text",
    max_tokens: int | None = None,
) -> str:
    """Single-shot call returning plain prose (or code -- strip it with strip_code_fence)."""
    model = model or model_for(call_name, LLM_MODEL)
    text, stop = _converse(system_prompt, user_prompt, model, temperature, max_tokens or DEFAULT_MAX_TOKENS, call_name)
    if stop == "max_tokens":
        log.warning("%s: answer cut off at max_tokens (%s); raise LLM_MAX_TOKENS if this recurs", call_name, max_tokens or DEFAULT_MAX_TOKENS)
    return text


def chat_json(
    system_prompt: str,
    user_prompt: str,
    model: str | None = None,
    temperature: float = 0.4,
    call_name: str = "unnamed_chat_json",
    max_tokens: int | None = None,
) -> str:
    """Single-shot call expecting a JSON object. Returns the JSON text with any code fence
    removed ("{}" if the model said nothing); the caller does `json.loads`. Raises LLMError
    when the answer was cut off at max_tokens and is no longer valid JSON, so a truncated
    answer is reported instead of being mistaken for an empty result."""
    model = model or model_for(call_name, LLM_MODEL)
    text, stop = _converse(system_prompt, user_prompt, model, temperature, max_tokens or DEFAULT_MAX_TOKENS, call_name)
    cleaned = strip_json_fence(text or "{}")
    if stop == "max_tokens":
        try:
            json.loads(cleaned)
        except ValueError as exc:
            raise LLMError(
                f"{call_name}: the answer was cut off at {max_tokens or DEFAULT_MAX_TOKENS} tokens "
                "(raise LLM_MAX_TOKENS)."
            ) from exc
    return cleaned


# --------------------------------------------------------------------------- prompts
_prompt_lock = threading.Lock()
_prompt_cache: dict[str, tuple[float, str | None]] = {}
_prompt_ids: dict[str, str] | None = None


def _configured_prompts() -> dict[str, str]:
    global _prompt_ids
    if _prompt_ids is None:
        try:
            parsed = json.loads(BEDROCK_PROMPT_IDS) if BEDROCK_PROMPT_IDS.strip() else {}
            _prompt_ids = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            log.warning("BEDROCK_PROMPT_IDS is not valid JSON; using in-source prompts")
            _prompt_ids = {}
    return _prompt_ids


def _fetch_prompt_text(identifier: str) -> str | None:
    """Fetch a Prompt Management prompt ("<ID>" or "<ID>:<VERSION>") and return its text."""
    prompt_id, _, version = identifier.partition(":")
    kwargs = {"promptIdentifier": prompt_id}
    if version:
        kwargs["promptVersion"] = version
    resp = aws_clients.bedrock_agent().get_prompt(**kwargs)
    variants = resp.get("variants") or []
    if not variants:
        return None
    cfg = variants[0].get("templateConfiguration", {})
    if "text" in cfg:
        return cfg["text"].get("text")
    if "chat" in cfg:
        system = cfg["chat"].get("system") or []
        return "\n".join(s.get("text", "") for s in system if "text" in s) or None
    return None


def system_prompt(name: str, fallback: str, **variables: object) -> str:
    """The system prompt for `name`. Uses Bedrock Prompt Management when `name` is in
    BEDROCK_PROMPT_IDS (cached for PROMPT_CACHE_SECONDS), substituting `{{var}}` placeholders
    from `variables`; otherwise -- or on any error -- returns `fallback` unchanged."""
    identifier = _configured_prompts().get(name)
    if not identifier:
        return fallback

    now = time.time()
    with _prompt_lock:
        cached = _prompt_cache.get(name)
    if cached and now - cached[0] < PROMPT_CACHE_SECONDS:
        text = cached[1]
    else:
        failed = False
        try:
            text = _fetch_prompt_text(identifier)
        except Exception as exc:  # noqa: BLE001 - never let Prompt Management break an LLM call
            log.warning("Prompt Management lookup for %s failed (%s); using in-source prompt", name, exc)
            text = None
            failed = True
        with _prompt_lock:
            # A failed lookup is only remembered briefly, so a transient error does not pin the
            # in-source prompt for the whole cache period.
            stamp = now - PROMPT_CACHE_SECONDS + 30 if failed else now
            _prompt_cache[name] = (stamp, text)

    if not text:
        return fallback
    if variables:
        # One pass, so a substituted value that itself contains "{{other}}" is left alone.
        text = re.sub(
            r"\{\{(\w+)\}\}",
            lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
            text,
        )
    return text
