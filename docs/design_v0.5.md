# SC_AI 설계서 v0.5 (구현 설계 + 환경 세팅)

> 작성일: 2026-09-29
> 근거: `docs/design_review_2026-09.md` (리뷰·근거·선행 연구는 그쪽을 본다. 이 문서는 "그래서 무엇을 어떻게 만드는가"만 적는다)
> 상태: 초안. 1장의 가정이 바뀌면 2장 이하를 다시 본다

---

## 1. 목표와 가정 (결정 사항)

리뷰 보고서 7장의 열린 질문에 아래처럼 답을 두고 설계했다. 다르게 정하면 알려달라.

| 질문 | 이 설계의 가정 | 영향 |
|---|---|---|
| 목표 | 1차: 오픈소스 봇 상대 승률(측정 가능). 2차: 사람 상대 실시간 플레이. 대회 출전은 비목표 | 외부 API 호출 허용, 프레임 시간 제한은 실시간 모드에서만 |
| 종족 | 저그 고정 | 맵 지식·빌드 DB·스크립트는 저그 기준 |
| 구현 방식 | 리뷰 5장의 B: **McRave(C++, MIT)를 몸체로**, Python 사이드카가 두뇌. McRave 훅이 어려우면 UAlbertaBot으로 대체 | 실행 계층을 빌려 쓰고 판단층에 집중 |
| 엔진 | Linux/OpenBW 헤드리스 = 개발·평가·코치 루프. Windows 1.16.1 + BWAPI 4.4.0 = 실제 게임 검증·사람 상대 | 두 레인, 같은 봇 바이너리 소스 |
| 모델 | Strategy: Opus 5.5. Tactical Advisor: Haiku 4.5. Coach·맵 지식 생성: Opus 5.5(Batch). | 리뷰 2장 비용표 기준 게임당 1~2달러 |
| 인간 조건(APM 제한) | 기본 off. 설정으로 on 가능, 결과에 항상 기록 | Command Queue 프로파일 |

---

## 2. 시스템 구성도

```
┌─────────────────────────── OFFLINE ────────────────────────────────────────┐
│ knowledge/                 coach/                       eval/               │
│  builds/*.json  ◄──────── Coach Agent (Opus 5.5 Batch) ◄── 게임 로그 JSONL   │
│  maps/*.json    ◄──────── Map Knowledge Gen (Opus 5.5)   │  리플레이 .rep     │
│  rules.md                     ▲ BWEM/BWEB 분석 덤프       │  metrics.json     │
│                               │                          ▼                  │
│                         run_eval (N게임, 상대 풀, 시드)  ── 회귀 게이트        │
└───────────────────────────────────────────────────────────────────────────┘
                                   ▲ 로그
┌─────────────────────────── REALTIME (게임 1판) ───────────────────────────┐
│  OpenBW / 1.16.1 ─ BWAPI ─┐                                                │
│                           ▼                                                │
│   McRave 몸체 (C++ AI 모듈)                                                 │
│   ├ InformationManager (= State Manager의 Tracker/Timeline)                 │
│   ├ BuildOrder/Strategy  ◄── [훅1] 외부 지시가 있으면 오프닝·조성·자세 우선     │
│   ├ Production, Placement(BWEB), Squads, Scouting, Micro (그대로)            │
│   ├ CommandQueue/APM 프로파일 [추가]                                          │
│   └ SidecarClient [추가]: 매 24프레임 상태 요약 POST, 최신 지시 수신 (비동기)   │
│                           │ HTTP loopback 127.0.0.1:8770                    │
│                           ▼                                                 │
│   Python 사이드카 (bot/sidecar)                                              │
│   ├ StateStore      : 상태 요약 누적, delta 계산, 이벤트 감지                  │
│   ├ Summarizer      : LLM 입력 3단(고정 지식 / 게임 요약 / delta) 생성          │
│   ├ PlanLedger      : 현재 계획, 결정 사유, 목표 상태, 변경 이력                │
│   ├ StrategyCaller  : 트리거 → Opus 5.5 호출(비동기, structured output)        │
│   ├ Validator       : 테크트리·자원·맵 지식 대조, 위반 시 수정/폐기             │
│   ├ AdvisorCaller   : (Phase 5) 교전/후퇴 질의 → Haiku 4.5                    │
│   └ Logger          : 레이어별 I/O, 지연, 비용, 프레임 → JSONL                 │
└───────────────────────────────────────────────────────────────────────────┘
```

