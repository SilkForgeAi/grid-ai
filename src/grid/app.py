"""Composition root: build the SDK LLM, Agent and Conversation with Grid's layers.

The SDK supplies the loop, tools, terminal, event stream, persistence, context
condensation, skills and MCP. Grid shapes it:

  - tools: terminal, file editor, grep, glob, task tracker (+ optional browser,
    sub-agents, and any MCP servers from .grid/mcp.json)
  - prompt: verification-first working rules, teaching depth, confidence
    reporting, and layered GRID.md instructions
  - safety: GridConfirmationPolicy + GridSecurityAnalyzer (model label,
    confidence escalation and deterministic rules; worst wins)
  - stuck detection thresholds and a step budget (max_iteration_per_run)

Every SDK import is deferred into function bodies so this module imports
without the SDK (the session logic is unit-tested against stand-ins).
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

from grid.confidence import ConfidenceGate
from grid.confidence_emit import CONFIDENCE_INSTRUCTION, read_confidence
from grid.config import GridConfig
from grid.events import action_info, action_reasoning, action_thought
from grid.models import DEFAULT_MODEL, ModelError, ModelProfile, build_llm_from_profile, resolve_profile  # noqa: F401
from grid.project import grid_home, load_instructions, project_key
from grid.safety import SAFETY_POLICY
from grid.teaching import teaching_prompt, why_did_this_break_prompt
from grid.tiers import GridTier, tier_from_risk_value

WORKING_RULES = """\
HOW TO WORK (Grid AI):
- Before changing code, restate the goal as something checkable (a test, a command and its expected output).
- Explore first: use grep/glob and view files instead of guessing paths or APIs.
- For anything with more than two steps, keep a task list with the task_tracker tool and update it as you go.
- Make small, focused edits. After each meaningful change, run the relevant tests yourself in the terminal and read the output.
- Never skip, delete or weaken a test to make it pass. Never silence failures.
- You are not done until the project's checks pass. Grid will run them itself before accepting "done".
- If the project has no tests covering your change, write one. If there is no test runner at all, end your final
  message with a line `VERIFY: <command>` naming a command that exits 0 only if your change works. Grid runs it.
- If you are blocked or need a decision only the user can make, finish and say exactly what you need.
- If the message is just conversation or a question, answer it and finish - don't touch files or run anything.
- When they ask you to build, make or fix something (or pick an option you offered), DO it in their project:
  create the files with your tools, run them to check they work, then explain briefly what you made and how to
  open it. Never answer a build request with only a plan or code pasted into the chat. Ask first only if a
  choice truly blocks you (one short question). Teaching happens while you build, not instead of building.
