"""Print the decision timeline of one game log (every LLM input/output is in the JSONL; this is the readable view).

python -m tools.show_game logs/games/<game>.jsonl            # timeline
python -m tools.show_game <log> --call 3                      # full input + output of call 3
python -m tools.show_game <log> --prefix                      # the cached system prompt used in this game
python -m tools.show_game <log> --series                      # the time-series table (last call's view)
python -m tools.show_game <log> --feedback                    # execution feedback section of every call
"""
from __future__ import annotations

import argparse
import json


def section(text: str, heading: str) -> str:
    """The body of one '## ...' section of an LLM input (up to the next heading)."""
    i = text.find(heading)
    if i < 0:
        return ""
    body = text[i:].split("\n", 1)[1] if "\n" in text[i:] else ""
    j = body.find("\n## ")
    return body if j < 0 else body[:j]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--call", type=int, default=None)
    ap.add_argument("--prefix", action="store_true")
    ap.add_argument("--series", action="store_true", help="print the time-series table of the game (from the last call's input)")
    ap.add_argument("--feedback", action="store_true", help="print the execution feedback section per call")
    args = ap.parse_args()
    recs = [json.loads(l) for l in open(args.log, encoding="utf-8")]
    if args.series or args.feedback:
        calls = [r for r in recs if r["layer"] == "strategy" and r.get("input")]
        if args.series and calls:
            print(section(calls[-1]["input"], "## 시계열"))
        if args.feedback:
            for n, r in enumerate(calls, 1):
                print(f"# call {n}  frame {r['frame']}  {r.get('game_time', '')}  trigger {r.get('trigger')}")
                print(section(r["input"], "## 직전 지시 실행 결과") + "\n")
        return
    if args.prefix:
        for r in recs:
            if r["layer"] == "prefix":
                print(f"# sha256 {r['sha256']}  model {r.get('model')}  backend {r.get('backend')}\n")
                print(r["text"])
        return
    calls = [r for r in recs if r["layer"] == "strategy"]
    if args.call is not None:
        r = calls[args.call - 1]
        print(f"# call {args.call}  frame {r['frame']}  trigger {r.get('trigger')}  effort {r.get('effort')}  "
              f"latency {r.get('latency_ms')} ms  cost ${r.get('cost_usd')}\n")
        print("## INPUT\n" + (r.get("input") or "") + "\n\n## OUTPUT\n" + json.dumps(r.get("output"), ensure_ascii=False, indent=1))
        if r.get("error"):
            print("## ERROR", r["error"])
        return
    last_state = None
    n = 0
    for r in recs:
        if r["layer"] == "state":
            last_state = r["input"]
        elif r["layer"] == "strategy":
            n += 1
            s = last_state or {}
            me, en = s.get("me", {}), s.get("enemy", {})
            o = r.get("output") or {}
            eb = {k: v["count"] for k, v in en.get("buildings_seen", {}).items()}
            line = (f"[{n:2d}] f{r['frame']:6d} {s.get('game_time','?'):>6} {str(r.get('trigger'))[:30]:30s} {str(r.get('effort')):6s} "
                    f"{(r.get('latency_ms') or 0)/1000:4.1f}s  me:d{me.get('units',{}).get('drone',0)} z{me.get('units',{}).get('zergling',0)} "
                    f"m{me.get('units',{}).get('mutalisk',0)} min{me.get('minerals',0)}  enemy:{eb}")
            if r.get("error"):
                print(line + f"  ERROR {r['error']}")
            else:
                print(line + f"\n      -> {o.get('opening')} {o.get('stance')} {o.get('expand_policy')} "
                      f"{o.get('army_objective',{}).get('type')}@{o.get('army_objective',{}).get('location')} keep={o.get('keep_current_plan')}"
                      f"\n      reason: {o.get('change_reason')}")
        elif r["layer"] == "validator":
            print(f"      validator {r.get('outcome')}: {r.get('fixes') or r.get('reasons')}")
        elif r["layer"] == "result":
            print(f"RESULT {r.get('result')} frames={r.get('frames')} cost=${r.get('cost_usd')} calls={r.get('strategy_calls')} flip_flops={r.get('flip_flops')}")


if __name__ == "__main__":
    main()