원칙 세 가지:
1. **몸체는 사이드카 없이도 완주한다.** 사이드카가 죽거나 늦으면 McRave 기본 전략으로 계속 플레이한다.
2. **LLM은 좌표·유닛 ID를 내지 않는다.** 정책 수준 지시만 내고, 기하와 실행은 몸체가 한다.
3. **모든 결정은 로그로 남고, 모든 변경은 평가 하네스를 통과해야 채택된다.**

---

## 3. 구성요소 상세

### 3.1 몸체: McRave 훅 3개

| 훅 | 위치(개념) | 동작 |
|---|---|---|
| 훅1 전략 주입 | 오프닝 선택·전환, 유닛 조성 결정, 공격/수비 자세를 정하는 함수 | 사이드카의 `Directive`가 있고 유효하면 그 값을 쓰고, 없으면 McRave 원래 로직 |
| 훅2 상태 송출 | `onFrame` 매 24프레임(1초) + 이벤트(`onUnitDiscover`, `onUnitDestroy` 중 적 건물, 교전 시작/종료) | `StateSummary` JSON을 백그라운드 스레드로 POST. 메인 스레드는 절대 기다리지 않는다 |
| 훅3 명령 계측 | 명령을 BWAPI에 내는 단일 지점 | 명령 수 계측, APM 프로파일이 켜져 있으면 토큰 버킷으로 제한, 로그 |

McRave를 고른 이유: C++/MIT, 저그가 강하고, 2026년까지 유지되며, OpenBW 포트 사례(lukecameron/starcraft-ai)가 있다. 리스크: 코드가 크다(114개 번역 단위). 훅1의 정확한 위치는 Phase 0에서 코드를 읽고 확정한다. 2주 안에 훅1이 안 되면 UAlbertaBot(구조가 단순, `StrategyManager`/`BuildOrderQueue`가 분리)으로 바꾼다.

### 3.2 사이드카 (Python 3.12)

| 모듈 | 입력 → 출력 | 비고 |
|---|---|---|
| `server.py` | HTTP: `POST /state`, `GET /directive`, `POST /event` | FastAPI + uvicorn. 응답은 항상 즉시(저장된 최신 지시) |
| `state_store.py` | StateSummary 스트림 → 누적 상태, delta, 이벤트 큐 | 적 건물 최초 발견 프레임, 마지막 위치, 교전 기록 |
| `summarizer.py` | 누적 상태 → LLM 입력 텍스트 3단 | 고정 지식은 파일에서, 게임 요약은 300토큰 이내, delta는 직전 호출 이후만 |
| `plan_ledger.py` | 결정 이력 | `current_plan`, `decided_at_frame`, `reason`, `goals[]`, `min_hold_seconds` |
| `strategy.py` | 트리거 → Directive | 4장 스키마, 5장 호출 사양. 한 번에 하나만 in-flight |
| `validator.py` | Directive → 승인/수정/폐기 | 테크트리(BWAPI 요구 조건 표), 자원, 맵 지식에 있는 확장/벽 이름만 허용 |
| `advisor.py` | 교전 질의 → 판단 | Phase 5. 기본 off |
| `logger.py` | 전부 → `logs/games/<id>.jsonl` | 레이어, 프레임, 입력, 출력, 지연 ms, usage 토큰, 비용 |

### 3.3 맵 지식 (offline, `knowledge/maps/<map>.json`)

리뷰에서 논의한 "건물 위치가 중요하다"의 해법이다. 실시간 LLM이 좌표를 정하는 대신, 맵별로 한 번 계산·판단해 파일로 둔다.

