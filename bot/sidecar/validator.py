"""Checks an LLM Directive against knowledge and game rules before it reaches the body."""
from __future__ import annotations

from dataclasses import dataclass, field

from .knowledge import Knowledge
from .schemas import Directive, StateSummary

# Minimal Zerg tech requirements: tech/unit -> required building (extend from BWAPI UnitType data later).
ZERG_REQUIRES: dict[str, str] = {
    "zergling": "spawning_pool", "metabolic_boost": "spawning_pool", "hydralisk": "hydralisk_den",
    "hydralisk_den": "spawning_pool", "lair": "spawning_pool", "mutalisk": "spire", "spire": "lair",
    "lurker": "lurker_aspect", "lurker_aspect": "lair", "queens_nest": "lair", "hive": "queens_nest",
    "ultralisk": "ultralisk_cavern", "ultralisk_cavern": "hive", "defiler": "defiler_mound",
    "defiler_mound": "hive", "guardian": "greater_spire", "devourer": "greater_spire", "greater_spire": "hive",
    "sunken_colony": "spawning_pool", "spore_colony": "evolution_chamber", "scourge": "spire",
}
TECH_ALIASES = {
    "zergling_speed": "metabolic_boost", "ling_speed": "metabolic_boost", "speed": "metabolic_boost",
    "hydra_range": "grooved_spines", "hydra_speed": "muscular_augments", "overlord_speed": "pneumatized_carapace",
    "crack_lings": "adrenal_glands", "hydra_den": "hydralisk_den", "lurker": "lurker_aspect", "mutas": "spire",
}
ZERG_UNITS = {"drone", "zergling", "hydralisk", "mutalisk", "lurker", "ultralisk", "defiler", "scourge",
              "guardian", "devourer", "overlord", "queen"}
DRONE_TARGET_MAX = 90
DRONE_PRIORITIES = ("economy", "balanced", "army")


@dataclass
class ValidationResult:
    directive: Directive
    ok: bool
    fixes: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def validate(d: Directive, knowledge: Knowledge, state: StateSummary | None) -> ValidationResult:
    d = d.model_copy(deep=True)
    fixes: list[str] = []
    rejected: list[str] = []

    if knowledge.opening_names and d.opening and d.opening not in knowledge.opening_names:
        rejected.append(f"unknown opening '{d.opening}'")
    if d.wall_natural not in knowledge.wall_names:
        fixes.append(f"wall_natural '{d.wall_natural}' not defined for this map -> none")
        d.wall_natural = "none"
    if d.army_objective.location not in knowledge.location_names:
        fixes.append(f"objective location '{d.army_objective.location}' unknown -> natural")
        d.army_objective.location = "natural"

    mix = {k: v for k, v in d.unit_mix_target.items() if k in ZERG_UNITS and v > 0}
    if len(mix) != len(d.unit_mix_target):
        fixes.append("dropped non-zerg or non-positive unit_mix entries")
    total = sum(mix.values())
    if total > 0 and abs(total - 1.0) > 0.05:
        mix = {k: round(v / total, 3) for k, v in mix.items()}
        fixes.append("normalized unit_mix_target to sum 1.0")
    d.unit_mix_target = mix

    d.tech_priority = [TECH_ALIASES.get(t, t) for t in d.tech_priority]
    d.tech_priority = [t for t in d.tech_priority if t in ZERG_REQUIRES or t in ZERG_UNITS or t in {
        "evolution_chamber", "melee_upgrade", "missile_upgrade", "carapace_upgrade", "overlord_speed", "burrow",
        "grooved_spines", "muscular_augments", "adrenal_glands", "pneumatized_carapace"}]
    sd: dict[str, int] = {}
    for k, v in d.static_defense.items():
        key = "sunken" if "sunken" in k else ("spore" if "spore" in k else None)
        if key is None or v < 0:
            fixes.append(f"dropped static_defense '{k}'")
            continue
        if key != k:
            fixes.append(f"static_defense '{k}' -> '{key}'")
        sd[key] = max(sd.get(key, 0), int(v))
    d.static_defense = sd
    d.drone_target = _clean_drone_target(d.drone_target, fixes)
    if not (0.0 <= d.confidence <= 1.0):
        d.confidence = max(0.0, min(1.0, d.confidence))
        fixes.append("clamped confidence")
    if d.review_after_seconds < 15:
        d.review_after_seconds = 15
        fixes.append("review_after_seconds raised to 15")

    if state is not None and d.stance == "all_in" and state.me.army_value < state.enemy.army_value_seen * 0.8:
        fixes.append("all_in with inferior army -> aggressive")
        d.stance = "aggressive"

    return ValidationResult(d, ok=not rejected, fixes=fixes, rejected=rejected)


def _clean_drone_target(dt, fixes: list[str]) -> dict:
    """{} when absent/invalid or total <= 0; otherwise total clamped to 1..DRONE_TARGET_MAX, priority in DRONE_PRIORITIES."""
    if not isinstance(dt, dict) or not dt:
        return {}
    try:
        total = int(float(dt.get("total", 0)))
    except (TypeError, ValueError):
        fixes.append("dropped drone_target (total not a number)")
        return {}
    if total <= 0:
        return {}
    if total > DRONE_TARGET_MAX:
        fixes.append(f"drone_target.total {total} clamped to {DRONE_TARGET_MAX}")
        total = DRONE_TARGET_MAX
    priority = str(dt.get("priority", "balanced")).lower()
    if priority not in DRONE_PRIORITIES:
        fixes.append(f"drone_target.priority '{priority}' -> balanced")
        priority = "balanced"
    out = {"total": total, "priority": priority}
    if bool(dt.get("override_opening", False)):
        out["override_opening"] = True
    return out


def apply_disabled_levers(d: Directive, disabled: tuple, state: StateSummary | None) -> Directive:
    """Reset disabled directive fields to their 'no override' value (lever ablation experiments)."""
    if not disabled:
        return d
    d = d.model_copy(deep=True)
    body = (state.body_defaults if state else {}) or {}
    if "opening" in disabled:
        d.opening = ""
    if "unit_mix" in disabled:
        d.unit_mix_target = {}
    if "tech_priority" in disabled:
        d.tech_priority = []
    if "stance" in disabled:
        d.stance = "neutral"
    if "objective" in disabled:
        d.army_objective = d.army_objective.model_copy(update={"type": "defend", "location": "natural"})
    if "expand_policy" in disabled:
        d.expand_policy = "allow_when_safe"
    if "static_defense" in disabled:
        d.static_defense = {}
    if "drone_target" in disabled:
        d.drone_target = {}
    if "wall" in disabled:
        d.wall_natural = body.get("wall_natural", "none") or "none"
    return d
