# SC_AI 설계 리뷰 및 개선 계획 (2026-09)

> 대상: `docs/blueprint.md` v0.4, `docs/brainstorm_log.md`
> 작성일: 2026-09-29
> 상태: 검토 요청 (7장의 열린 질문에 답이 정해지면 Blueprint v0.5로 반영)

## 0. 요약

**결론 한 줄: 3계층 구조는 유지하되, LLM을 "실시간 실행자"가 아니라 "이벤트 기반 전략가 + 오프라인 코치"로 쓰고, 첫 한 달 남짓은 LLM 없이 완주하는 봇과 평가 하네스를 만드는 데 쓴다.**

핵심 결론 6가지:

1. **Tactics를 SLM으로 매초 호출하는 설계가 가장 큰 위험이다.** 유닛 ID·좌표를 모델이 직접 내면 무효 명령이 매 호출 생기고, 1~2초 지연이면 응답 시점에 상태가 24~48프레임 지나 있으며, 비용도 Strategy보다 크다(게임당 약 3.4달러). 생산·배치·부대 편성은 기존 브루드워 봇들이 이미 풀어놓은 결정적 코드로 대체한다. LLM은 교전/후퇴/목표 같은 판단이 필요한 순간에만 이벤트 기반으로 부른다.
2. **Visual Inspection(Shimmer CNN) 계층은 삭제한다.** BWAPI 4.4.0 소스로 확인한 결과, 시야 안의 비탐지 클로킹 유닛은 종류와 위치가 그대로 노출되고(`isDetected()==false`), 아비터는 클로킹 유닛이 아니다. Phase 5 전체가 불필요하다.
3. **Micro RL은 1차 범위에서 뺀다.** 2026년 이전 상위 브루드워 봇은 모두 스크립트 마이크로 + 전투 시뮬레이터였고, 2026년에 RL로 우승한 Pluto는 마이크로 모듈이 아니라 315M 파라미터 전체 게임 정책이다. 스크립트로 시작하고, 규칙 작성·개선은 코드 생성 능력이 올라간 LLM에게 맡긴다.
4. **모델 개선의 이득은 실시간 경로보다 오프라인 루프에서 크다.** 1M 컨텍스트로 게임 로그 전체를 한 번에 읽고, Batch 50% 할인으로 게임당 1달러 미만에 최고 모델이 패인 분석과 코드·프롬프트 수정안을 낸다. 선행 연구(Compiled Agency, Alpha4Gate, LLM-SMAC)도 "LLM이 오프라인에서 코드를 쓰고 로그로 반복"하는 쪽이 "매 턴 LLM 호출"보다 성과가 좋았다.
5. **평가 하네스가 없으면 아무것도 개선되지 않는다.** 헤드리스 자동 대전(N게임, 고정 상대·맵·시드)과 승률·비용·flip-flop 지표를 Phase 2에 넣고, 모든 변경은 회귀 게이트를 통과해야 채택한다. LLM 전략의 효과는 "고정 빌드 vs 무작위 빌드 vs LLM" A/B로 검증한다.
6. **API 변화가 v0.4의 여러 우려를 해소한다.** Structured outputs가 JSON 스키마를 강제하고, prompt caching(캐시 읽기가 입력가의 5%)으로 빌드 DB를 통째로 넣어도 싸며, adaptive thinking + effort로 같은 모델을 가벼운 점검과 무거운 판단에 나눠 쓸 수 있다. 제안 구성의 실시간 LLM 비용은 게임당 약 1~2달러다.

바뀌지 않는 것: 전략/전술/마이크로의 계층 분리와 서로 다른 주기, "사실만 정리하는" State Manager, JSON 통신과 `reasoning` 필드, 피드백 루프, BWAPI 우선. 모두 선행 연구가 수렴한 방향과 같다.

가장 먼저 정할 결정(5장): 자체 Python 봇을 처음부터 짓느냐(A), 기존 오픈소스 저그 봇(Steamhammer/McRave)을 몸체로 쓰고 LLM 두뇌를 얹느냐(B). 유지되는 Python BWAPI 바인딩이 없다는 사실 때문에 A는 브리지 작업이 먼저 필요하다. 이 보고서는 **B로 시작해 가설을 검증한 뒤 A로 옮기는 것**을 추천한다.

문서 구성: 1장 현재 설계 리뷰와 사실 확인, 2장 모델·API 변화와 비용, 3장 선행 연구, 4장 개선 설계안(v0.5), 5장 구현 방식 비교, 6장 로드맵, 7장 리스크와 열린 질문, 8장 바로 할 일, 부록 참고 자료.

---

## 1. 현재 설계(Blueprint v0.4) 리뷰

### 1.1 유지할 만한 결정

| 결정 | 평가 |
|---|---|
| 전략(느림, 추론) / 전술 / 마이크로(빠름, 반사) 계층 분리와 서로 다른 호출 주기 | 옳다. 실시간 게임에 LLM을 넣는 거의 모든 선행 연구가 같은 구조로 수렴한다 (3장) |
| State Manager는 "사실 정리만, 판단은 안 함" | 옳다. 판단을 한 곳(LLM)에 모아야 로그로 원인 분석이 된다 |
| 레이어 간 JSON 통신 + `reasoning` 필드 + 전 레이어 I/O 로깅 | 옳다. 이 로그가 사후 분석 루프(4.7)의 원료가 된다 |
| Feedback loop(실행 결과를 Strategy에 되돌림) | 옳다. 다만 "계획 대비 실제" 비교는 State Manager가 기계적으로 계산해 넣어야 한다 |
| BWAPI로 먼저 검증, 화면 인식은 나중 | 옳다 |
| 빌드 오더 DB: 시스템 프롬프트 요약 + 매치업별 few-shot | 옳다. 지금은 prompt caching 때문에 "요약"이 아니라 상세 DB를 통째로 넣어도 된다 |

### 1.2 문제점과 리스크

