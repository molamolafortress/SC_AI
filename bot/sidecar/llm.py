"""LLM backends for the Strategy layer. `AnthropicBackend` is the real one; `FakeBackend`
is deterministic for tests and lockstep dev without spending; `RecordedBackend` replays a
directive sequence from a previous game log (replay-directive mode)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .schemas import Directive

# $/MTok, from the 2026-09 price table (design_review 2.1). Update when prices change.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-4-5": (1.0, 5.0, 0.10, 1.25),
}


@dataclass
class LLMResult:
    directive: Directive
    latency_ms: float
    usage: dict
    cost_usd: float
    raw_text: str = ""


def estimate_cost(model: str, usage: dict) -> float:
    inp, out, cread, cwrite = PRICES.get(model, (4.0, 20.0, 0.20, 5.0))
    return (
        usage.get("input_tokens", 0) * inp
        + usage.get("output_tokens", 0) * out
        + usage.get("cache_read_input_tokens", 0) * cread
        + usage.get("cache_creation_input_tokens", 0) * cwrite
    ) / 1e6


class Backend(Protocol):
    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult: ...


class AnthropicBackend:
    def __init__(self, model: str = "claude-opus-5-5", max_tokens: int = 4000):
        import anthropic  # imported lazily so tests do not need credentials

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult:
        t0 = time.perf_counter()
        try:
            r = self.client.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=[{"type": "text", "text": fixed_prefix, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
                output_config={"effort": effort},
                output_format=Directive,
            )
        except self._anthropic.RateLimitError as e:  # retried by SDK (max_retries=2); surface if still failing
            raise LLMUnavailable(f"rate limited: {e}") from e
        except self._anthropic.APIStatusError as e:
            if e.status_code >= 500:
                raise LLMUnavailable(f"server error {e.status_code}") from e
            raise LLMRejected(f"bad request {e.status_code}: {e}") from e
        except self._anthropic.APIConnectionError as e:
            raise LLMUnavailable(f"connection: {e}") from e
        latency = (time.perf_counter() - t0) * 1000
        if r.stop_reason == "refusal":
            raise LLMRejected(f"refusal: {getattr(r, 'stop_details', None)}")
        if r.parsed_output is None:
            raise LLMRejected(f"no parsed output (stop_reason={r.stop_reason})")
        usage = {k: getattr(r.usage, k, 0) or 0 for k in
                 ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        return LLMResult(r.parsed_output, latency, usage, estimate_cost(self.model, usage))


class LLMUnavailable(RuntimeError):
    """Transient: keep the current plan, retry on the next trigger."""


class LLMRejected(RuntimeError):
    """Permanent for this request: log and drop."""


class FakeBackend:
    """Deterministic stand-in: rule-based directive from the user message. Zero cost."""

    def __init__(self, latency_ms: float = 0.0, script: list[Directive] | None = None):
        self.latency_ms = latency_ms
        self.script = list(script or [])
        self.calls: list[tuple[str, str, str]] = []

    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult:
        self.calls.append((fixed_prefix, user_message, effort))
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        if self.script:
            d = self.script.pop(0)
        else:
            aggressive = "barracks x2" in user_message or "gateway x2" in user_message
            d = Directive(
                keep_current_plan=False,
                change_reason="fake backend: " + ("early pressure expected" if aggressive else "default macro"),
                opening="12hatch_11pool",
                unit_mix_target={"drone": 0.55, "zergling": 0.45} if aggressive else {"drone": 0.65, "zergling": 0.35},
                tech_priority=["metabolic_boost", "lair"],
                stance="defensive",
                expand_policy="allow_when_safe",
                static_defense={"sunken": 1 if aggressive else 0},
                confidence=0.6,
                review_after_seconds=45,
            )
        return LLMResult(d, self.latency_ms, {"input_tokens": 0, "output_tokens": 0}, 0.0)


class RecordedBackend:
    """Replays the directives of a previous game log in order (frame alignment is done by the caller)."""

    def __init__(self, log_path: Path):
        self.queue: list[Directive] = []
        for line in Path(log_path).read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("layer") == "strategy" and rec.get("output"):
                self.queue.append(Directive.model_validate(rec["output"]))

    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult:
        if not self.queue:
            raise LLMUnavailable("recorded directives exhausted")
        return LLMResult(self.queue.pop(0), 0.0, {}, 0.0)
