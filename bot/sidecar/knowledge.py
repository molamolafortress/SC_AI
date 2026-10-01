"""Loads the fixed knowledge that goes into the cached prompt prefix and feeds the Validator."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Knowledge:
    rules_text: str = ""
    builds: dict = field(default_factory=dict)       # {"openings": {name: {...}}, ...}
    map_knowledge: dict = field(default_factory=dict)  # knowledge/maps/<map>.json

    @classmethod
    def load(cls, knowledge_dir: Path, matchup: str, map_name: str) -> "Knowledge":
        k = cls()
        rules = knowledge_dir / "rules.md"
        if rules.exists():
            k.rules_text = rules.read_text(encoding="utf-8")
        builds = knowledge_dir / "builds" / f"{matchup}.json"
        if builds.exists():
            k.builds = json.loads(builds.read_text(encoding="utf-8"))
        k.map_knowledge = load_map_knowledge(knowledge_dir, map_name)
        return k

    @property
    def opening_names(self) -> set[str]:
        return set(self.builds.get("openings", {}).keys())

    @property
    def wall_names(self) -> set[str]:
        return {"none", *self.map_knowledge.get("walls", {}).keys()}

    @property
    def location_names(self) -> set[str]:
        base = {"main", "natural", "enemy_main", "enemy_natural", "center", "army"}
        return base | set(self.map_knowledge.get("expansions", {}).keys())

    def prefix_text(self) -> str:
        """Stable text for the cached system prompt (never include timestamps here)."""
        parts = [self.rules_text]
        if self.builds:
            parts.append("## Build database\n" + json.dumps(self.builds, ensure_ascii=False, indent=1, sort_keys=True))
        if self.map_knowledge:
            parts.append("## Map knowledge\n" + json.dumps(self.map_knowledge, ensure_ascii=False, indent=1, sort_keys=True))
        return "\n\n".join(p for p in parts if p)


def load_map_knowledge(knowledge_dir: Path, map_name: str) -> dict:
    maps_dir = knowledge_dir / "maps"
    if not maps_dir.exists():
        return {}
    wanted = _slug(map_name)
    for path in maps_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        known = _slug(data.get("map", path.stem))
        if known == wanted or path.stem == wanted or (known and wanted.startswith(known)):
            return data
    return {}


def _slug(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())