| # | 항목 | 문제 | 영향 | 제안 |
|---|---|---|---|---|
| R1 | **Tactics = SLM, 0.5~2초 주기** | 유닛 ID·좌표·건물 ID를 모델이 직접 출력한다. 존재하지 않는 ID, 건설 불가 좌표, 라바 수 착오가 매 호출 발생할 수 있다. 1~2초 지연이면 응답 시점에 상태가 24~48프레임 지나 있다. 초당 1회 호출은 비용도 Strategy보다 크다(2.4) | 가장 큰 실패 지점. 봇이 "생산을 못 하는" 상황이 자주 나온다 | 생산 스케줄링·건물 배치·부대 편성은 결정적 코드로. LLM은 이벤트 기반 판단(교전/후퇴/목표)만 |
| R2 | **Strategy 10초 고정 호출** | 대부분의 10초 구간은 새 정보가 없다. 같은 입력에 다른 답이 나오면 계획이 흔들린다(flip-flop) | 비용 2.5배, 일관성 저하 | 이벤트 기반(새 건물 발견, 교전 종료, 자원 임계, 정찰 귀환) + 30초 안전 주기. 출력에 `keep_current_plan` 옵션과 변경 사유 필드. 직전 결정을 입력에 포함 |
| R3 | **Micro = RL, Phase 4에서 신규 학습** | 환경 구축, 보상 설계, 학습, 실게임 전이까지 그 자체로 별도 연구 프로젝트. 상위 BW 봇 대부분은 스크립트 마이크로로 경쟁한다(3장) | 통합 시점이 몇 달 밀린다 | 1차는 스크립트 마이크로(카이팅·집중사격·서라운드·후퇴 임계). 모델의 코드 생성 능력이 올라갔으니 LLM이 규칙을 작성하고 마이크로 테스트 맵으로 검증하는 루프를 만든다. RL은 특정 교전 유형(저글링 vs 마린 등)에 한정해 후순위 |
| R4 | **Visual Inspection(Shimmer CNN)** | 문서는 "BWAPI는 공중 투명 유닛을 탐지 못 한다"고 전제한다. BWAPI는 시야 안의 비탐지 클로킹 유닛을 위치와 함께 노출하므로(1.3) 사람이 보는 "일렁임"에 해당하는 정보는 이미 있다 | Phase 5 전체(CNN 설계, 리플레이 데이터 수집, 학습)가 불필요 | Phase 5 삭제. `isDetected()==false` 유닛을 `suspected_cloaked`로 기록하는 코드 몇 줄로 대체. 화면 인식은 "온라인 래더에서 사람처럼 플레이" 트랙으로 분리 |
| R5 | **"LLM은 표준 빌드와 타이밍을 안다"는 가정** | 브루드워 빌드·타이밍은 모델이 대략은 알지만 숫자(서플라이 타이밍, 가스 타이밍)를 틀리게 말하는 일이 흔하다 | 그럴듯하지만 틀린 전략 | 큐레이션된 빌드 DB(Liquipedia 기반)를 캐시된 프리픽스로 항상 제공. 테크트리·자원 규칙은 코드로 검증(Validator) |
| R6 | **평가 하네스 부재** | 로드맵 어디에도 "N게임 자동 대전 → 승률"이 없다. LLM이 실제로 도움이 되는지 측정할 방법이 없다 | 개선 루프가 돌지 않는다. 감으로 튜닝 | Phase 0에 "1게임 자동 실행 + 로그", Phase 2에 헤드리스 N게임 자동 대전 + 지표 수집을 넣는다(6장) |
| R7 | **로드맵이 수평(레이어별)** | 통합이 Phase 6. 가장 큰 리스크(지연, 계층 간 계약 불일치)를 가장 늦게 만난다 | 늦은 실패 | 수직 슬라이스: 2~3주 안에 "고정 빌드 + 스크립트 전술/마이크로"로 내장 AI를 이기는 봇을 먼저 만들고, 그 위에 LLM을 얹어 A/B |
| R8 | **동기/비동기 설계 미정** | BWAPI `onFrame`은 반환할 때까지 게임을 멈춘다. 개발 단계에서는 이 성질을 이용해 동기 호출(락스텝)로 단순하게 시작할 수 있고, 실시간·대회 규칙에서는 비동기가 필수다 | 처음부터 비동기로 짜면 디버깅이 어렵고, 끝까지 동기면 실시간 불가 | 두 모드를 명시. 개발=락스텝, 평가/대회=비동기(백그라운드 스레드 + 결과 도착 시 다음 프레임 반영 + 상태가 크게 바뀌었으면 폐기) |
| R9 | **State Manager 입력 형식** | 5.1 스키마는 좋지만 매 호출 전체 상태를 보낸다. 토큰과 캐시 효율 모두 나쁘다 | 비용, 지연 | 고정 지식(캐시) / 게임 요약(누적, 짧음) / 직전 호출 이후 변화(delta) 3단 구조. 텍스트 요약(chain-of-summarization)을 State Manager가 생성 |
| R10 | 하드웨어 요구(RTX 4090, 64GB) | 로컬 SLM/RL 전제. API 중심 + 스크립트 마이크로면 일반 PC로 충분 | 진입 장벽 | 1차 범위에서 GPU 요구 삭제 |
| R11 | 문서 메타데이터 | `Last Updated: 2024-01-15`, Changelog 날짜가 실제 커밋(2026-02-04)과 다르다 | 사소 | 수정 |
| R12 | 대회 출전 여부 미정 | 대회(AIIDE/CoG 등)는 프레임 시간 제한이 있고 외부 네트워크 호출이 허용되지 않을 가능성이 크다(1.3) | LLM API 기반 봇은 대회용이 아니라 "연구/래더/사람 상대" 용도 | 목표를 명시: (a) 내장 AI·오픈소스 봇 상대 승률, (b) 사람 상대 실시간 플레이. 대회는 비목표 |

### 1.3 사실 확인 결과 (리서치 요약)

아래는 BWAPI 소스(4.4.0 main 브랜치의 `UnitUpdate.cpp`, `UnitImpl.cpp`, `GameUnits.cpp`)와 주요 봇 소스를 직접 읽어 확인한 내용이다. 신뢰도가 낮은 항목은 따로 표시했다.

**(a) 클로킹 유닛과 BWAPI — 신뢰도 높음(코드 확인)**
- 시야 안에 있고 버로우하지 않은 클로킹 유닛(옵저버, 다크템플러, 클로킹 레이스/고스트)은 `isVisible()==true`, `isDetected()==false`이며 `getType()`과 `getPosition()`이 **실제 값**으로 나온다. `getAllUnits()`에 포함되고 `onUnitShow`/`onUnitDiscover`도 발생한다. 못 얻는 것은 HP·쉴드·명령·타겟(0 또는 Unknown)뿐이다. 즉 사람이 보는 "일렁임"에 해당하는 정보(무엇이 어디에 있나)는 API가 이미 준다.
- 아비터는 클로킹 플래그 자체가 없다. 남을 클로킹시킬 뿐 자신은 항상 보이는 일반 유닛이다. 문서의 "옵저버/아비터 탐지 불가" 전제는 둘 다 틀렸다.
- 진짜 사각지대는 **버로우한 채 가만히 있는 비탐지 유닛**(공격하지 않는 럴커, 버로우 저글링, 스파이더 마인)이다. 이들은 접근 불가이며 화면에도 그려지지 않으므로 화면 인식으로도 못 본다. 럴커는 공격 중(쿨다운>0)이거나 이동 중이면 다시 접근 가능해진다.
- `canBuildHere()` 트릭은 안개 속 건물 탐지 누수였고 BWAPI Beta 3.3에서 막혔다. 클로킹 유닛용 트릭은 필요 없다(위치가 이미 노출됨).
- 실제 봇도 그렇게 쓴다: Stardust는 `(isBurrowed||isCloaked||hasPermanentCloak) && !isDetected`를 "비탐지"로 정의하고, Steamhammer는 비탐지 클로킹 적을 보면 부대에 디텍터를 배정한다.
- 결론: Visual Inspection(Shimmer CNN) 계층은 API가 주는 데이터의 열화 복사본이 된다. 삭제한다. 단, 실제 게임에서 5분 정도 `isVisible && !isDetected`인 적 유닛을 로그로 찍어 엣지 케이스를 한 번 확인할 것.

**(b) BWAPI / OpenBW / 헤드리스 실행 — 신뢰도 높음**
- 최신 릴리스는 BWAPI 4.4.0(2019). BWAPI 5는 `develop` 브랜치(CMake, protobuf 메시지, 크로스플랫폼 지향)에만 있고 미출시다. 의존하지 말 것.
- BWAPI는 브루드워 1.16.1(Windows)만 지원한다. Remastered는 미지원(2026-09에 ShieldBattery의 실험적 브리지가 나왔으나 대회 불가, 디버그 DLL 필요).
- OpenBW(오픈소스 엔진 재구현)는 Linux에서 헤드리스로 돈다. BWAPI 호환 포크는 4.2.0 API 수준이고 원본 MPQ 3개가 필요하다. 자기 보고 기준 약 1,800프레임/초(실시간의 약 75배). JBWAPI와 Stardust 개발 환경이 여기서 돈다.
- Windows 경로: bwheadless + sc-docker(Wine, BASIL 포크가 2025-07까지 유지, BWAPI 4.4.0 지원). 대회용 토너먼트 매니저는 Windows 전용.
- 실무 분리: 빠른 자가대전·평가는 OpenBW(Linux), 대회·실제 환경 검증은 1.16.1 + BWAPI 4.4.0(Windows).

