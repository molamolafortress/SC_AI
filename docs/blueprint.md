# StarCraft AI Blueprint

> Version: 0.4
> Last Updated: 2024-01-15
> Status: Design Phase

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        INPUT LAYER                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────┐          ┌────────────────────┐         │
│  │       BWAPI        │          │  VISUAL INSPECTION  │         │
│  │    (메모리 기반)    │          │    (화면 기반/DL)    │         │
│  │                    │          │                     │         │
│  │ • 유닛/건물 데이터  │          │ • Shimmer Detection │         │
│  │ • 자원/서플라이    │          │ • (향후 확장 가능)   │         │
│  │ • 이벤트 콜백      │          │                     │         │
│  │ • canBuildHere()  │          │                     │         │
│  └─────────┬──────────┘          └──────────┬──────────┘         │
│            │                                │                    │
│            └───────────────┬────────────────┘                    │
│                            ▼                                     │
└────────────────────────────┼────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     STATE MANAGER                                │
│          (데이터 취합, 정규화, 히스토리, 로깅)                       │
│                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │  TRACKER   │ │  TIMELINE  │ │   LOGGER   │ │   FEEDBACK   │  │
│  │            │ │            │ │            │ │   COLLECTOR  │  │
│  │ • 적 정보  │ │ • 이벤트   │ │ • 모든 I/O │ │              │  │
│  │ • 위치기억 │ │ • 타임스탬프│ │ • 레이어별 │ │ • 교전 결과  │  │
│  │ • 클로킹  │ │            │ │            │ │ • 생산 실적  │  │
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
      │ • 생산 분배 (어느 건물에서)│               │
      │ • 타이밍 공격 결정        │               │
      │ • 유닛 배치 위치 지정     │               │
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
                │ • 유닛 그룹핑 (스쿼드 편성)       │
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
| BWAPI Bridge | 게임 메모리 ↔ AI 인터페이스 | C++ / Python wrapper |
| Visual Inspection | 화면 기반 탐지 (Shimmer 등) | Deep Learning (CNN) |
| State Manager | 데이터 취합/정규화/히스토리/로깅 | Python |
| Strategy Layer | 고수준 의사결정 | LLM (GPT-5.2 / Gemini 3.0 Pro) |
| Tactics Layer | 중수준 실행 계획 | SLM (Gemini Lite / GPT-4o-mini) |
| Micro Layer | 저수준 유닛 컨트롤 | RL Policy Network |
| Command Queue | 명령 우선순위/충돌 해결 | Python |

---

## 3. Input Layer

### 3.1 BWAPI (메모리 기반)

게임 메모리에서 직접 데이터를 읽음. Fog of War 존중.

**제공 데이터:**
| 카테고리 | 데이터 |
|---------|--------|
| 유닛 기본 | ID, 타입, 소유자, 좌표, 방향, 속도 |
| 상태 | HP, 에너지, 쉴드, 쿨다운 |
| 행동 | 현재 명령, 타겟, 이동 중인지 |
| 건물 | 건설 진행도, 애드온, 생산 큐 |
| 자원 | 미네랄, 가스, 서플라이 |
| 맵 | 지형, 리전, 시야 정보 |

**특수 기능:**
- `canBuildHere()` - 지상 투명 유닛 탐지 (럴커, 다크템플러)
- 이벤트 콜백 (onUnitCreate, onUnitDestroy, onUnitHide, onUnitShow)

**한계:**
- 공중 투명 유닛 (옵저버, 아비터) 탐지 불가 → Visual Inspection 필요

### 3.2 Visual Inspection (화면 기반)

화면 캡처 + 딥러닝으로 BWAPI가 못 보는 것 탐지.

**현재 기능:**
- Shimmer Detection (공중 투명 유닛 일렁임 탐지)

**향후 확장 가능:**
- (TBD)

#### Shimmer Detector 스펙

```python
class ShimmerDetector:
    """CNN 기반 화면 일렁임 탐지"""

    def __init__(self):
        self.model = load_cnn_model()  # 사전 학습된 모델
        self.capture_interval = 4  # 매 4프레임마다 (6 FPS)

    def detect(self, screen_frame) -> list:
        """
        Input: 화면 캡처 이미지 (또는 특정 영역)
        Output: [{"x": int, "y": int, "confidence": float}, ...]
                의심 좌표 리스트
        """
        candidates = self.model.predict(screen_frame)
        return [c for c in candidates if c["confidence"] > 0.7]
```

