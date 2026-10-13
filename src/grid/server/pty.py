"""Interactive terminal: a real shell in a pseudo-terminal, bridged to xterm.js
over the app's (token- and origin-checked) websocket. One shell per open
terminal panel; it's killed when the panel closes."""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import fcntl
import json
import os
import pty
import shutil
import signal
import struct
import termios
import threading
import time


def default_shell() -> str:
    for cand in (os.environ.get("SHELL"), "/bin/zsh", "/bin/bash", "/bin/sh"):
        if cand and os.path.exists(cand):
            return cand
    return shutil.which("sh") or "/bin/sh"


class PtySession:
    def __init__(self, cwd: str, cols: int = 100, rows: int = 30):
        self.cwd = cwd
        # Everything the child needs is prepared before fork: the server is multi-threaded,
        # so the child should do as little as possible before exec.
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor", "GRID_TERMINAL": "1"}
        shell = default_shell()
        argv = [shell, "-l"]
        self.pid, self.fd = pty.fork()
        if self.pid == 0:  # child
            try:
                os.chdir(cwd)
                os.execve(shell, argv, env)
            finally:
                os._exit(1)
        self.resize(cols, rows)
        flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
        fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def resize(self, cols: int, rows: int) -> None:
        cols = max(10, min(int(cols), 1000))
        rows = max(2, min(int(rows), 500))
        with contextlib.suppress(OSError):
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def write(self, data: str) -> None:
        os.write(self.fd, data.encode("utf-8"))

    def read(self) -> str | None:
        try:
            chunk = os.read(self.fd, 65536)
        except BlockingIOError:
            return ""
        except OSError:
            return None
        if not chunk:
            return None
        return self._decoder.decode(chunk)

    def close(self) -> None:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(self.pid, signal.SIGHUP)
        with contextlib.suppress(OSError):
            os.close(self.fd)
        threading.Thread(target=_reap, args=(self.pid,), daemon=True).start()


def _reap(pid: int) -> None:
    """Wait for the shell to exit so it doesn't linger as a zombie; force it after 3s."""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            done, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return
        if done:
            return
        time.sleep(0.1)
    with contextlib.suppress(ProcessLookupError, OSError):
        os.killpg(pid, signal.SIGKILL)
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, 0)


async def serve_pty(ws, cwd: str) -> None:
    """Pump bytes between a websocket and a shell until either side closes."""
    loop = asyncio.get_running_loop()
    try:
        cols = int(ws.query_params.get("cols", "100") or 100)
        rows = int(ws.query_params.get("rows", "30") or 30)
    except ValueError:
        cols, rows = 100, 30
    session = PtySession(cwd, cols, rows)
    out_q: asyncio.Queue = asyncio.Queue()

    def on_readable():
        data = session.read()
        if data is None:
            loop.remove_reader(session.fd)
            out_q.put_nowait(None)
        elif data:
            out_q.put_nowait(data)

    loop.add_reader(session.fd, on_readable)

    async def pump_out():
        while True:
            data = await out_q.get()
            if data is None:
                with contextlib.suppress(Exception):
                    await ws.send_text(json.dumps({"type": "exit"}))
                    await ws.close()
                return
            await ws.send_text(json.dumps({"type": "output", "data": data}))

    sender = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive_text()
            try:
                m = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if m.get("type") == "input" and isinstance(m.get("data"), str):
                session.write(m["data"])
            elif m.get("type") == "resize":
                with contextlib.suppress(TypeError, ValueError):
                    session.resize(m.get("cols", 100), m.get("rows", 30))
    except Exception:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(Exception):
            loop.remove_reader(session.fd)
        session.close()
