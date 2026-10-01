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
    return SidecarConfig.load(None, **{"logs_dir": tmp_path / "logs", "mode": "lockstep", **kw})


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
    # start rule: frame 0 is observe-only (body defaults); the first LLM directive comes after scouting
    assert directives[0]["source"] == "body_default" and directives[0]["observe_only"]
    assert directives[1]["source"] in ("llm", "validator_fix") and not directives[1]["observe_only"]
    assert all(d["wall_natural"] == "none" for d in directives)
    triggers = [c[1].split("## 호출 이유\n")[1].split("\n")[0] for c in backend.calls]
    assert triggers[0] == "intel:scout_main"
    assert "game_start" not in triggers
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
        if d and not d["observe_only"]:
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


def _triggers(backend):
    return [c[1].split("## 호출 이유\n")[1].split("\n")[0] for c in backend.calls]


def _run(client, game_id, minutes, mutate=None, feed_directive=False):
    last = None
    for frame in range(0, int(minutes * 60 * 23.81), 24):
        s = state(frame, game_id, last if feed_directive else None)
        if mutate:
            mutate(s)
        d = client.post("/state", json=s).json()["directive"]
        if d:
            last = d["directive_id"]
    return frame


def test_validator_rejects_removed_placeholder_wall(tmp_path):
    cfg = make_cfg(tmp_path)
    k = Knowledge.load(cfg.knowledge_dir, "ZvP", "Fighting Spirit")
    assert k.wall_names == {"none"}
    v = validate(Directive(opening="12hatch_11pool", wall_natural="partial_2"), k, None)
    assert v.ok and v.directive.wall_natural == "none"
    assert any("partial_2" in f for f in v.fixes)
    data = json.loads((cfg.knowledge_dir / "maps" / "fighting_spirit.json").read_text(encoding="utf-8"))
    assert data["walls"] == {} and data["_source"].startswith("placeholder")
    assert all(md["wall_natural"] == "none" for md in data["matchup_defaults"].values())


def test_start_rule_observe_then_first_call_on_intel(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))
    _run(client, "g_start", 2.5)
    log = [json.loads(l) for l in (tmp_path / "logs" / "g_start.jsonl").read_text().splitlines()]
    issued = [r for r in log if r["layer"] == "directive"]
    assert issued[0]["trigger"] == "game_start_observe" and issued[0]["output"]["source"] == "body_default"
    assert issued[0]["output"]["observe_only"] and issued[0]["output"]["opening"] == "12hatch"
    first = [r for r in log if r["layer"] == "strategy"][0]
    assert first["trigger"] == "intel:scout_main" and first["frame"] >= int(1.5 * 60 * 23.81) - 24
    assert "observe_only (몸체 기본값 유지)" in first["input"]


def test_start_rule_deadline_when_nothing_scouted(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))

    def blind(s):
        s["intel"] = {}
        s["enemy"]["buildings_seen"] = {}
        s["me"]["minerals"] = 100  # no idle_resources trigger
    _run(client, "g_blind", 2.3, mutate=blind)
    calls = [r for r in (json.loads(l) for l in (tmp_path / "logs" / "g_blind.jsonl").read_text().splitlines()) if r["layer"] == "strategy"]
    assert calls and calls[0]["trigger"] == "safety_interval"
    deadline = cfg.frames(cfg.triggers.first_call_deadline_seconds)
    assert deadline <= calls[0]["frame"] < deadline + 24


def test_decide_at_start_restores_frame0_call(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.triggers.decide_at_start = True
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))
    _run(client, "g_old", 0.5)
    assert _triggers(backend)[0] == "game_start"