**학습 데이터:**
- Positive: 옵저버/아비터가 있는 화면 캡처
- Negative: 투명 유닛 없는 화면
- 소스: 리플레이에서 자동 수집 (투명 유닛 위치 known)

**탐지 → 대응 흐름:**
| 단계 | 담당 | 동작 |
|------|------|------|
| 탐지 | Shimmer Detector | "여기 일렁임 있음" |
| 판단 | Tactics (SLM) | "스캔 뿌리고 골리앗 보내" |
| 실행 | Micro (RL) | 골리앗 이동/공격 |

---

## 4. State Manager

### 역할: 사실 정리 Only (판단 X)

| 하는 것 | 안 하는 것 |
|--------|-----------|
| BWAPI + Visual Inspection 데이터 취합 | "이건 X 빌드다" 판단 |
| 적 유닛/건물 기록 | "위협적이다" 평가 |
| 타임스탬프 저장 | "어디로 갔을 것" 예측 |
| 마지막 위치 기억 | "그래서 어떻게 해야" 제안 |
| 클로킹 의심 좌표 기록 | |
| 모든 레이어 I/O 로깅 | |

### 4.1 Tracker (적 정보 기억)

```python
enemy_memory = {
    "units": {
        501: {
            "type": "marine",
            "last_pos": {"x": 2400, "y": 1800},
            "last_seen_frame": 3200,
            "first_seen_frame": 2800,
            "alive": True
        }
    },
    "buildings": {
        601: {
            "type": "barracks",
            "pos": {"x": 3100, "y": 3000},
            "first_seen_frame": 2400,
            "destroyed": False
        }
    },
    "suspected_cloaked": [
        {
            "source": "shimmer_detection",  # or "build_check"
            "pos": {"x": 2000, "y": 1500},
            "confidence": 0.85,
            "frame": 4200,
            "type_guess": "observer"  # or "lurker", "dark_templar", "arbiter"
        }
    ]
}
```

### 4.2 Timeline (이벤트 기록)

```python
timeline = [
    {"frame": 0,    "event": "game_start", "matchup": "ZvT"},
    {"frame": 2400, "event": "enemy_building_spotted", "type": "barracks", "pos": {...}},
    {"frame": 2800, "event": "enemy_unit_spotted", "type": "marine", "count": 1},
    {"frame": 3600, "event": "first_contact", "location": {...}, "result": "trade"},
    {"frame": 4200, "event": "shimmer_detected", "pos": {...}, "confidence": 0.85},
]
```

### 4.3 Logger (게임 로그)

```python
game_log = {
    "game_id": "uuid-1234",
    "start_time": "2024-01-15T14:30:00",
    "matchup": "ZvT",
    "map": "Fighting Spirit",
    "strategy_used": "9_pool_speed",

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

    "result": null,
    "duration_frames": null
}
```

### 4.4 Log File Structure

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

## 5. Strategy Layer (LLM)

### 호출 조건

| 트리거 | 설명 |
|--------|------|
| 정기 호출 | 10초마다 |
| 새 적 건물 발견 | 즉시 |
| 대규모 교전 발생/종료 | 즉시 |
| 자원 임계점 도달 | 예: 1000미네랄 초과 |
| 클로킹 유닛 탐지 | 즉시 (전략 재검토) |

### 5.1 Input Schema

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
    "expansion_count": 1,
    "suspected_cloaked": []
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

### 5.2 Output Schema

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

### 5.3 System Prompt (Draft)

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

## 6. Tactics Layer (SLM)

### 역할

| 하는 것 | 안 하는 것 |
|--------|-----------|
| Strategy 지시 → 구체적 실행 계획 | 전략 방향 결정 (Strategy 역할) |
| 생산 순서/타이밍 결정 | 개별 유닛 조작 (Micro 역할) |
| 생산 분배 (어느 건물에서) | 교전 중 타겟팅 |
| 유닛 배치 위치 지정 | 유닛 그룹핑 (Micro 역할) |
| "언제" 공격/수비 결정 | "어떻게" 싸울지 |
| 건물 위치 선정 | |
| 클로킹 대응 결정 (스캔 사용 등) | |

