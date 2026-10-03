"""Default system prompts kept as plain text files (backend/prompts/<call_name>.txt), NOT in code.

They are the starting point `scripts/bedrock_prompts.py create` uploads to Bedrock Prompt
Management, and what a dev checkout uses when Bedrock is not configured. A deployed backend
is expected to read its prompts from Bedrock; the Docker image does not include this folder.
A file may hold `{{variable}}` placeholders that the calling code fills in.
"""
from __future__ import annotations

import re
import threading

from app.config import PROMPTS_DIR

_SAFE_NAME = re.compile(r"^[a-z0-9_]+$")
_lock = threading.Lock()
_cache: dict[str, str | None] = {}


def load(name: str) -> str | None:
    """The file's text, or None if there is no such prompt file."""
    if not _SAFE_NAME.match(name):
        raise ValueError(f"invalid prompt name {name!r}")
    with _lock:
        if name in _cache:
            return _cache[name]
    path = PROMPTS_DIR / f"{name}.txt"
    # Read as bytes so the text is returned exactly as stored (no newline translation).
    text = path.read_bytes().decode("utf-8") if path.is_file() else None
    with _lock:
        _cache[name] = text
    return text


def names() -> list[str]:
    """Names of every prompt file present."""
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.txt")) if PROMPTS_DIR.is_dir() else []


def clear_cache() -> None:
    with _lock:
        _cache.clear()
