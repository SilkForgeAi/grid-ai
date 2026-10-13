"""Global defaults the app (and scheduled runs) start new sessions with."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from grid.config import GridConfig
from grid.project import grid_home
from grid.teaching import DepthLevel

ACCENTS = ("teal", "violet", "lime", "sunset")


@dataclass
class Settings:
    depth: str = DepthLevel.INTERMEDIATE.value
    step_budget: int = 25
    confidence_threshold: float = 0.6
    verify: bool = True
    plan_first: bool = False
    projects_root: str = str(Path.home() / "GridProjects")
    theme: str = "dark"              # system | light | dark
    accent: str = "teal"             # teal | violet | lime | sunset
    setup_done: bool = False         # finished (or skipped) the first-run model setup
    browser_visible: bool = False    # show Grid's browser window instead of running it in the background
    self_review: bool = True         # the agent reviews its own changes for consistency before "done"
    autonomous_max_steps: int = 300  # autonomous mode pauses after this many steps on one task

    def apply(self, config: GridConfig) -> GridConfig:
        config.depth = DepthLevel(self.depth)
        config.soft_step_budget = max(1, int(self.step_budget))
        config.confidence_threshold = float(self.confidence_threshold)
        config.verify = bool(self.verify)
        config.plan_first = bool(self.plan_first)
        config.self_review = bool(self.self_review)
        config.autonomous_max_steps = int(self.autonomous_max_steps)
        return config


def _path() -> Path:
    return grid_home() / "settings.json"


def load_settings() -> Settings:
    p = _path()
    if not p.is_file():
        return Settings()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    names = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in names})


def save_settings(update: dict) -> Settings:
    current = asdict(load_settings())
    names = {f.name for f in fields(Settings)}
    for k, v in update.items():
        if k in names:
            current[k] = v
    s = Settings(**current)
    DepthLevel(s.depth)  # validate
    if not 0 <= float(s.confidence_threshold) <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if int(s.step_budget) < 1:
        raise ValueError("step_budget must be at least 1")
    if not 10 <= int(s.autonomous_max_steps) <= 5000:
        raise ValueError("autonomous_max_steps must be between 10 and 5000")
    if s.theme not in ("system", "light", "dark"):
        raise ValueError("theme must be system, light or dark")
    if s.accent not in ACCENTS:
        raise ValueError(f"accent must be one of {', '.join(ACCENTS)}")
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return s