### 호출 주기
- 0.5~2초
- 트리거: 자원 변화, 생산 완료, Strategy 지시 갱신

### 6.1 Input Schema

```json
{
  "frame": 5400,
  "game_time": "3:45",

  "strategy_directive": {
    "strategy_id": "uuid",
    "strategy_name": "macro_expand",
    "phase": "transition_to_midgame",
    "immediate_goals": [
      {"type": "build", "target": "third_hatchery", "priority": 1},
      {"type": "defend", "location": "natural", "priority": 1}
    ],
    "unit_composition_target": {
      "drone": 30,
      "zergling": 12
    },
    "engagement_stance": "defensive",
    "reasoning": "적 2배럭 노가스 확인..."
  },

  "current_state": {
    "resources": {"minerals": 450, "gas": 88, "supply": "26/34"},
    "units": {
      "drone": 22,
      "zergling": 6
    },
    "buildings": {
      "hatchery": [
        {"id": 1, "pos": {"x": 500, "y": 500}, "larva": 3},
        {"id": 2, "pos": {"x": 1200, "y": 900}, "larva": 2}
      ],
      "spawning_pool": [{"id": 10, "idle": true}]
    },
    "in_production": [
      {"type": "drone", "remaining_frames": 120}
    ]
  },

  "enemy_state": {
    "last_seen_army_pos": {"x": 2400, "y": 1800},
    "estimated_army_size": "small",
    "suspected_cloaked": [
      {"pos": {"x": 2000, "y": 1500}, "type_guess": "observer", "confidence": 0.85}
    ]
  },

  "map_info": {
    "natural_pos": {"x": 1200, "y": 900},
    "third_pos": {"x": 1800, "y": 1400},
    "choke_points": [{"x": 1400, "y": 1100}]
  }
}
```

### 6.2 Output Schema

```json
{
  "tactics_id": "uuid",
  "timestamp": 5400,

  "production_orders": [
    {
      "unit_type": "drone",
      "count": 4,
      "from_building": 1,
      "priority": 1
    },
    {
      "unit_type": "drone",
      "count": 4,
      "from_building": 2,
      "priority": 1
    },
    {
      "unit_type": "zergling",
      "count": 6,
      "from_building": 2,
      "priority": 2
    }
  ],

  "building_orders": [
    {
      "type": "hatchery",
      "location": {"x": 1800, "y": 1400},
      "when": {"condition": "minerals >= 300"}
    }
  ],

  "unit_assignments": [
    {
      "unit_ids": [101, 102, 103, 104, 105, 106],
      "role": "defense",
      "position": {"x": 1400, "y": 1100},
      "stance": "hold_position"
    },
    {
      "unit_ids": [201],
      "role": "scout",
      "position": {"x": 3200, "y": 3200}
    }
  ],

  "special_actions": [
    {
      "type": "scan",
      "target": {"x": 2000, "y": 1500},
      "reason": "suspected_cloaked_observer"
    }
  ],

  "next_check_frame": 5640
}
```

### 6.3 System Prompt (Draft)

```markdown
You are a StarCraft: Brood War AI tactician playing as Zerg.

## Your Role
- Translate strategic goals into concrete execution plans
- Manage production scheduling and unit assignments
- You do NOT decide strategy (that's the Strategy layer)
- You do NOT control individual units in combat (that's the Micro layer)

## Your Responsibilities
1. Production: What to build, when, from which building
2. Positioning: Where units should be placed
3. Timing: When to move out, when to defend
4. Resource allocation: Balance between units and tech

## Output Rules
- Always output valid JSON
- Be specific: unit IDs, exact coordinates, building IDs
- Production should respect current resources and larva
- Consider travel time for unit positioning

Current state and strategy directive will be provided as JSON input.
```

---

## 7. Micro Layer (RL)

### 역할

| 하는 것 | 안 하는 것 |
|--------|-----------|
| 유닛별 이동/공격 명령 | 전략 결정 |
| 타겟 우선순위 결정 | 생산 결정 |
| 스플릿, 카이팅, 서라운드 | 건물 배치 |
| 유닛 그룹핑 (스쿼드 편성) | |
| retreat 판단 (threshold 기반) | |

