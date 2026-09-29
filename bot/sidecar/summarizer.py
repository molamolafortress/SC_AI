"""Builds the three-part LLM input: fixed prefix (cached) / game summary / delta."""
from __future__ import annotations

from .knowledge import Knowledge
from .plan_ledger import PlanLedger
from .state_store import StateStore

SYSTEM_ROLE = """You are the strategy layer of a StarCraft: Brood War bot playing Zerg.
You decide macro policy only. You never output coordinates, unit ids, or per-unit orders;
the bot body (production, placement, squads, micro) executes your policy.

Rules:
- Use only opening names from the build database, and only wall/location names from the map knowledge.
- Prefer keeping the current plan unless new information changes the assessment; if you change it, say why in change_reason.
- Be concrete: unit_mix_target fractions must sum to about 1.0; tech_priority is ordered.
- Think about what the enemy's scouted buildings and timings imply about their next 2 minutes.
- If the body cannot execute something (no wall defined for this map), do not ask for it.
"""


def fixed_prefix(knowledge: Knowledge) -> str:
    """Stable across the whole game -> cached. No timestamps, no per-call data."""
    return SYSTEM_ROLE + "\n\n" + knowledge.prefix_text()


def user_message(store: StateStore, ledger: PlanLedger, trigger: str) -> str:
    return (
        "## 게임 누적 요약 (타임라인)\n" + store.timeline_text() +
        "\n\n## 직전 결정과 실행 결과\n" + ledger.summary_text() +
        "\n\n## 직전 호출 이후 변화 (delta)\n" + store.delta_text() +
        "\n\n## 현재 상태\n" + store.current_state_text() +
        f"\n\n## 호출 이유\n{trigger}\n\n지금 결정하라. keep_current_plan=true 라면 나머지 필드는 현재 계획을 그대로 채워라."
    )
