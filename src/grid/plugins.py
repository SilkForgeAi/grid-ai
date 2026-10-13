"""Plugins: installable bundles of skills, slash commands and MCP servers.

Grid uses the SDK's standard plugin layout for skills, commands and tools:

    my-plugin/
      .plugin/plugin.json     {"name", "version", "description", ...}
      skills/<skill>/SKILL.md        knowledge the agent pulls in when relevant
      commands/<command>.md          slash commands: /my-plugin:command args
      .mcp.json                      MCP servers (external tools)

Two scopes: user (~/.grid/plugins, every project) and project
(<project>/.grid/plugins, that project only; wins on name clashes).
Installing copies the plugin in, so later changes at the source don't
silently change what runs. Hooks and agent definitions in a plugin are listed
but not run yet.

Sources: a local folder, `builtin:<name>` (Grid's starter catalog), or git
(`github:owner/repo`, an https/ssh git URL).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grid.project import grid_home

BUILTIN_DIR = Path(__file__).parent / "plugins_builtin"
_NAME_RE = re.compile(r"[^a-z0-9._-]+")


class PluginError(ValueError):
    pass


@dataclass
class CommandInfo:
    plugin: str
    name: str
    description: str = ""
    argument_hint: str | None = None

    @property
    def slash(self) -> str:
        return f"/{self.plugin}:{self.name}"


@dataclass
class PluginInfo:
    name: str
    version: str = ""
    description: str = ""
    scope: str = "user"            # user | project | preview | builtin
    path: str = ""
    enabled: bool = True
    source: str = ""
    skills: list[str] = field(default_factory=list)
    commands: list[CommandInfo] = field(default_factory=list)
    mcp: dict[str, str] = field(default_factory=dict)   # server -> what it runs / connects to
    has_hooks: bool = False
    agents: list[str] = field(default_factory=list)
    installed_at: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["commands"] = [asdict(c) | {"slash": c.slash} for c in self.commands]
        return d


def _dir_name(name: str) -> str:
    s = _NAME_RE.sub("-", name.lower()).strip("-.")
    if not s:
        raise PluginError(f"bad plugin name {name!r}")
    return s


def _describe_mcp(cfg) -> str:
    if hasattr(cfg, "model_dump"):
        cfg = cfg.model_dump(exclude_none=True)
    if not isinstance(cfg, dict):
        return str(cfg)
    if cfg.get("url"):
        return f"connects to {cfg['url']}"
    cmd = " ".join([str(cfg.get("command", ""))] + [str(a) for a in cfg.get("args", [])]).strip()
    return f"runs `{cmd}`" if cmd else "?"


def inspect_plugin(path: str | Path, *, scope: str = "preview", source: str = "") -> PluginInfo:
    """Load a plugin folder and describe everything it contains."""
    from openhands.sdk.plugin import Plugin

    try:
        plugin = Plugin.load(path)
    except Exception as exc:
        raise PluginError(f"not a valid plugin at {path}: {exc}") from exc
    return PluginInfo(
        name=plugin.name,
        version=plugin.version,
        description=plugin.description,
        scope=scope,
        path=str(Path(path).resolve()),
        source=source,
        skills=sorted(s.name for s in plugin.skills),
        commands=[CommandInfo(plugin.name, c.name, c.description, c.argument_hint) for c in plugin.commands],
        mcp={name: _describe_mcp(cfg) for name, cfg in plugin.mcp_config.items()},
        has_hooks=plugin.hooks is not None and bool(plugin.hooks.model_dump(exclude_none=True, exclude_defaults=True)),
        agents=[a.name for a in plugin.agents],
    )


def builtin_catalog() -> list[PluginInfo]:
    out = []
    if BUILTIN_DIR.is_dir():
        for d in sorted(BUILTIN_DIR.iterdir()):
            if d.is_dir():
                try:
                    out.append(inspect_plugin(d, scope="builtin", source=f"builtin:{d.name}"))
                except PluginError:
                    continue
    return out


def resolve_source(source: str) -> Path:
    """A local folder for `source`, fetching git sources into Grid's cache."""
    source = source.strip()
    if source.startswith("builtin:"):
        p = BUILTIN_DIR / source.split(":", 1)[1]
        if not p.is_dir():
            raise PluginError(f"no built-in plugin {source!r}")
        return p
    local = Path(os.path.expanduser(source))
    if local.is_dir():
        return local.resolve()
    if source.startswith(("github:", "https://", "http://", "git@", "ssh://")):
        from openhands.sdk.plugin import Plugin

        try:
            return Path(Plugin.fetch(source, cache_dir=grid_home() / "cache" / "plugins"))
        except Exception as exc:
            raise PluginError(f"couldn't fetch {source}: {exc}") from exc
    raise PluginError(f"plugin source not found: {source!r} (a folder, builtin:NAME, github:owner/repo, or a git URL)")


