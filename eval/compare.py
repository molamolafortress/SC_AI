"""python -m eval.compare eval/results/<baseline>/metrics.json eval/results/<candidate>/metrics.json"""
import json
import sys

from eval.metrics import compare

RUN_KEYS = ("mode", "alternate_sides", "safety_interval_seconds", "decide_at_start", "strategy", "strategy_backend",
            "opponent", "map", "seed")


def describe(m: dict) -> str:
    return ", ".join(f"{k}={m.get(k, '?')}" for k in RUN_KEYS)


def main(paths: list[str]) -> None:
    a, b = (json.load(open(p, encoding="utf-8")) for p in paths[:2])
    print(f"baseline  {a['win_rate']:.3f} {a['win_rate_ci95']}  n={a['games']}  [{describe(a)}]")
    print(f"candidate {b['win_rate']:.3f} {b['win_rate_ci95']}  n={b['games']}  [{describe(b)}]")
    differ = [k for k in ("mode", "alternate_sides", "safety_interval_seconds", "opponent", "map", "seed") if a.get(k) != b.get(k)]
    if differ:
        print(f"WARNING: runs differ in {differ}; the verdict is not a like-for-like comparison")
    print("verdict:", compare(a, b))


if __name__ == "__main__":
    main(sys.argv[1:])
