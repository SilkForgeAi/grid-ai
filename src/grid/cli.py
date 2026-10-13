"""Grid AI command line.

    grid "make the failing test pass"     run a task, then stay for follow-ups
    grid                                  interactive session
    grid --plan "add a --version flag"    plan first, approve, then execute
    grid --headless "task"                unattended (CI / scheduled): no prompts
    grid --autonomous "task"              you approve once up front; Grid stops asking
    grid --autonomous --allow push "..."  ...and may also git push (pre-approved RED)
    grid --resume                         continue the last session here
    grid undo [N]                         restore checkpoint N (default: one back)
    grid checkpoints                      list checkpoints for this project
    grid diff [N]                         changes since checkpoint N (default: first)
    grid sessions                         list saved sessions for this project
    grid models [list|add|remove|use|show|test]   bring your own model (see `grid models -h`)
    grid plugins [list|catalog|install|remove|enable|disable|show]   skills, commands, MCP servers
    grid schedule [list|add|remove|enable|disable|run|run-due|log]   recurring tasks
    grid app [--port N] [--no-browser]   the Grid app in your browser
    grid persona [adult|minor|grid|teacher]   Grid's personality (the Grid voice is 18+)

Exit codes: 0 verified/done, 1 error, 2 bad usage, 3 unverified,
4 needs approval (headless), 5 stuck, 6 paused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from grid.config import GridConfig
from grid.teaching import DepthLevel

SUBCOMMANDS = {"undo", "checkpoints", "diff", "sessions", "models", "plugins", "schedule", "app", "persona"}

REPL_HELP = """\
  <task>             give Grid a task (or a follow-up)
  /plan <task>       investigate, propose a plan, execute after you approve
  /undo [N]          restore checkpoint N (default: one step back)
  /checkpoints       list checkpoints
  /diff [N]          show changes since checkpoint N (default: start of last task)
  /verify            run the project's check now
  /learn <topic>     a step-by-step lesson where you write the code (/hint /check /next /solution /quiz)
  /model [NAME]      show the current model, or switch to a saved profile
  /depth <level>     beginner | intermediate | pro
  /yolo              stop asking for YELLOW actions this session (RED still asks)
  /auto [on|off] [--allow a,b]   autonomous mode: no prompts; RED only if pre-approved;
                     every task still has to pass a real check
  /help              this help
  /quit              exit (the session is saved; resume with `grid --resume`)"""


def _threshold(value: str) -> float:
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1") from None
    if not 0.0 <= f <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return f


def _positive(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if n < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="grid", description="Grid AI - a self-correcting, teaching-first coding agent.")
    p.add_argument("task", nargs="?", help="What you want Grid to do. Omit for an interactive session.")
    p.add_argument("--depth", choices=[d.value for d in DepthLevel], default=DepthLevel.INTERMEDIATE.value,
                   help="Teaching depth (default: intermediate).")
    p.add_argument("--workspace", default=None, help="Project folder (default: current directory).")
    p.add_argument("--plan", action="store_true", help="Plan first; execute only after approval.")
    p.add_argument("--headless", action="store_true",
                   help="Unattended: never prompt. Actions needing a human are rejected.")
    p.add_argument("--once", action="store_true", help="Exit after the task instead of staying for follow-ups.")
    p.add_argument("--resume", nargs="?", const="last", default=None, metavar="ID",
                   help="Resume the last (or a given) saved session for this project.")
    p.add_argument("--confidence-threshold", type=_threshold, default=0.6,
                   help="Below this self-rated confidence, actions are escalated to ask-first.")
    p.add_argument("--strict-confidence", action="store_true",
                   help="Low confidence also escalates YELLOW to RED.")
    p.add_argument("--escalate-on-missing", action="store_true",
                   help="Actions with no confidence score are treated as YELLOW.")
    p.add_argument("--no-enforce-confidence", action="store_true",
                   help="Show confidence badges only; don't let confidence change risk.")
    p.add_argument("--yolo", action="store_true", help="Don't confirm YELLOW actions (RED still always stops).")
    p.add_argument("--autonomous", action="store_true",
                   help="Run without asking (after you confirm once). RED actions are refused unless "
                        "pre-approved with --allow. Verification is mandatory.")
    p.add_argument("--allow", action="append", default=[], metavar="CATEGORY",
                   help="Pre-approve a RED category for autonomous mode: "
                        "delete, git-history, push, publish, deploy, network-exec, permissions, model-flagged.")
    p.add_argument("-y", "--yes", action="store_true",
                   help="Skip the autonomous-mode confirmation prompt (you are approving it now).")
    p.add_argument("--persona", choices=["grid", "teacher"], default=None,
                   help="Voice for this run. 'grid' (sweary senior engineer) needs a confirmed 18+ answer; 'teacher' is clean.")
    p.add_argument("--model", default=None,
                   help="Any LiteLLM model id for this run, e.g. anthropic/claude-opus-5-5 "
                        "(uses $LLM_BASE_URL / $LLM_API_KEY if set).")
    p.add_argument("--profile", default=None, help="Saved model profile to use (see `grid models`).")
    p.add_argument("--prompted-tools", action="store_true",
                   help="Describe tools in the prompt, for models without native tool calling.")
    p.add_argument("--local-only", action="store_true",
                   help="Refuse any model or MCP server that would send code off this machine.")
    p.add_argument("--step-budget", type=_positive, default=25, help="Check in every N agent steps.")
    p.add_argument("--verify", dest="verify_command", default=None, metavar="CMD",
                   help="Command that proves the task is done (default: GRID.md `verify:` or auto-detect).")
    p.add_argument("--no-verify", action="store_true", help="Accept 'done' without running a check.")
    p.add_argument("--no-review", action="store_true", help="Skip the consistency review of the agent's own changes before 'done'.")
    p.add_argument("--no-checkpoints", action="store_true", help="Disable checkpoints/undo.")
    p.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)   # on by default now
    p.add_argument("--no-browser", action="store_true", help="Don't give the agent Grid's browser.")
    p.add_argument("--sub-agents", action="store_true", help="Allow sub-agent delegation (uses more tokens).")
    return p.parse_args(argv)


def _config_from(args: argparse.Namespace) -> GridConfig:
    from grid.autonomy import parse_allow

    allow = parse_allow(args.allow)
    return GridConfig(
        autonomous=args.autonomous,
        allow_red=allow,
        depth=DepthLevel(args.depth),
        confidence_threshold=args.confidence_threshold,
        strict_confidence=args.strict_confidence,
        escalate_on_missing_confidence=args.escalate_on_missing,
        enforce_confidence=not args.no_enforce_confidence,
        confirm_yellow=not args.yolo,
        soft_step_budget=args.step_budget,
        verify=not args.no_verify,
        self_review=not args.no_review,
        verify_command=args.verify_command,
        checkpoints=not args.no_checkpoints,
        plan_first=args.plan,
        headless=args.headless,
        enable_browser=not args.no_browser,
        enable_sub_agents=args.sub_agents,
        prompted_tools=args.prompted_tools,
        local_only=args.local_only,
        persona=args.persona,
    )


# --------------------------------------------------------------- subcommands

def _subcommand(argv: list[str]) -> int:
    from grid.app import list_sessions
    from grid.checkpoints import CheckpointError, CheckpointStore

    cmd, rest = argv[0], argv[1:]
    if cmd == "persona":
        return _persona_command(rest)
    if cmd == "models":
        return _models_command(rest)
    if cmd == "plugins":
        return _plugins_command(rest)
    if cmd == "schedule":
        from grid.schedules import schedule_command

        return schedule_command(rest)
    if cmd == "app":
        from grid.server import app_command

        return app_command(rest)
    workspace = os.path.realpath(os.getcwd())
    if cmd == "sessions":
        rows = list_sessions(workspace)
        if not rows:
            print("no saved sessions for this project")
        for sid, mtime in rows:
            print(f"{sid}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))}")
        return 0
    try:
        store = CheckpointStore(workspace)
    except CheckpointError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 1
    cps = store.list()
    if cmd == "checkpoints":
        _print_checkpoints(store)
        return 0
    if not cps:
        print("no checkpoints yet for this project")
        return 0
    try:
        if cmd == "undo":
            if rest:
                ref = rest[0]
            else:
                head = store.head()
                idx = next((i for i, c in enumerate(cps) if c.sha == head), len(cps) - 1)
                if idx == 0:
                    print("already at the first checkpoint")
                    return 0
                ref = cps[idx - 1].id
            target, before = store.restore(ref)
            print(f"restored checkpoint #{target.id} ({target.label}); previous state saved as #{before.id}")
            return 0
        if cmd == "diff":
            base = store.get(rest[0]) if rest else cps[0]
            if base is None:
                print(f"no checkpoint {rest[0]!r}", file=sys.stderr)
                return 2
            print(store.diff(base.sha) or "(no changes)")
            return 0
    except CheckpointError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 1
    return 2


def _models_command(argv: list[str]) -> int:
    from grid.models import ModelError, ModelProfile, ModelStore, compat_summary, resolve_profile

    p = argparse.ArgumentParser(prog="grid models", description="Bring your own model: saved model profiles.")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("list", help="list saved profiles (default)")
    a = sub.add_parser("add", help="save a model profile")
    a.add_argument("name")
    a.add_argument("--model", required=True, help="LiteLLM model id, e.g. ollama/qwen3.6:27b")
    a.add_argument("--base-url", default=None, help="server URL for local/self-hosted/OpenAI-compatible models")
    a.add_argument("--key-env", default=None, metavar="ENV_VAR",
                   help="NAME of the env var holding the API key (the key itself is never saved)")
    a.add_argument("--prompted-tools", action="store_true", help="model has no native tool calling")
    a.add_argument("--note", default="")
    a.add_argument("--default", action="store_true", help="make this the default profile")
    a.add_argument("--replace", action="store_true", help="overwrite an existing profile")
    r = sub.add_parser("remove", help="delete a profile")
    r.add_argument("name")
    u = sub.add_parser("use", help="make a profile the default")
    u.add_argument("name")
    sh = sub.add_parser("show", help="show one profile and its last test")
    sh.add_argument("name")
    t = sub.add_parser("test", help="run a small real task to check the model works with Grid")
    t.add_argument("name", nargs="?", help="profile (default: the model Grid would use now)")
    t.add_argument("--model", default=None, help="test an ad-hoc LiteLLM model id instead")
    t.add_argument("--prompted-tools", action="store_true")
    args = p.parse_args(argv)
    store = ModelStore()
    try:
        if args.action in (None, "list"):
            profiles = store.list()
            default = store.default_name()
            if not profiles:
                print("no saved profiles. Grid uses $LLM_MODEL, or anthropic/claude-opus-5-5 by default.")
                print("add one: grid models add NAME --model PROVIDER/MODEL [--base-url URL] [--key-env VAR]")
                return 0
            for prof in profiles:
                mark = "*" if prof.name == default else " "
                where = f" @ {prof.base_url}" if prof.base_url else ""
                extras = ["local" if prof.is_local() else "cloud"]
                if prof.api_key_env:
                    extras.append(f"key ${prof.api_key_env}")
                if not prof.native_tool_calling:
                    extras.append("prompted tools")
                print(f"{mark} {prof.name:<14} {prof.model}{where}  [{', '.join(extras)}]  {compat_summary(prof)}")
            return 0
        if args.action == "add":
            prof = ModelProfile(name=args.name, model=args.model, base_url=args.base_url,
                                api_key_env=args.key_env, native_tool_calling=not args.prompted_tools,
                                note=args.note)
            store.add(prof, make_default=args.default, replace=args.replace)
            print(f"saved '{prof.name}' ({prof.model}, {'local' if prof.is_local() else 'cloud'})."
                  f" Check it works with Grid: grid models test {prof.name}")
            return 0
        if args.action == "remove":
            store.remove(args.name)
            print(f"removed '{args.name}'")
            return 0
        if args.action == "use":
            store.set_default(args.name)
            print(f"default model profile: '{args.name}'")
            return 0
        if args.action == "show":
            prof = store.get(args.name)
            print(json.dumps({k: v for k, v in prof.__dict__.items()}, indent=2))
            return 0
        if args.action == "test":
            from dataclasses import replace

            from grid.probe import format_result, run_probe

            os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
            os.environ.setdefault("LOG_LEVEL", "ERROR")
            if args.name:
                prof = store.get(args.name)
            else:
                prof, _ = resolve_profile(cli_model=args.model)
            if args.prompted_tools:
                prof = replace(prof, native_tool_calling=False)
            print(f"[grid] testing {prof.model} on a small real task (a few cents on cloud models)...")
            result = run_probe(prof)
            print(format_result(prof, result))
            if args.name:
                store.record_compat(args.name, result.to_record())
            return 0 if result.verdict != "not-ready" else 1
    except ModelError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    return 2


AGE_QUESTION = ("Grid's default personality is a foul-mouthed, roast-your-code senior engineer - for adults only.\n"
                "Are you 18 or older? [y]es / [n]o (Grid will be your teacher instead): ")


def _persona_command(argv: list[str]) -> int:
    from grid.persona import PersonaStore

    store = PersonaStore()
    action = argv[0] if argv else "status"
    try:
        if action == "adult":
            store.answer_age("adult")
        elif action == "minor":
            store.answer_age("minor")
        elif action in ("grid", "teacher"):
            store.choose(action)
        elif action != "status":
            print("usage: grid persona [status|adult|minor|grid|teacher]", file=sys.stderr)
            return 2
    except (PermissionError, ValueError) as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    p = store.load()
    voice = "Grid (adult mode)" if p.effective == "grid" else "Teacher"
    note = " - locked because you said you're under 18" if p.minor_lock else (
        " - answer the 18+ question to unlock the Grid voice: grid persona adult" if p.age_answer is None else "")
    print(f"voice: {voice}{note}")
    return 0


def ask_age_once(ask=input) -> None:
    """First interactive run: ask the 18+ question once. No answer = teacher for now."""
    from grid.persona import PersonaStore

    store = PersonaStore()
    if not store.load().needs_age_check:
        return
    try:
        answer = ask(AGE_QUESTION).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return
    if answer in ("y", "yes"):
        store.answer_age("adult")
        print("[grid] Grid voice unlocked. You can switch to teacher any time: grid persona teacher")
    elif answer in ("n", "no"):
        store.answer_age("minor")
        print("[grid] Teacher mode it is.")


def _print_plugin(info, *, detail: bool = False) -> None:
    state = "on " if info.enabled else "off"
    print(f"  [{state}] {info.name} {info.version} ({info.scope}) - {info.description}")
    if detail or info.scope in ("preview", "builtin"):
        if info.skills:
            print(f"        skills  : {', '.join(info.skills)}")
        if info.commands:
            print(f"        commands: {', '.join(c.slash for c in info.commands)}")
        for name, what in info.mcp.items():
            print(f"        MCP     : {name} - {what}")
        if info.has_hooks:
            print("        hooks   : present (not run by Grid yet)")


def _plugins_command(argv: list[str], ask=input) -> int:
    from grid.plugins import PluginError, PluginManager, builtin_catalog

    p = argparse.ArgumentParser(prog="grid plugins", description="Plugins: skills, slash commands and MCP servers.")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("list", help="installed plugins (default)")
    sub.add_parser("catalog", help="Grid's built-in starter plugins")
    i = sub.add_parser("install", help="install from a folder, builtin:NAME, github:owner/repo or a git URL")
    i.add_argument("source")
    i.add_argument("--project", action="store_true", help="install for this project only")
    i.add_argument("--replace", action="store_true", help="update an installed plugin")
    i.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    for name in ("remove", "enable", "disable", "show"):
        sp = sub.add_parser(name)
        sp.add_argument("name")
        sp.add_argument("--project", action="store_true")
    args = p.parse_args(argv)
    mgr = PluginManager(os.getcwd())
    scope = "project" if getattr(args, "project", False) else None
    try:
        if args.action in (None, "list"):
            infos = mgr.list()
            if not infos:
                print("no plugins installed. Browse: grid plugins catalog")
            for info in infos:
                _print_plugin(info)
            return 0
        if args.action == "catalog":
            for info in builtin_catalog():
                _print_plugin(info)
                print(f"        install : grid plugins install {info.source}")
            return 0
        if args.action == "install":
            preview = mgr.preview(args.source)
            print("This plugin adds:")
            _print_plugin(preview, detail=True)
            if preview.mcp:
                print("  MCP servers run programs on your computer when the agent uses them.")
            if not args.yes and ask("Install it? [y/N]: ").strip().lower() not in ("y", "yes"):
                print("not installed")
                return 1
            info = mgr.install(args.source, scope=scope or "user", replace=args.replace)
            print(f"installed {info.name} ({info.scope}). Commands: {', '.join(c.slash for c in info.commands) or 'none'}")
            return 0
        if args.action == "remove":
            mgr.remove(args.name, scope)
            print(f"removed {args.name}")
            return 0
        if args.action in ("enable", "disable"):
            mgr.set_enabled(args.name, args.action == "enable", scope)
            print(f"{args.name}: {args.action}d")
            return 0
        if args.action == "show":
            _print_plugin(mgr.get(args.name, scope), detail=True)
            return 0
    except PluginError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    return 2


def _print_checkpoints(store) -> None:
    head = store.head()
    cps = store.list()
    if not cps:
        print("no checkpoints yet for this project")
    for cp in cps:
        mark = "*" if cp.sha == head else " "
        when = time.strftime("%m-%d %H:%M:%S", time.localtime(cp.timestamp))
        tests = f"  [{cp.tests}]" if cp.tests else ""
        print(f"{mark} #{cp.id:<4} {when}  {cp.label}{tests}")


# --------------------------------------------------------------- autonomy opt-in

def _confirm_autonomous(allow, ask=input) -> bool:
    from grid.autonomy import describe_mode

    print("\n" + describe_mode(frozenset(allow)))
    try:
        answer = ask("Type 'yes' to let Grid run without asking: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == "yes"


def _auto_command(session, arg: str, ask=input) -> None:
    from grid.autonomy import parse_allow

    words = arg.split()
    if words and words[0] == "off":
        session.set_autonomous(False)
        return
    allow_vals: list[str] = []
    if "--allow" in words:
        i = words.index("--allow")
        allow_vals = words[i + 1:i + 2]
    try:
        allow = parse_allow(allow_vals)
    except ValueError as exc:
        print(f"[grid] {exc}")
        return
    if _confirm_autonomous(allow, ask):
        session.set_autonomous(True, allow)
    else:
        print("[grid] autonomous mode not enabled.")


def _model_command(session, arg: str) -> None:
    from grid.app import effective_profile
    from grid.models import ModelError, ModelStore

    try:
        if not arg:
            prof = effective_profile(session.config)
            print(f"[grid] model: {prof.model}" + (f" @ {prof.base_url}" if prof.base_url else ""))
            names = [p.name for p in ModelStore().list()]
            if names:
                print("[grid] saved profiles: " + ", ".join(names) + "  (/model NAME to switch)")
            return
        print("[grid] " + session.switch_model(ModelStore().get(arg)))
    except ModelError as exc:
        print(f"[grid] {exc}")


# --------------------------------------------------------------- REPL

def _repl(session, first_task: str | None, once: bool) -> int:
    from grid.project import detect_verify_command
    from grid.verify import run_verify

    last = None
    if first_task:
        last = session.submit(first_task)
        if once:
            return last.outcome.exit_code
    print("\n[grid] interactive session - /help for commands, /quit to exit.")
    while True:
        try:
            line = input("\ngrid> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        from grid.lessons import NAMES as LESSON_COMMANDS

        first = line.split()[0]
        if not line.startswith("/") or ":" in first or first[1:].lower() in LESSON_COMMANDS:   # tasks, /plugin:cmd, lessons
            last = session.submit(line)
            continue
        cmd, _, arg = line[1:].partition(" ")
        arg = arg.strip()
        if cmd in ("quit", "exit", "q"):
            break
        elif cmd == "help":
            print(REPL_HELP)
        elif cmd == "plan":
            if not arg:
                print("usage: /plan <task>")
            else:
                last = session.submit(arg, plan=True)
        elif cmd == "undo":
            print("[grid] " + session.undo(arg or None))
        elif cmd == "checkpoints":
            if session.checkpoints is not None:
                _print_checkpoints(session.checkpoints)
        elif cmd == "diff":
            if session.checkpoints is None:
                print("checkpoints are disabled")
                continue
            base = session.checkpoints.get(arg) if arg else (last.start_checkpoint if last else None)
            base = base or (session.checkpoints.list() or [None])[0]
            print(session.checkpoints.diff(base.sha) if base else "(no checkpoints)")
        elif cmd == "verify":
            command = session.config.verify_command or detect_verify_command(session.workspace)
            if not command:
                print("no check found - add `verify: <command>` to GRID.md")
            else:
                r = run_verify(command, session.workspace)
                print(r.tail())
                print(f"[grid][verify] {'PASS' if r.ok else 'FAIL'} - {r.label()}")
        elif cmd == "depth":
            try:
                session.config.depth = DepthLevel(arg)
                print(f"[grid] depth set to {arg} (applies to new sessions; current guidance stays)")
            except ValueError:
                print("usage: /depth beginner|intermediate|pro")
        elif cmd == "model":
            _model_command(session, arg)
        elif cmd == "auto":
            _auto_command(session, arg)
        elif cmd == "yolo":
            from grid.app import apply_grid_policy

            session.config.confirm_yellow = False
            apply_grid_policy(session.conversation, session.config)
            print("[grid] YELLOW actions will run without asking. RED still always asks.")
        else:
            print(f"unknown command /{cmd} - /help for commands")
    return last.outcome.exit_code if last is not None else 0


# --------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from grid.pyshim import ensure_python_command

    ensure_python_command()          # `python` works on Macs that only have python3
    if argv and argv[0] in SUBCOMMANDS:
        return _subcommand(argv)

    args = _parse_args(argv)
    if args.allow and not args.autonomous:
        print("grid: --allow only applies with --autonomous", file=sys.stderr)
        return 2
    if args.autonomous and args.no_verify:
        print("grid: --autonomous always verifies; drop --no-verify", file=sys.stderr)
        return 2
    try:
        config = _config_from(args)
    except ValueError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    from grid.models import ModelError, compat_summary, resolve_profile

    try:
        profile, source = resolve_profile(cli_model=args.model, cli_profile=args.profile)
        config.model_profile = profile
        from grid.app import effective_profile

        effective = effective_profile(config)
    except ModelError as exc:
        print(f"grid: {exc}", file=sys.stderr)
        return 2
    from grid.models import check_endpoint

    problem = check_endpoint(effective)
    if problem:
        print(f"[grid] warning: {problem}", file=sys.stderr)
    where = f" @ {effective.base_url}" if effective.base_url else ""
    print(f"[grid] model: {effective.model}{where}  ({source}"
          + (f", profile '{profile.name}': {compat_summary(profile)}" if profile.name not in ("cli", "env", "builtin") else "")
          + (", prompted tools" if not effective.native_tool_calling else "") + ")")
    workspace = os.path.realpath(args.workspace or os.getcwd())
    if not os.path.isdir(workspace):
        print(f"grid: workspace not found: {workspace}", file=sys.stderr)
        return 2
    if args.headless and not args.task:
        print("grid: --headless needs a task", file=sys.stderr)
        return 2

    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
    os.environ.setdefault("LOG_LEVEL", "WARNING")  # SDK info logs drown out Grid's own lines
    # Deferred: `grid --help` and the subcommands work without the SDK.
    from grid.app import last_session_id
    from grid.session import UI, GridSession

    resume_id = None
    if args.resume:
        resume_id = last_session_id(workspace) if args.resume == "last" else args.resume
        if not resume_id:
            print("grid: no saved session to resume in this project", file=sys.stderr)
            return 2

    interactive = not args.headless and sys.stdin.isatty()
    if interactive:
        ask_age_once()
    if args.autonomous and interactive and not args.yes and not _confirm_autonomous(config.allow_red):
        print("[grid] autonomous mode not enabled.")
        config.autonomous = False
        config.allow_red = frozenset()
    ui = UI(interactive=interactive)
    try:
        session = GridSession(workspace, config, ui, resume_id=resume_id)
    except Exception as exc:
        print(f"grid: could not start the agent: {exc}", file=sys.stderr)
        return 1
    if resume_id:
        print(f"[grid] resumed session {session.conversation.id}")
    try:
        if not interactive or args.once:
            if not args.task:
                print("grid: no task given (stdin is not a terminal)", file=sys.stderr)
                return 2
            report = session.submit(args.task)
            return report.outcome.exit_code
        return _repl(session, args.task, once=False)
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
