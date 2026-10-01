"""Plan ledger: remembers the current plan so the LLM does not flip-flop and so every
decision is explainable later from the log."""
from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import ExecutionFeedback, IssuedDirective


@dataclass
class LedgerEntry:
    directive: IssuedDirective
    trigger: str
    frame: int
    # What was requested of the body, kept explicitly so the execution feedback comparison is traceable.
    requested: dict = field(default_factory=dict)  # {"static_defense": {...}, "unit_mix_target": {...}, "stance": ...}


@dataclass
class PlanLedger:
    min_hold_frames: int
    history: list[LedgerEntry] = field(default_factory=list)
    flip_flops: int = 0

    @property
    def current(self) -> IssuedDirective | None:
        return self.history[-1].directive if self.history else None

    def can_change(self, frame: int) -> bool:
        cur = self.current
        return cur is None or frame - cur.issued_frame >= self.min_hold_frames

    def record(self, directive: IssuedDirective, trigger: str, frame: int) -> None:
        prev = self.current
        if prev is not None and not directive.keep_current_plan and _plan_key(prev) != _plan_key(directive):
            if frame - prev.issued_frame < 2 * self.min_hold_frames:
                self.flip_flops += 1
        requested = {"static_defense": dict(directive.static_defense), "unit_mix_target": dict(directive.unit_mix_target),
                     "stance": directive.stance, "expand_policy": directive.expand_policy, "opening": directive.opening,
                     "army_objective": directive.army_objective.model_dump(), "tech_priority": list(directive.tech_priority)}
        self.history.append(LedgerEntry(directive, trigger, frame, requested))

    def entry_for(self, directive_id: str | None) -> LedgerEntry | None:
        """Entry the body is reporting on; the current one when the id is missing or unknown."""
        for e in reversed(self.history):
            if directive_id and e.directive.directive_id == directive_id:
                return e
        return self.history[-1] if self.history else None

    def summary_text(self) -> str:
        cur = self.current
        if cur is None:
            return "이전 결정 없음 (게임 시작)."
        lines = [
            f"현재 계획 (id {cur.directive_id}, frame {cur.issued_frame}): opening={cur.opening}, "
            f"stance={cur.stance}, objective={cur.army_objective.type}@{cur.army_objective.location}, "
            f"expand={cur.expand_policy}, wall={cur.wall_natural}"
            + (", observe_only (몸체 기본값 유지)" if cur.observe_only else ""),
            f"결정 사유: {cur.change_reason}",
        ]
        if len(self.history) > 1:
            lines.append("이전 변경: " + "; ".join(
                f"f{e.frame} {e.directive.opening}/{e.directive.stance} ({e.trigger})" for e in self.history[-4:-1]))
        return "\n".join(lines)


def feedback_text(ledger: PlanLedger, ex: ExecutionFeedback) -> str:
    """'## 직전 지시 실행 결과' body: per override field applied/ignored with before->after, then the results
    (static defense built vs requested, actual army vs unit_mix_target, drones and delta)."""
    entry = ledger.entry_for(ex.directive_id)
    if entry is None:
        return "이전 지시 없음."
    req = entry.requested
    lines: list[str] = []
    if ex.directive_id is None and not ex.overrides:
        lines.append(f"몸체 실행 보고 없음 (현재 지시 {entry.directive.directive_id}).")
    else:
        head = f"지시 {ex.directive_id or '?'} 실행 보고"
        if ex.directive_id and ex.directive_id != entry.directive.directive_id:
            head += f" (현재 지시는 {entry.directive.directive_id})"
        lines.append(head + ":")
    for o in ex.overrides:
        status = "적용됨" if o.applied else "무시됨"
        change = f" {_v(o.before)} → {_v(o.after)}" if (o.before is not None or o.after is not None) else ""
        note = f" ({o.note})" if o.note else ""
        lines.append(f"- {o.field}: {status}{change}{note}")
    r = ex.results
    sd = req.get("static_defense", {})
    lines.append(f"결과: 성큰 요청 {sd.get('sunken', 0)} → 실제 {r.sunken}, 스포어 요청 {sd.get('spore', 0)} → 실제 {r.spore}")
    mix = req.get("unit_mix_target", {})
    if r.army_actual:
        total = sum(r.army_actual.values()) or 1
        actual_ratio = {k: round(v / total, 2) for k, v in r.army_actual.items()}
        lines.append(f"실제 조성: {r.army_actual} (비율 {actual_ratio}) vs 목표 {mix}")
    else:
        lines.append(f"실제 조성: 병력 없음 vs 목표 {mix}")
    sign = "+" if r.drone_delta_since_directive >= 0 else ""
    lines.append(f"드론: {r.drones} (지시 이후 {sign}{r.drone_delta_since_directive})")
    if ex.goals:
        lines.append("목표 상태: " + ", ".join(f"{g.goal}={g.status}" for g in ex.goals))
    return "\n".join(lines)


def _v(x) -> str:
    return "∅" if x is None else str(x)


def _plan_key(d: IssuedDirective) -> tuple:
    return (d.opening, d.stance, d.army_objective.type, d.army_objective.location, d.expand_policy)
