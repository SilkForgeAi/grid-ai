"""Scheduled tasks: run a Grid task on a cron schedule, unattended.

    grid schedule add nightly-tests --project ~/code/api --cron "0 2 * * *" \\
        --prompt "Run the tests; fix any failure you can prove the cause of."
    grid schedule add deps --project . --cron "@weekly" --autonomous --allow push --prompt "..."

Schedules run while `grid app` is open (it has a scheduler), or from your
system scheduler with one crontab line:  * * * * *  grid schedule run-due
Runs that were missed while nothing was running are skipped, not replayed.

Every run is unattended: headless by default (anything risky is refused), or
autonomous if you chose that when creating it (RED only for pre-approved
categories). Verification still applies, and each run is logged.

Times are local time. Pure Python except for the run itself.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from grid.project import grid_home

ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@weekdays": "0 9 * * 1-5",
}
_BOUNDS = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
_NAMES = ["minute", "hour", "day of month", "month", "day of week"]


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class Cron:
    expr: str
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]      # 0 = Sunday
    dom_star: bool
    dow_star: bool

    @classmethod
    def parse(cls, expr: str) -> Cron:
        text = ALIASES.get(expr.strip().lower(), expr.strip())
        parts = text.split()
        if len(parts) != 5:
            raise ScheduleError(f"cron needs 5 fields (minute hour day month weekday), got {expr!r}")
        sets = [_parse_field(p, lo, hi, name) for p, (lo, hi), name in zip(parts, _BOUNDS, _NAMES, strict=True)]
        weekdays = frozenset(0 if d == 7 else d for d in sets[4])
        return cls(expr, frozenset(sets[0]), frozenset(sets[1]), frozenset(sets[2]), frozenset(sets[3]),
                   weekdays, parts[2] == "*", parts[4] == "*")

    def _day_ok(self, dt: datetime) -> bool:
        dom = dt.day in self.days
        dow = ((dt.weekday() + 1) % 7) in self.weekdays
        if self.dom_star and self.dow_star:
            return True
        if self.dom_star:
            return dow
        if self.dow_star:
            return dom
        return dom or dow          # classic cron: either restriction matches

    def matches(self, dt: datetime) -> bool:
        return (dt.minute in self.minutes and dt.hour in self.hours and dt.month in self.months
                and self._day_ok(dt))

    def next_after(self, dt: datetime) -> datetime:
        """The first matching minute strictly after `dt`."""
        t = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = t + timedelta(days=366 * 5)
        while t < limit:
            if t.month not in self.months:
                t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
                continue
            if not self._day_ok(t):
                t = t.replace(hour=0, minute=0) + timedelta(days=1)
                continue
            if t.hour not in self.hours:
                t = t.replace(minute=0) + timedelta(hours=1)
                continue
            if t.minute not in self.minutes:
                t += timedelta(minutes=1)
                continue
            return t
        raise ScheduleError(f"cron {self.expr!r} never fires")

    def describe(self) -> str:
        presets = {v: k for k, v in ALIASES.items()}
        return presets.get(self.expr, self.expr)


def _parse_field(text: str, lo: int, hi: int, name: str) -> set[int]:
    out: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                raise ScheduleError(f"bad step in {name}: {text!r}")
            step = int(step_s)
        if part in ("*", ""):
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            if not (a_s.isdigit() and b_s.isdigit()):
                raise ScheduleError(f"bad range in {name}: {text!r}")
            a, b = int(a_s), int(b_s)
        elif part.isdigit():
            a = b = int(part)
            if step > 1:          # "5/15" = from 5, every 15
                b = hi
        else:
            raise ScheduleError(f"bad {name}: {text!r}")
        if not (lo <= a <= hi and lo <= b <= hi and a <= b):
            raise ScheduleError(f"{name} out of range {lo}-{hi}: {text!r}")
        out.update(range(a, b + 1, step))
    return out


# -- store ----------------------------------------------------------------------

@dataclass
class Schedule:
    id: str
    name: str
    project: str
    prompt: str
    cron: str
    mode: str = "headless"                      # headless | autonomous
    allow: list[str] = field(default_factory=list)
    model_profile: str | None = None
    enabled: bool = True
    created: float = field(default_factory=time.time)
    next_run: float | None = None
    last_run: float | None = None
    last_outcome: str | None = None

    def validate(self) -> None:
        Cron.parse(self.cron)
        if not self.prompt.strip():
            raise ScheduleError("a schedule needs a prompt")
        if not Path(self.project).is_dir():
            raise ScheduleError(f"project folder not found: {self.project}")
        if self.mode not in ("headless", "autonomous"):
            raise ScheduleError("mode must be headless or autonomous")
        if self.allow and self.mode != "autonomous":
            raise ScheduleError("allow only applies to autonomous schedules")
        from grid.autonomy import parse_allow

        try:
            parse_allow(self.allow)
        except ValueError as exc:
            raise ScheduleError(str(exc)) from exc


class ScheduleStore:
    def __init__(self, root: Path | None = None):
        self.root = root or (grid_home() / "schedules")
        self.path = self.root / "schedules.json"

    def _read(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[Schedule]:
        known = set(Schedule.__dataclass_fields__)
        return [Schedule(**{k: v for k, v in raw.items() if k in known})
                for raw in sorted(self._read().values(), key=lambda r: r.get("created", 0))]

    def get(self, ref: str) -> Schedule:
        for s in self.list():
            if s.id == ref or s.name == ref:
                return s
        raise ScheduleError(f"no schedule {ref!r}")

    def save(self, s: Schedule) -> Schedule:
        data = self._read()
        data[s.id] = asdict(s)
        self._write(data)
        return s

    def add(self, *, name: str, project: str, prompt: str, cron: str, mode: str = "headless",
            allow: list[str] | None = None, model_profile: str | None = None, now: datetime | None = None) -> Schedule:
        name = (name or "").strip()
        if not name or len(name) > 64:
            raise ScheduleError("a schedule needs a name (up to 64 characters)")
        if any(s.name == name for s in self.list()):
            raise ScheduleError(f"a schedule named {name!r} exists")
        s = Schedule(id=uuid.uuid4().hex[:8], name=name, project=os.path.realpath(os.path.expanduser(project)),
                     prompt=prompt, cron=cron, mode=mode, allow=list(allow or []), model_profile=model_profile)
        s.validate()
        s.next_run = Cron.parse(cron).next_after(now or datetime.now()).timestamp()
        return self.save(s)

    def remove(self, ref: str) -> None:
        s = self.get(ref)
        data = self._read()
        data.pop(s.id, None)
        self._write(data)

    def set_enabled(self, ref: str, enabled: bool, now: datetime | None = None) -> Schedule:
        s = self.get(ref)
        s.enabled = enabled
        if enabled:
            s.next_run = Cron.parse(s.cron).next_after(now or datetime.now()).timestamp()
        return self.save(s)

    def due(self, now: datetime | None = None) -> list[Schedule]:
        ts = (now or datetime.now()).timestamp()
        return [s for s in self.list() if s.enabled and s.next_run is not None and s.next_run <= ts]

    # -- run log ------------------------------------------------------------
    def runs_dir(self, s: Schedule) -> Path:
        return self.root / "runs" / s.id

    def runs(self, ref: str) -> list[dict]:
        s = self.get(ref)
        f = self.runs_dir(s) / "runs.jsonl"
        if not f.is_file():
            return []
        out = []
        for line in f.read_text(encoding="utf-8").splitlines():
            with contextlib.suppress(json.JSONDecodeError):
                out.append(json.loads(line))
        return out


# -- running --------------------------------------------------------------------

@contextlib.contextmanager
def _run_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def run_schedule(store: ScheduleStore, s: Schedule, *, llm=None, now: datetime | None = None) -> dict:
    """Run one schedule now, unattended. Returns the run record."""
    from grid.autonomy import parse_allow
    from grid.config import GridConfig
    from grid.models import ModelStore
    from grid.session import UI, GridSession

    started = now or datetime.now()
    run_dir = store.runs_dir(s)
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / f"{started.strftime('%Y%m%d-%H%M%S')}.log"
    record = {"schedule": s.id, "started": started.timestamp(), "log": str(log_path)}

    with _run_lock(run_dir / ".lock") as got, open(log_path, "a", encoding="utf-8") as log:
        def say(msg: str) -> None:
            log.write(msg + "\n")
            log.flush()

        if not got:
            say("[grid] skipped: the previous run of this schedule is still going")
            record.update(outcome="skipped", finished=time.time())
        else:
            say(f"[grid] scheduled run '{s.name}' ({s.mode}) in {s.project}")
            say(f"[grid] task: {s.prompt}")
            try:
                from grid.settings import load_settings

                config = load_settings().apply(GridConfig(headless=True))   # check-in steps, depth, verify...
                if s.model_profile:
                    config.model_profile = ModelStore().get(s.model_profile)
                if s.mode == "autonomous":
                    config.autonomous = True
                    config.allow_red = parse_allow(s.allow)
                session = GridSession(s.project, config, UI(say=say, interactive=False), llm=llm,
                                      visualizer=None)
                try:
                    report = session.submit(s.prompt)
                finally:
                    session.close()
                record.update(outcome=report.outcome.value, finished=time.time(),
                              changed=report.changed[:50], message=(report.message or "")[:2000])
            except Exception as exc:
                say(f"[grid] run failed: {type(exc).__name__}: {exc}")
                record.update(outcome="error", finished=time.time(), message=str(exc)[:2000])

    with open(run_dir / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    # re-read: the schedule may have been edited while it ran
    try:
        fresh = store.get(s.id)
    except ScheduleError:
        return record
    fresh.last_run = record["started"]
    fresh.last_outcome = record["outcome"]
    fresh.next_run = Cron.parse(fresh.cron).next_after(datetime.now()).timestamp()
    store.save(fresh)
    return record


def run_due(store: ScheduleStore | None = None, *, now: datetime | None = None, llm=None) -> list[dict]:
    store = store or ScheduleStore()
    return [run_schedule(store, s, llm=llm, now=now) for s in store.due(now)]


class Scheduler:
    """Background thread that runs due schedules (used by `grid app`)."""

    def __init__(self, store: ScheduleStore | None = None, interval: float = 30.0, on_run=None):
        self.store = store or ScheduleStore()
        self.interval = interval
        self.on_run = on_run
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # Missed runs are skipped: move stale next_run values forward first.
        now = datetime.now()
        for s in self.store.list():
            if s.enabled and (s.next_run is None or s.next_run < now.timestamp() - 60):
                s.next_run = Cron.parse(s.cron).next_after(now).timestamp()
                self.store.save(s)
        self._thread = threading.Thread(target=self._loop, name="grid-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            for s in self.store.due():
                threading.Thread(target=self._run_one, args=(s,), daemon=True).start()
                # move next_run forward right away so the next tick doesn't start it again
                s.next_run = Cron.parse(s.cron).next_after(datetime.now()).timestamp()
                self.store.save(s)

    def _run_one(self, s: Schedule) -> None:
        record = run_schedule(self.store, s)
        if self.on_run:
            with contextlib.suppress(Exception):
                self.on_run(s, record)


# -- CLI ------------------------------------------------------------------------

def _fmt_ts(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M") if ts else "-"


def schedule_command(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="grid schedule", description="Recurring Grid tasks.")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("--project", required=True)
    a.add_argument("--cron", required=True, help='5-field cron or @hourly/@daily/@weekly/@weekdays/@monthly')
    a.add_argument("--prompt", required=True)
    a.add_argument("--autonomous", action="store_true")
    a.add_argument("--allow", action="append", default=[])
    a.add_argument("--profile", default=None, help="model profile to use")
    for name in ("remove", "enable", "disable", "run", "log"):
        sp = sub.add_parser(name)
        sp.add_argument("ref", help="schedule name or id")
    sub.add_parser("run-due", help="run every schedule that is due (for cron/launchd)")
    args = p.parse_args(argv)
    store = ScheduleStore()
    try:
        if args.action in (None, "list"):
            items = store.list()
            if not items:
                print("no schedules. Add one: grid schedule add NAME --project DIR --cron '@daily' --prompt '...'")
            for s in items:
                state = "on " if s.enabled else "off"
                print(f"[{state}] {s.name} ({s.id})  {Cron.parse(s.cron).describe()}  {s.mode}  next {_fmt_ts(s.next_run)}"
                      f"  last {_fmt_ts(s.last_run)} {s.last_outcome or ''}")
                print(f"       {s.project}: {s.prompt[:80]}")
            return 0
        if args.action == "add":
            s = store.add(name=args.name, project=args.project, prompt=args.prompt, cron=args.cron,
                          mode="autonomous" if args.autonomous else "headless", allow=args.allow,
                          model_profile=args.profile)
            print(f"added '{s.name}' ({s.id}); next run {_fmt_ts(s.next_run)}")
            print("runs while `grid app` is open, or add to crontab:  * * * * *  grid schedule run-due")
            return 0
        if args.action == "remove":
            store.remove(args.ref)
            print(f"removed {args.ref}")
            return 0
        if args.action in ("enable", "disable"):
            store.set_enabled(args.ref, args.action == "enable")
            print(f"{args.ref}: {args.action}d")
            return 0
        if args.action == "run":
            os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
            rec = run_schedule(store, store.get(args.ref))
            print(f"{rec['outcome']}  log: {rec['log']}")
            return 0 if rec["outcome"] in ("verified", "done") else 1
        if args.action == "run-due":
            os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
            for rec in run_due(store):
                print(f"{rec['schedule']}: {rec['outcome']}  log: {rec['log']}")
            return 0
        if args.action == "log":
            runs = store.runs(args.ref)
            if not runs:
                print("no runs yet")
                return 0
            last = runs[-1]
            print(f"last run {_fmt_ts(last['started'])}: {last['outcome']}")
            with contextlib.suppress(OSError):
                print(Path(last["log"]).read_text(encoding="utf-8"))
            return 0
    except ScheduleError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    return 2
