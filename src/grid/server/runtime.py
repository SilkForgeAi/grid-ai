"""Bridges GridSession (threaded, blocking) to the browser (async, evented).

Each project gets a ProjectRuntime: one GridSession, one worker thread for the
running task, and an event log the browser subscribes to over a websocket.
When the session needs a decision (approval, plan, regression, budget), the
worker thread blocks in WebUI.ask() until the browser answers.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import re
import threading
import time
import uuid
from collections import deque
from dataclasses import replace

from grid.config import GridConfig
from grid.events import action_info, clean_reply, describe_action, is_action, is_observation, observation_text
from grid.session import UI, GridSession, Outcome

_OPTION_RE = re.compile(r"\[(\w)\]([\w ]*?)(?=\s*/|\s*:|\s*\(|$)")
_CONF_LINE = re.compile(r"^\s*CONFIDENCE\s*[:=].*$", re.IGNORECASE | re.MULTILINE)
MAX_OBS = 8000


class EventBus:
    """Append-only event log with live subscribers (asyncio queues)."""

    def __init__(self, maxlen: int = 5000):
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def publish(self, event: dict, *, store: bool = True) -> dict:
        """store=False: live-only (typing); not replayed to a client that connects later."""
        with self._lock:
            if store:
                event = {**event, "seq": next(self._seq), "ts": time.time()}
                self._events.append(event)
            subs = list(self._subs)
        for loop, q in subs:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(q.put_nowait, event)
        return event

    def since(self, seq: int = 0) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["seq"] > seq]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.append((asyncio.get_running_loop(), q))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = [(lp, qq) for lp, qq in self._subs if qq is not q]


def parse_options(prompt: str) -> list[dict]:
    """'[y]es / [n]o / [a]lways allow YELLOW' -> buttons."""
    out = []
    for m in _OPTION_RE.finditer(prompt):
        label = (m.group(1) + m.group(2)).strip()
        out.append({"key": m.group(1), "label": label})
    return out


class WebUI(UI):
    def __init__(self, bus: EventBus):
        self.bus = bus
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()
        super().__init__(say=self._say, ask=self._ask, interactive=True)

    def _say(self, text: str) -> None:
        self.bus.publish({"type": "say", "text": text})

    def _ask(self, prompt: str) -> str:
        ask_id = uuid.uuid4().hex[:8]
        slot = {"event": threading.Event(), "answer": "", "prompt": prompt}
        with self._lock:
            self._pending[ask_id] = slot
        self.bus.publish({"type": "ask", "id": ask_id, "prompt": prompt, "options": parse_options(prompt)})
        slot["event"].wait()
        with self._lock:
            self._pending.pop(ask_id, None)
        self.bus.publish({"type": "answered", "id": ask_id, "answer": slot["answer"]})
        return slot["answer"]

    def answer(self, ask_id: str, text: str) -> bool:
        with self._lock:
            slot = self._pending.get(ask_id)
        if slot is None:
            return False
        slot["answer"] = text
        slot["event"].set()
        return True

    def pending(self) -> list[dict]:
        with self._lock:
            return [{"id": k, "prompt": v["prompt"], "options": parse_options(v["prompt"])}
                    for k, v in self._pending.items()]

    def cancel_all(self, answer: str = "q") -> None:
        with self._lock:
            ids = list(self._pending)
        for i in ids:
            self.answer(i, answer)


class ProjectRuntime:
    def __init__(self, project, base_config: GridConfig, llm_factory=None, persist: bool = True,
                 use_settings: bool = False):
        self.project = project
        self.base_config = base_config
        self.use_settings = use_settings   # the Settings page (check-in steps, depth, verify...) shapes each new chat
        self.chosen: dict = {}             # picked in this project's chat (depth, plan first): wins over Settings
        self.llm_factory = llm_factory
        self.persist = persist
        self.bus = EventBus()
        self.ui = WebUI(self.bus)
        self.session: GridSession | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_user_text: str | None = None
        self.last_report = None
        self._resumed_once = False
        from grid.stream import StreamRelay

        self.relay = StreamRelay(lambda ev: self.bus.publish(ev, store=False))

    # -- session -------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _new_config(self) -> GridConfig:
        """Config for a chat being opened: this project's toggles (autonomous, model) plus the
        current Settings, read now so a change applies to the next chat without a restart."""
        config = replace(self.base_config)
        if self.use_settings:
            from grid.settings import load_settings

            load_settings().apply(config)
        for key, value in self.chosen.items():
            setattr(config, key, value)
        return config

    def ensure_session(self, *, resume_id: str | None = None, resume_last: bool = False) -> GridSession:
        """The project's chat. With resume_last (opening the app again), pick up the
        last chat where it left off; resume_id opens a specific earlier chat."""
        with self._lock:
            if self.session is None:
                if resume_id is None and resume_last and self.persist and not self._resumed_once:
                    from grid.app import last_session_id

                    resume_id = last_session_id(self.project.path)
                self._resumed_once = True
                config = self._new_config()
                llm = self.llm_factory() if self.llm_factory else None
                session = None
                if resume_id and self.persist:
                    try:
                        session = GridSession(
                            self.project.path, config, self.ui, llm=llm, resume_id=resume_id,
                            persist=True, visualizer=None, callbacks=[self._on_sdk_event], relay=self.relay,
                        )
                    except Exception as exc:   # tools changed since, corrupt files...: start fresh
                        self.bus.publish({"type": "say", "text": f"[grid] couldn't reopen that chat ({type(exc).__name__}); starting a new one with its summary."})
                        session = None
                        llm = self.llm_factory() if self.llm_factory else None
                resumed = session is not None
                if session is None:
                    session = GridSession(
                        self.project.path, self._new_config(), self.ui, llm=llm,
                        persist=self.persist, visualizer=None, callbacks=[self._on_sdk_event], relay=self.relay,
                    )
                self.session = session
                self.bus.publish({"type": "session", "id": session.chat_id, "resumed": resumed})
                if resumed:
                    self._replay(session)
                elif resume_id:
                    self._replay_archive(resume_id, session)
            return self.session

    # -- picking up an earlier chat --------------------------------------------------
    def _replay(self, session: GridSession) -> None:
        """Show a reopened chat's history in the app."""
        from grid.longmem import ChatArchive
        from grid.persona import MODE_NOTE

        rec = ChatArchive().get(self.project.path, session.chat_id)
        turns = list(rec.turns) if rec else []
        ti = 0
        expect_task = True
        out: list[dict] = []
        for event in list(session.conversation.state.events):
            name = type(event).__name__
            if name == "MessageEvent" and event.source == "user":
                text = "".join(getattr(c, "text", "") for c in event.llm_message.content)
                if expect_task:
                    shown = turns[ti].user if ti < len(turns) else _clean_task(text, MODE_NOTE)
                    out.append({"type": "user", "text": shown, "plan": False, "replay": True,
                                "images": _save_images(event.llm_message.content)})
                    expect_task = False
                else:
                    out.append({"type": "note", "text": _clean_task(text, MODE_NOTE)[:600], "replay": True})
                continue
            ev = self._convert(event)
            if ev is None:
                continue
            ev["replay"] = True
            out.append(ev)
            if ev.get("type") == "agent":          # a finish call or a plain reply ends the turn
                t = turns[ti] if ti < len(turns) else None
                if t is not None:
                    out.append({"type": "outcome", "outcome": t.outcome or "done", "message": "", "replay": True,
                                "changed": [f"M\t{c}" for c in t.changed], "verify": None, "start_checkpoint": None})
                ti += 1
                expect_task = True
        for ev in out[-600:]:
            self.bus.publish(ev)

    def _replay_archive(self, chat_id: str, session: GridSession) -> None:
        """The chat's files are gone (or don't fit any more): show its summary and
        hand it to the new chat so Grid knows what happened."""
        from grid.longmem import ChatArchive

        rec = ChatArchive().get(self.project.path, chat_id)
        if not rec:
            return
        for t in rec.turns:
            self.bus.publish({"type": "user", "text": t.user, "plan": False, "replay": True})
            if t.reply:
                self.bus.publish({"type": "agent", "text": clean_reply(t.reply), "final": True, "replay": True})
        lines = [f"- They asked: {t.user[:300]} | You: {t.reply[:400]}" for t in rec.turns[-12:]]
        session._notes.append(f"Note from Grid: the user reopened an earlier chat ('{rec.title}'). What happened then:\n"
                              + "\n".join(lines))

    def open_chat(self, chat_id: str) -> None:
        if self.running:
            raise RuntimeError("a task is running - stop it first")
        self.new_chat()
        self.ensure_session(resume_id=chat_id)

    def new_chat(self) -> None:
        if self.running:
            raise RuntimeError("a task is running - stop it first")
        with self._lock:
            if self.session is not None:
                self.session.close()
            self.session = None
            self._resumed_once = True     # a new chat is new: don't reopen the last one
        self.bus.publish({"type": "cleared"})

    def status(self) -> dict:
        s = self.session
        cfg = s.config if s else self.base_config
        model = None
        with contextlib.suppress(Exception):
            from grid.app import effective_profile

            prof = effective_profile(cfg)
            model = {"model": prof.model, "profile": prof.name, "base_url": prof.base_url}
        return {
            "running": self.running,
            "session_id": str(s.conversation.id) if s else None,
            "pending": self.ui.pending(),
            "autonomous": cfg.autonomous,
            "allow": sorted(cfg.allow_red),
            "depth": cfg.depth.value,
            "plan_first": cfg.plan_first,
            "model": model,
            "last_outcome": self.last_report.outcome.value if self.last_report else None,
        }

    # -- tasks ---------------------------------------------------------------
    def submit(self, text: str, *, plan: bool = False, images: list[str] | None = None) -> None:
        """images: attachment ids (grid.attachments) the user added to this message."""
        text = (text or "").strip()
        images = list(images or [])
        if not text and images:
            text = "Look at this image." if len(images) == 1 else "Look at these images."
        if not text:
            raise ValueError("empty task")
        if self.running:
            raise RuntimeError("a task is already running in this project")
        self._last_user_text = text
        # Show the message and the "thinking" state at once; building the chat (first message,
        # or right after opening the app) happens in the worker.
        self.bus.publish({"type": "user", "text": text, "plan": plan, "images": [f"/api/attachments/{a}" for a in images]})
        from grid.attachments import data_url

        urls = [data_url(a) for a in images]
        self.bus.publish({"type": "status", "running": True})

        def work():
            report = None
            try:
                session = self.ensure_session()
                report = session.submit(text, plan=plan, images=urls)
                self.last_report = report
            except Exception as exc:  # never let the worker die silently
                self.bus.publish({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            finally:
                self.bus.publish({
                    "type": "outcome",
                    "outcome": report.outcome.value if report else Outcome.ERROR.value,
                    "message": (report.message if report else "")[:4000],
                    "changed": report.changed if report else [],
                    "verify": report.verify.label() if report and report.verify else None,
                    "start_checkpoint": report.start_checkpoint.id if report and report.start_checkpoint else None,
                })
                self.bus.publish({"type": "status", "running": False})
                self.bus.publish({"type": "files_changed"})

        self._thread = threading.Thread(target=work, name=f"grid-task-{self.project.id}", daemon=True)
        self._thread.start()

    def answer(self, ask_id: str, text: str) -> bool:
        return self.ui.answer(ask_id, text)

    def stop(self) -> None:
        if self.session is not None:
            self.session.stop_requested = True
            self.session.cancel_verify.set()
            with contextlib.suppress(Exception):
                self.session.conversation.pause()
        self.ui.cancel_all("q")
        self.bus.publish({"type": "say", "text": "[grid] stop requested - pausing after the current step."})

    def wait(self, timeout: float | None = None) -> bool:
        t = self._thread
        if t is not None:
            t.join(timeout)
        return not self.running

    # -- settings ------------------------------------------------------------
    def set_autonomous(self, on: bool, allow) -> None:
        session = self.ensure_session()
        if on and self.use_settings:       # the step limit and review as Settings say right now
            from grid.settings import load_settings

            st = load_settings()
            session.config.autonomous_max_steps = st.autonomous_max_steps
            session.config.self_review = st.self_review
        session.set_autonomous(on, frozenset(allow or ()))
        self.base_config.autonomous = on
        self.base_config.allow_red = frozenset(allow or ())

    def switch_model(self, profile) -> str:
        if self.running:
            raise RuntimeError("wait for the current task to finish (or stop it) before switching models")
        self.base_config.model_profile = profile
        if self.session is None:
            return f"next task uses {profile.model}"
        return self.session.switch_model(profile)

    # -- SDK events -> browser ---------------------------------------------------
    def _on_sdk_event(self, event) -> None:
        try:
            ev = self._convert(event)
            if ev:
                self.bus.publish(ev)
        except Exception as exc:
            self.bus.publish({"type": "say", "text": f"[grid] event error: {exc}"})

    def _convert(self, event) -> dict | None:
        name = type(event).__name__
        if is_action(event):
            info = action_info(event)
            thought = _CONF_LINE.sub("", "".join(getattr(t, "text", "") for t in event.thought)).strip()
            if info.tool_name == "finish":
                msg = getattr(getattr(event, "action", None), "message", "") or thought
                return {"type": "agent", "text": clean_reply(msg), "final": True}
            if info.tool_name == "think":
                return {"type": "thought", "text": getattr(getattr(event, "action", None), "thought", "") or thought}
            risk = getattr(getattr(event, "security_risk", None), "value", None)
            out = {"type": "action", "id": str(event.id), "tool": info.tool_name,
                   "summary": describe_action(event), "thought": thought, "risk": risk,
                   "command": info.command, "path": info.path}
            act = getattr(event, "action", None)
            if info.tool_name == "file_editor" and act is not None:
                out["edit"] = {k: getattr(act, k, None) for k in ("old_str", "new_str", "file_text", "insert_line")
                               if getattr(act, k, None) is not None}
                if "file_text" in out["edit"] and len(out["edit"]["file_text"]) > MAX_OBS:
                    out["edit"]["file_text"] = out["edit"]["file_text"][:MAX_OBS] + "\n..."
            return out
        if is_observation(event):
            text = observation_text(event)
            obs = event.observation
            shots = _save_images(getattr(obs, "content", None))
            shot = getattr(obs, "screenshot_data", None)      # the browser keeps its screenshot separately
            if isinstance(shot, str) and shot and not shots:
                shots = _save_screenshot(shot)
            return {"type": "observation", "action_id": str(event.action_id), "tool": event.tool_name,
                    "text": text[-MAX_OBS:] if len(text) > MAX_OBS else text,
                    "truncated": len(text) > MAX_OBS,
                    "exit_code": getattr(obs, "exit_code", None),
                    "is_error": bool(getattr(obs, "is_error", False)),
                    "file": getattr(obs, "file", None), "images": shots}
        if name == "UserRejectObservation":
            return {"type": "rejected", "action_id": str(event.action_id), "reason": event.rejection_reason}
        if name == "MessageEvent":
            msg = event.llm_message
            text = "".join(getattr(c, "text", "") for c in msg.content)
            if event.source == "agent":
                return {"type": "agent", "text": clean_reply(text)}
            if event.source == "user":
                from grid.persona import MODE_NOTE

                text = text.removeprefix(MODE_NOTE).lstrip("\n")
                if self._last_user_text and text.startswith(self._last_user_text[:200]):
                    return None  # the task itself; already shown
                if text.startswith("(Running command"):
                    return {"type": "note", "text": text.split("\n", 1)[0]}
                return {"type": "note", "text": text}
            return None
        if name in ("AgentErrorEvent", "ConversationErrorEvent"):
            detail = getattr(event, "error", None) or getattr(event, "detail", "")
            code = getattr(event, "code", "")
            if code == "MaxIterationsReached":
                return None   # the session turns this into a check-in
            return {"type": "error", "text": str(detail)[:2000]}
        return None


def _save_images(content) -> list[str]:
    """Screenshots in a tool result (browser, computer, view_image) -> app URLs."""
    urls: list[str] = []
    try:
        from grid.attachments import save_data_url

        for item in content or []:
            for u in getattr(item, "image_urls", None) or []:
                if isinstance(u, str) and u.startswith("data:image/") and len(urls) < 4:
                    urls.append(f"/api/attachments/{save_data_url(u)}")
    except Exception:
        pass
    return urls


def _save_screenshot(b64: str) -> list[str]:
    try:
        import base64

        from grid.attachments import save

        return [f"/api/attachments/{save(base64.b64decode(b64.split(',', 1)[-1]))}"]
    except Exception:
        return []


def _clean_task(text: str, mode_note: str | None = None) -> str:
    from grid.events import clean_task

    return clean_task(text)


class Runtime:
    """All project runtimes for the app."""

    def __init__(self, llm_factory=None, persist: bool = True, config_factory=None):
        self.llm_factory = llm_factory
        self.persist = persist
        # The app's own runtime takes the Settings page into account; tests pass a fixed config.
        self.use_settings = config_factory is None
        self.config_factory = config_factory or GridConfig
        self._projects: dict[str, ProjectRuntime] = {}
        self._lock = threading.Lock()

    def get(self, project) -> ProjectRuntime:
        with self._lock:
            rt = self._projects.get(project.id)
            if rt is None:
                rt = ProjectRuntime(project, self.config_factory(), self.llm_factory, self.persist,
                                    use_settings=self.use_settings)
                self._projects[project.id] = rt
            return rt

    def peek(self, pid: str) -> ProjectRuntime | None:
        return self._projects.get(pid)

    def shutdown(self) -> None:
        for rt in list(self._projects.values()):
            rt.stop()
            if rt.session is not None:
                rt.session.close()


class Jobs:
    """Background jobs (model tests, verify runs) the UI polls."""

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, fn) -> str:
        jid = uuid.uuid4().hex[:10]
        with self._lock:
            self._jobs[jid] = {"id": jid, "kind": kind, "status": "running", "started": time.time()}

        def run():
            try:
                result = fn()
                upd = {"status": "done", "result": result}
            except Exception as exc:
                upd = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            with self._lock:
                self._jobs[jid].update(upd, finished=time.time())

        threading.Thread(target=run, daemon=True).start()
        return jid

    def get(self, jid: str) -> dict | None:
        with self._lock:
            j = self._jobs.get(jid)
            return dict(j) if j else None