파이프라인:
1. `tools/map_dump.py`: 몸체를 분석 모드로 한 번 실행해 BWEM/BWEB 결과를 덤프한다. 리전 그래프, 초크 폭·위치, 확장 위치와 자원량, 본진·앞마당·3번째 거리, 각 초크에 대해 BWEB이 찾은 벽 후보(건물 조합, 타일, 저글링 틈 여부), 언덕 여부.
2. `coach/map_knowledge.py`: 덤프 + 매치업 규칙을 Opus 5.5에 주고 판단을 받는다. "앞마당 초크는 벽 후보 2번으로 막을 가치가 있다(폭 좁고 본진 램프 뒤)", "3번째는 B 위치 우선(앞마당에서 가깝고 초크 하나)", "성큰 우선 위치는 앞마당 미네랄 라인 앞", "이 맵은 드랍 취약 지점 X". 출력은 아래 스키마로 structured output.
3. 사람이 검토하고 커밋한다. 실전에서는 Validator가 이 파일에 있는 이름만 허용하고, 몸체는 이름을 실제 타일로 푼다.

```json
{
  "map": "Fighting Spirit",
  "matchup_defaults": {
    "ZvT": {"wall_natural": "none", "third": "B", "sunken_spots": ["nat_mineral_front"]},
    "ZvP": {"wall_natural": "partial_2", "third": "B", "sunken_spots": ["nat_choke_inner"]}
  },
  "walls": {"partial_2": {"choke": "natural_main", "buildings": ["hatchery", "evolution_chamber", "creep_colony"], "tight": {"zergling": false, "zealot": true}}},
  "expansions": {"A": {"pos": [0,0], "distance_from_nat": 0}, "B": {"pos": [0,0], "distance_from_nat": 0}},
  "notes": ["앞마당 뒷길 드랍 자주 옴. 3번째 확장 후 오버로드 1기 상주"]
}
```

BWEB이 벽을 못 찾는 초크는 `walls`에 안 들어가고, Strategy는 그 맵에서 `wall_natural`을 지시할 수 없다. 이렇게 "안 막아지는 곳"이 자연스럽게 걸러진다.

---

## 4. 인터페이스

### 4.1 몸체 → 사이드카: `StateSummary` (매 1초 + 이벤트)

```json
{
  "game_id": "2026-09-29T10:00:00_fs_ZvT_ab12",
  "frame": 5400, "game_time": "3:45", "matchup": "ZvT", "map": "Fighting Spirit",
  "me": {"minerals": 450, "gas": 88, "supply": [26, 34], "larva": 5,
         "units": {"drone": 18, "zergling": 8, "overlord": 3},
         "buildings": {"hatchery": 2, "spawning_pool": 1, "extractor": 1},
         "tech": {"metabolic_boost": "researching"}, "army_value": 400,
         "army_pos": [1400, 1100]},
  "enemy": {"race": "terran",
            "units_seen": {"marine": {"count": 5, "last_frame": 5200}},
            "buildings_seen": {"barracks": {"count": 2, "first_frame": 2400}},
            "expansions": 1, "army_value_seen": 300, "army_pos_seen": [2400, 1800],
            "suspected_cloaked": []},
  "combat_sim": {"my_army_vs_seen": 1.3},
  "events": [{"type": "enemy_building_spotted", "what": "barracks", "frame": 2900}],
  "execution": {"directive_id": "d-0007", "goals": [{"goal": "expand_natural", "status": "done", "frame": 4200}]},
  "body_defaults": {"opening": "12hatch", "stance": "defensive"}
}
```

### 4.2 사이드카 → 몸체: `Directive` (Strategy 출력, Validator 통과본)

```json
{
  "directive_id": "d-0008", "issued_frame": 5400, "expires_frame": 6480,
  "keep_current_plan": false,
  "change_reason": "적 2배럭 노가스 확인. 5:30 마린 푸시 예상. 스피드링으로 수비 후 3해처리",
  "opening": "12hatch_11pool",
  "unit_mix_target": {"drone": 0.55, "zergling": 0.35, "hydralisk": 0.10},
  "tech_priority": ["metabolic_boost", "lair"],
  "stance": "defensive",
  "expand_policy": "allow_when_safe",
  "army_objective": {"type": "defend", "location": "natural"},
  "wall_natural": "none",
  "static_defense": {"sunken": 1, "spore": 0},
  "scout_policy": "overlord_on_path",
  "confidence": 0.7,
  "review_after_seconds": 45
}
```

