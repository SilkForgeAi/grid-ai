"""The Grid app: a local web UI over the agent (`grid app`)."""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import webbrowser


def _free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise OSError("no free port")


def app_command(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="grid app", description="Open the Grid app in your browser.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="just print the link")
    p.add_argument("--no-scheduler", action="store_true", help="don't run scheduled tasks while open")
    args = p.parse_args(argv)

    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    import uvicorn

    from grid.schedules import Scheduler
    from grid.server.api import create_app

    port = _free_port(args.port)
    token = secrets.token_urlsafe(24)
    scheduler = None if args.no_scheduler else Scheduler()
    app = create_app(token=token, port=port, scheduler=scheduler)
    if scheduler is not None:
        scheduler.start()
    url = f"http://127.0.0.1:{port}/?token={token}"
    print(f"\n  Grid is running at {url}\n  (this link signs you in; keep it private. Ctrl-C to quit)\n", flush=True)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(app_command(sys.argv[1:]))