**(c) Python 바인딩 — 신뢰도 높음**
- 유지되는 직접 바인딩은 없다. pybrood(BWAPI 4.1.2, 2018 중단), PyBW(2011), TorchCraft(2022 아카이브).
- 실제로 쓰이는 방식은 "32비트 C++ BWAPI 모듈/클라이언트 + IPC + 64비트 Python"이다. 예: Pluto(공유 메모리), rasdasd/starcraft-ai(TCP + FlatBuffers, 왕복 약 0.3ms, 1.16.1과 OpenBW 양쪽 지원, 2026-09 활동), MingleCraft(HTTP 루프백, 2026-09), bwapi-c2(C ABI, 초기 단계).
- JVM 대안: JBWAPI 2.2.0(순수 Java, BWAPI 4.4.0 호환, MIT, OpenBW/Linux 네이티브, 대회용 async 모드 내장, 2026-02 활동).

**(d) 대회·래더·참고 봇 — 신뢰도 중간(핵심 페이지 접근 불가, 발췌 기준)**
- AIIDE는 2025년에도 열렸다. 시간 규칙: 55ms 초과 프레임 320개 이상, 1초 초과 10개 이상, 10초 초과 1개면 패배. 외부 네트워크 허용 여부는 확인하지 못했고, 규칙 성격상 허용되지 않는다고 보는 것이 안전하다.
- IEEE CoG는 2024~2025 건너뛰고 2026 재개. 우승은 Pluto(전체 게임 RL, 3.4절).
- BASIL 래더는 Docker에서 24시간 최대 속도로 돌며 프레임 제한이 없고 30분 실시간 상한만 있다.
- 참고 봇(언어/라이선스/종족/최근 활동): Steamhammer(C++/MIT/전 종족·저그 중심/3.6.5, 소스는 satirist.org 배포), McRave(C++/MIT/전 종족·저그 최강/2026-05), PurpleWave(Scala/MIT/전 종족/2026-08), Stardust(C++/MIT+대회 포크 제한/프로토스/2026-08), UAlbertaBot(C++/MIT/2021 중단), ZZZKBot(C++/LGPLv3/저그/2025-10), Microwave(C++/GPLv3/저그/2022).
- 라이브러리: BWEM(맵 분석, 2017 동결이지만 안정), BWEB(건물 배치, 2026-04 활동), FAP(전투 시뮬, 2020), BOSS(빌드 오더 탐색, 2026-04 활동). BWTA는 사용 불가.

---

## 2. 2026년 9월 기준 모델·API 변화와 설계 영향

Blueprint v0.4(2026-02 작성)는 Strategy에 GPT-5.2 / Gemini 3.0 Pro, Tactics에 Gemini Flash / GPT-4o-mini를 전제했다. 이 보고서는 Claude 5 세대(2026-09 기준 API 가격표)를 기준으로 다시 계산했다. 다른 벤더를 써도 아래 결론(어느 레이어에 LLM을 넣고 빼야 하는가)은 바뀌지 않는다.

### 2.1 현재 모델과 가격 (Anthropic 1st-party API, $/MTok)

| 모델 | ID | 컨텍스트 | 입력 | 출력 | 캐시 읽기 | 비고 |
|---|---|---|---|---|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | 1M | 10.00 | 50.00 | 0.25 | 최상위 추론. thinking 항상 켜짐. 30일 데이터 보존 필수 |
| Claude Opus 5.5 | `claude-opus-5-5` | 1M | 4.00 | 20.00 | 0.20 | 기본 선택지. thinking 끌 수 없음(effort로만 조절, 기본 medium) |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 1M | 2.00 | 10.00 | 0.20 | `thinking: between_tools`로 사실상 thinking off 가능 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 200K | 1.00 | 5.00 | 0.10 | 가장 빠르고 저렴. thinking은 `budget_tokens` 방식 |

Batch API는 모든 토큰(캐시 포함) 50% 할인. 캐시 쓰기는 5분 TTL 기준 입력가의 1.25배.

### 2.2 설계에 직접 영향을 주는 기능 변화

| 기능 | Blueprint v0.4 가정 | 현재 | 설계 영향 |
|---|---|---|---|
| JSON 출력 | 프롬프트로 "Always output valid JSON" 부탁 | Structured outputs(`output_config.format`)로 스키마 강제, 도구 인자도 `strict: true` | 파싱 실패/필드 누락 처리 코드 대부분 불필요. 스키마 자체가 계약 |
| 추론 깊이 | 모델별 고정 | Adaptive thinking + `effort`(low~max) | 같은 모델로 "정기 점검"(low)과 "빌드 전환 판단"(high)을 나눠 호출 가능 |
| 반복 호출 비용 | 매 호출 전체 프롬프트 과금 | Prompt caching: 캐시 읽기가 입력가의 5%(Opus 5.5) | 빌드 오더 DB·유닛 스탯·규칙 등 고정 지식을 수천 토큰 넣어도 게임당 비용은 수십 센트 |
| 긴 로그 분석 | 200K 안팎, 요약 필요 | 1M 컨텍스트, 128K 출력 | 게임 한 판 전체 로그(수십만 토큰)를 한 번에 사후 분석 가능 |
| 오프라인 대량 분석 | 실시간 가격 | Batch 50% 할인 | 수백 게임 사후 분석이 몇 달러 수준 |
| 에이전트 루프 | 직접 구현 | SDK Tool Runner, 서버 도구, Managed Agents | "코치 에이전트"(로그 읽고 코드/프롬프트 고치는 오프라인 루프)를 만들기 쉬움 |
| 코드 생성 품질 | 보조 수준 | 장시간 자율 코딩(Claude Code) | 마이크로/전술의 규칙 기반 코드를 LLM이 작성·테스트·개선하는 것이 현실적 |

주의할 API 변경점(v0.4 프롬프트 설계에 그대로 영향):
- 최신 모델은 assistant prefill 불가, 강제 `tool_choice`(any/tool) 불가. JSON을 얻으려면 structured outputs를 쓴다.
- Opus 5.5는 thinking을 끌 수 없으므로 지연이 중요한 호출은 `effort: low`로 두거나 Sonnet 5.5(`between_tools`)/Haiku 4.5를 쓴다.
- 캐시는 prefix 일치 기반이다. 시스템 프롬프트/지식 DB를 앞에, 매 호출 바뀌는 게임 상태를 뒤에 둔다. 타임스탬프를 시스템 프롬프트에 넣으면 캐시가 매번 깨진다.

### 2.3 레이어별 모델 재배정 제안

| 레이어 | v0.4 | 제안 | 이유 |
|---|---|---|---|
| Strategy (실시간, 이벤트 기반) | GPT-5.2 / Gemini 3.0 Pro | **Opus 5.5** (effort low~medium, adaptive thinking, structured outputs, 캐시) / 비용 절감 시 Sonnet 5.5 | 5~30초 여유가 있으므로 상위 모델 사용 가능. 판단 품질이 곧 봇 실력 |
| Tactics (실행 계획) | Gemini Flash / GPT-4o-mini 매 0.5~2초 | **LLM 제거.** 결정적 코드(ProductionManager, BuildingPlacer, SquadManager) | 초당 1회 호출은 비용·지연·환각 모두 최악. 이 계층은 이미 "풀린 문제"(기존 BW 봇의 표준 구조) |
| Tactical Advisor (신설, 이벤트 기반) | 없음 | **Haiku 4.5** 또는 Sonnet 5.5(`between_tools`, effort low) | 교전 개시/후퇴/공격 목표처럼 "판단"이 필요한 순간만 호출(게임당 수십 회) |
| Micro | RL | 1차: 스크립트(LLM이 작성·개선) / 2차: RL | RL은 환경·보상·학습 파이프라인이 별도 프로젝트 규모 |
| Offline Coach (신설) | 없음 | **Opus 5.5** 또는 Fable 5.1, Batch, 1M 컨텍스트 | 게임 로그 전체를 읽고 패인 분석, 프롬프트/지식/코드 수정 제안. 지연 제약 없음 = 모델 개선의 이득이 가장 큰 곳 |
| 개발 | 사람 | Claude Code(에이전트) + 사람 리뷰 | 헤드리스 대전 하네스만 있으면 "코드 수정 → 대전 → 로그 → 수정" 루프를 자동화 가능 |

