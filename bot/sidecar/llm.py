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

    def __init__(self, latency_ms: float = 0.0, script: list[Directive] | None = None, observe_only: bool = False):
        self.latency_ms = latency_ms
        self.observe_only = observe_only
        self.script = list(script or [])
        self.calls: list[tuple[str, str, str]] = []

    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult:
        self.calls.append((fixed_prefix, user_message, effort))
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000)
        if self.script:
            d = self.script.pop(0)
        elif self.observe_only:
            d = Directive(observe_only=True, keep_current_plan=True, change_reason="observe only: body defaults", stance="neutral")
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
                enemy_build_guess=_fake_build_guess(user_message),
                expected_threats=["marine push 4:30-5:30"] if aggressive else [],
                our_response="1 sunken + lings, then drones" if aggressive else "drone up, scout again",
            )
        return LLMResult(d, self.latency_ms, {"input_tokens": 0, "output_tokens": 0}, 0.0)


def _fake_build_guess(user_message: str) -> str:
    """Echo McRave's guess from the intel brief, so the fake directive is traceable to its input."""
    marker = "McRave 추정: "
    i = user_message.find(marker)
    if i < 0:
        return "unknown"
    return user_message[i + len(marker):].split("\n", 1)[0][:120]


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


class ClaudeCliBackend:
    """Strategy backend through the Claude Code CLI in headless mode (`claude -p`).

    Uses whatever login the CLI has (a Claude subscription on a developer machine, or the cloud
    session's credentials), so no API key is needed. Slower than the API (CLI startup, ~2-7 s) and the
    prompt prefix is cached by the CLI's own 1-hour cache. Structured output via --json-schema.
    """

    def __init__(self, model: str = "claude-opus-5-5", timeout_s: float = 120.0, cwd: Path | None = None):
        import tempfile

        self.model = model
        self.timeout_s = timeout_s
        self.cwd = cwd or Path(tempfile.mkdtemp(prefix="sc_ai_cli_"))  # empty cwd: no CLAUDE.md, no project context
        self.schema = json.dumps(Directive.model_json_schema())

    def decide(self, fixed_prefix: str, user_message: str, effort: str) -> LLMResult:
        import subprocess

        cmd = ["claude", "-p", "--output-format", "json", "--json-schema", self.schema,
               "--system-prompt", fixed_prefix, "--tools", "", "--model", self.model, "--effort", effort,
               "--no-session-persistence", "--setting-sources", ""]
        t0 = time.perf_counter()
        try:
            r = subprocess.run(cmd, input=user_message, capture_output=True, text=True, timeout=self.timeout_s, cwd=self.cwd)
        except subprocess.TimeoutExpired as e:
            raise LLMUnavailable(f"claude cli timeout after {self.timeout_s}s") from e
        except FileNotFoundError as e:
            raise LLMUnavailable("claude cli not found on PATH") from e
        latency = (time.perf_counter() - t0) * 1000
        if r.returncode != 0:
            raise LLMUnavailable(f"claude cli exit {r.returncode}: {r.stderr[-300:]}")
        try:
            out = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            raise LLMRejected(f"claude cli non-json output: {r.stdout[:200]}") from e
        data = out.get("structured_output")
        if data is None:
            try:
                data = json.loads(out.get("result", ""))
            except json.JSONDecodeError as e:
                raise LLMRejected(f"no structured output: {str(out.get('result'))[:200]}") from e
        try:
            d = Directive.model_validate(data)
        except Exception as e:  # pydantic.ValidationError
            raise LLMRejected(f"schema validation failed: {e}") from e
        u = out.get("usage", {}) or {}
        usage = {k: u.get(k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
        cost = float(out.get("total_cost_usd") or estimate_cost(self.model, usage))
        return LLMResult(d, latency, usage, cost, raw_text=out.get("result", ""))
