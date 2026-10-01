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


def _intel(minute: float) -> dict:
    """Intel as the body emits it: scout reaches the enemy main at ~1:30, pool/gas seen, lings at 2:30."""
    intel = {"enemy_build": "Unknown", "enemy_opener": "Unknown", "enemy_transition": "Unknown",
             "flags": [], "mirror": {}, "buildings": {}, "workers_seen_max": 0, "expansions": 1,
             "gas": {"count": 0}, "scout": {"enemy_main_found": minute >= 1.0}, "army": {}}
    if minute >= 1.5:
        intel["scout"].update({"main_scouted_frame": 2143, "main_scouted_time": "1:30", "main_last_seen_frame": 2143})
        intel["workers_seen_max"] = 9
        intel["buildings"]["command_center"] = {"count": 1, "first_seen_frame": 2143, "started_frame": 0, "started_time": "0:00"}
    if minute >= 2.0:
        intel["buildings"]["barracks"] = {"count": 1, "first_seen_frame": 2900, "started_frame": 1700, "started_time": "1:11",
                                          "completes_frame": 3500, "completes_time": "2:27"}
        intel["buildings"]["refinery"] = {"count": 1, "first_seen_frame": 2900, "started_frame": 2500, "started_time": "1:45"}
        intel["gas"] = {"count": 1, "first_seen_frame": 2900, "first_seen_time": "2:01"}
        intel.update({"enemy_build": "RaxFact", "enemy_opener": "1Rax", "enemy_build_state": "likely"})
    if minute >= 2.5:
        intel["army"] = {"first_seen_frame": 3570, "first_seen_time": "2:30", "max_by_type": {"marine": 2}}
    return intel


def test_intel_event_triggers_medium_call_with_brief(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))
    for frame in range(0, int(3.5 * 60 * 23.81), 24):
        s = state(frame, "g_intel")
        s["enemy"]["buildings_seen"] = {}  # isolate: no enemy_building_spotted triggers from the fake stream
        s["intel"] = _intel(frame / 23.81 / 60)
        client.post("/state", json=s)
    triggers = [c[1].split("## 호출 이유\n")[1].split("\n")[0] for c in backend.calls]
    efforts = dict(zip(triggers, (c[2] for c in backend.calls)))
    assert "intel:scout_main" in triggers and "intel:gas" in triggers and "intel:army" in triggers
    assert efforts["intel:scout_main"] == cfg.models.strategy_effort_transition == "medium"
    msg = backend.calls[triggers.index("intel:gas")][1]
    # same-frame intel events ride along in the delta's event line (one call covers the batch)
    assert "intel:build_guess:RaxFact/1Rax/Unknown" in msg
    assert "## 정찰 브리핑 (intel)" in msg
    assert "barracks x1: 시작 1:11" in msg and "기준 1:10-1:20" in msg and "표준" in msg
    assert "본진 도달 1:30" in msg and "enemy_build_guess" in msg
    # the directive carries the free-text intel fields through validator and ledger untouched
    log = [json.loads(l) for l in (tmp_path / "logs" / "g_intel.jsonl").read_text().splitlines()]
    issued = [r for r in log if r["layer"] == "directive"]
    assert issued and issued[-1]["output"]["enemy_build_guess"].startswith("build=RaxFact")
    # intel is kept in the state record (the coach loop reads it from the log)
    states = [r for r in log if r["layer"] == "state"]
    assert states[-1]["input"]["intel"]["buildings"]["barracks"]["started_time"] == "1:11"


def test_knowledge_builds_cover_mcrave_openings():
    from bot.sidecar.config import SidecarConfig
    body_names = {"12hatch_11pool", "overpool", "12pool", "3hatch_muta", "2hatch_muta", "3hatch_hydra", "lurker_contain"}
    for matchup in ("ZvT", "ZvP", "ZvZ"):
        k = Knowledge.load(SidecarConfig().knowledge_dir, matchup, "Fighting Spirit")
        assert body_names <= k.opening_names, matchup
        assert k.reference_timings, matchup
    assert "9pool_speed" in Knowledge.load(SidecarConfig().knowledge_dir, "ZvZ", "Fighting Spirit").opening_names