- Web apps that anyone with a link should use: prefer a static site (index.html + CSS + JS, no server) unless
  it really needs a backend. It runs by opening index.html, and it can be published free on GitHub Pages,
  Netlify or Cloudflare Pages. You can't publish to the internet yourself: make it ready, check it works
  locally, then give the exact publishing steps. Don't suggest hosts that can't run what you built
  (GitHub Pages serves static files only - no Flask, no Streamlit)."""

PLAN_INSTRUCTION = """\
PLAN MODE: investigate and produce a plan only. You may read files, search, list directories and run tests,
but do NOT create, edit or delete files, install anything, or run commands that change state - those will be
rejected. When ready, call finish with the plan as your message, using these sections:
OBJECTIVE, CONTEXT (files involved), APPROACH, STEPS (numbered), VERIFICATION (the exact command that proves it works), RISKS."""


def effective_profile(config: GridConfig) -> ModelProfile:
    """The model profile this config runs with, after --prompted-tools and the
    local-only check. Raises ModelError when local-only forbids it."""
    profile = config.model_profile or resolve_profile()[0]
    if config.prompted_tools and profile.native_tool_calling:
        profile = replace(profile, native_tool_calling=False)
    if config.local_only and not profile.is_local():
        raise ModelError(
            f"--local-only: {profile.model}"
            + (f" @ {profile.base_url}" if profile.base_url else "")
            + " sends your code off this machine. Use a local profile (e.g. ollama/...)."
        )
    return profile


def build_llm(config: GridConfig):
    """The SDK LLM for this run: any LiteLLM model, local or cloud (see grid.models)."""
    return build_llm_from_profile(effective_profile(config), usage_id="grid-agent")


def load_mcp_config(workspace: str, local_only: bool = False) -> dict:
    """MCP servers from ~/.grid/mcp.json then <workspace>/.grid/mcp.json
    (project wins). Accepts {"mcpServers": {...}} or a bare {name: server}.
    With local_only, remote (url-based) servers are dropped."""
    servers: dict = {}
    for path in (grid_home() / "mcp.json", Path(workspace) / ".grid" / "mcp.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[grid] ignoring {path}: {exc}")
            continue
        servers.update(data.get("mcpServers", data) if isinstance(data, dict) else {})
    if local_only:
        for name in [n for n, cfg in servers.items() if isinstance(cfg, dict) and cfg.get("url")]:
            print(f"[grid] --local-only: skipping remote MCP server '{name}'")
            servers.pop(name)
    return servers


def resolve_persona(config: GridConfig) -> str:
    """The voice for a new conversation. Teacher unless a confirmed adult picked
    Grid; an explicit "teacher" always wins; asking for "grid" can't override the age line."""
    from grid.persona import GRID, TEACHER, PersonaStore

    effective = PersonaStore().load().effective
    if config.persona == TEACHER:
        return TEACHER
    return GRID if effective == GRID else TEACHER


def system_suffix(config: GridConfig, workspace: str) -> str:
    from grid.persona import persona_prompt

    parts = [persona_prompt(resolve_persona(config)), WORKING_RULES]
    teaching = teaching_prompt(config.depth)
    if teaching:
        parts.append(teaching)
        if config.why_did_this_break:
            parts.append(why_did_this_break_prompt())
    parts.append(CONFIDENCE_INSTRUCTION)
    parts += grid_tools_prompt(config, workspace)
    instructions = load_instructions(workspace)
    if instructions:
        parts.append(instructions)
    parts.append(SAFETY_POLICY)
    return "\n\n".join(parts)


def grid_tools_prompt(config: GridConfig, workspace: str) -> list[str]:
    """Instructions for Grid's own tools plus what Grid remembers from earlier chats."""
    out = []
    from grid.tools.prompts import capabilities_prompt

    caps = capabilities_prompt(_grid_tool_names(config))
    if browser_enabled(config):
        from grid.browser_setup import BROWSER_PROMPT

        caps = (caps or "WHAT ELSE YOU CAN DO (Grid tools):") + "\n" + BROWSER_PROMPT
    if caps:
        out.append(caps)
    if config.enable_memory:
        from grid.longmem import MEMORY_INSTRUCTION, context_prompt

        out.append(MEMORY_INSTRUCTION)
        try:
            ctx = context_prompt(workspace)
        except Exception as exc:  # memory must never stop a chat from starting
            print(f"[grid] couldn't load memory: {exc}")
            ctx = ""
        if ctx:
            out.append(ctx)
    return out


def browser_enabled(config: GridConfig) -> bool:
    from grid.moderation import restricted_mode

    if restricted_mode():
        return False
    if not config.enable_browser or config.local_only:
        return False
    from grid.browser_setup import chromium_path

    return chromium_path() is not None


def _grid_tool_names(config: GridConfig) -> list[str]:
    from grid.moderation import restricted_mode

    if restricted_mode():
        return []
    names = []
    if config.enable_memory:
        names.append("memory")
    if config.enable_web and not config.local_only:
        names += ["web_search", "web_fetch"]
    if config.enable_documents:
        names.append("create_document")
    if config.enable_access:
        names.append("request_access")
    if config.enable_images:
        names.append("view_image")
    if config.enable_computer:
        from grid.computer import backend

        if backend() is not None:
            names.append("computer")
    return names