몸체 쪽 해석 규칙: 필드가 없거나 `expires_frame`이 지났으면 McRave 기본값. `army_objective.location`과 `wall_natural`은 맵 지식의 이름만 온다.

### 4.3 로그 (`logs/games/<game_id>.jsonl`, 한 줄 = 한 사건)

`{"frame", "layer": "state|strategy|validator|advisor|command|result", "input", "output", "latency_ms", "usage": {"input_tokens","cache_read_input_tokens","output_tokens"}, "cost_usd"}`

게임 종료 시 `result` 한 줄: 승패, 프레임 수, 상대, 맵, 시드, 총 비용, Strategy 호출 수, flip-flop 수, Validator 거부 수, APM 프로파일.

---

## 5. LLM 호출 사양

### 5.1 Strategy (Opus 5.5)

트리거(이 중 하나면 호출, 한 번에 하나만 진행 중):
- 적 건물/테크 최초 발견, 정찰 유닛 귀환 또는 사망, 대규모 교전 종료(양측 손실 합 200 자원 이상), 유휴 자원(미네랄 800 이상 10초), 목표 완료/실패, `review_after_seconds` 경과, 마지막 호출 후 30초(안전 주기).

요청 구성(캐시 순서 고정):
1. `system[0]` (cache_control): 역할·출력 규칙 + `knowledge/rules.md`(저그 테크트리·타이밍 요약) + `knowledge/builds/ZvX.json` + 해당 맵의 `knowledge/maps/<map>.json`. 약 6~10K 토큰, 게임 내내 불변.
2. `messages`: 게임 누적 요약(Summarizer, 300토큰 이내) → 직전 Directive와 실행 결과 → 직전 호출 이후 delta → "지금 결정하라".

```python
from pydantic import BaseModel
import anthropic

class Directive(BaseModel):
    keep_current_plan: bool
    change_reason: str
    opening: str
    unit_mix_target: dict[str, float]
    tech_priority: list[str]
    stance: str            # defensive | neutral | aggressive | all_in
    expand_policy: str     # never | allow_when_safe | greedy
    army_objective: dict   # {"type": ..., "location": <맵 지식 이름>}
    wall_natural: str      # none | <맵 지식 벽 이름>
    static_defense: dict[str, int]
    scout_policy: str
    confidence: float
    review_after_seconds: int

client = anthropic.Anthropic()

def call_strategy(fixed_prefix: str, game_summary: str, last: str, delta: str, effort: str) -> Directive:
    r = client.messages.parse(
        model="claude-opus-5-5",
        max_tokens=4000,
        system=[{"type": "text", "text": fixed_prefix, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"{game_summary}\n\n{last}\n\n{delta}\n\n지금 결정하라."}],
        output_config={"effort": effort},   # 정기 점검 low, 빌드 전환 트리거 medium~high
        output_format=Directive,
    )
    return r.parsed_output
```

- thinking은 Opus 5.5에서 항상 켜져 있으므로 파라미터를 보내지 않는다. 깊이는 `effort`로만 조절한다.
- 응답을 SDK 예외별로 나눠 처리한다(429·5xx는 재시도, 400은 로그 후 폐기). 응답이 없으면 PlanLedger의 현재 계획 유지.
- 비동기: 호출은 스레드에서, 결과는 도착 즉시 Validator → `/directive`에 반영. 호출 시작 후 대규모 교전이 시작됐으면 결과를 폐기하고 재호출.
- 게임당 비용 상한(기본 3달러) 초과 시 Strategy 호출 중단, 몸체 기본 전략으로.

### 5.2 Tactical Advisor (Haiku 4.5, Phase 5)

- 트리거: CombatSim 비율이 0.8~1.25 사이인 교전 직전, 후퇴 중 재교전 판단, 공격 목표 도착 시.
- 입력 800토큰 이내(부대 구성, 위치, 지형 한 줄, 현재 자세). 출력: `{"engage": bool, "fallback_to": <이름>, "reason"}`. thinking 없음, `max_tokens` 200.
- 응답 지연이 1초를 넘으면 무시하고 규칙 결과 사용.

