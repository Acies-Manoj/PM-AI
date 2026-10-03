"""Compatibility shim: the LLM client now lives in `llm.py` (Amazon Bedrock).

The module name is a leftover from the Groq days. It only re-exports the public names so
existing `from app.services.common.groq_client import chat_json` imports keep working; new
code should import from `app.services.common.llm` directly.
"""
from app.services.common.llm import (  # noqa: F401
    chat_json,
    chat_text,
    strip_code_fence,
    strip_json_fence,
    system_prompt,
)
