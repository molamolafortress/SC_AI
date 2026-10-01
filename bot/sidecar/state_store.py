"""Accumulates StateSummary posts, computes deltas since the last LLM call, and decides
which trigger (if any) should fire."""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import SidecarConfig
from .schemas import Intel, StateSummary


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
    intel: Intel = field(default_factory=Intel)
    intel_seen: set[str] = field(default_factory=set)  # one-shot intel events already raised

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
        self._ingest_intel(s)
        for ev in s.events:
            tag = ev.type + (f":{ev.what}" if ev.what else "")
            self.pending_events.append(tag)
            self.timeline.append(f"f{ev.frame or s.frame} {tag}")
        if s.me.minerals >= self.cfg.triggers.idle_minerals:
            if self.idle_since_frame is None:
                self.idle_since_frame = s.frame
        else:
            self.idle_since_frame = None

    def _intel_event(self, s: StateSummary, key: str, text: str) -> None:
        if key in self.intel_seen:
            return
        self.intel_seen.add(key)
        self.pending_events.append(f"intel:{key}")
        self.timeline.append(f"f{s.frame} ({s.game_time}) intel: {text}")

    def _ingest_intel(self, s: StateSummary) -> None:
        """Detect NEW scouting intelligence -> `intel:<what>` triggers (transition triggers, effort medium)."""
        prev, cur = self.intel, s.intel
        self.intel = cur
        if cur.scout.main_scouted_frame >= 0 and prev.scout.main_scouted_frame < 0:
            self._intel_event(s, "scout_main", f"our scout reached the enemy main at {cur.scout.main_scouted_time}")
        if cur.gas.count > 0 and prev.gas.count == 0:
            self._intel_event(s, "gas", f"enemy gas first seen ({cur.gas.first_seen_time})")
        if cur.expansions >= 2 and prev.expansions < 2:
            self._intel_event(s, "expansion", f"enemy expansion seen (bases={cur.expansions})")
        if cur.army.first_seen_frame >= 0 and prev.army.first_seen_frame < 0:
            self._intel_event(s, "army", f"enemy army first seen {cur.army.max_by_type} at {cur.army.first_seen_time}")
        guess = (cur.enemy_build, cur.enemy_opener, cur.enemy_transition)
        if guess != (prev.enemy_build, prev.enemy_opener, prev.enemy_transition) and any(g != "Unknown" for g in guess):
            self._intel_event(s, "build_guess:" + "/".join(guess),
                              f"McRave build guess -> {'/'.join(guess)} ({cur.enemy_build_state}/{cur.enemy_opener_state}/{cur.enemy_transition_state})")

    def trigger(self, review_after_frame: int | None) -> str | None:
        """Return the trigger name that should fire now, or None."""
        s = self.latest
        if s is None:
            return None
        if self.at_last_call is None:
            return "game_start"
        for ev in self.pending_events:
            if ev.startswith(("enemy_building_spotted", "enemy_tech", "engagement_end", "scout_", "goal_", "cloaked", "intel:")):
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
        return trigger.startswith(("enemy_building_spotted", "enemy_tech", "engagement_end", "cloaked", "game_start", "intel:"))

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

    def intel_brief_text(self, reference_timings: dict | None = None) -> str:
        """'## 정찰 브리핑' body: enemy buildings with start times vs reference timings, workers, gas, expansions,
        scout status, McRave's guess, then the instruction block."""
        s, it = self.latest, self.intel
        if s is None:
            return ""
        ref = reference_timings or {}
        lines: list[str] = []
        sc = it.scout
        if not sc.enemy_main_found:
            lines.append("정찰: 적 본진 위치 미확인 (정찰 없음)")
        else:
            main = f"본진 도달 {sc.main_scouted_time}" if sc.main_scouted_frame >= 0 else "본진 미도달"
            nat = f"앞마당 확인 {sc.natural_scouted_time}" if sc.natural_scouted_frame >= 0 else "앞마당 미확인"
            stale = []
            if sc.main_last_seen_frame >= 0:
                stale.append(f"본진 마지막 시야 {_secs_ago(s.frame, sc.main_last_seen_frame)}초 전")
            if sc.natural_last_seen_frame >= 0:
                stale.append(f"앞마당 마지막 시야 {_secs_ago(s.frame, sc.natural_last_seen_frame)}초 전")
            lines.append(f"정찰: {main}, {nat}, full_scout={sc.full_scout}"
                         + (", 정찰 차단됨" if sc.scout_denied else "") + ((", " + ", ".join(stale)) if stale else ""))
        if it.buildings:
            lines.append("적 건물 (시작 추정 / 완성 추정 / 최초 목격 / 기준 타이밍):")
            for name, b in sorted(it.buildings.items(), key=lambda kv: (kv[1].started_frame if kv[1].started_frame >= 0 else 10**9, kv[0])):
                r = ref.get(name)
                refs = f" / 기준 {r}" if r else ""
                verdict = ""
                if r and b.started_frame >= 0:
                    rf = _parse_ref_frame(r)
                    if rf is not None:
                        d = (b.started_frame - rf) / 23.81
                        verdict = f" -> {'빠름' if d < -15 else '늦음' if d > 15 else '표준'} ({d:+.0f}s)"
                lines.append(f"- {name} x{b.count}: 시작 {b.started_time} / 완성 {b.completes_time} / 목격 {_t(b.first_seen_frame)}{refs}{verdict}")
        else:
            lines.append("적 건물: 아직 목격 없음")
        lines.append(f"적 일꾼 최대 목격 {it.workers_seen_max}, 가스 {it.gas.count}개"
                     + (f" (최초 {it.gas.first_seen_time})" if it.gas.count else " (미확인)")
                     + f", 적 기지 수 {it.expansions}" + (f", 일꾼 동원 {it.workers_pulled}" if it.workers_pulled else ""))
        if it.army.max_by_type:
            lines.append(f"적 병력 (최대 목격 수): {it.army.max_by_type}, 최초 {it.army.first_seen_time}")
        else:
            lines.append("적 병력: 아직 목격 없음")
        lines.append(f"McRave 추정: build={it.enemy_build}({it.enemy_build_state}) opener={it.enemy_opener}({it.enemy_opener_state}) "
                     f"transition={it.enemy_transition}({it.enemy_transition_state})"
                     + (f", flags={it.flags}" if it.flags else "") + (f", {it.mirror}" if it.mirror else ""))
        lines.append("")
        lines.append("지시: 위 정찰 정보와 기준 타이밍으로 적 빌드를 추론하라(enemy_build_guess). "
                     "앞으로 2-3분 안에 적이 가질 수 있는 것(유닛/테크/타이밍)을 expected_threats에 적고, "
                     "우리가 지금 준비해야 할 것을 our_response에 적은 뒤 그에 맞게 나머지 필드를 정하라. "
                     "정찰이 오래됐으면(마지막 시야가 60초 이상) 그 불확실성을 반영하라.")
        return "\n".join(lines)

    def timeline_text(self, max_lines: int = 25) -> str:
        return "\n".join(self.timeline[-max_lines:])


def _t(frame: int) -> str:
    if frame < 0:
        return "?"
    secs = int(frame / 23.81)
    return f"{secs // 60}:{secs % 60:02d}"


def _secs_ago(now: int, then: int) -> int:
    return max(0, int((now - then) / 23.81))


def _parse_ref_frame(ref: str) -> int | None:
    """'2:10' or '2:10-2:30' (takes the first time) -> frame."""
    head = ref.split("-")[0].split(" ")[0].strip()
    if ":" not in head:
        return None
    try:
        m, sec = head.split(":")
        return int((int(m) * 60 + int(sec)) * 23.81)
    except ValueError:
        return None