### 호출 주기
- 매 프레임 (~42ms at 24 FPS)

### 기술
- Reinforcement Learning (Policy Network)
- 로컬 실행 필수 (API latency 불가)

### 7.1 Input Schema

```json
{
  "frame": 5400,

  "my_units": [
    {
      "id": 101,
      "type": "zergling",
      "pos": {"x": 1400, "y": 1100},
      "hp": 35,
      "max_hp": 35,
      "cooldown": 0,
      "status": "idle"
    }
  ],

  "enemy_units": [
    {
      "id": 501,
      "type": "marine",
      "pos": {"x": 1450, "y": 1150},
      "hp": 40,
      "max_hp": 40
    }
  ],

  "tactics_order": {
    "role": "defense",
    "position": {"x": 1400, "y": 1100},
    "stance": "hold_position",
    "engagement_rule": "surround",
    "retreat_threshold": 0.3
  },

  "terrain": {
    "nearby_chokes": [{"x": 1400, "y": 1100, "width": 3}],
    "high_ground": []
  }
}
```

### 7.2 Output Schema (Action Space)

```json
{
  "unit_commands": [
    {
      "unit_id": 101,
      "action": "attack",
      "target_id": 501
    },
    {
      "unit_id": 102,
      "action": "move",
      "target_pos": {"x": 1420, "y": 1080}
    },
    {
      "unit_id": 103,
      "action": "hold_position"
    }
  ],

  "squad_update": {
    "create": [
      {"squad_id": "attack_1", "unit_ids": [101, 102, 103]}
    ],
    "dissolve": []
  }
}
```

### 7.3 Action Space Definition

| Action | Parameters | Description |
|--------|------------|-------------|
| attack | target_id | 특정 유닛 공격 |
| attack_move | target_pos | 위치로 이동하며 공격 |
| move | target_pos | 이동 |
| hold_position | - | 제자리 유지 |
| patrol | pos_a, pos_b | 순찰 |
| stop | - | 정지 |
| use_ability | ability_id, target | 스킬 사용 |

---

## 8. Layer Communication (JSON Schema)

### Strategy → Tactics
(See Section 6.1 - strategy_directive field)

### Tactics → Micro
(See Section 7.1 - tactics_order field)

### Execution Feedback → Strategy
(See Section 5.1 - execution_feedback field)

---

## 9. Model Selection

| 레이어 | 모델 | Latency 목표 | 비고 |
|--------|------|-------------|------|
| Strategy | GPT-5.2 / Gemini 3.0 Pro | 5~30초 | 복잡한 추론 |
| Tactics | Gemini Flash / GPT-4o-mini | 1~2초 | 빠른 응답, 저렴 |
| Micro | Local RL | <50ms | 실시간 필수 |
| Shimmer Detection | Local CNN | <100ms | 화면 분석 |

---

## 10. Hardware Requirements

### Minimum Spec
- GPU: RTX 4090 (24GB VRAM)
- RAM: 64GB
- CPU: Ryzen 7800X or equivalent

### Resource Allocation
- SLM (Tactics): ~6-8GB VRAM
- RL (Micro): ~1-2GB VRAM
- CNN (Shimmer): ~1-2GB VRAM
- LLM (Strategy): API 호출 (로컬 시 CPU offload)

---

## 11. Implementation Roadmap

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
- [ ] 상세 설계 ✓
- [ ] SLM 프롬프트 설계 ✓
- [ ] Strategy 연동

### Phase 4: Micro Layer
- [ ] RL 환경 설계
- [ ] 액션 스페이스 정의 ✓
- [ ] 학습 파이프라인

### Phase 5: Visual Inspection
- [ ] Shimmer Detector CNN 설계
- [ ] 학습 데이터 수집 (리플레이)
- [ ] State Manager 연동

### Phase 6: Integration
- [ ] 전체 시스템 통합
- [ ] Command Queue 구현
- [ ] 충돌 해결 로직

### Phase 7: Testing & Iteration
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
| 0.4 | 2024-01-15 | Input Layer 추가 (BWAPI + Visual Inspection), Tactics Layer 상세 설계, Micro Layer 역할 수정 (그룹핑 추가) |
