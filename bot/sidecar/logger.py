"""JSONL game log: one line per event across layers (design_v0.5.md 4.3)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class GameLogger:
    def __init__(self, logs_dir: Path, game_id: str):
        logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = logs_dir / f"{_safe(game_id)}.jsonl"
        self._lock = threading.Lock()
        self.total_cost_usd = 0.0
        self.strategy_calls = 0
        self.validator_rejects = 0

    def log(self, layer: str, frame: int, **fields) -> None:
        rec = {"ts": time.time(), "frame": frame, "layer": layer, **fields}
        line = json.dumps(rec, ensure_ascii=False, default=str)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def add_cost(self, usd: float) -> None:
        with self._lock:
            self.total_cost_usd += usd


def _safe(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)
