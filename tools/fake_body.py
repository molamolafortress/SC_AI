"""Simulates the bot body: posts a plausible ZvT state stream to the sidecar and prints
the directives it gets back. Used for end-to-end dev without a game.

python -m tools.fake_body --url http://127.0.0.1:8770 --minutes 8
"""
from __future__ import annotations

import argparse
import time

import httpx


def state(frame: int, game_id: str) -> dict:
    minute = frame / 23.81 / 60
    drones = min(12 + int(minute * 4), 40)
    lings = 0 if minute < 2.5 else min(int((minute - 2.5) * 6), 30)
    seen_b = {"command_center": {"count": 1, "first_frame": 0}}
    if minute >= 2.0:
        seen_b["barracks"] = {"count": 1 if minute < 3.0 else 2, "first_frame": 2900}
    if minute >= 4.5:
        seen_b["factory"] = {"count": 1, "first_frame": 6400}
    events = []
    if 5.9 <= minute < 6.0:
        events.append({"type": "engagement_end", "what": "natural", "frame": frame,
                       "detail": {"my_losses": {"zergling": 6}, "enemy_losses": {"marine": 4}}})
    return {
        "game_id": game_id, "frame": frame, "game_time": f"{int(minute)}:{int((minute % 1) * 60):02d}",
        "matchup": "ZvT", "map": "Fighting Spirit",
        "me": {"minerals": 200 + (frame * 7) % 900, "gas": 50 + (frame * 3) % 300, "supply": [drones + lings // 2, 9 + 8 * (1 + int(minute))],
               "larva": 3, "units": {"drone": drones, "zergling": lings, "overlord": 2 + int(minute)},
               "buildings": {"hatchery": 1 if minute < 1.5 else 2, "spawning_pool": 1 if minute >= 1.8 else 0,
                             "extractor": 1 if minute >= 2.2 else 0},
               "tech": {"metabolic_boost": "researching" if 3 < minute < 5 else ("done" if minute >= 5 else "not_started")},
               "army_value": lings * 25, "army_pos": [1400, 1100]},
        "enemy": {"race": "terran", "units_seen": {"marine": {"count": max(0, int((minute - 2) * 3)), "last_frame": frame}},
                  "buildings_seen": seen_b, "expansions": 1 if minute < 6 else 2,
                  "army_value_seen": max(0, int((minute - 2) * 3)) * 50, "army_pos_seen": [2400, 1800], "suspected_cloaked": []},
        "combat_sim": {"my_army_vs_seen": round(max(0.2, (lings * 25) / max(1, int((minute - 2) * 3) * 50 or 1)), 2)},
        "events": events,
        "execution": {"directive_id": None, "goals": []},
        "body_defaults": {"opening": "12hatch", "stance": "defensive"},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8770")
    ap.add_argument("--minutes", type=float, default=8)
    ap.add_argument("--realtime", action="store_true", help="sleep 1s between posts")
    args = ap.parse_args()
    game_id = f"fake_{int(time.time())}"
    last = None
    with httpx.Client(base_url=args.url, timeout=30) as c:
        for frame in range(0, int(args.minutes * 60 * 23.81), 24):
            r = c.post("/state", json=state(frame, game_id)).json()
            d = r["directive"]
            if d and (last is None or d["directive_id"] != last):
                last = d["directive_id"]
                print(f"[f{frame}] {d['directive_id']} {d['source']}: {d['opening']} {d['stance']} "
                      f"{d['army_objective']} mix={d['unit_mix_target']} | {d['change_reason'][:80]}")
            if args.realtime:
                time.sleep(1)
        print(c.post("/game/end", params={"game_id": game_id}, json={"result": "win", "frame": frame}).json())


if __name__ == "__main__":
    main()
