from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Budgets:
    per_game_usd: float = 3.0
    per_day_usd: float = 30.0


@dataclass
class Triggers:
    safety_interval_seconds: int = 30
    idle_minerals: int = 800
    idle_minerals_seconds: int = 10
    big_engagement_loss_value: int = 200
    min_hold_seconds: int = 20
    min_call_gap_seconds: int = 20      # debounce: non-critical triggers wait this long after the previous call
    critical_triggers: tuple = ("cloaked", "game_start")
    engagement_min_gap_seconds: int = 60   # at most one engagement-driven call per minute
    # Start rule (audit item D): at game_start the body keeps its own defaults (observe-only directive) and the
    # first real LLM call happens at the first intel/enemy trigger, or at first_call_deadline_seconds if nothing
    # was scouted by then. decide_at_start: true restores the old behaviour (LLM call at frame 0).
    decide_at_start: bool = False
    first_call_deadline_seconds: int = 120
    series_interval_seconds: int = 30   # time-series sampling interval (## 시계열 section)
    series_max_rows: int = 40


@dataclass
class Levers:
    """Which directive fields may override the body. Disabled levers are reset to "no override" before issuing."""
    disabled: tuple = ()   # any of: opening, unit_mix, tech_priority, stance, objective, expand_policy, static_defense, wall, drone_target


@dataclass
class ModelConfig:
    strategy_model: str = "claude-opus-5-5"
    strategy_effort_regular: str = "low"
    strategy_effort_transition: str = "medium"
    advisor_model: str = "claude-haiku-4-5"
    advisor_enabled: bool = False


@dataclass
class SidecarConfig:
    mode: str = "headless"  # lockstep | realtime | headless | replay-directive
    host: str = "127.0.0.1"
    port: int = 8770
    llm_backend: str = "anthropic"  # anthropic | fake | recorded
    frames_per_second: float = 23.81
    directive_ttl_seconds: int = 90
    knowledge_dir: Path = REPO_ROOT / "knowledge"
    logs_dir: Path = REPO_ROOT / "logs" / "games"
    budgets: Budgets = field(default_factory=Budgets)
    triggers: Triggers = field(default_factory=Triggers)
    models: ModelConfig = field(default_factory=ModelConfig)
    levers: Levers = field(default_factory=Levers)

    @classmethod
    def load(cls, path: str | Path | None = None, **overrides) -> "SidecarConfig":
        cfg = cls()
        path = path or os.environ.get("SIDECAR_CONFIG")
        if path and Path(path).exists():
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            for key, value in data.items():
                if key == "budgets":
                    cfg.budgets = Budgets(**value)
                elif key == "triggers":
                    cfg.triggers = Triggers(**value)
                elif key == "models":
                    cfg.models = ModelConfig(**value)
                elif key == "levers":
                    cfg.levers = Levers(disabled=tuple(value.get("disabled", ())))
                elif hasattr(cfg, key):
                    setattr(cfg, key, Path(value) if key.endswith("_dir") else value)
        if os.environ.get("SIDECAR_DISABLED_LEVERS"):
            cfg.levers = Levers(disabled=tuple(x for x in os.environ["SIDECAR_DISABLED_LEVERS"].split(",") if x))
        if os.environ.get("SIDECAR_LOGS_DIR"):
            cfg.logs_dir = Path(os.environ["SIDECAR_LOGS_DIR"])
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def frames(self, seconds: float) -> int:
        return int(seconds * self.frames_per_second)