def build_tools(config: GridConfig):
    from openhands.sdk import Tool

    from grid.moderation import restricted_mode

    if restricted_mode():
        import grid.isolated_tools  # noqa: F401

        return [Tool(name="grid_isolated_terminal"), Tool(name="grid_isolated_editor")]
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.glob import GlobTool
    from openhands.tools.grep import GrepTool
    from openhands.tools.task_tracker import TaskTrackerTool
    from openhands.tools.terminal import TerminalTool

    tools = [
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name=GrepTool.name),
        Tool(name=GlobTool.name),
        Tool(name=TaskTrackerTool.name),
    ]
    names = _grid_tool_names(config)
    if names:
        import grid.tools.definitions  # noqa: F401  (registers Grid's tools)

        tools += [Tool(name=n) for n in names]
    if browser_enabled(config):
        from openhands.tools.browser_use import BrowserToolSet

        from grid.browser_setup import patch_browser
        from grid.settings import load_settings

        patch_browser()
        tools.append(Tool(name=BrowserToolSet.name, params={"headless": not load_settings().browser_visible}))
    if config.enable_sub_agents:
        from openhands.tools.task import TaskToolSet

        tools.append(Tool(name=TaskToolSet.name))
    return tools


def build_agent(config: GridConfig, workspace: str, llm=None):
    from openhands.sdk import Agent, AgentContext

    llm = llm or build_llm(config)
    skills = []
    if config.load_project_skills:
        try:
            from openhands.sdk.skills.skill import load_project_skills

            skills = load_project_skills(workspace)
        except Exception as exc:  # a malformed skill file must not stop the agent
            print(f"[grid] could not load project skills: {exc}")

    context = AgentContext(
        skills=skills,
        system_message_suffix=system_suffix(config, workspace),
        load_user_skills=config.load_user_skills,
    )
    from grid.moderation import restricted_mode

    mcp = {} if restricted_mode() else load_mcp_config(workspace, local_only=config.local_only)
    if config.load_plugins and not restricted_mode():
        context, mcp = apply_plugins(workspace, context, mcp, local_only=config.local_only)

    condenser = None
    if config.condense_context:
        from openhands.sdk.context.condenser import default_condenser

        condenser = default_condenser(llm.model_copy(update={"usage_id": "grid-condenser"}))

    return Agent(
        llm=llm,
        tools=build_tools(config),
        agent_context=context,
        condenser=condenser,
        mcp_config=mcp,
        system_prompt_kwargs={"cli_mode": not browser_enabled(config)},
    )


def apply_plugins(workspace: str, context, mcp: dict, *, local_only: bool = False):
    """Merge enabled plugins' skills and MCP servers into the agent setup.
    Commands are expanded by the session (`/plugin:command args`), so the
    command-derived keyword skills are not added here."""
    from grid.plugins import PluginManager

    skills = {s.name: s for s in context.skills}
    for plugin in PluginManager(workspace).enabled_plugins():
        for skill in plugin.skills:
            skills[skill.name] = skill
        for name, cfg in plugin.mcp_config.items():
            raw = cfg.model_dump(exclude_none=True) if hasattr(cfg, "model_dump") else cfg
            if local_only and isinstance(raw, dict) and raw.get("url"):
                print(f"[grid] --local-only: skipping remote MCP server '{name}' from plugin '{plugin.name}'")
                continue
            mcp[name] = raw
    return context.model_copy(update={"skills": list(skills.values())}), mcp


def sessions_dir(workspace: str) -> Path:
    return grid_home() / "sessions" / project_key(workspace)


def last_session_id(workspace: str) -> str | None:
    f = sessions_dir(workspace) / "LAST"
    return f.read_text().strip() if f.is_file() else None


def list_sessions(workspace: str) -> list[tuple[str, float]]:
    d = sessions_dir(workspace)
    if not d.is_dir():
        return []
    out = [(p.name, p.stat().st_mtime) for p in d.iterdir() if p.is_dir()]
    return sorted(out, key=lambda t: t[1], reverse=True)


def streaming(llm):
    """The same model, streaming its reply (TestLLM and friends stay as they are)."""
    if type(llm).__name__ != "LLM" or llm.stream:
        return llm
    return llm.model_copy(update={"stream": True})


