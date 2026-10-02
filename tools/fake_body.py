"""Simulates the bot body: posts a plausible ZvT state stream to the sidecar and prints
the directives it gets back. Used for end-to-end dev without a game.

python -m tools.fake_body --url http://127.0.0.1:8770 --minutes 8

The stream carries every field of the body contract (regions, bases, production, intel positions,
execution feedback, engagement events) so the sidecar's prompt sections are exercised end to end.
"""
from __future__ import annotations

import argparse
import time

import httpx

REGIONS = {
    "main": {"tile": [10, 12], "owner": "me"}, "natural": {"tile": [20, 30], "owner": "me"},
    "third": {"tile": [40, 36], "owner": "none"}, "fourth": {"tile": [12, 60], "owner": "none"},
    "enemy_main": {"tile": [116, 112], "owner": "enemy"}, "enemy_natural": {"tile": [106, 94], "owner": "enemy"},
    "enemy_third": {"tile": [86, 88], "owner": "none"}, "center": {"tile": [64, 64], "owner": "none"},
    "path_mid": {"tile": [50, 52], "owner": "none"},
}


def _tm(minute: float) -> str:
    return f"{int(minute)}:{int((minute % 1) * 60):02d}"


def state(frame: int, game_id: str, directive_id: str | None = None) -> dict:
    minute = frame / 23.81 / 60
    drones = min(12 + int(minute * 4), 40)
    lings = 0 if minute < 2.5 else min(int((minute - 2.5) * 6), 30)
    marines = max(0, int((minute - 2) * 3))
    seen_b = {"command_center": {"count": 1, "first_frame": 0}}
    if minute >= 2.0:
        seen_b["barracks"] = {"count": 1 if minute < 3.0 else 2, "first_frame": 2900}
    if minute >= 4.5:
        seen_b["factory"] = {"count": 1, "first_frame": 6400}
    events = []
    if 5.7 <= minute < 5.8:
        events.append({"type": "engagement_start", "what": "natural", "frame": frame, "detail": {}})
    if 5.9 <= minute < 6.0:
        events.append({"type": "engagement_end", "what": "natural", "frame": frame,
                       "detail": {"my_losses": {"zergling": 6}, "enemy_losses": {"marine": 4}, "outcome": "held"}})
    regions = {k: dict(v) for k, v in REGIONS.items()}
    if minute >= 1.5:
        regions["natural"]["owner"] = "me"
    else:
        regions["natural"]["owner"] = "none"
    if minute >= 6.0:
        regions["enemy_natural"]["owner"] = "enemy"
    else:
        regions["enemy_natural"]["owner"] = "none"
    main_workers = min(drones, 16)
    nat_workers = max(0, drones - 16 - (3 if minute >= 2.2 else 0))
    bases = [{"name": "main", "workers_minerals": main_workers, "workers_gas": 3 if minute >= 2.2 else 0, "mineral_patches": 8,
              "gas_geysers": 1, "saturation": round(main_workers / 16, 2), "hatcheries": 1}]
    if minute >= 1.5:
        bases.append({"name": "natural", "workers_minerals": nat_workers, "workers_gas": 0, "mineral_patches": 8, "gas_geysers": 1,
                      "saturation": round(nat_workers / 16, 2), "hatcheries": 1})
    intel_buildings = {"command_center": {"count": 1, "first_seen_frame": 2143, "started_frame": 0, "started_time": "0:00",
                                          "completes_frame": 0, "completes_time": "0:00",
                                          "positions": [{"region": "enemy_main", "tile": [116, 112], "progress": 1.0,
                                                         "completes_time": "0:00", "last_seen_time": _tm(min(minute, 1.5))}]}} if minute >= 1.5 else {}
    if minute >= 2.0:
        intel_buildings["barracks"] = {"count": 1 if minute < 3.0 else 2, "first_seen_frame": 2900, "started_frame": 1700,
                                       "started_time": "1:11", "completes_frame": 3500, "completes_time": "2:27",
                                       "positions": [{"region": "enemy_main", "tile": [118, 108], "progress": min(1.0, round((frame - 1700) / 1800, 2)),
                                                      "completes_time": "2:27", "last_seen_time": _tm(min(minute, 2.1))}]}
    if minute >= 4.5:
        intel_buildings["factory"] = {"count": 1, "first_seen_frame": 6400, "started_frame": 6000, "started_time": "4:12",
                                      "completes_frame": 7900, "completes_time": "5:32",
                                      "positions": [{"region": "enemy_main", "tile": [112, 114], "progress": min(1.0, round((frame - 6000) / 1900, 2)),
                                                     "completes_time": "5:32", "last_seen_time": _tm(min(minute, 4.6))}]}
    enemy_bases = [{"region": "enemy_main", "workers_seen_max": min(9 + int(minute * 3), 24), "last_seen_time": _tm(min(minute, 2.1)), "hatcheries": 1}] if minute >= 1.5 else []
    if minute >= 6.0:
        enemy_bases.append({"region": "enemy_natural", "workers_seen_max": 4, "last_seen_time": _tm(minute), "hatcheries": 1})
    intel = {
        "enemy_build": "RaxFact" if minute >= 2.0 else "Unknown", "enemy_opener": "1Rax" if minute >= 2.0 else "Unknown",
        "enemy_transition": "Unknown", "enemy_build_state": "likely" if minute >= 2.0 else "unknown",
        "buildings": intel_buildings, "workers_seen_max": min(9 + int(minute * 3), 24) if minute >= 1.5 else 0,
        "gas": {"count": 1, "first_seen_frame": 2900, "first_seen_time": "2:01"} if minute >= 2.0 else {"count": 0},
        "expansions": 2 if minute >= 6.0 else 1,
        "scout": {"enemy_main_found": minute >= 1.0, "main_scouted_frame": 2143 if minute >= 1.5 else -1, "main_scouted_time": "1:30",
                  "main_last_seen_frame": 2143 if minute >= 1.5 else -1},
        "army": {"first_seen_frame": 3570, "first_seen_time": "2:30", "max_by_type": {"marine": marines}} if minute >= 2.5 else {},
        "enemy_bases": enemy_bases,
    }
    sunken_built = 1 if minute >= 4.0 else 0
    execution = {"directive_id": directive_id, "goals": [],
                 "overrides": ([{"field": "stance", "applied": True, "before": "defensive", "after": "defensive", "note": ""},
                                {"field": "unit_mix_target", "applied": True, "before": {"drone": 0.7, "zergling": 0.3},
                                 "after": {"drone": 0.65, "zergling": 0.35}, "note": "composition weights set"},
                                {"field": "wall_natural", "applied": False, "before": "none", "after": "none", "note": "no wall defined for this map"}]
                               if directive_id else []),
                 "results": {"sunken": sunken_built, "spore": 0, "army_actual": {"zergling": lings} if lings else {},
                             "drones": drones, "drone_delta_since_directive": min(drones - 12, 8)}}
    return {
        "game_id": game_id, "frame": frame, "game_time": _tm(minute),
        "matchup": "ZvT", "map": "Fighting Spirit",
        "regions": regions,
        "me": {"minerals": 200 + (frame * 7) % 900, "gas": 50 + (frame * 3) % 300, "supply": [drones + lings // 2, 9 + 8 * (1 + int(minute))],
               "larva": 3, "units": {"drone": drones, "zergling": lings, "overlord": 2 + int(minute)},
               "buildings": {"hatchery": 1 if minute < 1.5 else 2, "spawning_pool": 1 if minute >= 1.8 else 0,
                             "extractor": 1 if minute >= 2.2 else 0, "sunken_colony": sunken_built},
               "tech": {"metabolic_boost": "researching" if 3 < minute < 5 else ("done" if minute >= 5 else "not_started")},
               "army_value": lings * 25, "army_pos": [1400, 1100],
               "bases": bases, "army_region": "natural" if minute >= 2.5 else "main",
               "production": {"in_progress": {"drone": 2, "zergling": 2 if minute >= 2.5 else 0}, "larva": 3}},
        "enemy": {"race": "terran", "units_seen": {"marine": {"count": marines, "last_frame": frame}},
                  "buildings_seen": seen_b, "expansions": 1 if minute < 6 else 2,
                  "army_value_seen": marines * 50, "army_pos_seen": [2400, 1800], "suspected_cloaked": [],
                  "army_region_seen": ("path_mid" if 5.5 <= minute < 5.9 else "enemy_natural") if minute >= 2.5 else "",
                  "army_last_seen_time": _tm(minute) if minute >= 2.5 else ""},
        "combat_sim": {"my_army_vs_seen": round(max(0.2, (lings * 25) / max(1, marines * 50 or 1)), 2)},
        "events": events,
        "execution": execution,
        "intel": intel,
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
            r = c.post("/state", json=state(frame, game_id, last)).json()
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
