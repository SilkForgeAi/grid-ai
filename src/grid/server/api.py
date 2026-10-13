"""HTTP + websocket API for the Grid app (Starlette, bound to 127.0.0.1).

Security model (the app can run commands on your machine):
  - listens on 127.0.0.1 only; requests with any other Host are refused
    (blocks DNS-rebinding);
  - a random session token is set as an HttpOnly, SameSite=Strict cookie
    when you open the link Grid prints; every API call needs that cookie;
  - state-changing calls also need the `X-Grid: 1` header, which other web
    pages can't send without a CORS preflight (which is never granted);
  - the websocket checks the cookie and the Origin.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import re
from dataclasses import asdict
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from grid import __version__ as GRID_VERSION
from grid.execution import project_execution
from grid.learning import STARTERS
from grid.server.projects import TEMPLATES, FileOps, ProjectError, ProjectRegistry, browse_dirs
from grid.server.runtime import Jobs, Runtime

STATIC = Path(__file__).parent / "static"
COOKIE = "grid_token"


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def create_app(*, token: str, port: int, runtime: Runtime | None = None,
               registry: ProjectRegistry | None = None, scheduler=None) -> Starlette:
    runtime = runtime or Runtime()
    registry = registry or ProjectRegistry()
    jobs = Jobs()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    # ---------------------------------------------------------------- helpers
    def authed(request) -> bool:
        got = request.cookies.get(COOKIE, "")
        return bool(got) and hmac.compare_digest(got, token)

    def host_ok(request) -> bool:
        return request.headers.get("host", "") in allowed_hosts

    def guard(handler, *, mutating: bool = False):
        async def wrapped(request: Request):
            if not host_ok(request):
                return JSONResponse({"error": "bad host"}, status_code=403)
            if not authed(request):
                return JSONResponse({"error": "not signed in - open the link `grid app` printed"}, status_code=401)
            if mutating and request.headers.get("x-grid") != "1":
                return JSONResponse({"error": "missing X-Grid header"}, status_code=403)
            try:
                writes_project = mutating and request.path_params.get("pid") and (
                    request.url.path.endswith(("/file", "/replace", "/undo")) or "/files/" in request.url.path)
                lock = project_execution(project_of(request).path) if writes_project else contextlib.nullcontext()
                with lock:
                    result = await handler(request)
            except ApiError as exc:
                return JSONResponse({"error": str(exc)}, status_code=exc.status)
            except (ProjectError, ValueError, KeyError, IndexError, FileNotFoundError) as exc:
                msg = exc.args[0] if exc.args else str(exc)
                return JSONResponse({"error": str(msg)}, status_code=400)
            except RuntimeError as exc:
                return JSONResponse({"error": str(exc)}, status_code=409)
            if isinstance(result, Response):
                return result
            return JSONResponse(result)
        return wrapped

    async def body(request) -> dict:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("request body must be JSON") from exc
        if not isinstance(data, dict):
            raise ApiError("request body must be a JSON object")
        return data

    def project_of(request):
        return registry.get(request.path_params["pid"])

    def rt_of(request):
        return runtime.get(project_of(request))

    def files_of(request) -> FileOps:
        return FileOps(project_of(request).path)

    def checkpoint(request, label: str) -> None:
        """Snapshot before a user edit in the app, so it can be undone too."""
        with contextlib.suppress(Exception):
            from grid.checkpoints import CheckpointStore

            CheckpointStore(project_of(request).path).snapshot(label)

    # ---------------------------------------------------------------- pages
    async def index(request: Request):
        if not host_ok(request):
            return Response("bad host", status_code=403)
        q = request.query_params.get("token")
        if q:
            if not hmac.compare_digest(q, token):
                return HTMLResponse(_signin_page("That link has expired. Use the link `grid app` printed most recently."), 401)
            resp = RedirectResponse("/", status_code=303)
            resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return resp
        if not authed(request):
            return HTMLResponse(_signin_page("Open the link that `grid app` printed in your terminal."), 401)
        csp = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
               "font-src 'self' data:; worker-src 'self' blob:; "
               f"connect-src 'self' ws://127.0.0.1:{port} ws://localhost:{port}; frame-ancestors 'none'; "
               "base-uri 'none'; form-action 'self'")
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store", "Content-Security-Policy": csp,
                                                            "X-Content-Type-Options": "nosniff"})

    # ---------------------------------------------------------------- state
    async def state(request):
        from grid.models import ModelStore
        from grid.moderation import restricted_mode
        from grid.settings import load_settings

        st = load_settings()
        try:
            default_model = ModelStore().default_name()
        except Exception:
            default_model = None
        from grid.persona import PersonaStore

        return {"execution_mode": "restricted" if restricted_mode() else "trusted-host",
                "version": GRID_VERSION, "home": str(Path.home()), "settings": asdict(st),
                "persona": PersonaStore().load().to_dict(),
                "projects": [p.to_dict() for p in registry.list()], "templates": list(TEMPLATES),
                "starters": list(STARTERS),
                "default_model": default_model}

    # ---------------------------------------------------------------- projects
    async def projects_list(request):
        return {"projects": [p.to_dict() for p in registry.list()]}

    async def projects_create(request):
        from grid.settings import load_settings

        b = await body(request)
        root = b.get("location") or load_settings().projects_root
        p = registry.create(str(b.get("name", "")), root, git_init=bool(b.get("git_init", True)),
                            template=b.get("template") or "empty")
        return {"project": p.to_dict()}

    async def projects_open(request):
        b = await body(request)
        return {"project": registry.open(str(b.get("path", ""))).to_dict()}

    async def projects_forget(request):
        pid = request.path_params["pid"]
        rt = runtime.peek(pid)
        if rt and rt.running:
            raise ApiError("stop the running task first", 409)
        registry.forget(pid)
        return {"ok": True}

    async def fs_browse(request):
        return browse_dirs(request.query_params.get("path"))

    # ---------------------------------------------------------------- files
    async def tree(request):
        registry.touch(request.path_params["pid"])
        return {"entries": files_of(request).tree(request.query_params.get("path", ""),
                                                   request.query_params.get("hidden") == "1")}

    async def file_read(request):
        return files_of(request).read(request.query_params.get("path", ""))

    async def file_write(request):
        b = await body(request)
        if "expected_version" in b:
            path = files_of(request).resolve(str(b.get("path", "")))
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if current != b["expected_version"]:
                raise ApiError("This file changed on disk. Compare or reload it before saving.", 409)
        checkpoint(request, f"before you edited {b.get('path')}")
        files_of(request).write(str(b.get("path", "")), str(b.get("text", "")))
        checkpoint(request, f"you edited {b.get('path')}")
        return {"ok": True, "version": hashlib.sha256(str(b.get("text", "")).encode()).hexdigest()}

    async def file_at(request):
        from grid.checkpoints import CheckpointStore

        store = CheckpointStore(project_of(request).path)
        ref = request.query_params.get("ref", "")
        path = request.query_params.get("path", "")
        files_of(request).resolve(path)  # containment check
        text = await asyncio.to_thread(store.read_at, ref, path)
        return {"path": path, "ref": ref, "exists": text is not None, "text": text or ""}

    async def file_revert(request):
        from grid.checkpoints import CheckpointStore

        b = await body(request)
        rt = runtime.peek(request.path_params["pid"])
        if rt and rt.running:
            raise ApiError("stop the running task before reverting files", 409)
        path = str(b.get("path", ""))
        files_of(request).resolve(path)
        store = CheckpointStore(project_of(request).path)
        result = await asyncio.to_thread(store.restore_file, str(b.get("ref", "")), path)
        if rt:
            rt.bus.publish({"type": "files_changed"})
        return {"ok": True, "result": result}

    async def files_index(request):
        from grid.server.search import list_files

        return await asyncio.to_thread(list_files, project_of(request).path)

    async def search_files(request):
        from grid.server.search import Query, search

        b = await body(request)
        return await asyncio.to_thread(search, project_of(request).path, Query.from_dict(b))

    async def replace_files(request):
        from grid.server.search import Query, replace

        b = await body(request)
        rt = runtime.peek(request.path_params["pid"])
        if rt and rt.running:
            raise ApiError("stop the running task before replacing across files", 409)
        q = Query.from_dict(b)
        q.compile()  # bad patterns fail before the checkpoint
        only = b.get("only")
        paths = b.get("paths")
        if only is not None and not isinstance(only, list):
            raise ApiError("only must be a list")
        if paths is not None and not isinstance(paths, list):
            raise ApiError("paths must be a list")
        fo = files_of(request)
        for rel in [str(o.get("path", "")) for o in (only or []) if isinstance(o, dict)] + [str(x) for x in (paths or [])]:
            fo.resolve(rel)  # containment check before touching anything
        what = f"replace '{q.text[:40]}'"
        checkpoint(request, f"before {what}")
        result = await asyncio.to_thread(replace, project_of(request).path, q, str(b.get("replace", "")),
                                         paths=[str(x) for x in paths] if paths is not None else None, only=only or None)
        if result["replacements"]:
            checkpoint(request, f"{what} -> '{str(b.get('replace', ''))[:40]}' ({result['replacements']} in {len(result['files_changed'])} files)")
        if rt:
            rt.bus.publish({"type": "files_changed"})
        return result

    async def file_op(request):
        op = request.path_params["op"]
        b = await body(request)
        fo = files_of(request)
        path = str(b.get("path", ""))
        if op == "new":
            fo.new_file(path)
        elif op == "mkdir":
            fo.mkdir(path)
        elif op == "rename":
            checkpoint(request, f"before renaming {path}")
            fo.rename(path, str(b.get("to", "")))
        elif op == "delete":
            checkpoint(request, f"before deleting {path}")
            where = fo.delete(path)
            return {"ok": True, "trashed_to": where}
        else:
            raise ApiError(f"unknown file operation {op!r}", 404)
        return {"ok": True}

    # ---------------------------------------------------------------- agent
    async def session_status(request):
        return rt_of(request).status()

    async def task_submit(request):
        b = await body(request)
        rt = rt_of(request)
        imgs = b.get("images") or []
        if not isinstance(imgs, list) or len(imgs) > 6:
            raise ApiError("attach up to 6 images")
        from grid.attachments import AttachmentError, save_data_url

        try:
            ids = [save_data_url(str(u)) for u in imgs]
        except AttachmentError as exc:
            raise ApiError(str(exc)) from exc
        rt.submit(str(b.get("text", "")), plan=bool(b.get("plan", False)), images=ids)
        return {"ok": True}

    async def task_answer(request):
        b = await body(request)
        if not rt_of(request).answer(str(b.get("id", "")), str(b.get("text", ""))):
            raise ApiError("that question was already answered", 409)
        return {"ok": True}

    async def task_stop(request):
        rt_of(request).stop()
        return {"ok": True}

    async def new_chat(request):
        rt_of(request).new_chat()
        return {"ok": True}

    async def autonomous(request):
        from grid.autonomy import describe_mode, parse_allow

        b = await body(request)
        on = bool(b.get("on"))
        allow = parse_allow(b.get("allow") or [])
        if on and b.get("confirm") != "yes":
            raise ApiError("autonomous mode needs confirm: 'yes' from the user")
        rt = rt_of(request)
        await asyncio.to_thread(rt.set_autonomous, on, allow)
        return {"ok": True, "description": describe_mode(allow) if on else None}

    async def autonomy_info(request):
        from grid.autonomy import describe_mode
        from grid.rules import ALLOWABLE_RED, HARD_BLOCKED_RED
        from grid.settings import load_settings

        st = load_settings()
        return {"allowable": ALLOWABLE_RED, "hard_blocked": HARD_BLOCKED_RED, "max_steps": st.autonomous_max_steps,
                "self_review": st.self_review,
                "description": describe_mode(frozenset(), st.autonomous_max_steps, st.self_review)}

    async def undo(request):
        b = await body(request)
        rt = rt_of(request)
        if rt.running:
            raise ApiError("stop the running task before undoing", 409)
        session = await asyncio.to_thread(rt.ensure_session)
        msg = session.undo(b.get("ref"))
        rt.bus.publish({"type": "say", "text": f"[grid][undo] {msg}"})
        rt.bus.publish({"type": "files_changed"})
        return {"ok": True, "message": msg}

    async def checkpoints(request):
        from grid.checkpoints import CheckpointStore

        store = CheckpointStore(project_of(request).path)
        head = store.head()
        return {"checkpoints": [asdict(c) | {"head": c.sha == head} for c in reversed(store.list())]}

    async def diff(request):
        from grid.checkpoints import CheckpointStore

        store = CheckpointStore(project_of(request).path)
        cps = store.list()
        ref = request.query_params.get("ref")
        rt = runtime.peek(request.path_params["pid"])
        if ref:
            base = store.get(ref)
        elif rt and rt.last_report and rt.last_report.start_checkpoint:
            base = rt.last_report.start_checkpoint
        else:
            base = cps[0] if cps else None
        if base is None:
            return {"base": None, "diff": "", "files": []}
        text = await asyncio.to_thread(store.diff, base.sha)
        return {"base": asdict(base), "diff": text[:400_000], "files": store.changed_files(base.sha)}

    async def set_model(request):
        from grid.models import ModelProfile, ModelStore

        b = await body(request)
        if b.get("profile"):
            prof = ModelStore().get(str(b["profile"]))
        elif b.get("model"):
            prof = ModelProfile(name="adhoc", model=str(b["model"]), base_url=b.get("base_url") or None)
            prof.validate()
        else:
            raise ApiError("give a profile or a model")
        msg = await asyncio.to_thread(rt_of(request).switch_model, prof)
        return {"ok": True, "message": msg}

    async def project_settings(request):
        from grid.teaching import DepthLevel

        b = await body(request)
        rt = rt_of(request)
        cfgs = [rt.base_config] + ([rt.session.config] if rt.session else [])
        for cfg in cfgs:
            if "depth" in b:
                cfg.depth = DepthLevel(b["depth"])
            if "plan_first" in b:
                cfg.plan_first = bool(b["plan_first"])
        if "depth" in b:
            rt.chosen["depth"] = DepthLevel(b["depth"])
        if "plan_first" in b:
            rt.chosen["plan_first"] = bool(b["plan_first"])
        return rt.status()

    async def verify_now(request):
        from grid.project import detect_verify_command
        from grid.verify import run_verify

        path = project_of(request).path
        cmd = detect_verify_command(path)
        if not cmd:
            raise ApiError("no check found - add `verify: <command>` to GRID.md")
        def check():
            with project_execution(path):
                return _verify_result(run_verify(cmd, path))

        jid = jobs.start("verify", check)
        return {"job": jid}

    async def memory_list(request):
        from grid.memory import MemoryStore

        store = MemoryStore.for_workspace(project_of(request).path)
        return {"episodes": [asdict(e) | {"index": i} for i, e in enumerate(store.all())]}

    async def memory_delete(request):
        from grid.memory import MemoryStore

        store = MemoryStore.for_workspace(project_of(request).path)
        store.delete(int(request.path_params["index"]))
        return {"ok": True}

    async def commands(request):
        from grid.plugins import PluginManager

        builtin = [
            {"slash": "/plan", "description": "plan first, then execute after you approve", "builtin": True},
            {"slash": "/undo", "description": "restore the previous checkpoint", "builtin": True},
            {"slash": "/verify", "description": "run the project's check now", "builtin": True},
            {"slash": "/new", "description": "start a new chat", "builtin": True},
        ]
        from grid.lessons import COMMANDS as LESSONS

        builtin += [{"slash": f"/{c.name}", "argument_hint": c.usage.partition(" ")[2] or None,
                     "description": c.description, "builtin": True} for c in LESSONS]
        plug = [asdict(c) | {"slash": c.slash} for c in PluginManager(project_of(request).path).commands()]
        return {"commands": builtin + plug}

    # ---------------------------------------------------------------- websocket
    async def events_ws(ws: WebSocket):
        origin = ws.headers.get("origin", "")
        got = ws.cookies.get(COOKIE, "")
        if (ws.headers.get("host", "") not in allowed_hosts or origin not in allowed_origins
                or not got or not hmac.compare_digest(got, token)):
            await ws.close(code=4403)
            return
        try:
            project = registry.get(ws.path_params["pid"])
        except ProjectError:
            await ws.close(code=4404)
            return
        rt = runtime.get(project)
        await ws.accept()
        if rt.session is None and not rt._resumed_once and not rt.running:
            # opening the project again: pick the last chat back up (in the background)
            asyncio.get_running_loop().run_in_executor(None, _resume_quietly, rt)
        try:
            since = int(ws.query_params.get("since", "0") or 0)
        except ValueError:
            since = 0
        q = rt.bus.subscribe()

        async def pump():
            for ev in rt.bus.since(since):
                await ws.send_json(ev)
            await ws.send_json({"type": "hello", "status": rt.status()})
            while True:
                await ws.send_json(await q.get())

        sender = asyncio.create_task(pump())
        try:
            # Watch for the browser going away; otherwise a quiet project would keep a dead
            # subscriber (and its ever-growing queue) forever.
            while not sender.done():
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender
            rt.bus.unsubscribe(q)

    async def pty_ws(ws: WebSocket):
        from grid.server.pty import serve_pty

        origin = ws.headers.get("origin", "")
        got = ws.cookies.get(COOKIE, "")
        if (ws.headers.get("host", "") not in allowed_hosts or origin not in allowed_origins
                or not got or not hmac.compare_digest(got, token)):
            await ws.close(code=4403)
            return
        try:
            project = registry.get(ws.path_params["pid"])
        except ProjectError:
            await ws.close(code=4404)
            return
        from grid.moderation import restricted_mode

        if restricted_mode():
            await ws.close(code=4403, reason="Host terminal disabled in restricted mode")
            return
        await ws.accept()
        await serve_pty(ws, project.path)

    # ---------------------------------------------------------------- plugins
    def plugin_mgr(request):
        from grid.plugins import PluginManager

        pid = request.query_params.get("project")
        return PluginManager(registry.get(pid).path if pid else None)

    async def plugins_list(request):
        return {"plugins": [i.to_dict() for i in plugin_mgr(request).list()]}

    async def plugins_catalog(request):
        from grid.plugins import builtin_catalog

        installed = {(i.name) for i in plugin_mgr(request).list()}
        return {"plugins": [i.to_dict() | {"installed": i.name in installed} for i in builtin_catalog()]}

    async def plugins_preview(request):
        b = await body(request)
        info = await asyncio.to_thread(plugin_mgr(request).preview, str(b.get("source", "")))
        return {"plugin": info.to_dict()}

    async def plugins_install(request):
        b = await body(request)
        info = await asyncio.to_thread(plugin_mgr(request).install, str(b.get("source", "")),
                                       scope=b.get("scope") or "user", replace=bool(b.get("replace")))
        return {"plugin": info.to_dict(), "note": "applies to new chats"}

    async def plugins_enable(request):
        b = await body(request)
        plugin_mgr(request).set_enabled(request.path_params["name"], bool(b.get("enabled", True)), b.get("scope"))
        return {"ok": True}

    async def plugins_remove(request):
        plugin_mgr(request).remove(request.path_params["name"], request.query_params.get("scope"))
        return {"ok": True}

    # ---------------------------------------------------------------- models
    async def models_list(request):
        from grid.models import ModelStore, resolve_profile

        store = ModelStore()
        current, source = resolve_profile(store=store)
        return {"profiles": [asdict(p) | {"local": p.is_local()} for p in store.list()],
                "default": store.default_name(), "current": asdict(current) | {"source": source}}

    async def models_add(request):
        from grid.models import ModelProfile, ModelStore

        b = await body(request)
        prof = ModelProfile(name=str(b.get("name", "")), model=str(b.get("model", "")),
                            base_url=b.get("base_url") or None, api_key_env=b.get("api_key_env") or None,
                            native_tool_calling=not bool(b.get("prompted_tools")), note=str(b.get("note", "")),
                            think=bool(b.get("think")))
        ModelStore().add(prof, make_default=bool(b.get("default")), replace=bool(b.get("replace")))
        return {"ok": True}

    async def models_remove(request):
        from grid.models import ModelStore

        ModelStore().remove(request.path_params["name"])
        return {"ok": True}

    async def models_think(request):
        from grid.models import ModelStore

        on = bool((await body(request)).get("on"))
        ModelStore().set_think(request.path_params["name"], on)
        return {"ok": True, "think": on, "note": "applies to new chats"}

    async def models_default(request):
        from grid.models import ModelStore

        ModelStore().set_default(request.path_params["name"])
        return {"ok": True}

    async def models_test(request):
        from grid.models import ModelStore
        from grid.probe import format_result, run_probe

        name = request.path_params["name"]
        store = ModelStore()
        prof = store.get(name)

        def work():
            res = run_probe(prof, llm=runtime.llm_factory() if runtime.llm_factory else None)
            store.record_compat(name, res.to_record())
            return {"verdict": res.verdict, "report": format_result(prof, res), "record": res.to_record()}

        return {"job": jobs.start("model-test", work)}

    async def job_get(request):
        j = jobs.get(request.path_params["jid"])
        if j is None:
            raise ApiError("no such job", 404)
        return j

    # ---------------------------------------------------------------- schedules
    async def schedules_list(request):
        from grid.schedules import Cron, ScheduleStore

        out = []
        for s in ScheduleStore().list():
            out.append(asdict(s) | {"cron_text": Cron.parse(s.cron).describe()})
        return {"schedules": out}

    async def schedules_add(request):
        from grid.schedules import ScheduleStore

        b = await body(request)
        project = registry.get(str(b.get("project", "")))
        s = ScheduleStore().add(name=str(b.get("name", "")), project=project.path, prompt=str(b.get("prompt", "")),
                                cron=str(b.get("cron", "")), mode=b.get("mode") or "headless",
                                allow=list(b.get("allow") or []), model_profile=b.get("model_profile") or None)
        return {"schedule": asdict(s)}

    async def schedules_remove(request):
        from grid.schedules import ScheduleStore

        ScheduleStore().remove(request.path_params["sid"])
        return {"ok": True}

    async def schedules_enable(request):
        from grid.schedules import ScheduleStore

        b = await body(request)
        s = ScheduleStore().set_enabled(request.path_params["sid"], bool(b.get("enabled", True)))
        return {"schedule": asdict(s)}

    async def schedules_run(request):
        from grid.schedules import ScheduleStore, run_schedule

        store = ScheduleStore()
        s = store.get(request.path_params["sid"])
        llm = runtime.llm_factory() if runtime.llm_factory else None
        return {"job": jobs.start("schedule-run", lambda: run_schedule(store, s, llm=llm))}

    async def schedules_runs(request):
        from grid.schedules import ScheduleStore

        runs = ScheduleStore().runs(request.path_params["sid"])
        return {"runs": list(reversed(runs[-50:]))}

    async def schedules_log(request):
        from grid.schedules import ScheduleStore

        store = ScheduleStore()
        s = store.get(request.path_params["sid"])
        runs = store.runs(s.id)
        log = request.query_params.get("log")
        wanted = next((r for r in runs if r.get("log") == log), runs[-1] if runs else None)
        if not wanted:
            return {"text": ""}
        p = Path(wanted["log"])
        if store.runs_dir(s).resolve() not in p.resolve().parents:
            raise ApiError("bad log path", 403)
        return {"text": p.read_text(encoding="utf-8", errors="replace")[-200_000:] if p.is_file() else ""}

    # ---------------------------------------------------------------- chats (history)
    async def chats_list(request):
        from grid.longmem import ChatArchive

        p = project_of(request)
        rt = runtime.peek(p.id)
        current = rt.session.chat_id if rt and rt.session else None
        out = [{"id": c.id, "title": c.title, "updated": c.updated, "started": c.started, "turns": len(c.turns),
                "current": c.id == current, "last": (c.turns[-1].reply[:160] if c.turns else "")}
               for c in ChatArchive().chats(p.path)]
        return {"chats": out, "current": current}

    async def chat_open(request):
        rt = rt_of(request)
        await asyncio.to_thread(rt.open_chat, request.path_params["cid"])
        return {"ok": True}

    async def chat_rename(request):
        from grid.longmem import ChatArchive

        b = await body(request)
        ChatArchive().rename(project_of(request).path, request.path_params["cid"], str(b.get("title", "")))
        return {"ok": True}

    async def chat_delete(request):
        from grid.longmem import ChatArchive

        p = project_of(request)
        rt = runtime.peek(p.id)
        cid = request.path_params["cid"]
        if rt and rt.session and rt.session.chat_id == cid:
            raise ApiError("that's the open chat - switch to another chat first")
        ChatArchive().delete(p.path, cid)
        # Also forget the saved conversation, so a deleted chat never reopens on the next launch.
        hexid = cid.replace("-", "").lower()
        if re.fullmatch(r"[0-9a-f]{32}", hexid):
            import shutil

            from grid.app import sessions_dir

            d = sessions_dir(p.path)
            shutil.rmtree(d / hexid, ignore_errors=True)
            last = d / "LAST"
            try:
                if last.is_file() and last.read_text(encoding="utf-8").strip().replace("-", "").lower() == hexid:
                    last.unlink()
            except OSError:
                pass
        return {"ok": True}

    # ---------------------------------------------------------------- long-term memory
    async def facts_list(request):
        from grid.longmem import FactStore

        pid = request.query_params.get("project")
        ws = registry.get(pid).path if pid else None
        user, project = FactStore().for_context(ws)
        return {"user": [asdict(f) for f in user], "project": [asdict(f) for f in project]}

    async def facts_add(request):
        from grid.longmem import FactStore, MemoryError_

        b = await body(request)
        pid = b.get("project")
        try:
            f = FactStore().add(str(b.get("text", "")), str(b.get("scope") or "user"),
                                registry.get(pid).path if pid else None, source="user")
        except MemoryError_ as exc:
            raise ApiError(str(exc)) from exc
        return {"fact": asdict(f)}

    async def facts_update(request):
        from grid.longmem import FactStore, MemoryError_

        b = await body(request)
        try:
            f = FactStore().update(request.path_params["fid"], str(b.get("text", "")))
        except MemoryError_ as exc:
            raise ApiError(str(exc)) from exc
        return {"fact": asdict(f)}

    async def facts_delete(request):
        from grid.longmem import FactStore, MemoryError_

        try:
            FactStore().forget(request.path_params["fid"])
        except MemoryError_ as exc:
            raise ApiError(str(exc), 404) from exc
        return {"ok": True}

    async def memory_search(request):
        from grid.longmem import search

        pid = request.query_params.get("project")
        ws = registry.get(pid).path if pid else None
        hits = await asyncio.to_thread(search, request.query_params.get("q", ""), ws,
                                       everywhere=request.query_params.get("everywhere") == "1", limit=20)
        return {"hits": [{"kind": h.kind, "text": h.text, "ref": h.ref} for h in hits]}

    # ---------------------------------------------------------------- Mac access
    async def access_list(request):
        from grid.access import AccessStore, pretty

        return {"folders": [f | {"pretty": pretty(f["path"])} for f in AccessStore().folders()]}

    async def access_add(request):
        from grid.access import AccessStore

        b = await body(request)
        try:
            real = AccessStore().grant(os.path.expanduser(str(b.get("path", ""))), always=True, reason="added in Settings")
        except PermissionError as exc:
            raise ApiError(str(exc), 403) from exc
        return {"ok": True, "path": real}

    async def access_remove(request):
        from grid.access import AccessStore

        AccessStore().revoke(request.query_params.get("path", ""))
        return {"ok": True}

    async def attachment(request):
        from grid.attachments import AttachmentError, path_for

        try:
            p = path_for(request.path_params["aid"])
        except AttachmentError as exc:
            raise ApiError(str(exc), 404) from exc
        return FileResponse(p, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})

    async def browser_get(request):
        from grid.browser_setup import chromium_path, install_command
        from grid.settings import load_settings

        path = await asyncio.to_thread(chromium_path)
        return {"path": path, "visible": load_settings().browser_visible, "can_install": install_command() is not None}

    async def browser_install(request):
        from grid.browser_setup import install

        return {"job": jobs.start("browser-install", install)}

    async def computer_get(request):
        from grid.access import AppStore
        from grid.computer import backend

        b = await asyncio.to_thread(backend)
        perms = await asyncio.to_thread(b.permissions) if b else {}
        return {"available": b is not None, "backend": b.name if b else None, "permissions": perms,
                "apps": [a for a in AppStore().apps() if a["key"] != AppStore.SCREEN.lower()],
                "screen_always": AppStore().allowed(AppStore.SCREEN)}

    async def computer_revoke(request):
        from grid.access import AppStore

        AppStore().revoke(request.query_params.get("name", ""))
        return {"ok": True}

    async def computer_settings(request):
        from grid.computer import open_settings_pane

        b = await body(request)
        open_settings_pane(str(b.get("which", "")))
        return {"ok": True}

    async def download(request):
        """A document Grid made, for the browser version (the desktop app opens files itself)."""
        from grid.access import AccessStore, is_under

        path = os.path.realpath(os.path.expanduser(request.query_params.get("path", "")))
        ok_place = AccessStore().allowed(path) or any(is_under(path, p.path) for p in registry.list())
        if not ok_place or not os.path.isfile(path) or os.path.splitext(path)[1].lower() not in (".pdf", ".docx", ".xlsx", ".pptx"):
            raise ApiError("not a document Grid can hand out", 404)
        return FileResponse(path, filename=os.path.basename(path))

    # ---------------------------------------------------------------- first-run setup
    async def setup_get(request):
        from grid.onboarding import setup_status
        from grid.settings import load_settings

        st = await asyncio.to_thread(setup_status)
        return st | {"done": load_settings().setup_done}

    async def setup_ollama(request):
        from grid.models import is_local_endpoint
        from grid.onboarding import ollama_models

        url = request.query_params.get("base_url") or "http://localhost:11434"
        if not is_local_endpoint("ollama/x", url):
            raise ApiError("that isn't a local address")
        return {"models": await asyncio.to_thread(ollama_models, url)}

    async def setup_choose(request):
        from grid.models import ModelProfile, ModelStore
        from grid.onboarding import PROVIDERS

        b = await body(request)
        prov = next((p for p in PROVIDERS if p["id"] == b.get("provider")), None)
        if prov is None:
            raise ApiError("pick one of the listed providers")
        model = str(b.get("model") or prov["model"] or "").strip()
        if not model:
            raise ApiError("type the model id")
        if "/" not in model:
            model = prov["prefix"] + model
        name = {"anthropic": "claude"}.get(prov["id"], prov["id"])
        prof = ModelProfile(name=name, model=model, base_url=(b.get("base_url") or prov.get("base_url") or None),
                            api_key_env=prov.get("key_env"), note="added by first-run setup")
        ModelStore().add(prof, make_default=True, replace=True)   # new chats use it
        return await setup_get(request)

    async def setup_check(request):
        from grid.models import resolve_profile
        from grid.onboarding import quick_check

        prof, _ = resolve_profile()
        llm = runtime.llm_factory() if runtime.llm_factory else None
        return {"job": jobs.start("setup-check", lambda: quick_check(prof, llm=llm))}

    async def setup_done(request):
        from grid.settings import save_settings

        save_settings({"setup_done": True})
        return {"ok": True}

    # ---------------------------------------------------------------- persona
    async def persona_get(request):
        from grid.persona import PersonaStore

        return PersonaStore().load().to_dict()

    async def persona_set(request):
        from grid.persona import PersonaStore

        b = await body(request)
        store = PersonaStore()
        if "age" in b:
            store.answer_age(str(b["age"]))
        if "persona" in b:
            try:
                store.choose(str(b["persona"]))
            except PermissionError as exc:
                raise ApiError(str(exc), 403) from exc
        return store.load().to_dict() | {"note": "applies to new chats"}

    # ---------------------------------------------------------------- ui state
    # The particle screen keeps its look, size, place and clock in the page's storage, but the app
    # gets a new port (so a new, empty storage) every launch. These few small values live here.
    ui_key = re.compile(r"grid\.particles\.[a-z]{1,16}")

    def ui_state_path() -> Path:
        from grid.project import grid_home

        return grid_home() / "ui-state.json"

    def ui_state_load() -> dict:
        try:
            raw = json.loads(ui_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in raw.items() if isinstance(k, str) and ui_key.fullmatch(k) and isinstance(v, str)} \
            if isinstance(raw, dict) else {}

    async def ui_state_get(request):
        return {"values": ui_state_load()}

    async def ui_state_put(request):
        values = (await body(request)).get("values")
        if not isinstance(values, dict) or len(values) > 16:
            raise ApiError("values must be an object with at most 16 entries")
        for k, v in values.items():
            if not (isinstance(k, str) and ui_key.fullmatch(k)) or not (isinstance(v, str) and len(v) <= 4000):
                raise ApiError(f"not a ui value: {str(k)[:40]}")
        merged = {**ui_state_load(), **values}
        p = ui_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(merged, indent=1), encoding="utf-8")
        os.replace(tmp, p)
        return {"ok": True}

    # ---------------------------------------------------------------- settings
    async def settings_get(request):
        from grid.settings import load_settings

        return asdict(load_settings())

    async def settings_put(request):
        from grid.settings import save_settings

        return asdict(save_settings(await body(request)))

    g = guard
    m = lambda h: guard(h, mutating=True)  # noqa: E731
    routes = [
        Route("/", index),
        Route("/api/state", g(state)),
        Route("/api/projects", g(projects_list)),
        Route("/api/projects", m(projects_create), methods=["POST"]),
        Route("/api/projects/open", m(projects_open), methods=["POST"]),
        Route("/api/projects/{pid}", m(projects_forget), methods=["DELETE"]),
        Route("/api/fs/browse", g(fs_browse)),
        Route("/api/projects/{pid}/tree", g(tree)),
        Route("/api/projects/{pid}/file", g(file_read)),
        Route("/api/projects/{pid}/file", m(file_write), methods=["PUT"]),
        Route("/api/projects/{pid}/file-at", g(file_at)),
        Route("/api/projects/{pid}/files/revert", m(file_revert), methods=["POST"]),
        Route("/api/projects/{pid}/files-index", g(files_index)),
        Route("/api/projects/{pid}/search", m(search_files), methods=["POST"]),
        Route("/api/projects/{pid}/replace", m(replace_files), methods=["POST"]),
        Route("/api/projects/{pid}/files/{op}", m(file_op), methods=["POST"]),
        WebSocketRoute("/api/projects/{pid}/pty", pty_ws),
        Route("/api/projects/{pid}/session", g(session_status)),
        Route("/api/projects/{pid}/tasks", m(task_submit), methods=["POST"]),
        Route("/api/projects/{pid}/answer", m(task_answer), methods=["POST"]),
        Route("/api/projects/{pid}/stop", m(task_stop), methods=["POST"]),
        Route("/api/projects/{pid}/new-chat", m(new_chat), methods=["POST"]),
        Route("/api/projects/{pid}/autonomous", m(autonomous), methods=["POST"]),
        Route("/api/autonomy", g(autonomy_info)),
        Route("/api/projects/{pid}/undo", m(undo), methods=["POST"]),
        Route("/api/projects/{pid}/checkpoints", g(checkpoints)),
        Route("/api/projects/{pid}/diff", g(diff)),
        Route("/api/projects/{pid}/model", m(set_model), methods=["POST"]),
        Route("/api/projects/{pid}/settings", m(project_settings), methods=["POST"]),
        Route("/api/projects/{pid}/verify", m(verify_now), methods=["POST"]),
        Route("/api/projects/{pid}/memory", g(memory_list)),
        Route("/api/projects/{pid}/memory/{index:int}", m(memory_delete), methods=["DELETE"]),
        Route("/api/projects/{pid}/commands", g(commands)),
        WebSocketRoute("/api/projects/{pid}/events", events_ws),
        Route("/api/plugins", g(plugins_list)),
        Route("/api/plugins/catalog", g(plugins_catalog)),
        Route("/api/plugins/preview", m(plugins_preview), methods=["POST"]),
        Route("/api/plugins/install", m(plugins_install), methods=["POST"]),
        Route("/api/plugins/{name}/enable", m(plugins_enable), methods=["POST"]),
        Route("/api/plugins/{name}", m(plugins_remove), methods=["DELETE"]),
        Route("/api/models", g(models_list)),
        Route("/api/models", m(models_add), methods=["POST"]),
        Route("/api/models/{name}", m(models_remove), methods=["DELETE"]),
        Route("/api/models/{name}/default", m(models_default), methods=["POST"]),
        Route("/api/models/{name}/think", m(models_think), methods=["POST"]),
        Route("/api/models/{name}/test", m(models_test), methods=["POST"]),
        Route("/api/jobs/{jid}", g(job_get)),
        Route("/api/schedules", g(schedules_list)),
        Route("/api/schedules", m(schedules_add), methods=["POST"]),
        Route("/api/schedules/{sid}", m(schedules_remove), methods=["DELETE"]),
        Route("/api/schedules/{sid}/enable", m(schedules_enable), methods=["POST"]),
        Route("/api/schedules/{sid}/run", m(schedules_run), methods=["POST"]),
        Route("/api/schedules/{sid}/runs", g(schedules_runs)),
        Route("/api/schedules/{sid}/log", g(schedules_log)),
        Route("/api/projects/{pid}/chats", g(chats_list)),
        Route("/api/projects/{pid}/chats/{cid}/open", m(chat_open), methods=["POST"]),
        Route("/api/projects/{pid}/chats/{cid}/rename", m(chat_rename), methods=["POST"]),
        Route("/api/projects/{pid}/chats/{cid}", m(chat_delete), methods=["DELETE"]),
        Route("/api/memory/facts", g(facts_list)),
        Route("/api/memory/facts", m(facts_add), methods=["POST"]),
        Route("/api/memory/facts/{fid}", m(facts_update), methods=["PUT"]),
        Route("/api/memory/facts/{fid}", m(facts_delete), methods=["DELETE"]),
        Route("/api/memory/search", g(memory_search)),
        Route("/api/access", g(access_list)),
        Route("/api/access", m(access_add), methods=["POST"]),
        Route("/api/access", m(access_remove), methods=["DELETE"]),
        Route("/api/download", g(download)),
        Route("/api/browser", g(browser_get)),
        Route("/api/computer", g(computer_get)),
        Route("/api/computer/apps", m(computer_revoke), methods=["DELETE"]),
        Route("/api/computer/settings", m(computer_settings), methods=["POST"]),
        Route("/api/browser/install", m(browser_install), methods=["POST"]),
        Route("/api/attachments/{aid}", g(attachment)),
        Route("/api/setup", g(setup_get)),
        Route("/api/setup/ollama", g(setup_ollama)),
        Route("/api/setup/choose", m(setup_choose), methods=["POST"]),
        Route("/api/setup/check", m(setup_check), methods=["POST"]),
        Route("/api/setup/done", m(setup_done), methods=["POST"]),
        Route("/api/persona", g(persona_get)),
        Route("/api/persona", m(persona_set), methods=["POST"]),
        Route("/api/settings", g(settings_get)),
        Route("/api/ui-state", g(ui_state_get)),
        Route("/api/ui-state", m(ui_state_put), methods=["PUT"]),
        Route("/api/settings", m(settings_put), methods=["PUT"]),
        Mount("/static", app=StaticFiles(directory=str(STATIC)), name="static"),
    ]

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        yield
        if scheduler is not None:
            scheduler.stop()
        await asyncio.to_thread(runtime.shutdown)

    app = Starlette(routes=routes, lifespan=lifespan)
    app.state.runtime = runtime
    app.state.registry = registry
    app.state.jobs = jobs
    return app


def _resume_quietly(rt) -> None:
    with contextlib.suppress(Exception):
        rt.ensure_session(resume_last=True)


def _verify_result(r) -> dict:
    return {"ok": r.ok, "label": r.label(), "tail": r.tail(60), "command": r.command}


def _signin_page(msg: str) -> str:
    return (
        "<!doctype html><meta charset=utf-8><title>Grid</title>"
        "<style>body{font:16px system-ui;display:grid;place-items:center;height:100vh;margin:0;"
        "background:#0f1115;color:#e6e6e6}div{max-width:420px;text-align:center}</style>"
        f"<div><h1>Grid</h1><p>{msg}</p></div>"
    )
