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
from .validator import apply_disabled_levers, validate


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
    _last_engagement_call_frame: int = -10**9

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
        if trigger == "game_start" and not self.cfg.triggers.decide_at_start:
            self._observe_start()
            return
        if not self.store.is_transition_trigger(trigger) and not self.ledger.can_change(self.store.latest.frame):
            return
        # Debounce: a burst of intel/building events within min_call_gap_seconds is answered by one call (events stay
        # pending and ride along in the delta); only critical triggers bypass the gap.
        gap = self.cfg.frames(self.cfg.triggers.min_call_gap_seconds)
        frame = self.store.latest.frame
        if (not trigger.startswith(tuple(self.cfg.triggers.critical_triggers))
                and frame - self.store.last_call_frame < gap):
            return
        # At most one engagement-driven call per engagement_min_gap_seconds (skirmish chains otherwise call every 10 s).
        if trigger.startswith("engagement_end"):
            if frame - self._last_engagement_call_frame < self.cfg.frames(self.cfg.triggers.engagement_min_gap_seconds):
                self.store.pending_events = [e for e in self.store.pending_events if not e.startswith("engagement_end")]
                return
            self._last_engagement_call_frame = frame
        effort = (self.cfg.models.strategy_effort_transition if self.store.is_transition_trigger(trigger)
                  else self.cfg.models.strategy_effort_regular)
        msg = user_message(self.store, self.ledger, trigger, self.knowledge)
        snapshot = self.store.latest
        self.store.mark_called()
        if self.lockstep:
            self._run(trigger, msg, effort, snapshot)
        else:
            self._inflight = threading.Thread(target=self._run, args=(trigger, msg, effort, snapshot), daemon=True)
            self._inflight.start()

    def _observe_start(self) -> None:
        """Start rule (audit D): no LLM call at frame 0. Record an observe-only directive (body defaults) so the
        body keeps its own opening; the first real call comes at the first intel/enemy trigger or at the deadline."""
        s = self.store.latest
        assert s is not None
        stance = s.body_defaults.get("stance", "neutral")
        if stance not in ("defensive", "neutral", "aggressive", "all_in"):
            stance = "neutral"
        issued = IssuedDirective(
            observe_only=True, keep_current_plan=False,
            change_reason="game_start: 정찰 전에는 몸체 기본값 유지 (관찰만)",
            opening=s.body_defaults.get("opening", ""), stance=stance,
            review_after_seconds=self.cfg.triggers.first_call_deadline_seconds,
            directive_id=f"d-{next(self._ids):04d}", issued_frame=s.frame,
            expires_frame=s.frame + self.cfg.frames(self.cfg.directive_ttl_seconds), source="body_default",
        )
        with self._lock:
            self.ledger.record(issued, "game_start_observe", s.frame)
            self.review_after_frame = None
        self.store.mark_observing_start()
        self.logger.log("directive", s.frame, output=issued.model_dump(), trigger="game_start_observe")

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
        d = apply_disabled_levers(d, self.cfg.levers.disabled, latest)
        v = validate(d, self.knowledge, latest)
        if not v.ok:
            self.logger.validator_rejects += 1
            self.logger.log("validator", latest.frame, outcome="rejected", reasons=v.rejected, fixes=v.fixes)
            return
        if v.fixes:
            self.logger.log("validator", latest.frame, outcome="fixed", fixes=v.fixes)
        d = v.directive
        cur = self.ledger.current
        if d.keep_current_plan and cur is not None and not cur.observe_only:
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
