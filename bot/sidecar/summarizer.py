"""Builds the three-part LLM input: fixed prefix (cached) / game summary / delta."""
from __future__ import annotations

from .knowledge import Knowledge
from .plan_ledger import PlanLedger, feedback_text
from .state_store import StateStore

SYSTEM_ROLE = """You are the strategy layer of a StarCraft: Brood War bot playing Zerg.
You decide macro policy only. You never output coordinates, unit ids, or per-unit orders;
the bot body (production, placement, squads, micro) executes your policy.

Rules:
- Use only opening names from the build database, and only wall/location names from the map knowledge.
- Prefer keeping the current plan unless new information changes the assessment; if you change it, say why in change_reason.
- Be concrete: unit_mix_target fractions must sum to about 1.0; tech_priority is ordered.
- drone_target {"total": N, "priority": "economy|balanced|army"} sets the body's desired drone count; use it to drone up or stop droning (omit it to leave droning to the body).
- Think about what the enemy's scouted buildings and timings imply about their next 2-3 minutes: fill
  enemy_build_guess, expected_threats and our_response from the intel brief before choosing the other fields.
- If the body cannot execute something (no wall defined for this map), do not ask for it.
"""


def fixed_prefix(knowledge: Knowledge) -> str:
    """Stable across the whole game -> cached. No timestamps, no per-call data."""
    return SYSTEM_ROLE + "\n\n" + knowledge.prefix_text()


SERIES_INSTRUCTION = ("아래 표에서 추세를 읽어라: 경제 성장(min/gas/drone/bases), 병력 가치 역전(army vs e_army), "
                      "적 확장 시점(e_bases/e_wrk), 교전 결과(event). 한 줄은 30초.")


def user_message(store: StateStore, ledger: PlanLedger, trigger: str, knowledge: Knowledge | None = None) -> str:
    ref = knowledge.reference_timings if knowledge is not None else {}
    execution = store.latest.execution if store.latest is not None else None
    feedback = feedback_text(ledger, execution) if execution is not None else "이전 지시 없음."
    return (
        "## 게임 누적 요약 (타임라인)\n" + store.timeline_text() +
        "\n\n## 직전 결정과 실행 결과\n" + ledger.summary_text() +
        "\n\n## 직전 지시 실행 결과\n" + feedback +
        "\n\n## 시계열 (30초 간격)\n" + SERIES_INSTRUCTION + "\n" + store.series_text() +
        "\n\n## 직전 호출 이후 변화 (delta)\n" + store.delta_text() +
        "\n\n## 현재 상태\n" + store.current_state_text() +
        "\n\n## 정찰 브리핑 (intel)\n" + store.intel_brief_text(ref) +
        f"\n\n## 호출 이유\n{trigger}\n\n지금 결정하라. keep_current_plan=true 라면 나머지 필드는 현재 계획을 그대로 채워라."
    )
