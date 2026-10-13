"""Rescue tool calls that small local models write with junk after the arguments.

qwen3 and similar models often produce a complete, valid JSON object for a tool call and
then keep going (an extra brace, a second object, a stray sentence). The SDK rejects the
whole call ("Extra data ... unparseable JSON") and the model spends a slow step retrying.

Here a call whose arguments START with one complete JSON object keeps that object and
drops what follows. Nothing is guessed: arguments that are broken inside the object are
still rejected exactly as before, and every call still goes through Grid's approval rules.
"""

from __future__ import annotations

import json


def first_object(raw: str) -> dict | None:
    """The complete JSON object at the start of `raw`, if there is one."""
    text = (raw or "").lstrip()
    if not text.startswith("{"):
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def lenient(parse):
    def parse_lenient(raw_arguments: str):
        try:
            return parse(raw_arguments)
        except json.JSONDecodeError as exc:
            obj = first_object(raw_arguments)
            if obj is None:
                raise
            try:
                return parse(json.dumps(obj))
            except json.JSONDecodeError:
                raise exc from None

    parse_lenient._grid_lenient = True
    return parse_lenient


def install() -> None:
    """Wrap the SDK's argument parser once (safe to call repeatedly)."""
    try:
        import openhands.sdk.agent.agent as agent_module
    except ImportError:
        return
    current = getattr(agent_module, "parse_tool_call_arguments", None)
    if current is None or getattr(current, "_grid_lenient", False):
        return
    agent_module.parse_tool_call_arguments = lenient(current)
