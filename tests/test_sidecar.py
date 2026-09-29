import json

from fastapi.testclient import TestClient

from bot.sidecar.config import SidecarConfig
from bot.sidecar.knowledge import Knowledge
from bot.sidecar.llm import FakeBackend
from bot.sidecar.schemas import Directive, StateSummary
from bot.sidecar.server import create_app
from bot.sidecar.validator import validate
from tools.fake_body import state


def make_cfg(tmp_path, **kw):
    return SidecarConfig.load(None, logs_dir=tmp_path / "logs", mode="lockstep", **kw)


def test_validator_fixes_unknown_names_and_normalizes(tmp_path):
    cfg = make_cfg(tmp_path)
    k = Knowledge.load(cfg.knowledge_dir, "ZvT", "Fighting Spirit")
    d = Directive(opening="12hatch_11pool", wall_natural="full_wall_xyz", unit_mix_target={"drone": 3, "zergling": 1, "marine": 5},
                  army_objective={"type": "attack", "location": "somewhere"}, static_defense={"sunken": 1, "bunker": 2},
                  confidence=1.7, review_after_seconds=3)
    v = validate(d, k, None)
    assert v.ok
    assert v.directive.wall_natural == "none"
    assert v.directive.army_objective.location == "natural"
    assert abs(sum(v.directive.unit_mix_target.values()) - 1.0) < 0.01 and "marine" not in v.directive.unit_mix_target
    assert v.directive.static_defense == {"sunken": 1}
    assert v.directive.confidence == 1.0 and v.directive.review_after_seconds == 15


def test_validator_rejects_unknown_opening(tmp_path):
    cfg = make_cfg(tmp_path)
    k = Knowledge.load(cfg.knowledge_dir, "ZvT", "Fighting Spirit")
    v = validate(Directive(opening="4pool_cheese"), k, None)
    assert not v.ok and "unknown opening" in v.rejected[0]


def test_end_to_end_lockstep_with_fake_llm(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))
    game_id = "test_game"
    directives = []
    for frame in range(0, int(8 * 60 * 23.81), 24):
        r = client.post("/state", json=state(frame, game_id)).json()
        d = r["directive"]
        if d and (not directives or d["directive_id"] != directives[-1]["directive_id"]):
            directives.append(d)
    end = client.post("/game/end", params={"game_id": game_id}, json={"result": "win", "frame": frame}).json()
    assert end["ok"]
    summary = end["summary"]
    # game_start + barracks spotted + 2nd barracks count change + factory + engagement + safety intervals
    assert summary["strategy_calls"] >= 6
    assert summary["strategy_calls"] <= 25, "event-driven triggers must not call every second"
    assert directives[0]["source"] in ("llm", "validator_fix")
    assert all(d["wall_natural"] in ("none", "partial_2") for d in directives)
    triggers = [c[1].split("## 호출 이유\n")[1].split("\n")[0] for c in backend.calls]
    assert triggers[0] == "game_start"
    assert any(t.startswith("enemy_building_spotted:barracks") for t in triggers)
    assert any(t.startswith("enemy_building_spotted:factory") for t in triggers)
    # the cached prefix must be byte-identical across calls
    assert len({c[0] for c in backend.calls}) == 1
    log = (tmp_path / "logs" / f"{game_id}.jsonl").read_text().splitlines()
    layers = {json.loads(l)["layer"] for l in log}
    assert {"session", "state", "strategy", "directive", "result"} <= layers


def test_keep_current_plan_holds_previous_directive(tmp_path):
    cfg = make_cfg(tmp_path)
    first = Directive(opening="9pool_speed", stance="aggressive", change_reason="first", unit_mix_target={"zergling": 1.0})
    hold = Directive(keep_current_plan=True, opening="", change_reason="nothing new")
    backend = FakeBackend(script=[first, hold, hold, hold, hold, hold, hold, hold, hold, hold])
    client = TestClient(create_app(cfg, backend))
    ids = set()
    for frame in range(0, int(4 * 60 * 23.81), 24):
        d = client.post("/state", json=state(frame, "g2")).json()["directive"]
        if d:
            ids.add((d["directive_id"], d["opening"], d["stance"], d["source"]))
    openings = {o for _, o, _, _ in ids}
    assert openings == {"9pool_speed"}
    assert any(src == "ledger_hold" for _, _, _, src in ids)


def test_state_summary_roundtrip():
    s = StateSummary.model_validate(state(2400, "g"))
    assert s.me.units["drone"] > 0 and s.enemy.race == "terran"
