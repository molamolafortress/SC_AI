"""Aggregate per-game result lines (the `result` record of each JSONL log) into metrics.json
and compare two runs with a simple Wilson interval so 'no change' is an honest verdict."""
from __future__ import annotations

import json
import math
from pathlib import Path


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n == 0:
        return 0.0, 0.0, 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def collect(logs_dir: Path) -> list[dict]:
    results = []
    for path in sorted(Path(logs_dir).glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("layer") == "result":
                results.append(rec)
    return results


def summarize(results: list[dict]) -> dict:
    n = len(results)
    wins = sum(1 for r in results if r.get("result") == "win")
    p, lo, hi = wilson(wins, n)
    mean = lambda key: (sum(float(r.get(key, 0) or 0) for r in results) / n) if n else 0.0
    return {
        "games": n, "wins": wins, "win_rate": round(p, 3), "win_rate_ci95": [round(lo, 3), round(hi, 3)],
        "avg_frames": round(mean("frames")), "avg_cost_usd": round(mean("cost_usd"), 3),
        "avg_strategy_calls": round(mean("strategy_calls"), 1), "avg_flip_flops": round(mean("flip_flops"), 2),
        "avg_validator_rejects": round(mean("validator_rejects"), 2),
    }


def compare(a: dict, b: dict) -> str:
    """Verdict for a regression gate: improved / regressed / no_change (intervals overlap)."""
    if b["win_rate_ci95"][0] > a["win_rate_ci95"][1]:
        return "improved"
    if b["win_rate_ci95"][1] < a["win_rate_ci95"][0]:
        return "regressed"
    return "no_change"