### 5.3 Coach (Opus 5.5, Batch)

- 입력: 게임 로그 JSONL 전체 + `result` + 상대·맵 정보 + 현재 프롬프트/빌드 DB 버전.
- 출력(structured): 패인 요약, 결정적 실수 프레임 3개, 수정 제안 목록(`target: prompt|builds|map_knowledge|body_code`, `diff`, 기대 효과, 검증 방법).
- 여러 게임을 한 배치로. 제안은 `coach/proposals/<date>/`에 저장되고 사람이 고르거나 Claude Code가 브랜치로 만든다.

---

## 6. 건물 배치·교전 판단의 책임 분리

| 결정 | 누가 | 어떻게 |
|---|---|---|
| 앞마당을 막을지 | Strategy LLM (정책) | 맵 지식에 벽이 있을 때만 `wall_natural` 지시 가능 |
| 어떤 건물로 어느 타일에 | 맵 지식 + BWEB (기하) | 맵별로 미리 계산·검토된 벽 정의를 몸체가 타일로 푼다 |
| 성큰 몇 개, 어디 | 개수는 LLM, 위치는 맵 지식 `sunken_spots` 순서 | |
| 확장 순서 | 후보 이름은 맵 지식, 선택은 LLM(`expand_policy` + `army_objective`) | |
| 싸울지 | 규칙(CombatSim 비율 + `stance`) → 애매하면 Advisor | LLM은 자세만, 개시는 코드 |
| 교전 중 유닛 동작 | McRave Micro 스크립트 | LLM 관여 없음 |
| 벽이 어설픈 맵 | 코치 루프가 로그에서 발견 → 맵 지식 수정 또는 벽 후보 제외 | 오프라인 |

정직한 기대치: 이 방식의 배치·컨트롤 품질은 상위 오픈소스 봇 수준(사람 중위권 이상, 프로 미만)이다. 봇이 지는 주 원인은 판단이며, 그 부분을 LLM과 코치 루프가 맡는다.

---

## 7. 실행 모드와 인간 조건 프로파일

| 모드 | 게임 속도 | LLM | 용도 |
|---|---|---|---|
| lockstep | 최대. Strategy 호출 동안 `onFrame`이 기다린다 | 동기 | 개발·디버깅·결정론 회귀 |
| realtime | 24fps 고정 | 비동기 | 사람 상대, 실시간 평가 |
| headless | 최대 | 비동기 또는 기록 재생 | 평가 하네스 |
| replay-directive | 최대 | 없음. 이전 게임의 Directive 시퀀스를 프레임에 맞춰 재생 | Tactics/Micro 회귀를 LLM 없이 결정론적으로 |

APM 프로파일(`config/human_profile.yaml`, 기본 off): 토큰 버킷(apm, burst), 선택도 액션으로 계산, 부대 선택 12기 제한, 관측 지연 프레임 수. 훅3에서 강제하고 `result`에 기록.

---

## 8. 개발 환경 세팅 (추천)

### 8.1 하드웨어·OS
- GPU 불필요. CPU 코어 수가 평가 속도를 정한다. 8코어면 헤드리스 게임 8개 병렬.
- Linux(Ubuntu 22.04/24.04) 또는 Windows 11 + WSL2. 실제 게임 레인은 Windows 필요.
- 디스크 20GB(게임 데이터, 리플레이, 로그).

### 8.2 게임 데이터
- `scbw_bwapi440.zip`(David Churchill 배포, 1.16.1 + BWAPI 4.4.0 + 맵 팩)을 Windows 레인에 쓴다. OpenBW에는 여기서 MPQ 3개(`StarDat.mpq`, `BrooDat.mpq`, `patch_rt.mpq`)를 복사한다. 원본 정품에서 추출해도 된다.
- 맵: SSCAI 맵 팩(Fighting Spirit, Python, Benzene 등 표준 2인용 맵 위주). 처음엔 맵 3개로 시작.