### 2.4 게임당 비용 추정 (15분 게임, 실시간 기준)

가정: Strategy 호출 1회 = 캐시된 프리픽스 8K + 동적 상태 2K 입력, 출력 1.5K(thinking 포함). Tactics LLM 호출 1회 = 캐시 3K + 동적 1.5K, 출력 0.4K. 사후 분석 = 입력 150K, 출력 6K.

| 구성 | 게임당 비용(USD) |
|---|---|
| Strategy, 10초 고정 호출(100회), Opus 5.5 | ≈ 4.0 |
| Strategy, 이벤트 기반(≈40회), Opus 5.5 | ≈ 1.6 |
| Strategy, 이벤트 기반(≈40회), Sonnet 5.5 | ≈ 0.8 |
| **Tactics를 LLM으로, 1초 주기(900회), Haiku 4.5** | **≈ 3.4** |
| Tactics를 LLM으로, 1초 주기(900회), Sonnet 5.5 | ≈ 6.9 |
| Tactical Advisor, 이벤트 기반(≈60회), Haiku 4.5 | ≈ 0.2 |
| 사후 분석 1회, Opus 5.5 Batch | ≈ 0.4 |
| 사후 분석 1회, Fable 5.1 Batch | ≈ 0.9 |

읽는 법:
- v0.4 구성(Strategy 10초 고정 + Tactics SLM 1초)은 게임당 약 7달러, 100게임 평가 한 번에 700달러다. 평가를 자주 돌릴 수 없는 구조는 개선 루프가 돌지 않는다.
- 제안 구성(Strategy 이벤트 기반 + Advisor 이벤트 기반 + 사후 분석)은 게임당 약 2달러 안팎이고, Strategy를 Sonnet 5.5로 두면 1달러 대다.
- 사후 분석은 1M 컨텍스트와 Batch 덕분에 게임당 1달러 미만이다. 여기에 가장 좋은 모델을 쓰는 것이 비용 대비 효과가 가장 크다.
- 숫자는 토큰 가정에 비례한다. 구현 후 `usage` 필드로 실측해 갱신할 것.

---

## 3. 선행 연구가 말해주는 것 (2023~2026)

이 프로젝트와 같은 시도(LLM 전략 + 스크립트/RL 실행)는 StarCraft II 쪽에서 2023년부터 많이 나왔다. 브루드워/BWAPI에 LLM을 붙인 논문은 찾지 못했고, 실험적 하네스 하나(MingleCraft)만 있다. 아래는 설계 결정과 직접 관련된 결과만 추렸다. 수치 일부는 논문 요약 발췌 기준이므로 인용 시 원문 확인이 필요하다.

### 3.1 LLM은 매크로(전략)에서만 쓸모가 있었다

| 연구 | 구조 | 결과 | 시사점 |
|---|---|---|---|
| TextStarCraft II / Chain of Summarization (Ma et al., NeurIPS 2024) | LLM = 매크로 액션 선택만, 마이크로는 스크립트. 프레임 요약(CoS)으로 N프레임마다 질의 | GPT-4가 내장 AI "Harder" 승리, "VeryHard"는 패배. API 모델로 한 게임에 약 7시간 | 게임이 LLM을 기다리는 락스텝 구조. 매크로 액션 추상화가 표준이 됨 |
| SwarmBrain (2024) | LLM "Overmind" + 조건반응 상태기계 "ReflexNet"로 지연 은폐 | Hard 약 76% | 반사 계층을 코드로 두고 LLM은 위에서만. 이 보고서의 구조와 같다 |
| LLM-PySC2 (NeurIPS 2025) | 전체 액션 공간을 텍스트로, 스레드로 비동기 질의 | GPT-4o-mini: Lv1~7 승률 100/100/92/50/42/8/0% | "추론 능력 향상이 곧 의사결정 향상은 아니다", 환각 심각 |
| AVA (2025, ACL Findings 2026) | VLM이 유닛을 직접 조작 | 단순 교전은 75~90%지만 **카이팅 등 고빈도 마이크로는 0%** | LLM/VLM에게 마이크로를 맡기지 말 것 |
| STAR 벤치마크 (2026) | 턴제 vs 실시간 비교 | 추론 모델은 턴제에서 우세, 실시간에서는 지연 때문에 패배("strategy–execution gap") | 실시간 경로의 호출 수와 지연을 설계로 줄여야 한다 |
| MASMP (2025) | LLM이 FSM/행동트리를 흉내 내며 전략 변수를 메모리에 유지 | Lv6 80%, Lv7 60% | 실패 유형을 명명: 환각, 국소 탐욕, 사이클 간 전략 불일치, knowing-doing gap. Plan Ledger가 필요한 이유 |
| HIMA / EpicStar (2025~2026) | 호출 수 최소화(게임당 11회), 에피소드 메모리 | CoS 대비 토큰 14.5%로 유사 성능 | 이벤트 기반 호출 + 메모리가 효과적 |

### 3.2 LLM을 실시간 루프에 넣는 것보다 오프라인에서 코드를 쓰게 하는 편이 성과가 좋았다

- **LLM-SMAC (2024)**: LLM(planner/coder/critic)이 온라인으로 행동하는 대신 결정트리 파이썬 코드를 작성 → 거의 완벽한 승률, 유사 맵 전이.
- **Compiled Agency (2026)**: Claude Code가 한 세션에서 958줄짜리 테란 컨트롤러를 작성(실행 중 LLM 호출 0회) → Elite 내장 AI 상대 14/16 승. 같은 논문에서 "매 턴 모델을 호출하는 매크로 액션 에이전트는 Elite의 4분의 1 수준". 단, 세션 간 편차가 크다(14/16, 2/16, 12/16).
- **Alpha4Gate (실무 저장소, SC2)**: Claude를 0.5초 루프 밖에 두고("생각은 잘하고 행동은 느리다") 게임 30초당 최대 1회 코치로 호출, 오프라인에서는 JSONL 로그/리플레이를 읽고 코드 수정을 제안 → 난이도 4 승률 50%→83%(자체 제안 6건). 교훈: "학습 점수는 거짓말한다", 회귀 게이트 필수.
- **LLM 플래너 vs 수작업 행동트리** 직접 비교(2026, 2v2 게임): 46.4% vs 51.5%로 유의차 없음. LLM이 실시간에서 스크립트를 이긴다는 증거는 아직 약하다.
- 반대 증거: PLAP(MicroRTS)에서 GPT-4o 제로샷이 베이스라인 80%를 이김. 소규모 게임에서는 가능하다.

시사점: **이 프로젝트에서 모델 성능 향상의 이득을 가장 크게 받는 곳은 "실시간 Strategy 호출"이 아니라 "로그를 읽고 코드와 전략을 고치는 오프라인 루프"다.** 실시간 Strategy는 유지하되 호출 수를 줄이고, 개선의 주 엔진은 코치 루프로 둔다(4.7).

### 3.3 실패 유형과 대응 (선행 연구에서 반복 보고됨)

