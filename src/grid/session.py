"""GridSession — drives an SDK Conversation the way a coding agent needs.

`conversation.run()` returns whenever the agent stops: finished, waiting for
approval, out of step budget, stuck, or paused. The session decides what happens
next, which is where Grid's product behavior lives:

  - approvals: show each pending action with its tier and reasons; approve,
    reject (with a reason the agent sees), or allow YELLOW for the session.
    RED is always asked. Headless runs reject what needs a human.
  - checkpoints: every state-changing action is snapshotted (shadow git), so
    any step can be undone; test runs are tied to the checkpoint they ran on.
  - regression revert: when a change lowers the test pass rate, the session
    restores the last good checkpoint and tells the agent what happened.
  - step budget: every N steps, a check-in instead of a hard stop.
  - plan mode: read-only investigation -> plan -> user approval -> execution.
  - proof of outcome: "done" is accepted only after Grid runs the verify
    command itself and it passes (the agent gets sent back otherwise).

All user interaction goes through `UI`, so the whole loop is testable with a
scripted UI and the SDK's TestLLM.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from grid.access import granted_roots
from grid.app import (
    PLAN_INSTRUCTION,
    apply_grid_policy,
    apply_plan_policy,
    build_conversation,
    confidence_badge,
)
from grid.autonomy import AutonomyPolicy, PendingItem, describe_mode
from grid.checkpoints import Checkpoint, CheckpointError, CheckpointStore
from grid.config import GridConfig
from grid.events import (
    action_info,
    action_reasoning,
    action_thought,
    describe_action,
    is_action,
    is_observation,
    observation_text,
    observation_tool,
)
from grid.execution import exclusive_task
from grid.memory import Episode, MemoryStore
from grid.project import detect_test_runner, verify_from_instructions
from grid.regression import RegressionDetector, RunResult
from grid.rules import classify_command, is_read_only
from grid.safety import REFUSAL, action_blocked_reason, blocked_reason
from grid.tiers import GridTier, tier_from_risk_value
from grid.verify import VerifyResult, declared_verify_command, run_verify, test_integrity_reason, trivial_check_reason


class Outcome(str, Enum):
    VERIFIED = "verified"          # done, and the verify command passed
    DONE = "done"                  # done, nothing to verify (no changes / no check found)
    UNVERIFIED = "unverified"      # done, but the check still fails
    PLANNED = "planned"            # plan produced (headless plan or plan rejected)
    PAUSED = "paused"              # user stopped, or waiting on the user
    NEEDS_APPROVAL = "needs_approval"  # headless and the agent kept needing a human
    STUCK = "stuck"
    ERROR = "error"
    BLOCKED = "blocked"

    @property
    def exit_code(self) -> int:
        return {
            Outcome.VERIFIED: 0, Outcome.DONE: 0, Outcome.PLANNED: 0,
            Outcome.UNVERIFIED: 3, Outcome.NEEDS_APPROVAL: 4, Outcome.STUCK: 5,
            Outcome.PAUSED: 6, Outcome.ERROR: 1, Outcome.BLOCKED: 7,
        }[self]


@dataclass
class UI:
    """How the session talks to a human. `ask` returns the raw answer."""

    say: Callable[[str], None] = print
    ask: Callable[[str], str] = input
    interactive: bool = True


@dataclass
class TaskReport:
    outcome: Outcome
    message: str = ""
    verify: VerifyResult | None = None
    changed: list[str] = field(default_factory=list)
    start_checkpoint: Checkpoint | None = None


_STATE_CHANGING_TOOLS = {"terminal", "file_editor", "apply_patch"}


class GridSession:
    def __init__(
        self,
        workspace: str | None = None,
        config: GridConfig | None = None,
        ui: UI | None = None,
        *,
        llm=None,
        resume_id: str | None = None,
        persist: bool = True,
        visualizer="default",
        callbacks: list | None = None,
        relay=None,
    ):
        self.config = config or GridConfig()
        from grid.moderation import restricted_mode

        if restricted_mode():
            from dataclasses import replace

            self.config = replace(self.config, enable_browser=False, enable_sub_agents=False, enable_web=False,
                                  enable_computer=False, enable_access=False, enable_memory=False,
                                  load_plugins=False, load_project_skills=False, load_user_skills=False)
        self.relay = relay                # grid.stream.StreamRelay: live text for the app
        self.workspace = os.path.realpath(workspace or os.getcwd())
        self.ui = ui or UI()
        self.memory = MemoryStore.for_workspace(self.workspace)
        self.detector = RegressionDetector()
        self.checkpoints: CheckpointStore | None = None
        if self.config.checkpoints:
            try:
                self.checkpoints = CheckpointStore(self.workspace)
            except CheckpointError as exc:
                self.ui.say(f"[grid] checkpoints disabled: {exc}")

        self._plan_mode = False
        self._regression_reason: str | None = None
        self._pending_desc: dict[str, tuple[str, bool]] = {}
        self._run_for_checkpoint: dict[int, RunResult] = {}
        self._steps = 0
        self._start: Checkpoint | None = None
        self._notes: list[str] = []
        self._policy_history: list[str] = []
        self.stop_requested = False       # set by the app's Stop button; checked between steps
        self.cancel_verify = threading.Event()
        self._task_verify = True          # lesson tasks turn verification off
        self._reviewed = False            # the one consistency review of this task has been asked for
        self._watch_regressions = True    # ...and regression revert

        from grid.app import resolve_persona

        self.voice = resolve_persona(self.config)   # the voice baked into this conversation
        self._initial_voice = self.voice

        self.conversation = build_conversation(
            self.config, self.workspace, llm=llm, callbacks=[self._on_event, *(callbacks or [])],
            conversation_id=resume_id, persist=persist, visualizer=visualizer,
            token_callbacks=[relay.on_chunk] if relay is not None else None,
        )
        if self.checkpoints is not None:
            self.checkpoints.session = str(self.conversation.id)
        self.chat_id = str(self.conversation.id)
        from grid.persona import PersonaStore
        from grid.tools.host import ToolHost, register

        prof = PersonaStore().load()
        register(self.chat_id, ToolHost(workspace=self.workspace, ask=self._tool_ask, say=self.ui.say,
                                        safe_search=prof.minor_lock or prof.age_answer != "adult"))
        if self.config.autonomous:
            self.set_autonomous(True, self.config.allow_red)

    # ------------------------------------------------------------------ plugins
    def _expand_command(self, text: str) -> str | None:
        if not self.config.load_plugins or not text.lstrip().startswith("/"):
            return None
        from grid.plugins import PluginManager, expand_command

        try:
            return expand_command(text, PluginManager(self.workspace).enabled_plugins())
        except Exception as exc:
            self.ui.say(f"[grid] plugin command failed to expand: {exc}")
            return None

    # ------------------------------------------------------------------ model
    def switch_model(self, profile) -> str:
        """Swap the agent's model mid-session (history is kept)."""
        from dataclasses import replace

        from grid.app import effective_profile
        from grid.models import build_llm_from_profile

        trial = replace(self.config, model_profile=profile)
        effective = effective_profile(trial)  # raises ModelError under --local-only
        llm = build_llm_from_profile(effective, usage_id=f"grid-agent-{effective.name}")
        if self.relay is not None:
            from grid.app import streaming

            llm = streaming(llm)
        self.conversation.switch_llm(llm)
        self.config.model_profile = profile
        return f"now using {effective.model}" + (f" @ {effective.base_url}" if effective.base_url else "")

    # ------------------------------------------------------------------ autonomy
    def set_autonomous(self, on: bool, allow: frozenset[str] | None = None) -> None:
        """Turn autonomous mode on/off. The caller is responsible for having
        obtained the user's approval (the CLI asks before calling this)."""
        self.config.autonomous = on
        if allow is not None:
            self.config.allow_red = frozenset(allow)
        if on:
            self.config.confirm_yellow = False
            self.config.confirm_unknown = False
            self.config.auto_revert = True
            self.config.verify = True          # never relaxed in autonomous mode
            self.ui.say("[grid] " + describe_mode(self.config.allow_red, self.config.autonomous_max_steps, self.config.self_review))
        else:
            self.config.confirm_yellow = True
            self.config.confirm_unknown = True
            self.ui.say("[grid] autonomous mode off - Grid will ask before risky actions again.")
        apply_grid_policy(self.conversation, self.config)

    def _tool_ask(self, prompt: str) -> str | None:
        """Tools (folder access) ask the person only when someone is there to answer."""
        if not self._asking or self.stop_requested:
            return None
        return self.ui.ask(prompt)

    @property
    def _asking(self) -> bool:
        """True when a human should be prompted (interactive and not autonomous)."""
        return self.ui.interactive and not self.config.autonomous

    # ------------------------------------------------------------------ events
    def _on_event(self, event) -> None:
        try:
            if self.relay is not None and (is_action(event) or type(event).__name__ == "MessageEvent"):
                self.relay.end()         # that model call is done; its result is a real event now
            if is_action(event):
                self._steps += 1
                self._pending_desc[str(getattr(event, "id", ""))] = (
                    describe_action(event), is_read_only(action_info(event))
                )
                badge = confidence_badge(event, self.config)
                if badge:
                    self.ui.say(badge)
            elif is_observation(event):
                self._on_observation(event)
        except Exception as exc:  # an observer must never kill the agent loop
            self.ui.say(f"[grid] observer error: {exc}")

    def _on_observation(self, event) -> None:
        tool = observation_tool(event)
        cp = None
        desc, read_only = self._pending_desc.pop(str(getattr(event, "action_id", "")), (tool, False))
        if self.checkpoints is not None and tool in _STATE_CHANGING_TOOLS and not read_only:
            cp = self.checkpoints.snapshot(f"after: {desc[:120]}")
            if cp is not None:
                self.ui.say(f"[grid][checkpoint] #{cp.id} {cp.label}")
        if tool != "terminal" or not self._watch_regressions:
            return
        result = self.detector.record_from_output(observation_text(event))
        if result is None:
            return
        self._tie_run_to_checkpoint(result, cp)
        if self.detector.is_regression():
            self._regression_reason = self.detector.reason() or "test pass rate dropped"
            self.ui.say(f"\n[grid][regression] {self._regression_reason}\n")
            self.conversation.pause()  # reentrant: takes effect before the next step

    def _tie_run_to_checkpoint(self, result: RunResult, cp: Checkpoint | None) -> None:
        if self.checkpoints is None:
            return
        if cp is None:
            cp = self._head_checkpoint()
        if cp is None:
            return
        good = not self.detector.is_regression() and not result.errored
        tests = "suite failed to run" if result.errored else f"{result.passed}/{result.executed} passed"
        self.checkpoints.mark(cp, tests=tests, good=good)
        if good:
            self._run_for_checkpoint[cp.id] = result

    # ------------------------------------------------------------------ public
    @exclusive_task
    def submit(self, task: str, *, plan: bool | None = None, images: list[str] | None = None) -> TaskReport:
        """Run one task to an outcome. Follow-ups reuse the same conversation."""
        plan = self.config.plan_first if plan is None else plan
        self.stop_requested = False
        self.cancel_verify.clear()
        original = task

        from grid.moderation import policy_reason

        reason = blocked_reason(task) or policy_reason(task, kind="task", context=self._policy_history)
        if reason:
            self.ui.say(f"[grid][safety] {reason} {REFUSAL}")
            return TaskReport(Outcome.BLOCKED, REFUSAL)

        self._policy_history = [*self._policy_history[-7:], task]
        from grid.moderation import set_context

        set_context(self.chat_id, self._policy_history)

        from grid.lessons import expand_lesson
        from grid.persona import GRID, MODE_NOTE, TEACHER, PersonaStore, says_under_18

        # Under-18 check first, so the reply to this very message is already in teacher mode.
        if says_under_18(task):
            store = PersonaStore()
            if not store.load().minor_lock:
                store.lock_minor()
                self.ui.say("[grid][persona] Teacher mode is on.")
            self.voice = TEACHER
        elif self.voice == GRID and PersonaStore().load().effective == TEACHER:
            self.voice = TEACHER         # locked or switched in Settings since this chat started

        lesson = expand_lesson(task)
        expanded = None
        self._task_verify = lesson is None
        self._watch_regressions = lesson is None
        if lesson is not None:
            task = lesson
        else:
            expanded = self._expand_command(task)
            if expanded is not None:
                task = expanded

        if blocked_reason(task) or (task != original and policy_reason(task, kind="expanded_task", context=self._policy_history)):
            self.ui.say(f"[grid][safety] {REFUSAL}")
            return TaskReport(Outcome.BLOCKED, REFUSAL)

        # Plain conversation gets a quick, streamed answer; anything that needs tools falls through.
        from grid.quick import needs_tools

        if (self.config.quick_replies and not plan and not images and lesson is None and expanded is None
                and not original.lstrip().startswith("/") and not needs_tools(original)):
            reply = self._quick_reply(original)
            if reply is not None:
                self._record_quick(task if task != original else original, reply)
                report = TaskReport(Outcome.DONE, reply)
                self._archive(original, report)
                return report

        start = None
        # Freeze existing project verification before the agent can edit its
        # instructions. A newly supplied check still goes through scrutiny.
        self._frozen_verify = None
        self._frozen_verify = self._choose_verify_command("", [])
        if self.checkpoints is not None:
            start = self.checkpoints.current(f"start: {original[:80]}")
            self.checkpoints.mark(start, good=True)
        self._start = start
        self._reviewed = False
        # The system prompt of a chat that started in the Grid voice still has it, so every
        # later message carries the switch until the chat ends.
        if self.voice == TEACHER and self._initial_voice == GRID:
            task = f"{MODE_NOTE}\n{task}"

        raw_task = original
        recall = self.memory.recall_prompt(task)
        if self.config.enable_memory:
            from grid.longmem import recall_for_task

            try:
                past = recall_for_task(original, self.workspace, self.chat_id)
            except Exception:
                past = ""
            if past:
                recall = f"{recall}\n\n{past}" if recall else past
        message = task if not recall else f"{task}\n\n{recall}"
        if self._notes:
            message = "\n".join(self._notes) + "\n\n" + message
            self._notes.clear()

        images = [u for u in (images or []) if isinstance(u, str) and u.startswith("data:image/")]
        if images and not self._sees_images():
            self.ui.say("[grid] This model can't see images, so Grid sent your message without them. Pick a model "
                        "that can (a vision-capable model) in Models to work with screenshots and pictures.")
            images = []
        self._images = images
        if images:
            raw_task = f"{raw_task} [{len(images)} image{'s' if len(images) > 1 else ''} attached]"

        if plan:
            planned = self._plan(message)
            if planned is not None:
                planned.start_checkpoint = start
                self._archive(raw_task, planned)
                return planned
            message = ("The plan is approved. Execute it now step by step, keeping the task "
                       "tracker updated, and run the tests to prove it works.")

        self.conversation.send_message(self._with_images(message))
        report = self._drive()
        report.start_checkpoint = start
        if start is not None and self.checkpoints is not None:
            try:
                report.changed = self.checkpoints.changed_files(start.sha)
            except CheckpointError:
                pass
        self._summarize(report)
        self._archive(raw_task, report)
        return report

    # ------------------------------------------------------------------ quick replies
    def _quick_reply(self, text: str) -> str | None:
        from grid.quick import build_messages, history_messages, quick_llm, run_quick, supports_quick

        if not supports_quick(self.conversation.agent.llm):
            return None
        try:
            context = ""
            if self.config.enable_memory:
                from grid.longmem import context_prompt, recall_for_task

                context = "\n\n".join(p for p in (context_prompt(self.workspace, self.chat_id),
                                                    recall_for_task(text, self.workspace, self.chat_id)) if p)
            history = history_messages(list(self.conversation.state.events))
            agent_llm = self.conversation.agent.llm
            messages = build_messages(voice=self.voice, project=os.path.basename(self.workspace),
                                      workspace=self.workspace, history=history, task=text, context=context,
                                      no_think="qwen3" in str(agent_llm.model).lower())
            llm = quick_llm(agent_llm)
        except Exception:
            return None
        if self.stop_requested:
            return None
        return run_quick(llm, messages, self.relay)

    def _record_quick(self, user_text: str, reply: str) -> None:
        """Write a quick exchange into the agent's history so later work knows it happened."""
        from openhands.sdk.event import MessageEvent
        from openhands.sdk.llm import Message, TextContent

        self.conversation.send_message(user_text)
        event = MessageEvent(source="agent", llm_message=Message(role="assistant", content=[TextContent(text=reply)]))
        add = getattr(self.conversation, "_on_event_with_state_lock", None) or self.conversation._on_event
        add(event)

    def _sees_images(self) -> bool:
        try:
            return bool(self.conversation.agent.llm.vision_is_active())
        except Exception:
            return False

    def _with_images(self, text: str):
        """The user's message, with any pasted images attached (only on the first send)."""
        images, self._images = getattr(self, "_images", []), []
        if not images:
            return text
        from openhands.sdk.llm import ImageContent, Message, TextContent

        return Message(role="user", content=[TextContent(text=text), ImageContent(image_urls=images)])

    def _archive(self, task: str, report: TaskReport) -> None:
        """Keep a summary of this turn so later chats can recall it."""
        if not self.config.enable_memory:
            return
        try:
            from grid.longmem import ChatArchive

            reply = report.message or self._final_response()
            ChatArchive().record(self.chat_id, self.workspace, task, reply, outcome=report.outcome.value,
                                 changed=[c.split("\t")[-1] for c in report.changed])
        except Exception as exc:
            self.ui.say(f"[grid] couldn't save this chat to memory: {exc}")

    # ------------------------------------------------------------------ plan mode
    def _plan(self, message: str) -> TaskReport | None:
        """Returns a report if the session should stop after planning, or None
        when the plan was approved and execution should continue."""
        self._plan_mode = True
        apply_plan_policy(self.conversation)
        try:
            self.conversation.send_message(self._with_images(f"{PLAN_INSTRUCTION}\n\nTASK:\n{message}"))
            while True:
                report = self._drive(finishing=False)
                if report.outcome is not Outcome.DONE:
                    return report
                plan_text = self._final_response()
                self.ui.say("\n========== PLAN ==========\n" + plan_text + "\n==========================")
                if self.config.autonomous:
                    self.ui.say("[grid] autonomous: executing the plan.")
                    return None
                if not self.ui.interactive:
                    return TaskReport(Outcome.PLANNED, plan_text)
                answer = self.ui.ask("Execute this plan? [y]es / [n]o / or type changes: ").strip()
                if answer.lower() in ("y", "yes", ""):
                    return None
                if answer.lower() in ("n", "no", "q"):
                    return TaskReport(Outcome.PLANNED, plan_text)
                self.conversation.send_message(f"Revise the plan: {answer}")
        finally:
            self._plan_mode = False
            apply_grid_policy(self.conversation, self.config)

    # ------------------------------------------------------------------ main loop
    def _drive(self, finishing: bool = True) -> TaskReport:
        from openhands.sdk.conversation.state import ConversationExecutionStatus as S

        verify_attempts = 0
        budgets = 0
        headless_rejections = 0
        while True:
            if self.stop_requested:
                return TaskReport(Outcome.PAUSED, "stopped by the user")
            try:
                self.conversation.run()
            except KeyboardInterrupt:
                self.ui.say("\n[grid] interrupted - session saved; continue with a new message or /undo.")
                return TaskReport(Outcome.PAUSED, "interrupted")
            except Exception as exc:  # ConversationRunError and friends
                self.ui.say(f"[grid] agent error: {exc}")
                return TaskReport(Outcome.ERROR, str(exc))

            status = self.conversation.state.execution_status

            if self._regression_reason is not None:
                if not self._handle_regression():
                    return TaskReport(Outcome.PAUSED, "stopped after regression")
                continue

            if status == S.WAITING_FOR_CONFIRMATION:
                decision = self._handle_approval()
                if decision == "quit":
                    return TaskReport(Outcome.PAUSED, "stopped at approval")
                if decision == "blocked":
                    return TaskReport(Outcome.BLOCKED, REFUSAL)
                if decision in ("headless-reject", "auto-reject"):
                    headless_rejections += 1
                    if headless_rejections >= 3:
                        return TaskReport(Outcome.NEEDS_APPROVAL,
                                          "the agent repeatedly needed approval for risky actions")
                continue

            if status == S.FINISHED:
                if not finishing:
                    return TaskReport(Outcome.DONE, self._final_response())
                if self._request_review():
                    continue
                verdict = self._verify_done(verify_attempts)
                if verdict is None:  # sent back to fix a failing check
                    verify_attempts += 1
                    continue
                return verdict

            if status == S.ERROR and self._last_error_code() == "MaxIterationsReached":
                budgets += 1
                if self._budget_checkin(budgets):
                    continue
                return TaskReport(Outcome.PAUSED, f"paused after {self._steps} steps")

            if status == S.STUCK:
                self.ui.say("[grid] the agent is repeating itself without progress (stuck).")
                if self._asking:
                    hint = self.ui.ask("Give it a hint to continue, or press enter to stop: ").strip()
                    if hint and not self.stop_requested:
                        self.conversation.send_message(hint)
                        continue
                return TaskReport(Outcome.STUCK, "stuck")

            if status == S.PAUSED:
                return TaskReport(Outcome.PAUSED, "paused")

            if status == S.ERROR:
                return TaskReport(Outcome.ERROR, self._last_error_detail() or "agent error")

            return TaskReport(Outcome.PAUSED, f"stopped with status {status}")

    # ------------------------------------------------------------------ approvals
    def _pending_actions(self):
        from openhands.sdk.conversation.state import ConversationState

        state = self.conversation.state
        events = state.active_branch() if hasattr(state, "active_branch") else state.events
        return ConversationState.get_unmatched_actions(events)

    def _assess(self, event) -> tuple[GridTier, list[str], set[str]]:
        from grid.analyzer import _risk_value, assess_full

        value, reasons, categories = assess_full(
            _risk_value(event), action_thought(event) or "", action_reasoning(event),
            action_info(event), workspace=self.workspace,
            threshold=self.config.confidence_threshold, strict=self.config.strict_confidence,
            escalate_on_missing=self.config.escalate_on_missing_confidence,
            enforce_confidence=self.config.enforce_confidence,
            roots=granted_roots(str(self.conversation.id)),
        )
        return tier_from_risk_value(value), reasons, categories

    def _handle_approval(self) -> str:
        pending = self._pending_actions()
        if not pending:
            return "approve"

        # A prohibited payload is rejected even in autonomous mode or after
        # the user has pre-approved a command category. No approval card.
        if any(action_blocked_reason(e, context=self._policy_history) for e in pending):
            self.conversation.reject_pending_actions(REFUSAL)
            self.ui.say(f"[grid][safety] {REFUSAL}")
            return "blocked"

        if self._plan_mode:
            writes = [describe_action(e) for e in pending if not is_read_only(action_info(e))]
            if writes:
                self.conversation.reject_pending_actions(
                    "Plan mode is read-only. Blocked: " + "; ".join(writes)
                    + ". Put this in the plan instead, or re-issue only read-only actions."
                )
            return "approve"  # read-only actions run on the next run()

        assessed = [(e, *self._assess(e)) for e in pending]
        worst = GridTier.GREEN
        for _, tier, _, _ in assessed:
            worst = tier if _rank(tier) > _rank(worst) else worst

        if self.config.autonomous:
            ok, blocked = AutonomyPolicy(self.config.allow_red).decide([
                PendingItem(describe_action(e), tier, frozenset(cats)) for e, tier, _, cats in assessed
            ])
            if ok:
                for e, tier, reasons, _ in assessed:
                    if tier is GridTier.RED:
                        self.ui.say(f"[grid][autonomous] running pre-approved RED: {describe_action(e)}"
                                    f" - {', '.join(reasons)}")
                return "approve"
            self.ui.say("[grid][autonomous] refused: " + " | ".join(blocked))
            self.conversation.reject_pending_actions(
                "Not run: Grid is in autonomous mode and the user has not pre-approved this. "
                + " | ".join(blocked)
                + ". Find a safer way to reach the goal, or finish and state exactly what a human needs to do."
            )
            return "auto-reject"

        lines = ["", "[grid] approval needed:"]
        for e, tier, reasons, _ in assessed:
            why = f" - {', '.join(reasons)}" if reasons else ""
            lines.append(f"  [{tier.value}] {describe_action(e)}{why}")
        self.ui.say("\n".join(lines))

        if not self.ui.interactive:
            if worst is GridTier.YELLOW and not self.config.confirm_yellow:
                return "approve"
            self.conversation.reject_pending_actions(
                "Not run: Grid is running unattended and this action needs a human "
                f"({worst.value}). Find a safer way, or finish and explain what approval you need."
            )
            return "headless-reject"

        options = "[y]es / [n]o"
        if worst is not GridTier.RED:
            options += " / [a]lways allow YELLOW this session"
        options += " / [q]uit"
        answer = self.ui.ask(f"Run this? {options}: ").strip()
        low = answer.lower()
        if low in ("y", "yes"):
            return "approve"
        if low in ("a", "always") and worst is not GridTier.RED:
            self.config.confirm_yellow = False
            apply_grid_policy(self.conversation, self.config)
            return "approve"
        if low in ("q", "quit"):
            self.conversation.reject_pending_actions("User stopped the session.")
            return "quit"
        reason = answer if low not in ("n", "no", "") else "User rejected the action."
        self.conversation.reject_pending_actions(reason)
        return "reject"

    # ------------------------------------------------------------------ regression
    def _handle_regression(self) -> bool:
        """Revert (or not). Returns True to keep driving, False to stop."""
        reason, self._regression_reason = self._regression_reason, None
        sig = self._regression_signature()
        target = self.checkpoints.last_good() if self.checkpoints else None

        choice = "r" if target is not None else "k"
        if self._asking:
            prompt = "[r]evert to last good checkpoint" if target is not None else ""
            prompt += (" / " if prompt else "") + "[k]eep going / [s]top: "
            if target is not None:
                self.ui.say(f"[grid] last good checkpoint: #{target.id} {target.label} ({target.tests})")
            choice = (self.ui.ask(prompt).strip().lower() or choice)[:1]
            if choice == "q" or self.stop_requested:
                choice = "s"
        elif not self.config.auto_revert:
            choice = "k"

        lesson = reason or "test pass rate dropped"
        if choice == "s":
            self.memory.add(Episode(error_signature=sig, lesson=lesson, kind="regression"))
            self.ui.say("[grid] stopped. Use /undo to roll back.")
            return False
        if choice == "r" and target is not None and self.checkpoints is not None:
            _, before = self.checkpoints.restore(target.id)
            good_run = self._run_for_checkpoint.get(target.id)
            if good_run is not None:
                self.detector.record(good_run)  # comparisons resume from the good state
            self.ui.say(f"[grid][undo] restored checkpoint #{target.id}; the regressed state is "
                        f"saved as #{before.id}.")
            self.memory.add(Episode(error_signature=sig, lesson=f"{lesson} Reverted; a different approach was needed.",
                                    kind="regression"))
            self.conversation.send_message(
                f"Grid detected a regression ({lesson}) and restored the workspace to checkpoint "
                f"#{target.id} ('{target.label}', tests: {target.tests}). Your last change was undone. "
                "Re-read the affected files and take a different approach."
            )
            return True
        self.memory.add(Episode(error_signature=sig, lesson=lesson, kind="regression"))
        self.conversation.send_message(
            f"Warning from Grid: {lesson} Fix the regression before doing anything else."
        )
        return True

    def _regression_signature(self) -> str:
        latest = self.detector.latest
        if latest is None:
            return "test regression"
        if latest.errored:
            return "test regression (suite failed to run)"
        return f"test regression ({latest.passed}/{latest.executed} passing)"

    # ------------------------------------------------------------------ review
    def _changed_since_start(self) -> list[str] | None:
        if self.checkpoints is None or self._start is None:
            return None
        try:
            return self.checkpoints.changed_files(self._start.sha)
        except CheckpointError:
            return None

    def _request_review(self) -> bool:
        """Once per task with changes: send the agent back to re-read its work for consistency.
        True means the review was asked for and the agent is working again."""
        from grid.consistency import changed_paths, review_request, static_problems

        if self._reviewed or not self.config.self_review or not self._task_verify:
            return False
        if not self.config.verify and not self.config.autonomous:
            return False
        files = changed_paths(self._changed_since_start() or [])
        if not files:
            return False
        self._reviewed = True
        problems = static_problems(self.workspace, self._changed_since_start() or [])
        self.ui.say(f"[grid][review] Re-reading {len(files)} changed file{'s' if len(files) != 1 else ''} "
                    "for consistency before calling it done.")
        self.conversation.send_message(review_request(files, problems))
        return True

    # ------------------------------------------------------------------ verify
    def _verify_done(self, attempts: int) -> TaskReport | None:
        """Accept "done" only with proof. None means the agent was sent back."""
        final = self._final_response()
        if not self._task_verify:
            return TaskReport(Outcome.DONE, final)       # lesson: the learner's tests may be red on purpose
        if not self.config.verify and not self.config.autonomous:
            return TaskReport(Outcome.DONE, final)
        changed: list[str] = []
        if self.checkpoints is not None and self._start is not None:
            try:
                changed = self.checkpoints.changed_files(self._start.sha)
            except CheckpointError:
                changed = ["?"]   # can't tell what changed: verify rather than assume nothing did
            if not changed:
                return TaskReport(Outcome.DONE, final)  # nothing changed, nothing to prove

        def send_back(text: str) -> TaskReport | None:
            if attempts < self.config.max_verify_attempts:
                self.conversation.send_message(text)
                return None
            return TaskReport(Outcome.UNVERIFIED, final)

        # Grid's own quick checks first: broken syntax or conflict markers are never "done".
        from grid.consistency import static_problems

        problems = static_problems(self.workspace, changed) if changed and changed != ["?"] else []
        if problems:
            self.ui.say(f"[grid][verify] FAIL - {len(problems)} problem{'s' if len(problems) != 1 else ''} in the "
                        f"changed files: {problems[0]}" + (" ..." if len(problems) > 1 else ""))
            return send_back(
                "Grid checked the files you changed before accepting 'done' and found problems:\n"
                + "\n".join(f"- {p}" for p in problems) + "\nFix them, then finish again."
            )

        command, source = self._choose_verify_command(final, changed)
        if command is None:
            self.ui.say("[grid][verify] no check found yet - asking the agent to provide one.")
            return send_back(
                "Grid can't accept 'done' yet: this project has no test runner or `verify:` command, so "
                "nothing proves your change works. Write a test that exercises it (preferred), or end your "
                "final message with a line `VERIFY: <command>` that exits 0 only if the change works."
            )

        if self.checkpoints is not None and self._start is not None:
            integrity = test_integrity_reason(self.checkpoints.diff(self._start.sha))
            if integrity:
                if not self._asking:
                    return TaskReport(Outcome.UNVERIFIED, integrity + " Review these changes before accepting verification.")
                answer = self.ui.ask(f"{integrity} Inspect the diff. Accept these test changes for verification? [y/n]: ")
                if answer.strip().lower() not in ("y", "yes"):
                    return TaskReport(Outcome.UNVERIFIED, "Test changes need review before verification.")

        if source == "agent":
            refusal = self._refuse_agent_check(command)
            if refusal:
                self.ui.say(f"[grid][verify] refused agent check `{command}`: {refusal}")
                return send_back(
                    f"Grid won't accept `{command}` as proof: {refusal}. Provide a check that actually "
                    "exercises your change (a test is best) and fails if it is broken."
                )

        self.ui.say(f"[grid][verify] running {command} ({source}) ...")
        result = run_verify(command, self.workspace, timeout=self.config.verify_timeout, cancel=self.cancel_verify)
        if result.cancelled or self.stop_requested:
            return TaskReport(Outcome.PAUSED, "Verification stopped by the user.", verify=result)
        if result.summary is not None:
            self.detector.record(result.summary)
        if result.ok:
            self.ui.say(f"[grid][verify] PASS - {result.label()}  (check result)")
            if self.checkpoints is not None:
                cp = self.checkpoints.current("verified")
                self.checkpoints.mark(cp, tests=result.label(), good=True)
            return TaskReport(Outcome.VERIFIED, final, verify=result)

        self.ui.say(f"[grid][verify] FAIL - {result.label()}")
        report = send_back(
            f"Grid ran `{command}` before accepting 'done' and it failed "
            f"(exit {result.exit_code}). The task is not done until this passes. "
            f"Last lines of output:\n```\n{result.tail()}\n```"
        )
        if report is not None:
            report.verify = result
            self.memory.add(Episode(
                error_signature=f"verify failed: {command}",
                lesson=f"Agent declared done while `{command}` still failed. Output tail: {result.tail(8)}",
                kind="failure",
            ))
        return report

    def _choose_verify_command(self, final: str, changed: list[str]) -> tuple[str | None, str]:
        """(command, source). Sources: user (flag), project (GRID.md), detected
        (test runner), agent (VERIFY: line, or a GRID.md the agent edited)."""
        frozen = getattr(self, "_frozen_verify", None)
        if frozen and frozen[0]:
            return frozen
        if self.config.verify_command:
            return self.config.verify_command, "user"
        from_md = verify_from_instructions(self.workspace)
        if from_md is not None:
            cmd, fname = from_md
            edited = any(line.split("\t")[-1] == fname for line in changed)
            return cmd, ("agent" if edited else "project")
        runner = detect_test_runner(self.workspace)
        if runner:
            return runner, "detected"
        declared = declared_verify_command(final)
        if declared:
            return declared, "agent"
        return None, "none"

    def _refuse_agent_check(self, command: str) -> str | None:
        """A check the agent chose runs outside the approval gate, so it gets
        the same scrutiny: no fake checks, nothing RED, YELLOW only with consent."""
        trivial = trivial_check_reason(command)
        if trivial:
            return trivial
        verdict = classify_command(command, self.workspace)
        if verdict.tier is GridTier.RED:
            return "it is a RED action (" + ", ".join(verdict.reasons) + ")"
        if verdict.tier is GridTier.YELLOW:
            if self._asking:
                answer = self.ui.ask(f"Run the agent's check `{command}` ({', '.join(verdict.reasons)})? [y/n]: ")
                return None if answer.strip().lower() in ("y", "yes") else "the user declined to run it"
            if not (self.config.autonomous or not self.config.confirm_yellow):
                return "it needs approval (" + ", ".join(verdict.reasons) + ")"
        return None

    def _task_start(self) -> Checkpoint | None:
        return self._start

    def _head_checkpoint(self) -> Checkpoint | None:
        if self.checkpoints is None:
            return None
        head = self.checkpoints.head()
        matches = [c for c in self.checkpoints.list() if c.sha == head]
        return matches[-1] if matches else None

    # ------------------------------------------------------------------ budget
    def _budget_checkin(self, budgets: int) -> bool:
        n = self.config.soft_step_budget
        self.ui.say(f"\n[grid][check-in] {budgets * n} steps so far on this task.")
        if self.config.autonomous:
            if budgets * n >= self.config.autonomous_max_steps:
                self.ui.say(f"[grid][autonomous] step cap ({self.config.autonomous_max_steps}) reached - pausing.")
                return False
            return True
        if not self.ui.interactive:
            return budgets < self.config.headless_max_budgets
        answer = self.ui.ask("Continue? [y]es / [n]o / or type guidance: ").strip()
        if answer.lower() in ("n", "no", "q"):
            return False
        if answer and answer.lower() not in ("y", "yes"):
            self.conversation.send_message(answer)
        return True

    # ------------------------------------------------------------------ helpers
    def _final_response(self) -> str:
        from openhands.sdk.conversation.response_utils import get_agent_final_response

        try:
            from grid.events import clean_reply

            return clean_reply(get_agent_final_response(self.conversation.state.events) or "")
        except Exception:
            return ""

    def _last_error(self):
        for e in reversed(list(self.conversation.state.events)):
            if type(e).__name__ == "ConversationErrorEvent":
                return e
        return None

    def _last_error_code(self) -> str | None:
        e = self._last_error()
        return getattr(e, "code", None) if e is not None else None

    def _last_error_detail(self) -> str | None:
        e = self._last_error()
        return getattr(e, "detail", None) if e is not None else None

    def _summarize(self, report: TaskReport) -> None:
        lines = ["", f"[grid] outcome: {report.outcome.value.upper()}"]
        if report.changed:
            lines.append(f"[grid] changed files ({len(report.changed)}):")
            lines += [f"    {c}" for c in report.changed[:30]]
            if report.start_checkpoint is not None:
                lines.append(f"[grid] undo this task: /undo {report.start_checkpoint.id}  "
                             f"(or `grid undo {report.start_checkpoint.id}`)")
        self.ui.say("\n".join(lines))

    # ------------------------------------------------------------------ undo
    def undo(self, ref: str | int | None = None) -> str:
        if self.checkpoints is None:
            return "checkpoints are disabled"
        cps = self.checkpoints.list()
        if not cps:
            return "no checkpoints yet"
        if ref is None:
            head = self.checkpoints.head()
            idx = next((i for i, c in enumerate(cps) if c.sha == head), len(cps) - 1)
            if idx == 0:
                return "already at the first checkpoint"
            ref = cps[idx - 1].id
        target, before = self.checkpoints.restore(ref)
        self._notes.append(
            f"Note from Grid: the user restored the workspace to checkpoint #{target.id} "
            f"('{target.label}'). Files may differ from what you last saw - re-read before editing."
        )
        return f"restored checkpoint #{target.id} ({target.label}); previous state saved as #{before.id}"

    def close(self) -> None:
        from grid.tools.host import unregister

        unregister(self.chat_id)
        try:
            self.conversation.close()
        except Exception:
            pass


def _rank(tier: GridTier) -> int:
    return {GridTier.GREEN: 0, GridTier.UNKNOWN: 1, GridTier.YELLOW: 1, GridTier.RED: 2}[tier]