### 8.3 Linux/OpenBW 레인 (컨테이너 권장)
```
docker/
  Dockerfile.openbw     # ubuntu:24.04 + build-essential cmake sdl2(선택) → OpenBW + OpenBW/bwapi 포크 빌드 → BWAPILauncher
  Dockerfile.bot        # 위 이미지 + McRave 포트 빌드(.so) + Python 사이드카
  compose.yaml          # 게임 1판 = launcher(플레이어1: 우리 봇) + launcher(플레이어2: 상대 봇) LAN 모드 + sidecar
```
- OpenBW BWAPI 포크는 4.2.0 API 수준이다. McRave/ZZZKBot/UAlbertaBot을 4.4.0 헤더로 빌드하는 패치는 lukecameron/starcraft-ai의 방식을 참고해 직접 만든다(그 저장소는 라이선스가 없으므로 복사하지 않는다).
- 상대 풀 초기값: ZZZKBot(저그 러시, 약함), UAlbertaBot(중간), 수정 전 McRave 원본(강함, 자기 baseline).
- 환경변수: `OPENBW_ENABLE_UI=0`(헤드리스), `OPENBW_LAN_MODE=LOCAL`(2인스턴스). 정확한 값은 OpenBW/bwapi README에서 확인.

### 8.4 Windows 1.16.1 레인
- Visual Studio 2022(x86 툴셋), BWAPI 4.4.0 SDK, `scbw_bwapi440.zip`. McRave를 Win32 DLL로 빌드해 `bwapi-data/AI/`에 둔다. 사이드카는 같은 PC의 Python에서 실행.
- 내장 AI 상대 확인, 사람 상대 플레이, 리플레이 시청은 여기서.

### 8.5 Python 사이드카
- Python 3.12, `uv`로 관리. 의존성: `anthropic`, `pydantic`, `fastapi`, `uvicorn`, `orjson`, `numpy`, 분석용 `pandas`/`duckdb`.
- 비밀: `ANTHROPIC_API_KEY`는 `.env`(git 제외) 또는 `ant auth login`. 코드에 넣지 않는다.
- 비용 안전장치: 사이드카 시작 시 일일 예산(기본 30달러), 게임당 예산(3달러). 초과 시 LLM 호출 중단 로그.

### 8.6 Claude Code용
- 저장소 루트 `CLAUDE.md`: 빌드 명령, 1게임 실행 명령, `run_eval` 사용법, 로그 위치, "변경은 회귀 게이트 통과 후 병합" 규칙, 건드리면 안 되는 것(맵 지식 파일은 사람 검토 후에만).
- 컨테이너에서 헤드리스 평가가 돌면 Claude Code가 "수정 → 30게임 → 비교" 루프를 혼자 돌릴 수 있다. MPQ는 비공개 볼륨으로 마운트.

---

## 9. 저장소 구조

```
SC_AI/
  CLAUDE.md
  docs/                 blueprint.md(v0.4, 보존), design_review_2026-09.md, design_v0.5.md(이 문서), adr/
  knowledge/            rules.md, builds/ZvT.json ZvP.json ZvZ.json, maps/<map>.json
  body/                 mcrave/(서브모듈 또는 pinned clone) + patches/ + hooks/(SidecarClient.cpp, ApmProfile.cpp)
  bot/sidecar/          server.py state_store.py summarizer.py plan_ledger.py strategy.py validator.py advisor.py logger.py
  eval/                 run_eval.py, opponents.yaml, metrics.py, results/
  coach/                analyze.py(batch), map_knowledge.py, proposals/
  tools/                map_dump.py, replay_index.py, cost_report.py
  docker/               Dockerfile.openbw Dockerfile.bot compose.yaml
  config/               modes.yaml human_profile.yaml budgets.yaml
  logs/ replays/        (git 제외)
```

---

## 10. 평가 하네스와 코치 루프

`python -m eval.run_eval --games 30 --opponent zzzkbot --map "Fighting Spirit" --mode headless --strategy llm|fixed|random --seed 1`

