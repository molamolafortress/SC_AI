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
        frame, last = 0, None
        for frame in range(0, int(rng.uniform(6, 12) * 60 * 23.81), 24):
            d = client.post("/state", json=state(frame, game_id, last)).json()["directive"]
            last = d["directive_id"] if d else last
        result = "win" if rng.random() < 0.55 else "loss"
        client.post("/game/end", params={"game_id": game_id}, json={"result": result, "frame": frame})


OPPONENTS = {  # name -> (module .so, race). Extend as more bots are ported to OpenBW.
    "probe": ("body/sidecar_client/probe_module/build/SidecarProbeModule.so", "Terran"),  # idle; pipeline check only
    "mcrave": ("build/mcrave/McRave.so", "Zerg"),  # pristine McRave as opponent = our own baseline body
    "mcrave_terran": ("build/mcrave/McRave.so", "Terran"),    # McRave plays all races: ZvT test bed
    "mcrave_protoss": ("build/mcrave/McRave.so", "Protoss"),  # ZvP test bed
    "zzzkbot": ("build/zzzkbot/ZZZKBot.so", "Zerg"),  # 4-pool/speedling rush bot (body/zzzkbot_port)
    "ualbertabot": ("build/ualbertabot/UAlbertaBot.so", "Protoss"),  # any race; strategy picked by race from its config (body/ualbertabot_port)
}
# Opponents that need files under p2/bwapi-data/ (copied in by tools/run_game_openbw.sh via OPP_DATA_DIR).
OPPONENT_DATA_DIRS = {
    "ualbertabot": "body/ualbertabot_port/bwapi-data",  # AI/UAlbertaBot_Config.txt
}


def run_openbw(cfg: SidecarConfig, args, out_dir: Path) -> None:
    """N real games on headless OpenBW. Starts a sidecar subprocess (fake/anthropic per config), runs
    tools/run_game_openbw.sh per game (``--parallel`` at a time), and reads results from the sidecar logs."""
    import os
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor

    out_dir.mkdir(parents=True, exist_ok=True)
    our = Path(args.our_module).resolve()
    opp_so, opp_race = OPPONENTS[args.opponent]
    opp = Path(opp_so).resolve()
    for p in (our, opp):
        if not p.exists():
            raise SystemExit(f"module not found: {p}")
    port = 8770 + (args.seed % 100)
    env = dict(os.environ, SIDECAR_CONFIG=args.config, SIDECAR_LOGS_DIR=str(cfg.logs_dir), SIDECAR_DISABLED_LEVERS=args.disable_levers or "")
    backend = (args.llm or cfg.llm_backend) if args.strategy == "llm" else "observe"
    sidecar = subprocess.Popen([sys.executable, "-m", "bot.sidecar.server", "--config", args.config, "--llm", backend,
                                "--port", str(port), "--mode", "lockstep" if args.lockstep else "headless"],
                               env=env, stdout=open(out_dir / "sidecar.out", "w"), stderr=subprocess.STDOUT)
    try:
        time.sleep(2)
        game_env = dict(os.environ, SIDECAR_HOST="127.0.0.1", SIDECAR_PORT=str(port), SIDECAR_CONFIG=args.config,
                        SC_AI_MAX_FRAMES=str(args.max_frames), SC_AI_LOCKSTEP="1" if args.lockstep else "0")
        # the sidecar writes logs to cfg.logs_dir; tell it via the config override used by SidecarConfig.load
        game_env["SIDECAR_LOGS_DIR"] = str(cfg.logs_dir)
        if args.opponent in OPPONENT_DATA_DIRS:
            game_env["OPP_DATA_DIR"] = str(Path(OPPONENT_DATA_DIRS[args.opponent]).resolve())

        def one(i: int) -> str:
            run_dir = out_dir / "games" / f"{i:03d}"
            side = "p2" if (args.alternate_sides and i % 2 == 1) else "p1"
            r = subprocess.run(["tools/run_game_openbw.sh", str(our), str(opp), args.map, "Zerg", opp_race, str(run_dir), f"g{i}"],
                               env=dict(game_env, OUR_SIDE=side), capture_output=True, text=True)
            line = (r.stdout.strip().splitlines() or ["?"])[-1]
            print(f"game {i} ({side}): {line}", flush=True)
            return line

        with ThreadPoolExecutor(max_workers=args.parallel) as ex:
            list(ex.map(one, range(args.games)))
    finally:
        sidecar.terminate()
        sidecar.wait(10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=30)
    ap.add_argument("--opponent", default="probe")
    ap.add_argument("--map", default="maps/BroodWar/sscai/(4)FightingSpirit.scx")
    ap.add_argument("--strategy", default="fixed", choices=["fixed", "random", "llm"])
    ap.add_argument("--runner", default="mock", choices=["mock", "openbw"])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--config", default="config/sidecar.yaml")
    ap.add_argument("--parallel", type=int, default=1)
    ap.add_argument("--alternate-sides", dest="alternate_sides", action="store_true", default=True,
                    help="odd games: our bot is player 2 (removes host/start-position bias); default on")
    ap.add_argument("--no-alternate-sides", dest="alternate_sides", action="store_false")
    ap.add_argument("--lockstep", dest="lockstep", action="store_true", default=True,
                    help="game waits for each LLM call (decision lands on the frame it was asked for); default on")
    ap.add_argument("--no-lockstep", dest="lockstep", action="store_false")
    ap.add_argument("--disable-levers", default="", help="comma list of directive levers reset to no-override (ablation)")
    ap.add_argument("--max-frames", type=int, default=43200, help="frame cap per game (30 game-minutes); leaving counts as timeout")
    ap.add_argument("--llm", default=None, choices=["anthropic", "claude-cli", "fake", "recorded"], help="backend for --strategy llm")
    ap.add_argument("--our-module", default="build/mcrave/McRave.so")
    args = ap.parse_args()

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{args.runner}_{args.opponent}_{args.strategy}{('_no-' + args.disable_levers.replace(',', '-')) if args.disable_levers else ''}_s{args.seed}"
    out_dir = Path("eval/results") / run_id
    cfg = SidecarConfig.load(args.config, logs_dir=out_dir / "logs", mode="lockstep" if args.lockstep else "headless")
    if args.runner == "openbw":
        run_openbw(cfg, args, out_dir)
    else:
        run_mock(cfg, args.games, args.seed, args.strategy)
    if args.strategy == "llm":
        backend = args.llm or cfg.llm_backend
        if backend == "fake" and args.runner == "openbw":
            backend = "claude-cli"
    else:
        backend = "observe" if args.runner == "openbw" else "fake"
    metrics = {"run_id": run_id, "args": vars(args), "mode": cfg.mode, "lockstep": args.lockstep,
               "alternate_sides": args.alternate_sides, "safety_interval_seconds": cfg.triggers.safety_interval_seconds,
               "decide_at_start": cfg.triggers.decide_at_start, "strategy": args.strategy, "strategy_backend": backend,
               "opponent": args.opponent, "map": args.map, "seed": args.seed, **summarize(collect(cfg.logs_dir))}
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
