"""Wire schemas between the bot body and the sidecar (design_v0.5.md section 4)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["defensive", "neutral", "aggressive", "all_in"]
ExpandPolicy = Literal["never", "allow_when_safe", "greedy"]


class SeenUnit(BaseModel):
    count: int = 0
    last_frame: int = 0


class SeenBuilding(BaseModel):
    count: int = 0
    first_frame: int = 0


class MyState(BaseModel):
    minerals: int = 0
    gas: int = 0
    supply: tuple[int, int] = (0, 0)
    larva: int = 0
    units: dict[str, int] = Field(default_factory=dict)
    buildings: dict[str, int] = Field(default_factory=dict)
    tech: dict[str, str] = Field(default_factory=dict)
    army_value: int = 0
    army_pos: tuple[int, int] | None = None


class EnemyState(BaseModel):
    race: str = "unknown"
    units_seen: dict[str, SeenUnit] = Field(default_factory=dict)
    buildings_seen: dict[str, SeenBuilding] = Field(default_factory=dict)
    expansions: int = 0
    army_value_seen: int = 0
    army_pos_seen: tuple[int, int] | None = None
    suspected_cloaked: list[dict] = Field(default_factory=list)


class GameEvent(BaseModel):
    type: str
    what: str | None = None
    frame: int = 0
    detail: dict = Field(default_factory=dict)


class GoalStatus(BaseModel):
    goal: str
    status: Literal["pending", "ongoing", "done", "failed"]
    frame: int = 0


class ExecutionFeedback(BaseModel):
    directive_id: str | None = None
    goals: list[GoalStatus] = Field(default_factory=list)


class StateSummary(BaseModel):
    """Posted by the body every ~24 frames and on events."""

    game_id: str
    frame: int
    game_time: str = "0:00"
    matchup: str = "ZvT"
    map: str = "unknown"
    me: MyState = Field(default_factory=MyState)
    enemy: EnemyState = Field(default_factory=EnemyState)
    combat_sim: dict[str, float] = Field(default_factory=dict)
    events: list[GameEvent] = Field(default_factory=list)
    execution: ExecutionFeedback = Field(default_factory=ExecutionFeedback)
    body_defaults: dict[str, str] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)


class ArmyObjective(BaseModel):
    type: Literal["defend", "attack", "harass", "contain", "hold"] = "defend"
    location: str = "natural"


class Directive(BaseModel):
    """Strategy LLM output. Macro policy only: no coordinates, no unit ids."""

    keep_current_plan: bool = False
    change_reason: str = ""
    opening: str = ""
    unit_mix_target: dict[str, float] = Field(default_factory=dict)
    tech_priority: list[str] = Field(default_factory=list)
    stance: Stance = "defensive"
    expand_policy: ExpandPolicy = "allow_when_safe"
    army_objective: ArmyObjective = Field(default_factory=ArmyObjective)
    wall_natural: str = "none"
    static_defense: dict[str, int] = Field(default_factory=dict)
    scout_policy: str = "overlord_on_path"
    confidence: float = 0.5
    review_after_seconds: int = 45


class IssuedDirective(Directive):
    """Directive as served to the body, with bookkeeping added by the sidecar."""

    directive_id: str
    issued_frame: int
    expires_frame: int
    source: Literal["llm", "validator_fix", "ledger_hold", "fallback"] = "llm"


class AdvisorQuery(BaseModel):
    frame: int
    my_army: dict[str, int]
    enemy_army: dict[str, int]
    combat_ratio: float
    terrain: str = ""
    stance: Stance = "neutral"


class AdvisorAnswer(BaseModel):
    engage: bool
    fallback_to: str = "natural"
    reason: str = ""
