# StarCraft AI Blueprint

> Version: 0.3
> Last Updated: 2024-01-15
> Status: Design Phase

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        BWAPI BRIDGE                              │
│                    (Game State 수집)                             │
└─────────────────────┬───────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                     STATE MANAGER                                │
│          (정규화, 히스토리, 각 레이어용 뷰 생성)                     │
│                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │  TRACKER   │ │  TIMELINE  │ │   LOGGER   │ │   FEEDBACK   │  │
│  │            │ │            │ │            │ │   COLLECTOR  │  │
│  │ • 적 정보  │ │ • 이벤트   │ │ • 모든 I/O │ │              │  │
│  │ • 위치기억 │ │ • 타임스탬프│ │ • 레이어별 │ │ • 교전 결과  │  │
│  │           │ │            │ │            │ │ • 생산 실적  │  │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘  │
└─────┬────────────────────┬────────────────────┬─────────────────┘
      │                    │                    │
      │ (전체 상태)         │ (전술용 상태)       │ (마이크로용 상태)
      ▼                    │                    │
┌───────────────┐          │                    │
│   STRATEGY    │          │                    │
│    (LLM)      │          │                    │
│               │          │                    │
│ • 빌드 오더    │          │                    │
│ • 상대 분석    │          │                    │
│ • 전략 목표    │          │                    │
│               │          │                    │
│ [5-30초 주기]  │          │                    │
└───────┬───────┘          │                    │
        │                  │                    │
        │ 전략 지시         │                    │
        ▼                  ▼                    │
      ┌─────────────────────────┐               │
      │        TACTICS          │               │
      │         (SLM)           │               │
      │                         │               │
      │ • 빌드오더 → 생산 스케줄   │               │
      │ • 타이밍 공격 결정        │               │
      │ • 부대 편성/배치          │               │
      │                         │               │
      │ [0.5-2초 주기]           │               │
      └───────────┬─────────────┘               │
                  │                             │
                  │ 전술 명령                    │
                  ▼                             ▼
                ┌─────────────────────────────────┐
                │            MICRO                │
                │            (RL)                 │
                │                                 │
                │ • 유닛별 이동/공격               │
                │ • 타겟 우선순위                  │
                │ • 스플릿/카이팅                  │
                │                                 │
                │ [매 프레임]                      │
                └───────────────┬─────────────────┘
                                │
                                ▼
                ┌─────────────────────────────────┐
                │         COMMAND QUEUE           │
                │      (검증, 충돌 해결)            │
                └───────────────┬─────────────────┘
                                │
                                ▼
                ┌─────────────────────────────────┐
                │          BWAPI BRIDGE           │
                │          (명령 실행)             │
                └─────────────────────────────────┘
```

### Feedback Loop
```
Strategy ◄───────────────────────────────────────┐
    │                                            │
    ▼                                            │
Tactics ─────────────────────────────────────────┤
    │                          Execution         │
    ▼                          Feedback          │
Micro ───────────────────────────────────────────┘
```

---

## 2. Core Components

| 컴포넌트 | 역할 | 기술 스택 |
|---------|------|----------|
| BWAPI Bridge | 게임 ↔ AI 인터페이스 | C++ / Python wrapper |
| State Manager | 상태 수집/정규화/히스토리/로깅 | Python |
| Strategy Layer | 고수준 의사결정 | LLM (GPT-5.2 / Gemini 3.0 Pro) |
| Tactics Layer | 중수준 실행 계획 | SLM (Gemini Lite / GPT-4o-mini) |
| Micro Layer | 저수준 유닛 컨트롤 | RL Policy Network |
| Command Queue | 명령 우선순위/충돌 해결 | Python |

---

## 3. State Manager

### 역할: 사실 정리 Only (판단 X)

| 하는 것 | 안 하는 것 |
|--------|-----------|
| 적 유닛/건물 기록 | "이건 X 빌드다" 판단 |
| 타임스탬프 저장 | "위협적이다" 평가 |
| 마지막 위치 기억 | "어디로 갔을 것" 예측 |
| 이벤트 로그 | "그래서 어떻게 해야" 제안 |
| 모든 레이어 I/O 로깅 | - |

### 3.1 Tracker (적 정보 기억)

```python
enemy_memory = {
    "units": {
        501: {
            "type": "marine",
            "last_pos": {"x": 2400, "y": 1800},
            "last_seen_frame": 3200,
            "first_seen_frame": 2800,
            "alive": True  # False if onUnitDestroy 호출됨
        }
    },
    "buildings": {
        601: {
            "type": "barracks",
            "pos": {"x": 3100, "y": 3000},
            "first_seen_frame": 2400,
            "destroyed": False
        }
    }
}
```

### 3.2 Timeline (이벤트 기록)

```python
timeline = [
    {"frame": 0,    "event": "game_start", "matchup": "ZvT"},
    {"frame": 2400, "event": "enemy_building_spotted", "type": "barracks", "pos": {...}},
    {"frame": 2800, "event": "enemy_unit_spotted", "type": "marine", "count": 1},
    {"frame": 3600, "event": "first_contact", "location": {...}, "result": "trade"},
]
```

### 3.3 Logger (게임 로그)

```python
game_log = {
    "game_id": "uuid-1234",
    "start_time": "2024-01-15T14:30:00",
    "matchup": "ZvT",
    "map": "Fighting Spirit",
    "strategy_used": "9_pool_speed",  # 게임 후 태깅 가능

    "layer_logs": [
        {
            "frame": 3600,
            "layer": "strategy",
            "input": {...},
            "output": {...},
            "reasoning": "적 2배럭 확인, 수비 가능",
            "latency_ms": 2500
        },
        {
            "frame": 3600,
            "layer": "tactics",
            "input": {...},
            "output": {...},
            "latency_ms": 150
        },
        {
            "frame": 3600,
            "layer": "micro",
            "input": {...},
            "output": {...},
            "latency_ms": 8
        }
    ],

    "result": null,  # 게임 끝나면 "win" / "loss"
    "duration_frames": null
}
```

### 3.4 Log File Structure

```
/logs
  /games
    /2024-01-15_143000_ZvT_uuid1234.json
    /2024-01-15_150000_ZvP_uuid5678.json
  /summary
    /by_strategy.json
    /by_matchup.json