class PluginManager:
    def __init__(self, workspace: str | os.PathLike | None = None):
        self.workspace = Path(os.path.realpath(workspace)) if workspace else None

    # -- locations -----------------------------------------------------------
    def _root(self, scope: str) -> Path:
        if scope == "user":
            return grid_home() / "plugins"
        if scope == "project":
            if self.workspace is None:
                raise PluginError("project scope needs a project")
            return self.workspace / ".grid" / "plugins"
        raise PluginError(f"unknown scope {scope!r} (user or project)")

    def _registry_path(self, scope: str) -> Path:
        return self._root(scope) / "registry.json"

    def _registry(self, scope: str) -> dict:
        p = self._registry_path(scope)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_registry(self, scope: str, data: dict) -> None:
        p = self._registry_path(scope)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, p)

    def _scopes(self) -> list[str]:
        return ["user", "project"] if self.workspace is not None else ["user"]

    # -- queries ---------------------------------------------------------------
    def list(self) -> list[PluginInfo]:
        out: list[PluginInfo] = []
        for scope in self._scopes():
            reg = self._registry(scope)
            for dirname, meta in sorted(reg.items()):
                path = self._root(scope) / dirname
                try:
                    info = inspect_plugin(path, scope=scope, source=meta.get("source", ""))
                except PluginError as exc:
                    info = PluginInfo(name=dirname, scope=scope, path=str(path), description=f"(broken: {exc})")
                info.enabled = bool(meta.get("enabled", True))
                info.installed_at = meta.get("installed_at")
                out.append(info)
        return out

    def get(self, name: str, scope: str | None = None) -> PluginInfo:
        for info in self.list():
            if info.name == name and (scope is None or info.scope == scope):
                return info
        raise PluginError(f"plugin {name!r} is not installed")

    def enabled_plugins(self):
        """SDK Plugin objects for every enabled plugin; project scope wins on
        name clashes. A plugin that fails to load is skipped with a warning."""
        from openhands.sdk.plugin import Plugin

        chosen: dict[str, Path] = {}
        for scope in self._scopes():
            for dirname, meta in self._registry(scope).items():
                if meta.get("enabled", True):
                    chosen[dirname] = self._root(scope) / dirname
        plugins = []
        for dirname, path in chosen.items():
            try:
                plugins.append(Plugin.load(path))
            except Exception as exc:
                print(f"[grid] plugin '{dirname}' failed to load and was skipped: {exc}")
        return plugins

    def commands(self) -> list[CommandInfo]:
        return [c for info in self.list() if info.enabled for c in info.commands]

    # -- changes ---------------------------------------------------------------
    def preview(self, source: str) -> PluginInfo:
        return inspect_plugin(resolve_source(source), source=source)

    def install(self, source: str, *, scope: str = "user", enable: bool = True, replace: bool = False) -> PluginInfo:
        src = resolve_source(source)
        info = inspect_plugin(src, source=source)
        dirname = _dir_name(info.name)
        dest = self._root(scope) / dirname
        reg = self._registry(scope)
        if (dest.exists() or dirname in reg) and not replace:
            raise PluginError(f"plugin {info.name!r} is already installed ({scope}); use replace to update it")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git", "__pycache__", "node_modules"))
        reg[dirname] = {"enabled": enable, "source": source, "installed_at": time.time(), "version": info.version}
        self._save_registry(scope, reg)
        return self.get(info.name, scope)

    def set_enabled(self, name: str, enabled: bool, scope: str | None = None) -> None:
        info = self.get(name, scope)
        reg = self._registry(info.scope)
        dirname = Path(info.path).name
        reg.setdefault(dirname, {})["enabled"] = enabled
        self._save_registry(info.scope, reg)

    def remove(self, name: str, scope: str | None = None) -> None:
        info = self.get(name, scope)
        reg = self._registry(info.scope)
        dirname = Path(info.path).name
        reg.pop(dirname, None)
        self._save_registry(info.scope, reg)
        root = self._root(info.scope).resolve()
        target = Path(info.path).resolve()
        if target.parent == root and target.exists():
            shutil.rmtree(target)


# -- slash commands -------------------------------------------------------------

_SLASH_RE = re.compile(r"^\s*/([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)(?:\s+(.*))?$", re.DOTALL)


def expand_command(text: str, plugins) -> str | None:
    """`/plugin:command args` -> the command's instructions with $ARGUMENTS filled
    in, or None when `text` isn't a known plugin command."""
    m = _SLASH_RE.match(text or "")
    if not m:
        return None
    pname, cname, args = m.group(1), m.group(2), (m.group(3) or "").strip()
    for plugin in plugins:
        if plugin.name != pname:
            continue
        for cmd in plugin.commands:
            if cmd.name == cname:
                body = cmd.content
                if "$ARGUMENTS" in body:
                    body = body.replace("$ARGUMENTS", args)
                elif args:
                    body = f"{body}\n\nArguments: {args}"
                return f"(Running command /{pname}:{cname})\n\n{body}"
    return None
