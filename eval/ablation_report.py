"""Summarize conditions (glob patterns) side by side: win rate with CI, calls, cost, flip-flops, drones at 6:00/10:00,
engagement calls, lever usage. python -m eval.ablation_report "label=glob" ...
e.g. python -m eval.ablation_report "baseline=eval/results/*_mcrave_fixed_s20[13]" "full=eval/results/*_llm_s30[1-6]" """
import glob
import json
import statistics as st
import sys

from eval.metrics import wilson


def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")]


def state_at(recs, seconds):
    best = None
    for r in recs:
        if r["layer"] == "state" and r["frame"] <= seconds * 23.81:
            best = r["input"]
    return best


def game_row(recs):
    res = next((r for r in recs if r["layer"] == "result"), None)
    if res is None:
        return None
    s6, s10 = state_at(recs, 360), state_at(recs, 600)
    dirs = [r["output"] for r in recs if r["layer"] == "directive" and r["output"].get("source") != "body_default"]
    trig = {}
    for r in recs:
        if r["layer"] == "strategy":
            k = (r.get("trigger") or "?").split(":")[0]
            trig[k] = trig.get(k, 0) + 1
    return dict(win=res["result"] == "win", frames=res["frames"], calls=res["strategy_calls"], cost=res["cost_usd"],
                ff=res["flip_flops"], d6=s6["me"]["units"].get("drone", 0) if s6 else None,
                d10=s10["me"]["units"].get("drone", 0) if s10 else None,
                eng=trig.get("engagement_end", 0),
                p_def=(sum(d.get("stance") == "defensive" for d in dirs) / len(dirs)) if dirs else 0,
                p_never=(sum(d.get("expand_policy") == "never" for d in dirs) / len(dirs)) if dirs else 0,
                p_static=(sum(bool(d.get("static_defense")) for d in dirs) / len(dirs)) if dirs else 0)


def main():
    conds = [a.split("=", 1) for a in sys.argv[1:]]
    print(f"{'cond':12s} {'n':>3} {'wins':>4} {'rate':>6} {'ci95':>14} {'frames':>7} {'calls':>5} {'cost':>5} {'ff':>4} {'d6':>5} {'d10':>5} {'eng':>4} {'def':>4} {'never':>5} {'stat':>4}")
    for label, pat in conds:
        rows = []
        for d in glob.glob(pat):
            for f in glob.glob(d + "/logs/*.jsonl"):
                row = game_row(load(f))
                if row:
                    rows.append(row)
        if not rows:
            print(f"{label:12s} (no games)"); continue
        n = len(rows); w = sum(r["win"] for r in rows); p, lo, hi = wilson(w, n)
        m = lambda k: st.mean([r[k] for r in rows if r[k] is not None]) if any(r[k] is not None for r in rows) else 0
        print(f"{label:12s} {n:3d} {w:4d} {p:6.3f} [{lo:5.2f},{hi:5.2f}]  {m('frames'):7.0f} {m('calls'):5.1f} {m('cost'):5.2f} {m('ff'):4.1f} {m('d6'):5.1f} {m('d10'):5.1f} {m('eng'):4.1f} {m('p_def'):4.2f} {m('p_never'):5.2f} {m('p_static'):4.2f}")


if __name__ == "__main__":
    main()
