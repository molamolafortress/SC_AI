"""StrategyCaller: turns triggers into validated directives, one LLM call in flight at a time."""
from __future__ import annotations

import hashlib
import itertools
import threading
from dataclasses import dataclass, field

from .config import SidecarConfig
from .knowledge import Knowledge
from .llm import Backend, LLMRejected, LLMResult, LLMUnavailable
from .logger import GameLogger
from .plan_ledger import PlanLedger
from .schemas import Directive, IssuedDirective, StateSummary
from .state_store import StateStore
from .summarizer import fixed_prefix, user_message
from .validator import validate


@dataclass
class StrategyCaller:
    cfg: SidecarConfig
    knowledge: Knowledge
    backend: Backend
    store: StateStore
    ledger: PlanLedger
    logger: GameLogger
    lockstep: bool = False
    _prefix: str = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _inflight: threading.Thread | None = None
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    review_after_frame: int | None = None
    budget_exhausted: bool = False

    def __post_init__(self) -> None:
        self._prefix = fixed_prefix(self.knowledge)
        # The cached system prompt is identical for every call of the game: log it once, in full, with its hash.
        self.logger.log("prefix", 0, sha256=hashlib.sha256(self._prefix.encode("utf-8")).hexdigest(), text=self._prefix,
                        model=self.cfg.models.strategy_model, backend=type(self.backend).__name__)

    # ---- called on every state post -------------------------------------------------
    def on_state(self) -> None:
        if self.budget_exhausted or self.store.latest is None:
            return
        if self._inflight is not None and self._inflight.is_alive():
            return  # one call in flight
        trigger = self.store.trigger(self.review_after_frame)
        if trigger is None:
            return
        if not self.store.is_transition_trigger(trigger) and not self.ledger.can_change(self.store.latest.frame):
            return
        effort = (self.cfg.models.strategy_effort_transition if self.store.is_transition_trigger(trigger)
                  else self.cfg.models.strategy_effort_regular)
        msg = user_message(self.store, self.ledger, trigger)
        snapshot = self.store.latest
        self.store.mark_called()
        if self.lockstep:
            self._run(trigger, msg, effort, snapshot)
        else:
            self._inflight = threading.Thread(target=self._run, args=(trigger, msg, effort, snapshot), daemon=True)
            self._inflight.start()

    # ---- the call itself ----------------------------------------------------------------
    def _run(self, trigger: str, msg: str, effort: str, snapshot: StateSummary) -> None:
        self.logger.strategy_calls += 1
        try:
            result: LLMResult = self.backend.decide(self._prefix, msg, effort)
        except LLMUnavailable as e:
            self.logger.log("strategy", snapshot.frame, trigger=trigger, error=str(e), outcome="unavailable_keep_plan")
            return
        except LLMRejected as e:
            self.logger.log("strategy", snapshot.frame, trigger=trigger, error=str(e), outcome="rejected")
            return
        self.logger.add_cost(result.cost_usd)
        self.logger.log("strategy", snapshot.frame, trigger=trigger, effort=effort, input=msg,
                        output=result.directive.model_dump(), raw_text=result.raw_text,
                        latency_ms=round(result.latency_ms, 1), usage=result.usage, cost_usd=round(result.cost_usd, 5),
                        game_time=snapshot.game_time)
        if self.logger.total_cost_usd >= self.cfg.budgets.per_game_usd:
            self.budget_exhausted = True
            self.logger.log("strategy", snapshot.frame, outcome="budget_exhausted", total_cost_usd=self.logger.total_cost_usd)
        self._apply(result.directive, trigger, snapshot)

    def _apply(self, d: Directive, trigger: str, snapshot: StateSummary) -> None:
        latest = self.store.latest or snapshot
        # Stale check: a big engagement started after the call began -> discard, re-trigger.
        if any(ev.startswith("engagement_start") for ev in self.store.pending_events):
            self.logger.log("strategy", latest.frame, outcome="discarded_stale", trigger=trigger)
            return
        v = validate(d, self.knowledge, latest)
        if not v.ok:
            self.logger.validator_rejects += 1
            self.logger.log("validator", latest.frame, outcome="rejected", reasons=v.rejected, fixes=v.fixes)
            return
        if v.fixes:
            self.logger.log("validator", latest.frame, outcome="fixed", fixes=v.fixes)
        d = v.directive
        cur = self.ledger.current
        if d.keep_current_plan and cur is not None:
            d = cur.model_copy(update={"keep_current_plan": True, "change_reason": d.change_reason or cur.change_reason})
            source = "ledger_hold"
        else:
            source = "validator_fix" if v.fixes else "llm"
        issued = IssuedDirective(
            **d.model_dump(exclude={"directive_id", "issued_frame", "expires_frame", "source"}),
            directive_id=f"d-{next(self._ids):04d}",
            issued_frame=latest.frame,
            expires_frame=latest.frame + self.cfg.frames(self.cfg.directive_ttl_seconds),
            source=source,
        )
        with self._lock:
            self.ledger.record(issued, trigger, latest.frame)
            self.review_after_frame = latest.frame + self.cfg.frames(issued.review_after_seconds)
        self.logger.log("directive", latest.frame, output=issued.model_dump(), trigger=trigger)

    # ---- served to the body ---------------------------------------------------------------
    def current_directive(self) -> IssuedDirective | None:
        with self._lock:
            return self.ledger.current

    def wait_idle(self, timeout: float = 30.0) -> None:
        if self._inflight is not None:
            self._inflight.join(timeout)
