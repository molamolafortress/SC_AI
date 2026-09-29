"""Plan ledger: remembers the current plan so the LLM does not flip-flop and so every
decision is explainable later from the log."""
from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import IssuedDirective


@dataclass
class LedgerEntry:
    directive: IssuedDirective
    trigger: str
    frame: int


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
        self.history.append(LedgerEntry(directive, trigger, frame))

    def summary_text(self) -> str:
        cur = self.current
        if cur is None:
            return "이전 결정 없음 (게임 시작)."
        lines = [
            f"현재 계획 (id {cur.directive_id}, frame {cur.issued_frame}): opening={cur.opening}, "
            f"stance={cur.stance}, objective={cur.army_objective.type}@{cur.army_objective.location}, "
            f"expand={cur.expand_policy}, wall={cur.wall_natural}",
            f"결정 사유: {cur.change_reason}",
        ]
        if len(self.history) > 1:
            lines.append("이전 변경: " + "; ".join(
                f"f{e.frame} {e.directive.opening}/{e.directive.stance} ({e.trigger})" for e in self.history[-4:-1]))
        return "\n".join(lines)


def _plan_key(d: IssuedDirective) -> tuple:
    return (d.opening, d.stance, d.army_objective.type, d.army_objective.location, d.expand_policy)
