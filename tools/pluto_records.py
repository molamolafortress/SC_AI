"""Tabulate Pluto's own per-game records (bwapi-data/write/pluto_bandit_<opp>.txt, one JSON line per start/end).
Columns: game id, Pluto race, its opening, result (Pluto's view), frames, inference ms, lowest win estimate and when.
python -m tools.pluto_records eval/results/pluto_state_baseline/pluto_bandit_SC_AI.txt [--traj]"""
import json
import sys


def load(path):
    starts, ends = {}, {}
    for line in open(path, encoding="utf-8", errors="replace"):
        if line.startswith('{"t":"start"'):
            r = json.loads(line); starts[r["id"]] = r
        elif line.startswith('{"t":"end"'):
            r = json.loads(line); ends[r["id"]] = r
    return [(starts.get(i), ends[i]) for i in sorted(ends)]


def main():
    path = sys.argv[1]; traj = "--traj" in sys.argv
    rows = load(path)
    print(f"{'id':>3} {'race':>4} {'opening':<16} {'pluto':>5} {'frames':>6} {'mm:ss':>5} {'inf_ms':>6} {'win_min':>7} {'at':>5}")
    for s, e in rows:
        f = e["frames"]; mmss = f"{int(f / 23.81 // 60)}:{int(f / 23.81 % 60):02d}"
        at = f"{int(e['win_min_frame'] / 23.81 // 60)}:{int(e['win_min_frame'] / 23.81 % 60):02d}"
        print(f"{e['id']:>3} {(s or {}).get('own_race', '?'):>4} {(s or {}).get('bo', '?'):<16} {e['result']:>5} {f:>6} {mmss:>5} {e['infer_avg_ms']:>6.0f} {e['win_min']:>7.2f} {at:>5}")
        if traj:
            print("     traj:", " ".join(f"{x:+.2f}" for x in e["win_traj"]))
    wins = sum(e["result"] == "win" for _, e in rows)
    print(f"Pluto {wins}-{len(rows) - wins}; games where Pluto's estimate fell below -0.3: "
          f"{sum(e['win_min'] < -0.3 for _, e in rows)}")


if __name__ == "__main__":
    main()