```

---

## 4. Strategy Layer (LLM)

### 호출 조건

| 트리거 | 설명 |
|--------|------|
| 정기 호출 | 10초마다 |
| 새 적 건물 발견 | 즉시 |
| 대규모 교전 발생/종료 | 즉시 |
| 자원 임계점 도달 | 예: 1000미네랄 초과 |

### 4.1 Input Schema

```json
{
  "frame": 5400,
  "game_time": "3:45",
  "matchup": "ZvT",

  "my_state": {
    "resources": {"minerals": 450, "gas": 88, "supply": "26/34"},
    "units": {
      "drone": 18,
      "zergling": 8,
      "overlord": 3
    },
    "buildings": {
      "hatchery": 2,
      "spawning_pool": 1,
      "extractor": 1
    },
    "tech": {
      "metabolic_boost": "researching",
      "lair": "not_started"
    }
  },

  "enemy_state": {
    "race": "terran",
    "units_seen": {
      "marine": {"count": 5, "last_frame": 5200},
      "scv": {"count": 8, "last_frame": 4800}
    },
    "buildings_seen": {
      "command_center": {"count": 1, "frame_first": 0},
      "barracks": {"count": 2, "frame_first": 2400},
      "refinery": {"count": 0}
    },
    "expansion_count": 1
  },

  "timeline_summary": [
    {"frame": 2400, "event": "barracks_spotted"},
    {"frame": 2900, "event": "second_barracks_spotted"},
    {"frame": 4200, "event": "first_contact", "result": "even_trade"}
  ],

  "current_strategy": {
    "name": "9_pool_speed",
    "phase": "early_aggression"
  },

  "execution_feedback": {
    "last_strategy_id": "uuid-previous",
    "issued_at_frame": 3600,

    "production_result": {
      "planned": {"drone": 24, "zergling": 12},
      "actual": {"drone": 22, "zergling": 10},
      "reason": "harass로 드론 2기 손실"
    },

    "engagements": [
      {
        "frame": 4800,
        "location": {"x": 2400, "y": 1800},
        "tactics_order": "defend_natural",
        "micro_execution": "surround_attempt",
        "result": {
          "my_losses": {"zergling": 4},
          "enemy_losses": {"marine": 3},
          "outcome": "trade_even"
        }
      }
    ],

    "strategic_goals_status": [
      {"goal": "expand_natural", "status": "completed", "frame": 4200},
      {"goal": "defend", "status": "ongoing"}
    ]
  }
}
```

### 4.2 Output Schema

```json
{
  "strategy_id": "uuid",
  "timestamp": 5400,

  "decision": {
    "strategy_name": "macro_expand",
    "phase": "transition_to_midgame",

    "immediate_goals": [
      {"type": "build", "target": "third_hatchery", "priority": 1},
      {"type": "defend", "location": "natural", "priority": 1},
      {"type": "tech", "target": "lair", "priority": 2}
    ],

    "unit_composition_target": {
      "drone": 30,
      "zergling": 12,
      "overlord": 4
    },

    "engagement_stance": "defensive",
    "expand_allowed": true,
    "all_in": false
  },

  "reasoning": "적 2배럭 노가스 확인. 마린 푸시 예상되나 스피드링 완료 시 수비 가능. 경제 우위 가져가기 위해 3해처리 진행.",

  "confidence": 0.75,

  "next_review_trigger": {
    "time_based": 4500,
    "event_based": ["enemy_tech_building", "large_engagement"]
  }
}
```

### 4.3 System Prompt (Draft)

```markdown
You are a StarCraft: Brood War AI strategist playing as Zerg.