| 실패 유형 | 보고 | 이 설계의 대응 |
|---|---|---|
| 무효/환각 액션 | StarEvolve: 검증기+SFT 전 유효 액션 비율 48% | 매크로 액션만 출력, structured outputs, Validator |
| 전략 불일치(사이클마다 바뀜) | MASMP, LLM-PySC2 | Plan Ledger, `keep_current_plan`, 최소 유지 시간 |
| 지연으로 인한 패배 | STAR, "latency-kills"(행동 지연만으로 점수 76% 하락) | 이벤트 기반 호출, 비동기 + 결과 폐기, 반사 계층은 코드 |
| 비용/시간 | TextSC2 게임당 7시간 | 캐시, delta 입력, Batch 사후 분석 |
| 실행 편차 | Compiled Agency 세션 간 편차 | 회귀 게이트(하네스)로만 채택 |

### 3.4 브루드워 마이크로: RL의 현재 위치

- 2026년 이전 상위 BW 대회 봇(PurpleWave, Stardust, BananaBrain, SAIDA, CherryPi)은 모두 스크립트 마이크로 + 전투 시뮬레이터(FAP류)로 경쟁했다. CherryPi(FAIR)는 ML을 빌드 선택·건물 배치에만 썼고 전투는 수작업이었다.
- 2016~2020년 RL 마이크로 논문(TorchCraft 기반 BiCNet, COMA 등)은 고립된 소규모 시나리오에서만 성과를 냈다.
- **2026년 변곡점: Pluto**(tscmoo). 315M 파라미터 자가대전 RL 네트워크 하나가 전 종족·전체 게임을 플레이(6프레임당 1스텝, CPU 20~60ms). CoG 2026에서 PurpleWave를 4:1로 이김. 이는 "마이크로 모듈로서의 RL"이 아니라 "전체 게임 정책으로서의 RL"이며, 대규모 자가대전 인프라가 필요하다.
- 시사점: 개인 프로젝트 1차 범위에서 RL 마이크로는 비용 대비 효과가 낮다. 스크립트 + 전투 시뮬레이터로 시작하고, RL은 Pluto 같은 공개 코드를 참고해 후순위로 둔다. AIIDE 규칙(프레임당 55ms)은 프레임 단위 정책에 실질적 제약이다.

### 3.5 지연·비용 처리 패턴 (채택할 것)

- 호출 수 줄이기: 프레임 요약(CoS), 이벤트 기반, 행동 재사용(EpicStar), 반사 계층(SwarmBrain/MASMP).
- 비동기: 스레드 질의(LLM-PySC2), 한 번에 하나만 in-flight + 응답 TTL + 실행 전 재검증 + 중복 억제(MingleCraft, 브루드워 하네스), "최신 관측만 사용, 만료된 행동 폐기"(latency-kills).
- 구조화: 옵션 ID만 출력하게 하는 합법 행동 트리(MingleCraft), 엄격한 JSON 스키마 + 검증기 우선 실행, SLM 기본 + LLM 폴백.
- 계획 캐싱: 유사 상황에서 이전 계획 재사용(Agentic Plan Caching 등). 이 프로젝트에서는 Plan Ledger로 단순하게 시작.

참고 링크는 부록 A에 모았다.

---

## 4. 개선 설계안 (Blueprint v0.5 제안)

핵심 변화는 세 가지다. (1) 실시간 경로에서 LLM 호출을 "판단이 필요한 순간"으로 제한하고 실행은 결정적 코드가 맡는다. (2) 화면 인식 계층을 제거한다. (3) 오프라인 코치 루프와 평가 하네스를 1급 구성요소로 추가한다. 모델 성능 향상의 이득은 실시간 경로보다 오프라인 루프에서 훨씬 크게 나타난다.