def test_time_series_rows_capped_and_stable(tmp_path):
    from bot.sidecar.state_store import StateStore
    cfg = make_cfg(tmp_path)
    cfg.triggers.series_max_rows = 5
    store = StateStore(cfg)
    for frame in range(0, int(6 * 60 * 23.81), 24):
        store.ingest(StateSummary.model_validate(state(frame, "g")))
        if frame == 2400:
            rows_at_100s = list(store.series_rows)
    assert len(store.series_rows) == 5  # 12 samples in 6 minutes (0:00..5:30), capped to the newest 5
    assert store.series_rows[-1].startswith(" 5:30 |") and store.series_rows[0].startswith(" 3:30 |")
    assert rows_at_100s[-1].startswith(" 1:30 |")
    text = store.series_text()
    header = text.split("\n")[0]
    assert header.split(" | ")[0].strip() == "time" and "e_army" in header and "event" in header
    # event markers: first enemy building types and engagement outcome land in the interval's row
    full = StateStore(make_cfg(tmp_path))
    for frame in range(0, int(6.5 * 60 * 23.81), 24):
        full.ingest(StateSummary.model_validate(state(frame, "g")))
    rows = full.series_rows
    assert len(rows) == 13 and [r.split(" | ")[0].strip() for r in rows][:3] == ["0:00", "0:30", "1:00"]
    # byte-stable: rows written earlier are exactly the rows of a longer run
    assert rows[:5] == store.series_rows[:0] + [r for r in rows[:5]] and text.split("\n")[1:] == rows[7:12]
    assert any("barracks" in r for r in rows) and any("factory" in r for r in rows)
    assert any("교전 held" in r for r in rows)
    assert rows[0].split(" | ")[-1] == "command_center"


def test_user_message_sections_order_and_feedback(tmp_path):
    cfg = make_cfg(tmp_path)
    backend = FakeBackend()
    client = TestClient(create_app(cfg, backend))
    _run(client, "g_fb", 6.2, feed_directive=True)
    msg = backend.calls[-1][1]
    order = [msg.index(h) for h in ("## 직전 결정과 실행 결과", "## 직전 지시 실행 결과", "## 시계열 (30초 간격)",
                                    "## 직전 호출 이후 변화 (delta)", "## 현재 상태", "## 정찰 브리핑 (intel)")]
    assert order == sorted(order)
    fb = msg.split("## 직전 지시 실행 결과\n")[1].split("\n## ")[0]
    assert "- stance: 적용됨 defensive → defensive" in fb
    assert "- wall_natural: 무시됨 none → none (no wall defined for this map)" in fb
    assert "성큰 요청 1 → 실제 1" in fb and "실제 조성: {'zergling'" in fb and "vs 목표 {'drone': 0." in fb
    assert "드론: " in fb and "지시 이후 +" in fb
    assert "추세를 읽어라" in msg
    # positions in text (audit A)
    cur = msg.split("## 현재 상태\n")[1].split("\n## ")[0]
    assert "아군 기지: 본진: 일꾼 16/16 (가스 3/3), 해처리 1" in cur and "앞마당: 일꾼" in cur
    # the inspected call may fall in a window where the enemy army was not recently seen: check across all calls
    all_cur = "\n".join(c[1].split("## 현재 상태\n")[1].split("\n## ")[0] for c in backend.calls if "## 현재 상태\n" in c[1])
    assert "아군 병력 위치: 앞마당" in all_cur and "적 병력 위치: 적 앞마당 (마지막 목격" in all_cur
    assert "적 기지: 적 본진: 일꾼 최대" in cur and "지역 소유: 아군 ['main', 'natural']" in cur
    brief = msg.split("## 정찰 브리핑 (intel)\n")[1]
    assert "barracks@enemy_main 완성됨, 마지막 목격 2:06" in brief
    fact = [c[1] for c in backend.calls if c[1].split("## 호출 이유\n")[1].startswith("enemy_building_spotted:factory")][0]
    assert "factory@enemy_main 진행 " in fact and "%, 완성 5:32, 마지막 목격" in fact
    # engagement_end detail in the delta/event line and in the timeline
    eng = [c[1] for c in backend.calls if "engagement_end" in c[1].split("## 호출 이유\n")[1]]
    assert eng, "engagement_end must trigger a call"
    assert "engagement_end:natural@앞마당 (결과 held, 아군 손실 zergling 6, 적 손실 marine 4)" in eng[0]
    # the ledger keeps what was requested so the comparison is explicit
    sess = client.app.state.sessions["g_fb"]
    assert sess.ledger.history[-1].requested["unit_mix_target"] == sess.ledger.current.unit_mix_target


