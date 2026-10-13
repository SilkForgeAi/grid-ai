"""Quick replies: plain conversation answered in a second or two.

The full agent carries a big prompt (instructions plus every tool's description).
Sending all of that for "hey" or "what's a closure?" is slow - painfully so on a
local model. So each message first goes to the same model with a short prompt and
no tools. It either answers (streamed straight into the chat) or replies with the
WORK marker, and the message goes to the agent as usual.

Both paths share one conversation: a quick exchange is written into the agent's
history, so the agent knows what was said and the next quick reply sees what the
agent did. Quick replies can't touch anything, so they need no approvals.
"""

from __future__ import annotations

import re

WORK = "<<WORK>>"

QUICK_RULES = """\
RIGHT NOW you're replying in the chat WITHOUT tools: in this reply you can't open files, run code, test,
search the web, make documents, use the browser or the Mac, or save memories.

- Answer directly when the message is conversation, a greeting, a question you can answer from what you know,
  an explanation of a concept, advice, or a follow-up about what was already said in this chat.
  Keep it natural and concise; use Markdown (code blocks for code).
- If a good answer needs ANY tool - looking at or changing the project's files, writing or running code for them,
  building something, testing, checking current facts or the web, making a PDF/Word/Excel/PowerPoint file,
  using the browser or the Mac, remembering or forgetting something - reply with exactly <<WORK>> and nothing
  else. Grid then does the work with its tools.
- If you're unsure which, reply <<WORK>>.
- Never pretend you did something you can't do in this reply."""

_THINK_TAG = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)

# Messages that ask Grid to DO something go straight to the agent. Small local models
# are bad at sending them on themselves (they write a plan and paste code instead),
# so the quick path is only for messages that read as plain conversation.
_ACTION = re.compile(
    r"\b(build|make|create|write|code|fix|add|implement|set\s?up|install|run|deploy|host|publish|launch|"
    r"test|debug|refactor|edit|change|update|delete|remove|rename|move|search|look\s?up|google|browse|"
    r"open|save|download|upload|generate|draw|design|start|begin|continue|go\s+ahead|do\s+it|"
    r"let'?s|option|pick|choose|files?|folders?|repo|project|codebase|readme|app|apps|website|site|"
    r"web\s?page|game|script|pdf|docx?|excel|spreadsheet|powerpoint|slides|screenshot|commit|push)\b",
    re.IGNORECASE)
_GO_AHEAD = re.compile(r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|go|do it|let'?s go|sounds good|please|#?\d{1,2})\W*$",
                       re.IGNORECASE)


def needs_tools(text: str) -> bool:
    """True when the message asks for work (or says "yes"/"2" to an offer): skip the quick path."""
    return bool(_ACTION.search(text) or _GO_AHEAD.match(text))


def _strip_think(text: str) -> str:
    return _THINK_TAG.sub("", text).lstrip()


def wants_work(text: str) -> bool:
    t = text.strip()
    return WORK in t or "<<WORK" in t[:20]


def could_still_be_work(text: str) -> bool:
    """True while the reply might still turn out to be the marker."""
    t = text.strip()
    return not t or WORK.startswith(t)


def history_messages(events, *, max_chars: int = 8000, max_messages: int = 14):
    """The chat so far, as plain user/assistant turns (no tool chatter)."""
    from openhands.sdk.llm import Message, TextContent

    from grid.events import clean_reply, clean_task, is_action

    turns: list[tuple[str, str]] = []
    for e in events:
        name = type(e).__name__
        if name == "MessageEvent":
            text = "".join(getattr(c, "text", "") for c in e.llm_message.content).strip()
            if not text:
                continue
            if e.source == "user":
                text = clean_task(text)
                if text.startswith("(Running command") or text.startswith("Revise the plan"):
                    continue
                turns.append(("user", text))
            elif e.source == "agent":
                turns.append(("assistant", clean_reply(text)))
        elif is_action(e) and getattr(e, "tool_name", "") == "finish":
            msg = getattr(getattr(e, "action", None), "message", "") or ""
            if msg.strip():
                turns.append(("assistant", clean_reply(msg)))
    # merge runs of the same role (the agent may speak several times in one task)
    merged: list[list[str]] = []
    for role, text in turns:
        if merged and merged[-1][0] == role:
            merged[-1][1] += "\n\n" + text
        else:
            merged.append([role, text])
    out, total = [], 0
    for role, text in reversed(merged[-max_messages:]):
        text = text[:3000]
        if total + len(text) > max_chars and out:
            break
        total += len(text)
        out.append(Message(role=role, content=[TextContent(text=text)]))
    out.reverse()
    while out and out[0].role != "user":
        out.pop(0)
    return out


def build_messages(*, voice: str, project: str, workspace: str, history, task: str, context: str = "",
                   no_think: bool = False):
    from openhands.sdk.llm import Message, TextContent

    from grid.persona import persona_prompt
    from grid.safety import SAFETY_POLICY

    system = "\n\n".join(p for p in (
        persona_prompt(voice),
        f"You're in the project '{project}' ({workspace}).",
        context,
        QUICK_RULES,
        SAFETY_POLICY,
    ) if p)
    if no_think:
        task = f"{task} /no_think"      # Qwen3's switch for "answer without a long think"
    return [Message(role="system", content=[TextContent(text=system)]), *history,
            Message(role="user", content=[TextContent(text=task)])]


def supports_quick(llm) -> bool:
    """Real models only: scripted test models replay fixed answers and can't take a side call."""
    return type(llm).__name__ == "LLM"


def quick_llm(agent_llm):
    """The agent's model, streaming, without long thinking (a chat reply should be quick)."""
    update = {"usage_id": "grid-quick", "stream": True, "reasoning_effort": "none", "max_output_tokens": 1500}
    extra = dict(getattr(agent_llm, "litellm_extra_body", None) or {})
    if "options" in extra:                       # Ollama takes its limit as an option
        extra["options"] = {**extra["options"], "num_predict": 1500}
        update["litellm_extra_body"] = extra
    return agent_llm.model_copy(update=update)


def run_quick(llm, messages, relay=None) -> str | None:
    """The reply, or None when the message needs the agent (or the quick call failed)."""
    state = {"text": "", "shown": False}

    def on_token(chunk):
        try:
            delta = chunk.choices[0].delta
        except (AttributeError, IndexError):
            return
        if getattr(delta, "reasoning_content", None) and relay is not None and not state["shown"]:
            state.setdefault("thinking", "")
            state["thinking"] += delta.reasoning_content
            relay.set_thinking(state["thinking"])
        piece = getattr(delta, "content", None)
        if not piece:
            return
        state["text"] += piece
        visible = _strip_think(state["text"])
        if relay is None or wants_work(visible) or could_still_be_work(visible):
            return
        state["shown"] = True
        relay.set_text(visible)

    if relay is not None:
        relay.begin()
    try:
        resp = llm.completion(messages, on_token=on_token)
    except Exception:
        if relay is not None:
            relay.end()
        return None
    text = "".join(getattr(c, "text", "") for c in (resp.message.content or [])) or state["text"]
    text = _strip_think(text).strip()
    if relay is not None:
        relay.end()
    if not text or wants_work(text) or getattr(resp.message, "tool_calls", None):
        if relay is not None and state["shown"]:
            relay.cancel()
        return None
    from grid.events import clean_reply

    return clean_reply(text)
