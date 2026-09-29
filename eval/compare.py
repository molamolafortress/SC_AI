"""python -m eval.compare eval/results/<baseline>/metrics.json eval/results/<candidate>/metrics.json"""
import json
import sys

from eval.metrics import compare

a, b = (json.load(open(p, encoding="utf-8")) for p in sys.argv[1:3])
print(f"baseline  {a['win_rate']:.3f} {a['win_rate_ci95']}  n={a['games']}")
print(f"candidate {b['win_rate']:.3f} {b['win_rate_ci95']}  n={b['games']}")
print("verdict:", compare(a, b))