def test_engagement_start_discards_inflight_result(tmp_path):
    cfg = make_cfg(tmp_path, mode="headless")
    cfg.triggers.decide_at_start = True
    backend = FakeBackend(latency_ms=400)
    client = TestClient(create_app(cfg, backend))
    r = client.post("/state", json=state(0, "g_eng")).json()
    assert r["directive"] is None and r["trigger_pending"]
    s = state(24, "g_eng")
    s["events"] = [{"type": "engagement_start", "what": "natural", "frame": 24, "detail": {}}]
    client.post("/state", json=s)
    sess = client.app.state.sessions["g_eng"]
    assert "engagement_start:natural" in sess.store.pending_events
    sess.strategy.wait_idle(5)
    log = [json.loads(l) for l in (tmp_path / "logs" / "g_eng.jsonl").read_text().splitlines()]
    assert any(r["layer"] == "strategy" and r.get("outcome") == "discarded_stale" for r in log)
    assert not [r for r in log if r["layer"] == "directive"]
    assert client.get("/directive", params={"game_id": "g_eng"}).json() is None


def test_event_endpoint_renders_engagement_detail(tmp_path):
    cfg = make_cfg(tmp_path)
    client = TestClient(create_app(cfg, FakeBackend()))
    client.post("/state", json=state(0, "g_ev"))
    r = client.post("/event", params={"game_id": "g_ev"}, json={
        "type": "engagement_end", "what": "center", "frame": 500,
        "detail": {"my_losses": {"zergling": 8}, "enemy_losses": {}, "outcome": "lost"}}).json()
    assert r["ok"]
    sess = client.app.state.sessions["g_ev"]
    assert sess.store.pending_events[-1] == "engagement_end:center"
    assert sess.store.timeline[-1] == "f500 engagement_end:center@중앙 (결과 lost, 아군 손실 zergling 8, 적 손실 없음)"
    assert sess.store.trigger(None) == "engagement_end:center"


def test_map_knowledge_from_dump(tmp_path):
    from tools.map_knowledge_from_dump import convert
    dump = {"map": "Dump Map", "regions": {"main": [1, 2]},
            "bases": [{"tile": [8, 10], "minerals": 9, "gas": 1, "isStart": True}, {"tile": [120, 118], "minerals": 9, "gas": 1, "isStart": True},
                      {"tile": [20, 30], "minerals": 7, "gas": 1}, {"tile": [100, 100], "minerals": 7, "gas": 1}],
            "chokes": [{"center": [15, 20], "width": 7}], "natural_defenses": [[3, 3]]}
    out = convert(dump, "x.json")
    assert out["walls"] == {} and out["expansions"]["A"]["pos"] == [20, 30] and out["expansions"]["B"]["nearest_start"] == 1
    assert out["matchup_defaults"]["ZvP"]["wall_natural"] == "none" and out["matchup_defaults"]["ZvT"]["sunken_spots"] == ["nat_defense_1"]
    dump["natural_wall"] = {"buildings": ["hatchery", "evolution_chamber"], "tiles": [[1, 1]], "zergling_tight": False}
    out = convert(dump, "x.json")
    assert list(out["walls"]) == ["bweb_natural"] and out["matchup_defaults"]["ZvP"]["wall_natural"] == "bweb_natural"
    maps = tmp_path / "maps"
    maps.mkdir()
    (maps / "dumpmap.json").write_text(json.dumps(out), encoding="utf-8")
    from bot.sidecar.knowledge import load_map_knowledge
    k = Knowledge(map_knowledge=load_map_knowledge(tmp_path, "Dump Map"))
    assert k.wall_names == {"none", "bweb_natural"} and {"A", "B"} <= k.location_names
