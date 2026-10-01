"""Convert a body map dump (McRave analysis mode: BWEM bases + BWEB wall/defense tiles) into knowledge/maps/<slug>.json.

python -m tools.map_knowledge_from_dump logs/map_dumps/fighting_spirit.json [--out knowledge/maps/fighting_spirit.json]

Dump format (written by the body):
  {"map": "Fighting Spirit",
   "regions": {"main": [x, y], ...}                       # optional, named regions for one start position
   "bases": [{"tile": [x, y], "minerals": 9, "gas": 1, "isStart": true}, ...],
   "chokes": [{"center": [x, y], "width": 7}, ...],
   "natural_wall": {"buildings": ["hatchery", "evolution_chamber", "creep_colony"], "tiles": [[x, y], ...], "zergling_tight": false},
   "natural_defenses": [[x, y], ...]}

Output: real expansion positions (named A, B, C... by nearest start and distance from it), chokes, the natural wall
(named `bweb_natural`) ONLY if the dump has one, and defense positions the sunken_spots names refer to.
Map files are adopted only after human review (CLAUDE.md), so the result is written with `_source` set to the dump path
and `_reviewed: false`.
"""
from __future__ import annotations

import argparse
import json
import math
import string
from pathlib import Path

from bot.sidecar.config import REPO_ROOT
from bot.sidecar.knowledge import _slug


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def convert(dump: dict, source: str = "") -> dict:
    bases = dump.get("bases", [])
    starts = [b for b in bases if b.get("isStart")]
    others = [b for b in bases if not b.get("isStart")]
    start_tiles = [list(b["tile"]) for b in starts]
    expansions: dict[str, dict] = {}
    ranked = []
    for b in others:
        if start_tiles:
            idx, d = min(((i, _dist(b["tile"], st)) for i, st in enumerate(start_tiles)), key=lambda t: t[1])
        else:
            idx, d = -1, 0.0
        ranked.append((idx, d, b))
    ranked.sort(key=lambda t: (t[0], t[1]))
    names = list(string.ascii_uppercase) + [f"{a}{b}" for a in string.ascii_uppercase for b in string.ascii_uppercase]
    for name, (idx, d, b) in zip(names, ranked):
        expansions[name] = {"pos": list(b["tile"]), "minerals": int(b.get("minerals", 0)), "gas": int(b.get("gas", 0)),
                            "nearest_start": idx, "distance_from_start": round(d, 1)}
    out: dict = {
        "map": dump.get("map", "unknown"),
        "_source": source or "body map dump",
        "_reviewed": False,
        "starts": start_tiles,
        "expansions": expansions,
        "chokes": [{"center": list(c["center"]), "width": c.get("width")} for c in dump.get("chokes", [])],
        "walls": {},
        "defense_positions": {},
    }
    if isinstance(dump.get("regions"), dict) and dump["regions"]:
        out["regions"] = {k: list(v) for k, v in dump["regions"].items()}
    wall = dump.get("natural_wall") or {}
    if wall.get("buildings") and wall.get("tiles"):
        out["walls"]["bweb_natural"] = {
            "choke": "natural_main", "buildings": list(wall["buildings"]), "tiles": [list(t) for t in wall["tiles"]],
            "tight": {"zergling": bool(wall.get("zergling_tight", False))},
        }
    for i, t in enumerate(dump.get("natural_defenses", []) or [], start=1):
        out["defense_positions"][f"nat_defense_{i}"] = list(t)
    spots = list(out["defense_positions"].keys())[:2]
    wall_name = "bweb_natural" if out["walls"] else "none"
    third = next(iter(expansions), "")
    out["matchup_defaults"] = {
        "ZvT": {"wall_natural": "none", "third": third, "sunken_spots": spots},
        "ZvP": {"wall_natural": wall_name, "third": third, "sunken_spots": spots},
        "ZvZ": {"wall_natural": "none", "third": third, "sunken_spots": spots[:1]},
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--out", default=None, help="default knowledge/maps/<slug>.json")
    args = ap.parse_args()
    dump = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    out = convert(dump, source=str(args.dump))
    path = Path(args.out) if args.out else REPO_ROOT / "knowledge" / "maps" / f"{_slug(out['map'])}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(out['expansions'])} expansions, walls={list(out['walls'])}, "
          f"defense_positions={len(out['defense_positions'])}); review before committing")


if __name__ == "__main__":
    main()
