"""Live replies: turn the model's token stream into what the app shows while it types.

The SDK streams raw chunks (litellm `ModelResponseStream`) from every model call.
`StreamRelay` folds them into one "segment" per call and reports, throttled:

  - thinking: the model is reasoning (we show a shimmer and the tail of it)
  - text:     plain words as they arrive (a direct reply, or what it says before using a tool)
  - final:    the `message` of a `finish` call, decoded from the half-written JSON arguments
  - tool:     which tool it is about to use

Nothing here is stored: the finished message arrives as a normal event and replaces
the live one. A relay must never break the agent, so every callback swallows errors.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable

_CONF_LINE = re.compile(r"^\s*CONFIDENCE\s*[:=].*$", re.IGNORECASE | re.MULTILINE)
_FIELD = {}


def partial_string_field(buf: str, key: str = "message") -> str | None:
    """The value of `key` in a JSON object that may still be arriving.

    '{"message": "Hel'      -> 'Hel'
    '{"message": "a\\nb", ' -> 'a\nb'
    Returns None until the key's string has started."""
    pat = _FIELD.get(key)
    if pat is None:
        pat = _FIELD[key] = re.compile('"' + re.escape(key) + r'"\s*:\s*"')
    m = pat.search(buf)
    if not m:
        return None
    out = []
    i = m.end()
    n = len(buf)
    while i < n:
        c = buf[i]
        if c == '"':
            break
        if c == "\\":
            if i + 1 >= n:
                break                      # escape not complete yet
            e = buf[i + 1]
            if e == "u":
                hexs = buf[i + 2:i + 6]
                if len(hexs) < 4:
                    break
                try:
                    out.append(chr(int(hexs, 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append({"n": "\n", "t": "\t", "r": "", "b": "\b", "f": "\f"}.get(e, e))
            i += 2
            continue
        out.append(c)
        i += 1
    text = "".join(out)
    # a surrogate pair split across chunks: drop the dangling half
    if text and 0xD800 <= ord(text[-1]) <= 0xDBFF:
        text = text[:-1]
    try:
        return text.encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError:
        return text


def strip_confidence(text: str) -> str:
    return _CONF_LINE.sub("", text).rstrip()


class StreamRelay:
    """Chunks in, throttled `emit(dict)` calls out. One instance per chat."""

    def __init__(self, emit: Callable[[dict], None], interval: float = 0.05):
        self.emit = emit
        self.interval = interval
        self._lock = threading.Lock()
        self._sid = 0
        self._reset()

    def _reset(self) -> None:
        self._text = ""
        self._thinking = ""
        self._tools: dict[int, dict] = {}
        self._last = 0.0
        self._phase = None
        self._dirty = False
        self._open = False

    # -- lifecycle -----------------------------------------------------------------
    def begin(self) -> int:
        with self._lock:
            self._sid += 1
            self._reset()
            self._open = True
            return self._sid

    def end(self) -> None:
        """A model call finished (its result arrives as a normal event): flush and close."""
        with self._lock:
            if self._open:
                self._flush(force=True)
            self._reset()

    def cancel(self) -> None:
        """Take back what was shown for the last segment (a quick reply that turned into work)."""
        with self._lock:
            sid = self._sid
            self._reset()
        try:
            self.emit({"type": "stream", "sid": sid, "phase": "cancel"})
        except Exception:
            pass

    # -- feeding -------------------------------------------------------------------
    def on_chunk(self, chunk) -> None:
        """Token callback for the SDK conversation."""
        try:
            self._on_chunk(chunk)
        except Exception:
            pass

    def _on_chunk(self, chunk) -> None:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            return
        delta = getattr(choices[0], "delta", None)
        if delta is None:
            return
        with self._lock:
            # A segment is one model call; it ends when the call's result arrives as an event
            # (end()). Chunk ids can't be used: some providers give every chunk a new one.
            if not self._open:
                self._sid += 1
                self._reset()
                self._open = True
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                self._thinking += reasoning
                self._dirty = True
            content = getattr(delta, "content", None)
            if content:
                self._text += content
                self._dirty = True
            for tc in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc, "index", 0) or 0
                slot = self._tools.setdefault(idx, {"name": "", "args": ""})
                fn = getattr(tc, "function", None)
                if fn is not None:
                    if getattr(fn, "name", None):
                        slot["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        slot["args"] += fn.arguments
                self._dirty = True
            self._flush()

    def set_text(self, text: str) -> None:
        """For callers that do their own parsing (the quick reply)."""
        with self._lock:
            if not self._open:
                self._sid += 1
                self._reset()
                self._open = True
            self._text = text
            self._dirty = True
            self._flush()

    def set_thinking(self, text: str) -> None:
        with self._lock:
            if not self._open:
                self._sid += 1
                self._reset()
                self._open = True
            self._thinking = text
            self._dirty = True
            self._flush()

    # -- output --------------------------------------------------------------------
    def _snapshot(self) -> dict | None:
        tools = [t for _, t in sorted(self._tools.items())]
        finish = next((t for t in tools if t["name"] == "finish"), None)
        if finish is not None:
            msg = partial_string_field(finish["args"], "message")
            if msg is not None:
                return {"phase": "final", "text": msg}
        named = [t["name"] for t in tools if t["name"] and t["name"] != "finish"]
        text = strip_confidence(self._text)
        if named:
            return {"phase": "tool", "tool": named[-1], "text": text}
        if text.strip():
            return {"phase": "text", "text": text}
        if self._thinking:
            return {"phase": "thinking", "text": self._thinking[-600:]}
        if finish is not None:
            return {"phase": "final", "text": ""}
        return None

    def _flush(self, force: bool = False) -> None:
        if not self._dirty:
            return
        now = time.monotonic()
        snap = self._snapshot()
        if snap is None:
            return
        if not force and snap["phase"] == self._phase and now - self._last < self.interval:
            return
        self._phase = snap["phase"]
        self._last = now
        self._dirty = False
        snap.update(type="stream", sid=self._sid)
        if self._thinking and snap["phase"] != "thinking":
            snap["thought_chars"] = len(self._thinking)
        try:
            self.emit(snap)
        except Exception:
            pass
