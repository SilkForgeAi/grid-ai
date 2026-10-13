"""Grid AI runtime configuration.

Holds the tunables from ROADMAP §4 (autonomy) and §7 (teaching). Kept free of
SDK imports so it can be constructed and tested anywhere; `stuck_thresholds()`
lazily builds the SDK object only when actually needed by the live agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid.models import ModelProfile
from grid.teaching import DepthLevel


@dataclass
class GridConfig:
    # --- Autonomy (§4) ---
    confidence_threshold: float = 0.6
    strict_confidence: bool = False
    confirm_yellow: bool = True          # soft-confirm MEDIUM/YELLOW actions
    confirm_unknown: bool = True         # treat UNKNOWN conservatively
    soft_step_budget: int = 25           # check in with the user every N steps
    enforce_confidence: bool = True      # low confidence escalates risk (not just a badge)
    escalate_on_missing_confidence: bool = False  # nudge un-scored LOW actions to MEDIUM

    # --- Stuck detection (§4, maps to SDK StuckDetectionThresholds) ---
    stuck_action_error: int = 2          # roadmap: stop after same error twice
    stuck_action_observation: int = 3    # roadmap: same file 3x without progress
    stuck_monologue: int = 3
    stuck_alternating: int = 6

    # --- Teaching (§7) ---
    depth: DepthLevel = DepthLevel.INTERMEDIATE
    why_did_this_break: bool = True

    # --- Verification (§5): not done until the check passes ---
    verify: bool = True
    verify_command: str | None = None     # None -> GRID.md `verify:` line or auto-detect
    max_verify_attempts: int = 2          # times Grid sends the agent back to fix a red check
    self_review: bool = True              # one consistency review of its own changes before "done"
    verify_timeout: float = 600.0

    # --- Checkpoints / regression ---
    checkpoints: bool = True
    auto_revert: bool = True              # headless: revert on regression without asking

    # --- Autonomous mode (user opts in; Grid stops asking) ---
    autonomous: bool = False
    allow_red: frozenset[str] = frozenset()   # pre-approved RED categories (grid.rules.ALLOWABLE_RED)
    autonomous_max_steps: int = 300           # hard cap per task, then pause

    # --- Session ---
    plan_first: bool = False              # plan, get approval, then execute
    headless: bool = False                # no human: RED/unknown actions are rejected, not asked
    headless_max_budgets: int = 4         # headless: stop after this many step budgets

    # --- Personality ---
    persona: str | None = None            # "teacher" forces the teacher voice; "grid" only works for confirmed adults

    # --- Model (bring your own) ---
    model_profile: ModelProfile | None = None   # None -> grid.models.resolve_profile()
    prompted_tools: bool = False          # describe tools in the prompt (models without tool calling)
    local_only: bool = False              # refuse models/MCP servers that leave this machine

    # --- Capabilities (SDK tools) ---
    enable_browser: bool = True           # Grid's own browser, when Chrome/Chromium is on this machine
    enable_sub_agents: bool = False       # off by default: sub-agents multiply token cost
    enable_web: bool = True               # web_search + web_fetch (off with local_only)
    enable_documents: bool = True         # create_document (PDF / Word)
    enable_memory: bool = True            # long-term memory tool + context from earlier chats
    enable_access: bool = True            # request_access for folders outside the project
    enable_images: bool = True            # view_image (screenshots, photos) for vision models
    enable_computer: bool = True          # use the Mac's apps (screenshot/click/type), asking per app
    condense_context: bool = True         # summarize old history on long tasks
    quick_replies: bool = True            # plain conversation answered with a short prompt (see grid.quick)
    load_project_skills: bool = True      # AGENTS.md, .cursorrules, .agents/skills
    load_user_skills: bool = True         # ~/.openhands/skills
    load_plugins: bool = True             # enabled plugins (user + project scope)

    def stuck_thresholds(self):
        """Build the SDK StuckDetectionThresholds. Imported lazily so this module
        stays SDK-free for testing."""
        from openhands.sdk.conversation.types import StuckDetectionThresholds

        return StuckDetectionThresholds(
            action_error=self.stuck_action_error,
            action_observation=self.stuck_action_observation,
            monologue=self.stuck_monologue,
            alternating_pattern=self.stuck_alternating,
        )