## Your Role
- Analyze game state and decide high-level strategy
- You do NOT control units directly
- Your decisions are executed by lower layers (Tactics, Micro)

## Decision Framework
1. Identify enemy's likely build/strategy from scouting info
2. Assess threat level and timing
3. Decide: aggression vs expansion vs tech
4. Set unit composition targets
5. Explain your reasoning

## Output Rules
- Always output valid JSON
- "reasoning" field must explain WHY
- Be specific with numbers (drone count, timing)
- Consider your current resources and production capacity

## Game Knowledge
- You know standard builds and timings
- You understand unit counters
- You know map positions matter

Current game state will be provided as JSON input.
```

---

## 5. Tactics Layer (SLM)

> **Status: To Be Designed**

### 역할
- Strategy의 지시를 받아 구체적 실행 계획 수립
- 생산 큐 관리 (무엇을, 언제, 어디서)
- 부대 편성 및 배치
- 타이밍 공격 결정

### 호출 주기
- 0.5~2초

### Input
- State Manager: 현재 자원, 유닛 현황
- Strategy Layer: 빌드 오더, 전략 목표, 위협 평가

### Output
- Micro Layer로: 스쿼드 구성, 목표 지점, 교전 규칙

---

## 6. Micro Layer (RL)

> **Status: To Be Designed**

### 역할
- 유닛별 이동/공격 명령
- 타겟 우선순위 결정
- 스플릿, 카이팅 등 마이크로 컨트롤

### 호출 주기
- 매 프레임 (~42ms)

### 기술
- Reinforcement Learning (Policy Network)
- 로컬 실행 필수 (API latency 불가)

---

## 7. Layer Communication (JSON Schema)

### Strategy → Tactics

```json
{
  "strategy_id": "uuid",
  "timestamp": 1234567,
  "game_phase": "early_game",
  "build_order": "9_pool_speed",
  "strategic_goals": [
    {"type": "harass", "target": "enemy_natural", "priority": 1},
    {"type": "expand", "location": "natural", "priority": 2}
  ],
  "unit_composition_target": {
    "zergling": 12,
    "drone": 16,
    "overlord": 2
  },
  "threat_assessment": {
    "detected_build": "2_rax_pressure",
    "confidence": 0.75,
    "recommended_response": "defensive_sunken"
  }
}
```

### Tactics → Micro

```json
{
  "tactics_id": "uuid",
  "timestamp": 1234567,
  "squad_orders": [
    {
      "squad_id": "attack_group_1",
      "units": [101, 102, 103, 104],
      "objective": "harass",
      "target_area": {"x": 2400, "y": 1800},
      "engagement_rule": "hit_and_run",
      "retreat_threshold": 0.4
    }
  ],
  "production_queue": [
    {"unit_type": "zergling", "count": 6, "priority": 1},
    {"unit_type": "drone", "count": 2, "priority": 2}
  ],
  "building_orders": [
    {"type": "sunken_colony", "location": {"x": 1200, "y": 900}}
  ]
}
```

---

## 8. Model Selection

| 레이어 | 모델 | Latency 목표 | 비고 |
|--------|------|-------------|------|
| Strategy | GPT-5.2 / Gemini 3.0 Pro | 5~30초 | 복잡한 추론 |
| Tactics | Gemini Flash / GPT-4o-mini | 1~2초 | 빠른 응답, 저렴 |
| Micro | Local RL | <50ms | 실시간 필수 |

---

## 9. Hardware Requirements

### Minimum Spec
- GPU: RTX 4090 (24GB VRAM)
- RAM: 64GB
- CPU: Ryzen 7800X or equivalent

### Resource Allocation
- SLM (Tactics): ~6-8GB VRAM
- RL (Micro): ~1-2GB VRAM
- LLM (Strategy): API 호출 (로컬 시 CPU offload)

---

## 10. Implementation Roadmap

### Phase 1: Foundation
- [ ] BWAPI Bridge 설정
- [ ] State Manager 구현
- [ ] 로깅 시스템 구축

### Phase 2: Strategy Layer
- [ ] LLM 프롬프트 설계 완료
- [ ] Few-shot 예시 작성
- [ ] 빌드 오더 DB 구축
- [ ] API 연동

### Phase 3: Tactics Layer
- [ ] 상세 설계
- [ ] SLM 프롬프트 설계
- [ ] Strategy 연동

### Phase 4: Micro Layer
- [ ] RL 환경 설계
- [ ] 액션 스페이스 정의
- [ ] 학습 파이프라인

### Phase 5: Integration
- [ ] 전체 시스템 통합
- [ ] Command Queue 구현
- [ ] 충돌 해결 로직

### Phase 6: Testing & Iteration
- [ ] 테스트 게임
- [ ] 로그 분석
- [ ] Fine-tuning

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | 2024-01-15 | Initial architecture |
| 0.2 | 2024-01-15 | Hierarchical layer structure |
| 0.3 | 2024-01-15 | State Manager finalized, Feedback loop added |
