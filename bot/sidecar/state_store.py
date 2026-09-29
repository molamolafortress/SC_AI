"""Accumulates StateSummary posts, computes deltas since the last LLM call, and decides
which trigger (if any) should fire."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import SidecarConfig
from .schemas import StateSummary


@dataclass
class StateStore:
    cfg: SidecarConfig
    latest: StateSummary | None = None
    first: StateSummary | None = None
    at_last_call: StateSummary | None = None
    last_call_frame: int = -10**9
    idle_since_frame: int | None = None
    enemy_buildings_known: set[str] = field(default_factory=set)
    enemy_units_known: set[str] = field(default_factory=set)
    pending_events: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)

    def ingest(self, s: StateSummary) -> None:
        if self.first is None:
            self.first = s
            self.timeline.append(f"f{s.frame} game_start {s.matchup} on {s.map}")
        self.latest = s
        for name, b in s.enemy.buildings_seen.items():
            if name not in self.enemy_buildings_known and b.count > 0:
                self.enemy_buildings_known.add(name)
                self.pending_events.append(f"enemy_building_spotted:{name}")
                self.timeline.append(f"f{s.frame} enemy {name} spotted")
        for name, u in s.enemy.units_seen.items():
            if name not in self.enemy_units_known and u.count > 0:
                self.enemy_units_known.add(name)
                self.timeline.append(f"f{s.frame} enemy {name} first seen")
        for ev in s.events:
            tag = ev.type + (f":{ev.what}" if ev.what else "")
            self.pending_events.append(tag)
            self.timeline.append(f"f{ev.frame or s.frame} {tag}")
        if s.me.minerals >= self.cfg.triggers.idle_minerals:
            if self.idle_since_frame is None:
                self.idle_since_frame = s.frame
        else:
            self.idle_since_frame = None

    def trigger(self, review_after_frame: int | None) -> str | None:
        """Return the trigger name that should fire now, or None."""
        s = self.latest
        if s is None:
            return None
        if self.at_last_call is None:
            return "game_start"
        for ev in self.pending_events:
            if ev.startswith(("enemy_building_spotted", "enemy_tech", "engagement_end", "scout_", "goal_", "cloaked")):
                return ev
        t = self.cfg.triggers
        if self.idle_since_frame is not None and s.frame - self.idle_since_frame >= self.cfg.frames(t.idle_minerals_seconds):
            return "idle_resources"
        if review_after_frame is not None and s.frame >= review_after_frame:
            return "review_due"
        if s.frame - self.last_call_frame >= self.cfg.frames(t.safety_interval_seconds):
            return "safety_interval"
        return None

    def is_transition_trigger(self, trigger: str) -> bool:
        return trigger.startswith(("enemy_building_spotted", "enemy_tech", "engagement_end", "cloaked", "game_start"))

    def mark_called(self) -> None:
        self.at_last_call = self.latest
        self.last_call_frame = self.latest.frame if self.latest else 0
        self.pending_events.clear()
        self.idle_since_frame = None

    def delta_text(self) -> str:
        """What changed since the last LLM call, compact."""
        s, p = self.latest, self.at_last_call
        if s is None:
            return ""
        if p is None:
            return "첫 호출. 아래 현재 상태 전체 참고."
        lines = [f"경과: frame {p.frame} → {s.frame} ({s.game_time})"]
        lines.append(f"자원: {p.me.minerals}/{p.me.gas} → {s.me.minerals}/{s.me.gas}, 서플라이 {s.me.supply[0]}/{s.me.supply[1]}, 라바 {s.me.larva}")
        for name in sorted(set(p.me.units) | set(s.me.units)):
            a, b = p.me.units.get(name, 0), s.me.units.get(name, 0)
            if a != b:
                lines.append(f"아군 {name}: {a} → {b}")
        for name in sorted(set(p.me.buildings) | set(s.me.buildings)):
            a, b = p.me.buildings.get(name, 0), s.me.buildings.get(name, 0)
            if a != b:
                lines.append(f"아군 건물 {name}: {a} → {b}")
        for name, t in s.me.tech.items():
            if p.me.tech.get(name) != t:
                lines.append(f"테크 {name}: {t}")
        for name, u in s.enemy.units_seen.items():
            if p.enemy.units_seen.get(name, None) is None or p.enemy.units_seen[name].count != u.count:
                lines.append(f"적 {name} 목격 수: {u.count} (마지막 frame {u.last_frame})")
        for name, b in s.enemy.buildings_seen.items():
            if name not in p.enemy.buildings_seen:
                lines.append(f"적 건물 신규: {name} x{b.count} (frame {b.first_frame})")
        if s.enemy.expansions != p.enemy.expansions:
            lines.append(f"적 확장 수: {p.enemy.expansions} → {s.enemy.expansions}")
        if s.combat_sim:
            lines.append("전투 시뮬: " + ", ".join(f"{k}={v:.2f}" for k, v in s.combat_sim.items()))
        if s.enemy.suspected_cloaked:
            lines.append(f"클로킹 의심: {len(s.enemy.suspected_cloaked)}건")
        if s.execution.goals:
            lines.append("목표 상태: " + ", ".join(f"{g.goal}={g.status}" for g in s.execution.goals))
        if self.pending_events:
            lines.append("이벤트: " + ", ".join(self.pending_events))
        return "\n".join(lines)

    def current_state_text(self) -> str:
        s = self.latest
        if s is None:
            return ""
        return (
            f"현재 frame {s.frame} ({s.game_time}), 매치업 {s.matchup}, 맵 {s.map}\n"
            f"아군: 자원 {s.me.minerals}/{s.me.gas}, 서플라이 {s.me.supply[0]}/{s.me.supply[1]}, 라바 {s.me.larva}, "
            f"유닛 {s.me.units}, 건물 {s.me.buildings}, 테크 {s.me.tech}, 병력 가치 {s.me.army_value}\n"
            f"적({s.enemy.race}): 유닛 { {k: v.count for k, v in s.enemy.units_seen.items()} }, "
            f"건물 { {k: v.count for k, v in s.enemy.buildings_seen.items()} }, 확장 {s.enemy.expansions}, "
            f"목격 병력 가치 {s.enemy.army_value_seen}\n"
            f"몸체 기본값: {s.body_defaults}"
        )

    def timeline_text(self, max_lines: int = 25) -> str:
        return "\n".join(self.timeline[-max_lines:])
