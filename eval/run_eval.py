"""Evaluation harness entry point.

python -m eval.run_eval --games 30 --opponent zzzkbot --map "Fighting Spirit" --strategy llm --runner mock

Runners:
  mock    - no game engine; drives the sidecar with tools.fake_body and a scripted outcome. Validates the
            pipeline (sidecar, logs, metrics) end to end. Win/loss is random with a fixed seed.
  openbw  - TODO(Phase 0/2): launches two BWAPILauncher instances (our body + opponent) in LAN mode with the
            sidecar, waits for the result. See docs/setup_openbw.md.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from fastapi.testclient import TestClient

from bot.sidecar.config import SidecarConfig
from bot.sidecar.llm import FakeBackend
from bot.sidecar.server import create_app, make_backend
from eval.metrics import collect, summarize
from tools.fake_body import state


def run_mock(cfg: SidecarConfig, games: int, seed: int, strategy: str) -> None:
    backend = make_backend("anthropic", cfg) if strategy == "llm" and cfg.llm_backend == "anthropic" else FakeBackend()
    client = TestClient(create_app(cfg, backend))
    rng = random.Random(seed)
    for i in range(games):
        game_id = f"mock_{seed}_{i:03d}"
        frame = 0
        for frame in range(0, int(rng.uniform(6, 12) * 60 * 23.81), 24):
            client.post("/state", json=state(frame, game_id))
        result = "win" if rng.random() < 0.55 else "loss"
        client.post("/game/end", params={"game_id": game_id}, json={"result": result, "frame": frame})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--opponent", default="zzzkbot")
    ap.add_argument("--map", default="Fighting Spirit")
    ap.add_argument("--strategy", default="fixed", choices=["fixed", "random", "llm"])
    ap.add_argument("--runner", default="mock", choices=["mock", "openbw"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--config", default="config/sidecar.yaml")
    args = ap.parse_args()

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{args.runner}_{args.opponent}_{args.strategy}_s{args.seed}"
    out_dir = Path("eval/results") / run_id
    cfg = SidecarConfig.load(args.config, logs_dir=out_dir / "logs", mode="lockstep")
    if args.runner == "openbw":
        raise SystemExit("openbw runner not implemented yet: see docs/setup_openbw.md and design_v0.5.md Phase 0/2")
    run_mock(cfg, args.games, args.seed, args.strategy)
    metrics = {"run_id": run_id, "args": vars(args), **summarize(collect(cfg.logs_dir))}
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
