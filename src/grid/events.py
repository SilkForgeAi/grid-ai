"""Duck-typed readers for SDK events.

Everything Grid needs to pull out of an SDK event lives here, written against
attribute names rather than SDK classes so it is unit-testable without the SDK
(tests pass simple stand-in objects).
"""

from __future__ import annotations

from grid.rules import ActionInfo


def _flatten(content) -> str:
    """Text from a str, or from a sequence of TextContent-like items."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    parts: list[str] = []
    try:
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
    except TypeError:
        return ""
    return "\n".join(parts)


def is_action(event) -> bool:
    return hasattr(event, "tool_call_id") and hasattr(event, "thought")


def is_observation(event) -> bool:
    return hasattr(event, "observation") and hasattr(event, "action_id")


def observation_text(event) -> str:
    """Text of a tool observation (ObservationEvent.observation.content).
    Returns "" for anything that isn't a tool observation, so the agent's own
    prose can never be mistaken for test output."""
    if not is_observation(event):
        return ""
    obs = event.observation
    text = getattr(obs, "text", None)
    if isinstance(text, str):
        return text
    return _flatten(getattr(obs, "content", None))


def observation_tool(event) -> str:
    return getattr(event, "tool_name", "") or ""


def action_thought(event) -> str | None:
    """Thought text of an ActionEvent, or None if the event isn't an action."""
    thought = getattr(event, "thought", None)
    if thought is None:
        return None
    return _flatten(thought)


def action_reasoning(event) -> str | None:
    reasoning = getattr(event, "reasoning_content", None)
    return reasoning if isinstance(reasoning, str) and reasoning else None


def action_info(event) -> ActionInfo:
    """Extract tool name, command and path from an ActionEvent."""
    tool = getattr(event, "tool_name", "") or ""
    action = getattr(event, "action", None)
    command = getattr(action, "command", None)
    path = getattr(action, "path", None)
    if tool.startswith("browser_"):           # what the rules need to see
        command = getattr(action, "url", None) or getattr(action, "text", None)
    elif tool == "computer":
        parts = [getattr(action, k, None) for k in ("action", "purpose", "text", "keys")]
        command = "|".join(p if isinstance(p, str) else "" for p in parts)
    return ActionInfo(
        tool_name=tool,
        command=command if isinstance(command, str) else None,
        path=path if isinstance(path, str) else None,
    )


def describe_action(event) -> str:
    """One-line human description of what an action will do."""
    info = action_info(event)
    if info.tool_name in ("terminal", "file_editor") and not info.command and not info.path:
        return f"{info.tool_name} (the model's call couldn't be read)"   # malformed arguments
    if info.tool_name == "terminal":
        return f"$ {info.command}"
    if info.tool_name == "file_editor":
        return f"file_editor {info.command or ''} {info.path or ''}".rstrip()
    action = getattr(event, "action", None)

    def field(name: str) -> str:
        v = getattr(action, name, None)
        return v if isinstance(v, str) else ""

    if info.tool_name == "web_search":
        return f'search the web: "{field("query")[:100]}"'
    if info.tool_name == "web_fetch":
        return f"read {field('url')[:140]}"
    if info.tool_name == "create_document":
        return f'make a {field("format").upper() or "document"}: "{field("title")[:80]}" in {field("folder") or "~/Downloads"}'
    if info.tool_name == "browser_navigate":
        return f"browser: open {field('url')[:140]}"
    if info.tool_name == "browser_type":
        return f"browser: type \"{field('text')[:60]}\""
    if info.tool_name.startswith("browser_"):
        return "browser: " + info.tool_name.removeprefix("browser_").replace("_", " ")
    if info.tool_name == "computer":
        act = field("action").replace("_", " ")
        what = field("purpose") or field("app") or field("keys") or (f'"{field("text")[:40]}"' if field("text") else "")
        return f"Mac: {act}" + (f" - {what[:100]}" if what else "")
    if info.tool_name == "view_image":
        return f"look at {field('path')[-120:]}"
    if info.tool_name == "request_access":
        return f"ask to use {field('folder')}"
    if info.tool_name == "memory":
        cmd = info.command or ""
        detail = field("text") or field("id")
        return f"memory {cmd}" + (f": {detail[:100]}" if detail else "")
    return info.tool_name


_REPLY_KEYS = ("message", "response", "answer", "text", "content")


def clean_reply(text: str) -> str:
    """Small models sometimes write their finish call as text: '{"message": "Hi!"}'
    or '{"name": "finish", "arguments": {"message": "Hi!"}}'. Show just the words."""
    import json

    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`").removeprefix("json").strip()
    if not (t.startswith("{") and t.endswith("}")):
        return text
    try:
        data = json.loads(t)
    except ValueError:
        return text
    for _ in range(3):
        if not isinstance(data, dict):
            return text
        args = data.get("arguments", data.get("parameters"))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = None
        if isinstance(args, dict) and "name" in data:
            data = args
            continue
        for k in _REPLY_KEYS:
            if isinstance(data.get(k), str) and data[k].strip():
                return data[k]
        return text
    return text


def clean_task(text: str) -> str:
    """A user message as the person typed it: no voice switch, Grid notes or recalled memories."""
    from grid.persona import MODE_NOTE

    text = (text or "").removeprefix(MODE_NOTE).lstrip("\n")
    while text.startswith("Note from Grid:"):
        text = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    for marker in ("\n\nLESSONS FROM PAST SESSIONS", "\n\nFROM EARLIER CHATS"):
        text = text.split(marker, 1)[0]
    return text.strip()
