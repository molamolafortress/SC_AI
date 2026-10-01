"""Merge several run directories (chunks of the same condition) into one metrics.json.

python -m eval.merge eval/results/combined_fixed eval/results/<run1> eval/results/<run2> ...
"""
import json
import sys
from pathlib import Path

from eval.metrics import collect, summarize

out = Path(sys.argv[1]); runs = [Path(p) for p in sys.argv[2:]]
results = []
for r in runs:
    results += collect(r / "logs")
out.mkdir(parents=True, exist_ok=True)
first = next((json.load(open(r / "metrics.json", encoding="utf-8")) for r in runs if (r / "metrics.json").exists()), {})
metrics = {"run_id": out.name, "merged_from": [r.name for r in runs], "args": first.get("args"), **{k: v for k, v in first.items() if k in ("mode", "lockstep", "alternate_sides", "safety_interval_seconds", "decide_at_start", "strategy", "strategy_backend", "opponent", "map")}, **summarize(results)}
(out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: metrics[k] for k in ("games", "wins", "timeouts", "win_rate", "win_rate_ci95", "avg_frames", "avg_cost_usd", "avg_strategy_calls", "avg_flip_flops")}, ensure_ascii=False))