- 출력 `eval/results/<run_id>/metrics.json`: 승률(신뢰구간), 평균 게임 길이, 자원 유휴 평균, 유닛 손실 자원비, Strategy 호출 수, flip-flop 수, Validator 거부율, 평균 응답 지연, 게임당 비용, 프레임 시간 p99.
- 회귀 게이트: 같은 상대·맵·시드 세트로 변경 전후 비교. 승률 차이가 신뢰구간 안이면 "변화 없음"으로 판정. 한 번에 하나만 바꾼다.
- 코치 루프: `run_eval` 종료 → 패배 게임 로그를 Batch로 Coach에 → 제안 저장 → (사람 또는 Claude Code) 브랜치 생성 → `run_eval` → 게이트 통과 시 병합.

---

## 11. 단계별 작업 (체크리스트)

**Phase 0 — 환경 (1주)**
- [ ] `scbw_bwapi440.zip` 확보, MPQ·맵 정리
- [ ] Docker로 OpenBW + BWAPI 포크 빌드, `BWAPILauncher` 헤드리스 실행 확인
- [ ] ZZZKBot, UAlbertaBot을 OpenBW에서 빌드해 서로 1게임(LAN 모드), 리플레이 저장 확인
- [ ] McRave 빌드(OpenBW용 .so, Windows용 DLL). 안 되면 UAlbertaBot으로 전환 결정
- [ ] 저장소 구조, `CLAUDE.md`, `config/*.yaml` 초안

**Phase 1 — 몸체 + 훅 (1~2주, LLM 없음)**
- [ ] 훅2: StateSummary 송출(백그라운드 스레드) + 사이드카 `server.py` 수신·로그
- [ ] 훅1: Directive 수신·해석(고정 파일에서 읽는 테스트 지시로 검증: 오프닝 바꾸기, 자세 바꾸기)
- [ ] 훅3: 명령 계측, APM 프로파일 off 상태 로그
- [ ] `tools/map_dump.py`로 맵 3개 분석 덤프
- [ ] 완료 기준: 헤드리스에서 ZZZKBot·UAlbertaBot 상대 30게임 완주, 승률과 로그가 나온다

**Phase 2 — 평가 하네스 (1주)**
- [ ] `run_eval` 병렬 실행(코어 수만큼), metrics, 회귀 비교 스크립트
- [ ] `replay-directive` 모드
- [ ] 완료 기준: 명령 한 줄로 승률 표

**Phase 3 — Strategy LLM (2주)**
- [ ] `knowledge/rules.md`, `builds/ZvT.json` 등 작성(Liquipedia 기반, 사람 검토)
- [ ] 맵 지식 생성 파이프라인 + 맵 3개 검토·커밋
- [ ] Summarizer, PlanLedger, Validator, StrategyCaller, 비용 상한
- [ ] lockstep 모드로 디버깅 → headless 비동기
- [ ] A/B: fixed vs random vs llm(Opus 5.5) vs llm(Sonnet 5.5), effort low vs medium, 상대 2개 × 30게임

**Phase 4 — 코치 루프 (2주)**
- [ ] Coach 프롬프트·structured output, Batch 실행, 제안 저장
- [ ] Claude Code 워크플로: 제안 → 브랜치 → `run_eval` → 보고
- [ ] 완료 기준: 코치 제안으로 회귀 게이트를 통과한 개선 3건

**Phase 5 — 심화 (지속)**
- [ ] realtime 모드 + Windows 레인 사람 상대
- [ ] Tactical Advisor(Haiku 4.5)
- [ ] 상대 풀 확장(PurpleWave via JBWAPI 등), 맵 확장
- [ ] (선택) 인간 조건 프로파일 on 실험, (선택) 마이크로 RL 시나리오

---

## 12. 리스크와 미확정

| 항목 | 상태 | 대응 |
|---|---|---|
| McRave의 훅1 위치와 난이도 | 미확인(코드 안 읽음) | Phase 0 첫 작업. 2주 한도, UAlbertaBot 대체안 |
| OpenBW BWAPI 포크(4.2.0)에서 McRave 빌드 | 사례는 있으나 패치 필요 | lukecameron 방식 참고해 자체 패치 |
| OpenBW LAN 모드 환경변수 정확한 값 | README 미확인 | Phase 0에서 확인 |
| Strategy 응답 지연(캐시 히트 시 예상 3~8초) | 미실측 | `usage`·지연 로그로 실측 후 트리거 조정 |
| LLM 지식 오류 | 확실히 발생 | 빌드 DB·맵 지식을 프롬프트에, Validator, 코치 루프 |
| 몸체의 배치·컨트롤 품질 한계 | 프로 미만 | 병목 아님. 코치 루프에서 발견 시 몸체 코드 수정 |