```
┌──────────────────────────── OFFLINE LOOP (지연 제약 없음) ────────────────────────────┐
│  Game Logs / Replays ──► Coach Agent (Opus 5.5 / Fable 5.1, Batch, 1M ctx)            │
│        ▲                     │ 패인 분석, 프롬프트·지식DB·코드 수정 제안, 테스트 작성    │
│        │                     ▼                                                        │
│  Eval Harness (헤드리스 N게임 자동 대전, 승률/지표) ◄── 제안 채택 여부는 회귀 결과로 결정  │
└────────┼──────────────────────────────────────────────────────────────────────────────┘
         │ 로그
┌────────┴───────────────────── REALTIME LOOP ───────────────────────────────────────────┐
│  BWAPI ──► State Manager ──► Summarizer(delta/요약) ──► Strategy (LLM, 이벤트 기반)     │
│               │  Tracker/Timeline/Logger/           │ 매크로 지시: 빌드, 조성, 자세, 목표 │
│               │  CombatSim(FAP)/PlanLedger          ▼                                   │
│               │                          Tactics (결정적 코드)                           │
│               │                          Production · Placement · Squad · Scout          │
│               │                                  │      ▲                                │
│               │                                  │      │ 이벤트 기반 판단(교전/후퇴/목표)  │
│               │                                  │   Tactical Advisor (Haiku 4.5, 선택)   │
│               │                                  ▼                                       │
│               │                          Micro (스크립트 → 후일 RL)                       │
│               │                                  ▼                                       │
│               └────────────────────────► Command Queue (검증) ──► BWAPI                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Input Layer: BWAPI만

- Visual Inspection 계층은 삭제한다. 시야 안의 비탐지 클로킹 유닛은 BWAPI가 위치를 노출하므로(1.3) `isDetected()==false`인 적 유닛을 State Manager가 `suspected_cloaked`로 기록하면 된다. 시야 밖 유닛은 사람도 못 본다.
- 브리지: 유지되는 Python 바인딩이 없으므로(1.3c) 5장의 선택에 따라 (B) 오픈소스 C++ 봇 + 로컬 HTTP 사이드카, 또는 (A) 32비트 C++ BWAPI 모듈 + TCP/공유 메모리 + 64비트 Python 중 하나로 확정한다. 어느 쪽이든 실제 게임은 브루드워 1.16.1 + BWAPI 4.4.0, 자동 평가는 OpenBW(Linux 헤드리스) 또는 sc-docker로 분리한다.
- 비탐지 클로킹 유닛 처리는 Tracker의 몇 줄이면 된다: `isCloaked()||isBurrowed()` 이고 `!isDetected()`인 적 유닛을 `suspected_cloaked`에 종류·위치·프레임과 함께 기록하고, 이 목록이 비어 있지 않으면 Strategy 트리거(디텍션 우선순위)와 Tactics(스포어/오버로드 배치)에 넘긴다.

### 4.2 State Manager: "사실 정리" 범위를 넓힌다

기존 Tracker / Timeline / Logger / Feedback Collector에 다음을 추가한다. 모두 판단이 아니라 계산이다.

| 추가 모듈 | 하는 일 | 왜 State Manager인가 |
|---|---|---|
| Summarizer | LLM 입력용 3단 구조 생성: 고정 지식(캐시) / 게임 누적 요약(짧은 텍스트) / 직전 호출 이후 delta | 토큰·캐시 효율. 선행 연구의 chain-of-summarization과 같은 역할 |
| CombatSim | 아군/적 부대 가치와 교전 예측(FAP류 시뮬레이터) | "이길 수 있나"의 근거를 숫자로. LLM은 결과를 읽고 판단만 |
| Plan Ledger | 현재 전략, 결정 시각, 결정 사유, 완료/실패한 목표 | flip-flop 방지. 직전 결정을 항상 입력에 포함 |
| Validator | LLM 출력이 테크트리·자원·서플라이 규칙에 맞는지 검사, 위반 시 수정 요청 또는 폐기 | 환각을 실행 전에 차단 |
| Replay/Log Store | 프레임 스냅샷(JSONL), 레이어별 I/O, 최종 결과, 리플레이 파일 경로 | 오프라인 루프의 원료 |

### 4.3 Strategy Layer (LLM): 매크로 결정만, 이벤트 기반

- 호출 트리거: 새 적 건물/테크 발견, 정찰 귀환, 대규모 교전 종료, 자원 임계(예: 미네랄 800 이상 유휴), 목표 완료, 30초 안전 주기. 대부분의 10초 구간은 호출하지 않는다.
- 출력은 매크로 지시로 제한한다. 좌표·유닛 ID·건물 ID를 출력하지 않는다.

```json
{
  "keep_current_plan": false,
  "change_reason": "적 3배럭 확인, 노가스. 마린 푸시 타이밍 5:30 예상",
  "opening": "12hatch_11pool",
  "unit_mix_target": {"drone": 0.55, "zergling": 0.35, "hydralisk": 0.10},
  "tech_priority": ["metabolic_boost", "lair", "hydralisk_den"],
  "stance": "defensive",
  "expand_policy": "allow_when_safe",
  "army_objective": {"type": "defend", "location": "natural"},
  "scout_policy": "keep_one_overlord_on_path",
  "confidence": 0.7,
  "review_after_seconds": 45
}
```

- 요청 구성(캐시 순서): [시스템 프롬프트 + 빌드 DB + 유닛/테크 규칙 요약] (cache_control) → [게임 누적 요약] → [직전 결정과 결과] → [delta 상태] → [structured output 스키마].
- 모델: Opus 5.5, adaptive thinking, effort low(정기) / medium~high(빌드 전환 트리거). structured outputs로 스키마 강제. 지연이 신경 쓰이면 Sonnet 5.5.
- 비동기 실행: 백그라운드 스레드에서 호출, 도착 시 다음 프레임에 반영. 호출 시작 이후 대규모 교전이 시작됐으면 결과를 폐기하고 재호출.

### 4.4 Tactics Layer: 결정적 코드 (LLM 없음)

기존 BW 봇들이 수년간 다듬은 표준 구조를 그대로 쓴다. 이 계층의 입력은 Strategy의 매크로 지시, 출력은 구체 명령이다.

| 모듈 | 역할 | 비고 |
|---|---|---|
| ProductionManager | 오프닝 빌드 오더 큐 실행 → 이후 `unit_mix_target`과 `tech_priority`를 만족하도록 라바/자원 배분 | 저그 특유의 라바 관리 포함 |
| BuildingPlacer | 해처리/건물 위치 선정, 확장 위치 순서 | 맵 분석 라이브러리 활용(1.3) |
| SquadManager | 부대 편성(방어/공격/정찰/수비 분산), `army_objective`에 따라 목표 지점 배정 | 유닛 ID는 여기서만 다룬다 |
| ScoutManager | 오버로드/저글링 정찰 경로, 정찰 정보 갱신 | |
| Tactical Advisor (선택, LLM) | 교전 개시·후퇴·공격 목표 변경처럼 CombatSim 수치만으로 애매한 순간에 Haiku 4.5/Sonnet 5.5에 질의(게임당 수십 회) | 없어도 동작해야 한다. 기본값은 규칙 기반 |

### 4.5 Micro Layer: 스크립트 우선, RL은 후순위

- 1차: 유닛 유형별 스크립트(저글링 서라운드/후퇴, 히드라 카이팅, 뮤탈 집중사격, 럴커 버로우 위치). 후퇴 임계는 CombatSim 결과 기반.
- 이 코드를 LLM(Claude Code)이 작성하고, "마이크로 테스트 맵"(소규모 교전 시나리오 여러 개)에서 승률로 검증하는 루프를 만든다. 사람은 리뷰만 한다.
- 2차(선택): 특정 교전 유형을 RL로 대체. 스크립트가 baseline이자 fallback이 된다.

### 4.6 Command Queue

- 검증: 유닛 존재, 명령 가능 여부, 건설 가능 위치, 자원, 프레임당 명령 수 상한.
- 우선순위: Micro 회피 명령 > Tactical Advisor > Production > 정찰.
- 모든 명령을 로그에 남긴다(누가, 왜, 어떤 상위 지시 때문에).

### 4.7 Offline Loop (신설): 코치 에이전트 + 평가 하네스

이 프로젝트에서 모델 개선의 이득이 가장 크게 나는 곳이다. 지연 제약이 없으므로 가장 좋은 모델을 Batch로 싸게 쓸 수 있다.

1. **평가 하네스**: 헤드리스로 N게임 자동 대전(맵·상대·시드 고정), 승률·평균 게임 길이·자원 유휴·유닛 손실 비율·프레임 시간·LLM 비용을 집계. 결과를 JSON으로 저장. 이것이 "개선됐다"의 유일한 기준.
2. **코치 에이전트**: 게임 로그 전체(1M 컨텍스트) + 리플레이 요약을 읽고 (a) 패인과 결정적 실수 프레임, (b) Strategy 프롬프트/빌드 DB 수정안, (c) Tactics/Micro 코드 수정안과 테스트를 낸다.
3. **채택 규칙**: 수정안은 브랜치로 만들고 하네스 회귀(같은 상대·맵·시드)를 통과해야 병합. 한 번에 하나씩.
4. 이 루프는 Claude Code가 그대로 돌릴 수 있다. 저장소에 `CLAUDE.md`(실행 방법, 테스트, 로그 위치)와 하네스 명령만 있으면 된다.

### 4.8 실행 모드

| 모드 | 설명 | 용도 |
|---|---|---|
| Lockstep | `onFrame` 안에서 LLM을 동기 호출. 게임이 기다린다 | 개발·디버깅. 지연 0, 비동기 버그 없음 |
| Realtime | LLM 비동기, 프레임 예산 준수 | 사람 상대, 실시간 평가 |
| Headless batch | 게임 속도 최대. LLM이 포함되면 Lockstep(지연 영향 제거) 또는 속도 고정 Realtime 중 하나를 명시하고 지표에 기록 | 평가 하네스 |

---

## 5. 구현 방식 비교 (가장 먼저 정해야 할 결정)

Blueprint는 "C++ / Python wrapper"라고만 적었다. 유지되는 Python 바인딩이 없다는 사실(1.3c) 때문에 이 결정이 Phase 0의 대부분을 좌우한다.

| | A. 자체 Python 봇 + C++ 브리지 | B. 오픈소스 봇을 몸체로 + LLM 두뇌 | C. JBWAPI(Java/Kotlin) 자체 봇 |
|---|---|---|---|
| 구성 | 32비트 C++ BWAPI 모듈이 프레임마다 상태를 직렬화해 64비트 Python으로 전달(TCP/공유 메모리). 전 계층을 Python으로 구현 | Steamhammer 또는 McRave(C++, MIT, 저그 강함)를 그대로 실행. 오프닝 선택·유닛 믹스·자세 같은 전략 파라미터만 Python 사이드카(LLM)가 결정해 HTTP/파일로 주입 | 순수 JVM으로 BWAPI 4.4.0 클라이언트. 브리지 불필요, OpenBW/Linux 네이티브, async 모드 내장 |
| Phase 1 baseline 도달 | 2~4주(Tactics/Micro를 처음부터, Claude Code 보조) | **즉시**(대회 수준 실행 계층 확보) | 2~4주 |
| 설계 일치도 | 문서의 아키텍처 그대로 | State Manager·Tactics는 봇 내부 구조(InformationManager 등)로 대체. Strategy·코치 루프는 문서대로 | 문서대로, 언어만 다름 |
| LLM 기여 측정 | 약한 실행 계층 위에서 측정되므로 "LLM 덕에 이겼는지, 실행이 나빠 졌는지" 분리가 어려움 | **강한 실행 계층 위에서 순수하게 전략 기여만 측정** | A와 같음 |
| 위험 | 브리지 직접 작성(참고: rasdasd/starcraft-ai), 프레임당 직렬화 비용, 32/64비트 경계 | C++ 코드베이스 학습, 남의 구조에 맞춰야 함, Steamhammer 소스가 GitHub 밖 배포 | Python 생태계(로그 분석·RL·LLM 도구)와 분리. 참고 봇(PurpleWave)이 Scala |
| 코치 루프 적합성 | Python이라 로그 분석과 코드 수정 루프가 자연스러움 | Claude Code가 C++도 다루므로 가능. 코드가 크고 성숙해서 수정 효과 검증이 오히려 쉬움 | 가능 |

**추천: B로 시작해서 필요하면 A로 옮긴다.**

이유: 이 프로젝트의 가설은 "LLM 전략층이 적응력을 준다"이지 "Tactics/Micro를 새로 짤 수 있다"가 아니다. 선행 연구(3장)는 실행 계층이 약하면 LLM이 무엇을 해도 티가 안 난다고 말한다. 기존 봇을 몸체로 쓰면 6주 안에 가설을 강한 baseline 위에서 검증할 수 있고, 그동안 만든 Python 사이드카(State 요약, Strategy 호출, Plan Ledger, Validator, 코치 루프, 평가 하네스)는 A로 옮겨도 그대로 쓴다. 검증이 끝나면 자체 봇을 짓는 것이 자기 설계를 실현하는 길이고, 그때는 무엇을 짓는지 알고 짓게 된다.

B에서의 구체 연결점:
- Steamhammer: 오프닝은 설정 파일에서 선택하고, 저그 유닛 믹스는 `StrategyBoss`가 결정한다. 두 지점에 "외부 지시가 있으면 우선"하는 훅을 넣는다.
- McRave: 빌드/전략 선택 모듈이 있고 2026년까지 활발히 유지된다. 저그 성능이 좋다는 점에서 우선 검토 대상.
- 사이드카 통신: 봇이 매 N프레임 상태 요약을 로컬 HTTP로 POST하고, 사이드카는 즉시 "직전 지시"를 응답한다(비동기). LLM 호출은 사이드카 안에서 이벤트 기반으로 일어난다. 이 방식은 MingleCraft가 2026-09에 같은 형태로 공개한 바 있다.
- 평가: sc-docker(BASIL 포크) 또는 OpenBW 헤드리스로 자동 대전. 상대 풀은 내장 AI + 수정하지 않은 원본 봇(자기 자신의 baseline) + 다른 오픈소스 봇.

A를 고를 경우: rasdasd/starcraft-ai의 방식(TCP + FlatBuffers, 1.16.1과 OpenBW 양쪽)을 참고해 브리지를 먼저 만들고, Tactics는 Steamhammer/UAlbertaBot의 매니저 구조를 그대로 옮긴다. BWEM/BWEB/FAP은 C++이므로 브리지 프로세스 쪽에 두고 결과(리전, 확장 위치, 건물 위치 후보, 전투 예측)만 Python에 넘기는 편이 낫다.

---

## 6. 실행 계획 (로드맵 v2: 수직 슬라이스)

원칙: 매 단계 끝에 "전체 게임을 끝까지 플레이하는 봇"이 있어야 한다. 레이어 하나를 완성하고 다음으로 넘어가는 대신, 얇은 전체를 먼저 만들고 두껍게 한다. 기간은 혼자 개발 + Claude Code 보조를 가정한 대략치다.

| Phase | 기간 | 산출물 | 완료 기준 |
|---|---|---|---|
| **0. 환경** | 1주 | 게임 + BWAPI 실행 환경, 브리지 선택 확정(5장), 헤드리스 실행 스크립트, 저장소 구조, `CLAUDE.md` | 명령 한 줄로 내장 AI와 1게임이 돌고 로그(JSONL)와 리플레이가 저장된다 |
| **1. Tracer bullet** | 2주 | State Manager(Tracker/Timeline/Logger), 결정적 Tactics(고정 오프닝 1개 + 단순 생산/확장/배치), 스크립트 Micro(어택무브 + 후퇴 임계), Command Queue. **LLM 없음** | 내장 AI(저그/테란/프로토스) 상대 승률 80% 이상. 이것이 baseline |
| **2. 평가 하네스** | 1~2주 | N게임 자동 대전, 지표 집계, 상대 풀(내장 AI + 오픈소스 봇 1~2개), 결과 대시보드 | `run_eval --games 30 --opponent X` 한 번으로 승률 표가 나온다 |
| **3. Strategy LLM** | 2주 | Summarizer, Plan Ledger, Validator, Strategy 호출(이벤트 기반, structured outputs, 캐시), Lockstep 모드 | 같은 상대 30게임 A/B: 고정 빌드 vs LLM 전략. 승률·비용·flip-flop 횟수 비교 |
| **4. 코치 루프** | 2주 | 게임 로그 → Opus 5.5(Batch) 사후 분석 → 수정 제안 → 하네스 회귀 → 채택. Claude Code용 워크플로 | 코치 제안으로 승률이 오른 사례 3건 이상 |
| **5. 심화** | 지속 | Realtime 비동기 모드, Tactical Advisor, 마이크로 스크립트 고도화(마이크로 테스트 맵), 오픈소스 봇 상대 승률, (선택) RL 마이크로 | 사람 상대 실시간 플레이 가능. 오픈소스 봇 상대 승률 50% 이상 |

5장에서 B(오픈소스 봇 몸체)를 고르면 Phase 1은 "봇 빌드·실행 + 로그 스키마 + 사이드카 훅"으로 바뀌고 1주 안팎으로 줄어든다. Phase 2 이후는 동일하다.

**첫 마일스톤(Phase 1 완료)까지 LLM 호출이 없다는 점이 중요하다.** 여기까지가 안 되면 LLM은 아무것도 개선할 수 없고, 여기까지가 되면 LLM의 기여를 측정할 수 있다.

### 6.1 Phase 3 A/B 설계 (핵심 가설 검증)

가설: "LLM 전략층은 상대 빌드에 적응함으로써 고정 빌드보다 다양한 상대에게 높은 승률을 낸다."

| 조건 | 설명 |
|---|---|
| Baseline | Phase 1 봇, 오프닝 고정 |
| Baseline+Random | 오프닝 3개 중 무작위 선택(적응이 아니라 다양성의 효과를 분리) |
| LLM Strategy | Opus 5.5 이벤트 기반 |
| LLM Strategy (cheap) | Sonnet 5.5 동일 설정 |

측정: 상대별 승률, 결정 횟수/게임, flip-flop(30초 안에 전략 변경) 횟수, Validator 거부율, 게임당 비용, 평균 응답 지연. 상대는 내장 AI 3종족 + 오픈소스 봇 2개, 각 30게임.

### 6.2 저장소 구조 제안

```
SC_AI/
  docs/            blueprint, 이 보고서, 결정 기록(ADR)
  knowledge/       빌드 DB(매치업별), 유닛/테크 규칙 요약 (LLM 캐시 프리픽스 원본)
  bot/             state/ tactics/ micro/ strategy/ command_queue/ bridge/
  eval/            run_eval, 상대 풀 설정, 지표 집계, 결과
  coach/           사후 분석 프롬프트, 배치 실행, 제안 → 브랜치 생성
  logs/  replays/  (git 제외)
  CLAUDE.md        실행/테스트/평가 방법. Claude Code가 자율 반복할 수 있게
