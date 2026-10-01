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
                elif hasattr(cfg, key):
                    setattr(cfg, key, Path(value) if key.endswith("_dir") else value)
        if os.environ.get("SIDECAR_LOGS_DIR"):
            cfg.logs_dir = Path(os.environ["SIDECAR_LOGS_DIR"])
        for key, value in overrides.items():
            setattr(cfg, key, value)
        return cfg

    def frames(self, seconds: float) -> int:
        return int(seconds * self.frames_per_second)
