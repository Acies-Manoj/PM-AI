"""OpenRouter chat client -- the one place every LLM call in the pipeline goes
through. OpenRouter exposes an OpenAI-compatible Chat Completions API, so this
wraps the `openai` SDK pointed at OpenRouter's base URL instead of a bespoke
HTTP client.

Three ways to call a model, from simplest to most capable:
  - chat_text()      plain prose in, plain prose out
  - chat_json()      forces a single JSON object response
  - run_agent_loop()  real function-calling: the model picks tools, we execute
                      them locally against real data, feed results back, and
                      it keeps going until it calls a designated "finish" tool
                      (or, absent one, stops emitting tool calls at all)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import OpenAI

from app.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        if not OPENROUTER_API_KEY:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not set. Paste your key from "
                "https://openrouter.ai/keys into backend/.env"
            )
        _client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=OPENROUTER_API_KEY)
    return _client


def chat_text(system_prompt: str, user_prompt: str, model: str, temperature: float = 0.3) -> str:
    """Single-shot call returning plain prose."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


def chat_json(system_prompt: str, user_prompt: str, model: str, temperature: float = 0.2) -> dict:
    """Single-shot call constrained to a JSON object response. Returns {} on
    a malformed response rather than raising -- callers decide the fallback."""
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    raw = response.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


@dataclass
class ToolSpec:
    """One callable an agent may invoke, described as an OpenAI-style function
    tool. `handler` is called locally with the arguments the model chose --
    it never runs model-generated code, only the Python we wrote here."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the function's arguments
    handler: Callable[..., Any]

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class AgentTrace:
    """What happened during a tool-calling run."""

    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_text: str = ""
    # Populated only when the loop ended via `finish_tool` -- the arguments
    # the model passed to it, i.e. the agent's structured final answer.
    final_args: dict[str, Any] | None = None


def run_agent_loop(
    system_prompt: str,
    user_prompt: str,
    tools: list[ToolSpec],
    model: str,
    *,
    finish_tool: str | None = None,
    temperature: float = 0.2,
    max_iterations: int = 6,
) -> AgentTrace:
    """A real ReAct loop: the model chooses tools, we execute them locally,
    feed the results back as `tool` messages, and let it keep going.

    If `finish_tool` is given, the loop ends the moment the model calls that
    tool and its arguments are returned as `final_args` -- this is how an
    agent hands back a typed, structured result instead of free-form text.
    Otherwise the loop ends when the model responds with no tool calls at
    all, and that response is returned as `final_text`.
    """
    client = get_client()
    tool_map = {t.name: t for t in tools}
    openai_tools = [t.to_openai_tool() for t in tools]

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    trace: list[dict[str, Any]] = []

    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            return AgentTrace(tool_calls=trace, final_text=message.content or "")

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        finished_args: dict[str, Any] | None = None
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if finish_tool and tc.function.name == finish_tool:
                finished_args = args
                result: Any = {"status": "received"}
            else:
                spec = tool_map.get(tc.function.name)
                if spec is None:
                    result = {"error": f"Unknown tool '{tc.function.name}'"}
                else:
                    try:
                        result = spec.handler(**args)
                    except Exception as exc:  # noqa: BLE001
                        result = {"error": str(exc)}

            trace.append({"tool": tc.function.name, "args": args, "result": result})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

        if finished_args is not None:
            return AgentTrace(tool_calls=trace, final_text="", final_args=finished_args)

    # Out of iterations -- one last plain-text attempt, no tools offered.
    response = client.chat.completions.create(model=model, temperature=temperature, messages=messages)
    return AgentTrace(tool_calls=trace, final_text=response.choices[0].message.content or "")