```

## 7. 리스크와 열린 질문

| 리스크 | 완화 |
|---|---|
| 게임 환경 세팅(1.16.1, Windows/Wine, 헤드리스)에서 시간 소모 | Phase 0을 별도로 두고, 컨테이너화된 환경(1.3)을 우선 시도 |
| LLM 지연이 실시간에서 문제 | 개발은 Lockstep, 실시간은 비동기 + 결과 폐기 규칙. Strategy는 원래 5~30초 여유 |
| LLM의 브루드워 지식 오류 | 빌드 DB를 프롬프트에 넣고 Validator로 검증. 코치 루프에서 오류 사례를 DB에 반영 |
| 결정 흔들림(flip-flop) | Plan Ledger + `keep_current_plan` + 최소 유지 시간 |
| 비용 폭주 | 이벤트 기반 호출, 캐시, 게임당 비용 상한(초과 시 규칙 기반 fallback) |
| API 장애 | Strategy 응답이 없으면 직전 계획 유지. 봇은 LLM 없이도 완주해야 한다 |
| Tactics를 코드로 짜는 공수 | 오픈소스 봇 구조를 참고하고, 코드 작성은 Claude Code에 맡기고 사람은 리뷰 |
| 대회 출전 불가(외부 네트워크) | 비목표로 명시. 필요하면 후일 로컬 모델(SLM) 트랙 검토 |

열린 질문(사용자 결정 필요):
1. 목표를 어디에 둘 것인가: 내장 AI/오픈소스 봇 상대 승률(측정 가능) vs 사람 상대 실시간 플레이(체감). 둘 다 가능하지만 우선순위가 로드맵 순서를 정한다.
2. 구현 언어/브리지: 5장의 선택지 중 하나. Python 중심이면 브리지 리스크를 Phase 0에서 먼저 확인해야 한다.
3. 종족은 저그 고정으로 가는가. 저그는 라바 관리 때문에 Tactics 코드가 가장 복잡하다. 반면 문서의 설계는 모두 저그 기준이다.
4. 대회 출전 여부. 출전하려면 실시간 프레임 예산과 오프라인(네트워크 없음) 제약이 설계에 들어온다.

## 8. 바로 할 일

1. 이 보고서를 검토하고 열린 질문 1~4에 답을 정한다.
2. Blueprint를 v0.5로 갱신한다: Visual Inspection 삭제, Tactics를 결정적 코드로, Offline Loop·Eval Harness 추가, 모델 표 갱신, 날짜 수정.
3. Phase 0 착수: 게임 환경과 브리지를 세팅하고 "1게임 자동 실행 + 로그 저장"을 만든다.
4. 이후 Phase 1은 Claude Code에 맡길 수 있는 크기의 작업으로 쪼갠다(State Manager → Production → Squad → Micro 순).

---

## 부록 A. 참고 자료

선행 연구 (LLM × StarCraft)
- TextStarCraft II / Chain of Summarization: https://arxiv.org/abs/2312.11865 , https://github.com/histmeisah/Large-Language-Models-play-StarCraftII/
- SwarmBrain: https://arxiv.org/abs/2401.17749
- LLM-PySC2: https://arxiv.org/abs/2411.05348 , https://github.com/NKAI-Decision-Team/LLM-PySC2
- LLM-SMAC (LLM이 결정트리 코드를 작성): https://arxiv.org/abs/2410.16024
- HEP: https://arxiv.org/abs/2502.11122
- AVA (VLM 마이크로, 카이팅 0%): https://arxiv.org/abs/2503.05383
- SC2Arena / StarEvolve (검증기+SFT): https://arxiv.org/abs/2508.10428
- HIMA: https://arxiv.org/abs/2508.06042 , EpicStar: https://arxiv.org/abs/2608.12626
- MASMP: https://arxiv.org/abs/2510.18395
- STAR 벤치마크 (strategy–execution gap): https://arxiv.org/abs/2603.09337
- Compiled Agency (오프라인 작성 컨트롤러): https://arxiv.org/abs/2609.18996
- LLM 플래너 vs 행동트리 비교: https://arxiv.org/abs/2606.20014
- PLAP (MicroRTS): https://arxiv.org/abs/2509.13127
- latency-kills: https://github.com/RPG-478/latency-kills
- Alpha4Gate (Claude 코치 + 오프라인 코드 수정): https://github.com/aberson/Alpha4Gate
- RTSCortex: https://github.com/262412/RTSCortex , SunTzu: https://github.com/yorhaha/SunTzu
- MingleCraft / JevCraft (BWAPI LLM 하네스): https://github.com/minglelabs/MingleCraft , https://github.com/minglelabs/jevcraft
- 논문 목록: https://github.com/git-disl/awesome-LLM-game-agent-papers

LLM이 코드/보상을 작성하는 접근
- Voyager: https://arxiv.org/abs/2305.16291 , PolicyEvolve: https://arxiv.org/abs/2509.06053 , RL-LLM-DT: https://arxiv.org/abs/2412.11417v2
- Eureka: https://arxiv.org/abs/2310.12931 , "When LLM Reward Design Fails": https://arxiv.org/abs/2605.28918

브루드워 봇·마이크로
- Pluto (전체 게임 RL, CoG 2026): https://github.com/tscmoo/pluto
- PurpleWave: https://github.com/dgant/PurpleWave , Stardust: https://github.com/bmnielsen/Stardust
- CherryPi 회고: http://satirist.org/ai/starcraft/blog/archives/720-AIIDE-2018-what-CherryPi-learned.html
- TorchCraftAI (아카이브): https://github.com/TorchCraft/TorchCraftAI
- RL 마이크로 논문: https://arxiv.org/abs/1609.02993 , https://arxiv.org/abs/1703.10069 , https://arxiv.org/abs/1906.12266
- CoG StarCraft AI Competition: https://davechurchill.ca/starcraft/cog/

BWAPI · 환경 · 라이브러리
- BWAPI 4.4.0 소스(`UnitUpdate.cpp`, `UnitImpl.cpp`, `GameUnits.cpp`): https://github.com/bwapi/bwapi , 변경 이력: https://github.com/bwapi/bwapi/wiki/Changes , BWAPI 5 develop: https://github.com/bwapi/bwapi/tree/develop
- Remastered 미지원 논의: https://github.com/bwapi/bwapi/discussions/912 , ShieldBattery 실험 브리지: https://github.com/ShieldBattery/robotics-facility
- "BWAPI and information leaks"(클로킹 유닛 노출 설명): http://satirist.org/ai/starcraft/blog/archives/645-BWAPI-and-information-leaks.html
- OpenBW: https://github.com/OpenBW/openbw , OpenBW BWAPI 포크: https://github.com/OpenBW/bwapi , Stardust 개발 환경: https://github.com/bmnielsen/StardustDevEnvironment
- sc-docker(BASIL 포크): https://github.com/basil-ladder/sc-docker , bwheadless: https://github.com/tscmoo/bwheadless , 토너먼트 매니저: https://github.com/davechurchill/StarcraftAITournamentManager
- Python 브리지 사례: https://github.com/rasdasd/starcraft-ai , https://github.com/RadicalZephyr/bwapi-c2 , pybrood(중단): https://github.com/neumond/pybrood
- JBWAPI: https://github.com/JavaBWAPI/JBWAPI
- 봇: Steamhammer http://satirist.org/ai/starcraft/steamhammer/ , McRave https://github.com/Cmccrave/McRave , UAlbertaBot https://github.com/davechurchill/ualbertabot , ZZZKBot https://github.com/chriscoxe/ZZZKBot
- 라이브러리: BWEM https://bwem.sourceforge.net/ (커뮤니티 포크 https://github.com/N00byEdge/BWEM-community ), BWEB https://github.com/Cmccrave/BWEB , FAP https://github.com/N00byEdge/FAP , BOSS https://github.com/davechurchill/BOSS
- BASIL 규칙: https://www.basil-ladder.net/rules.html , AIIDE 2025 CFP: https://sites.google.com/ualberta.ca/aiide2025/calls/call-for-starcraft-ai-competition

Claude API (2026-09 기준)
- 모델 개요: https://platform.claude.com/docs/en/about-claude/models/overview , 가격: https://platform.claude.com/docs/en/about-claude/pricing
- Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs , Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching , Batch: https://platform.claude.com/docs/en/build-with-claude/batch-processing
