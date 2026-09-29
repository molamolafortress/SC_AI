"""HTTP loopback server the bot body talks to.

POST /state      StateSummary          -> {"directive": IssuedDirective|null, "trigger_pending": bool}
GET  /directive                        -> IssuedDirective|null (latest, always instant)
POST /event      GameEvent             -> ack (out-of-band events between state posts)
POST /game/end   {"result": "win|loss|draw", "frame": n}   -> summary line, closes the game
GET  /health

Run: python -m bot.sidecar.server --config config/sidecar.yaml --llm fake
"""
from __future__ import annotations

import argparse
import threading
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from .config import SidecarConfig
from .knowledge import Knowledge
from .llm import AnthropicBackend, Backend, FakeBackend, RecordedBackend
from .logger import GameLogger
from .plan_ledger import PlanLedger
from .schemas import GameEvent, IssuedDirective, StateSummary
from .state_store import StateStore
from .strategy import StrategyCaller


class GameSession:
    """Everything that lives for one game."""

    def __init__(self, cfg: SidecarConfig, backend: Backend, first: StateSummary):
        self.cfg = cfg
        self.game_id = first.game_id
        self.knowledge = Knowledge.load(cfg.knowledge_dir, first.matchup, first.map)
        self.store = StateStore(cfg)
        self.ledger = PlanLedger(min_hold_frames=cfg.frames(cfg.triggers.min_hold_seconds))
        self.logger = GameLogger(cfg.logs_dir, first.game_id)
        self.strategy = StrategyCaller(cfg, self.knowledge, backend, self.store, self.ledger, self.logger,
                                       lockstep=(cfg.mode == "lockstep"))
        self.logger.log("session", first.frame, game_id=first.game_id, matchup=first.matchup, map=first.map,
                        mode=cfg.mode, has_map_knowledge=bool(self.knowledge.map_knowledge))

    def on_state(self, s: StateSummary) -> IssuedDirective | None:
        self.store.ingest(s)
        self.logger.log("state", s.frame, input=s.model_dump(exclude={"game_id"}))
        self.strategy.on_state()
        return self.strategy.current_directive()

    def end(self, result: str, frame: int) -> dict:
        self.strategy.wait_idle(5.0)
        summary = {
            "game_id": self.game_id, "result": result, "frames": frame,
            "cost_usd": round(self.logger.total_cost_usd, 4),
            "strategy_calls": self.logger.strategy_calls, "flip_flops": self.ledger.flip_flops,
            "validator_rejects": self.logger.validator_rejects, "directives": len(self.ledger.history),
        }
        self.logger.log("result", frame, **summary)
        return summary


class EndRequest(BaseModel):
    result: str
    frame: int = 0


def make_backend(kind: str, cfg: SidecarConfig, recorded_log: str | None = None) -> Backend:
    if kind == "anthropic":
        return AnthropicBackend(model=cfg.models.strategy_model)
    if kind == "recorded":
        return RecordedBackend(Path(recorded_log))
    return FakeBackend()


def create_app(cfg: SidecarConfig, backend: Backend) -> FastAPI:
    app = FastAPI(title="SC_AI sidecar")
    sessions: dict[str, GameSession] = {}
    lock = threading.Lock()

    def session_for(s: StateSummary) -> GameSession:
        with lock:
            if s.game_id not in sessions:
                sessions[s.game_id] = GameSession(cfg, backend, s)
            return sessions[s.game_id]

    @app.get("/health")
    def health():
        return {"ok": True, "mode": cfg.mode, "games": list(sessions)}

    @app.post("/state")
    def post_state(s: StateSummary):
        sess = session_for(s)
        d = sess.on_state(s)
        return {"directive": d.model_dump() if d else None,
                "trigger_pending": sess.strategy._inflight is not None and sess.strategy._inflight.is_alive()}

    @app.get("/directive")
    def get_directive(game_id: str):
        sess = sessions.get(game_id)
        d = sess.strategy.current_directive() if sess else None
        return d.model_dump() if d else None

    @app.post("/event")
    def post_event(game_id: str, ev: GameEvent):
        sess = sessions.get(game_id)
        if sess is None:
            return {"ok": False, "error": "unknown game"}
        sess.store.pending_events.append(ev.type + (f":{ev.what}" if ev.what else ""))
        sess.store.timeline.append(f"f{ev.frame} {ev.type}")
        sess.logger.log("event", ev.frame, input=ev.model_dump())
        return {"ok": True}

    @app.post("/game/end")
    def game_end(game_id: str, req: EndRequest):
        sess = sessions.pop(game_id, None)
        if sess is None:
            return {"ok": False, "error": "unknown game"}
        return {"ok": True, "summary": sess.end(req.result, req.frame)}

    app.state.sessions = sessions
    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--llm", default=None, choices=["anthropic", "fake", "recorded"])
    ap.add_argument("--recorded-log", default=None)
    ap.add_argument("--mode", default=None)
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args()
    overrides = {k: v for k, v in {"llm_backend": args.llm, "mode": args.mode, "port": args.port}.items() if v}
    cfg = SidecarConfig.load(args.config, **overrides)
    app = create_app(cfg, make_backend(cfg.llm_backend, cfg, args.recorded_log))
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