def apply_grid_policy(conversation, config: GridConfig) -> None:
    from grid.policy import GridConfirmationPolicy

    conversation.set_confirmation_policy(
        GridConfirmationPolicy(
            confirm_yellow=config.confirm_yellow,
            confirm_unknown=config.confirm_unknown,
        )
    )


def apply_plan_policy(conversation) -> None:
    """Plan mode: every action pauses so the session can allow reads and reject writes."""
    from openhands.sdk.security.confirmation_policy import AlwaysConfirm

    conversation.set_confirmation_policy(AlwaysConfirm())


def build_conversation(
    config: GridConfig,
    workspace: str,
    *,
    llm=None,
    callbacks=None,
    conversation_id: str | None = None,
    persist: bool = True,
    visualizer="default",
    token_callbacks=None,
):
    """A ready SDK Conversation with Grid's policy, analyzer, stuck thresholds,
    step budget and (optionally) on-disk persistence for resume."""
    from openhands.sdk import Conversation

    from grid.analyzer import GridSecurityAnalyzer
    from grid.moderation import restricted_mode
    from grid.policy import GridConfirmationPolicy  # noqa: F401  (a saved chat names it; resuming needs it registered)
    from grid.toolcall_repair import install as rescue_tool_calls

    rescue_tool_calls()     # a valid call followed by junk (small local models) is kept, not thrown away

    if restricted_mode():
        from grid.isolation import require_isolation

        require_isolation()
    agent = build_agent(config, workspace, llm=llm)
    kwargs = {}
    if token_callbacks:
        # Stream the model's words into the app as it writes them.
        agent = agent.model_copy(update={"llm": streaming(agent.llm)})
        kwargs["token_callbacks"] = list(token_callbacks)
    if persist:
        d = sessions_dir(workspace)
        d.mkdir(parents=True, exist_ok=True)
        cid = uuid.UUID(conversation_id) if conversation_id else uuid.uuid4()
        kwargs.update(persistence_dir=str(d), conversation_id=cid, delete_on_close=False)
    if visualizer != "default":
        kwargs["visualizer"] = visualizer

    conversation = Conversation(
        agent=agent,
        workspace=workspace,
        callbacks=list(callbacks or []),
        stuck_detection_thresholds=config.stuck_thresholds(),
        max_iteration_per_run=max(1, config.soft_step_budget),
        **kwargs,
    )
    if persist:
        (sessions_dir(workspace) / "LAST").write_text(str(conversation.id))

    apply_grid_policy(conversation, config)
    conversation.set_security_analyzer(
        GridSecurityAnalyzer(
            confidence_threshold=config.confidence_threshold,
            strict=config.strict_confidence,
            escalate_on_missing=config.escalate_on_missing_confidence,
            enforce_confidence=config.enforce_confidence,
            workspace=os.path.realpath(workspace),
            chat_id=str(conversation.id),
        )
    )
    return conversation


# --- observe-only confidence badge -------------------------------------------

def _action_base_tier(event) -> GridTier:
    risk = getattr(event, "security_risk", None)
    value = getattr(risk, "value", None)
    if isinstance(value, str):
        try:
            return tier_from_risk_value(value)
        except ValueError:
            return GridTier.UNKNOWN
    return GridTier.UNKNOWN


def confidence_badge(event, config: GridConfig) -> str | None:
    """`[grid][confidence] ...` line for an ActionEvent, or None for other events."""
    thought = action_thought(event)
    if thought is None or not getattr(event, "tool_call_id", None):
        return None
    if action_info(event).tool_name in ("finish", "think"):
        return None
    gate = ConfidenceGate(threshold=config.confidence_threshold, strict=config.strict_confidence)
    reading = read_confidence(thought, _action_base_tier(event), gate, reasoning=action_reasoning(event))
    if reading is None:
        return "[grid][confidence] no score reported - treating cautiously."
    badge = f"[grid][confidence] {reading.label} ({reading.base_tier.value})"
    if reading.downgraded:
        badge += f" -> downgraded to {reading.effective_tier.value} (ask first)"
    return badge