---

## 13. 구현 현황 (2026-09-29, 첫 구현 세션)

| 항목 | 상태 | 위치 |
|---|---|---|
| Python 사이드카(서버, 상태 저장, 요약, 원장, 검증기, 전략 호출, LLM 백엔드 3종, 로거) | 구현, 테스트 5개 통과 (fake LLM 기준) | `bot/sidecar/` |
| 실제 Anthropic 호출 경로 | 코드 작성됨, **미실행**(이 환경에 API 키 없음). 첫 실행 시 `usage`·지연을 로그로 확인할 것 | `bot/sidecar/llm.py` |
| 지식 파일 | 규칙·ZvT 빌드 초안. 맵 지식은 플레이스홀더(좌표 없음) | `knowledge/` |
| 평가 하네스 | mock 러너 + Wilson 구간 지표 + 비교 판정. OpenBW 러너는 게임당 스크립트만 | `eval/`, `tools/run_game_openbw.sh` |
| OpenBW 헤드리스 빌드 | 이 컨테이너에서 성공(gcc 13 패치 1줄). MPQ 없어 게임 실행은 미검증 | `docs/setup_openbw.md`, `body/patches/openbw/` |
| C++ 사이드카 클라이언트 + 상태 추적기 + 프로브 AI 모듈 | OpenBW BWAPI에 대해 컴파일 성공. 게임 내 동작은 MPQ 필요 | `body/sidecar_client/` |
| McRave 훅 분석 | 완료. 훅 위치·스니펫·공수 추정(훅 38h + Linux 포트 8~16h) | `body/HOOKS.md` |
| McRave Linux 포트 | 완료(2026-09-30). OpenBW BWAPI 헤더로 114 TU 빌드, `McRave.so` dlopen·심볼 확인. 패치 5개(39파일), 게임 내 실행은 MPQ 대기 | `body/mcrave_port/`, `body/patches/mcrave/` |
| McRave 훅 1~3 구현 | 완료(2026-10-01, 컴파일 검증만). 패치 0006(Sidecar.h/.cpp 신규)·0007(7파일 35줄). 훅1 8개 필드 덮어쓰기, 훅2 24프레임 송출, 훅3 계측만. 게임 내 동작은 MPQ 대기 | `body/mcrave_port/HOOKS_IMPL.md` |

McRave 분석에서 드러난 설계 보정:
- McRave는 전략 상태를 전역으로 두고 **매 프레임 다시 계산**한다. 따라서 훅1은 "McRave가 계산한 뒤 Directive 값으로 덮어쓰기"가 최소 변경이다. 채팅 명령 `/bo`가 이미 런타임 빌드 전환을 하므로 안전하다.
- McRave는 FAP가 아니라 자체 전투 시뮬(Horizon)을 쓴다. `combat_sim` 필드는 Horizon 수치로 채운다.
- 훅1의 오프닝 덮어쓰기는 **지시(directive id)당 한 번만** 적용한다. 매 프레임 적용하면 McRave의 정찰 반응(예: 2배럭 발견 시 풀 먼저)과 매 프레임 싸운다. 몸체의 반응은 유지하고, 같은 이벤트로 트리거된 다음 지시가 다시 결정한다.
- 명령 발행 지점이 단일하지 않다(약 25곳 우회). 훅3은 계측만 먼저 하고, 제한(APM 프로파일)은 나중에 `Cmd::` 심을 도입한다.
- VS2017 전용 빌드라 Linux 포트가 선행 과제다. 그 전까지 OpenBW 레인은 프로브 모듈과 UAlbertaBot/ZZZKBot으로 파이프라인을 검증한다.

다음 작업 순서: (1) MPQ·맵 확보 → 프로브 모듈로 OpenBW 1게임 + 사이드카 로그 확인 → (2) McRave Linux 포트 → (3) 훅1·2 → (4) Phase 2 하네스 루프.
