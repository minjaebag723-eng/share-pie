# SharePie (쉐어파이) — Claude Code 프로젝트 지침

이 문서는 이 저장소에서 작업할 때마다 먼저 읽어야 하는 핵심 규칙입니다. 아래 원칙과 어긋나는 방식으로 코드를 짜지 마세요.

## 0. 절대 원칙 (모든 작업에 우선 적용)

1. **SharePie는 정산 서비스다. 그 이상도 이하도 아니다.** 아래 2번 구조를 항상 기준으로 삼는다.
2. **AI는 이해·판단만 한다. 금액 계산은 절대 AI(LLM)가 하지 않는다.** 산술은 항상 일반 코드(JavaScript/TypeScript)로 처리한다. (챌린지 A의 "AI/코드 역할 구분 설명" 및 "불필요한 추론 최소화" 요건을 충족하기 위해 우리 팀이 채택한 설계 원칙 — 챌린지 원문이 직접 강제하는 규칙은 아님)
3. **모든 Kiln API 호출은 어느 Stage에 속하는지 태깅하고, 그 호출의 input/output 토큰 수를 반드시 로깅한다.** (아래 5번 참고)
4. **테스트넷/데브넷 전용.** 실제 화폐, 실제 은행 계좌, 실제 메인넷 트랜잭션을 다루는 코드를 작성하지 않는다.
5. 기존 UI 자산(`Share Pie.dc.html`)의 색상·애니메이션·구조를 임의로 갈아엎지 않는다.
6. **Shopping 모듈을 만들 때 "예산 기준 비교 계산"을 절대 생략하지 않는다.** 단순히 공동구매 목록을 나열하거나 인기순으로 정렬만 하는 기능은 "agent finance"(챌린지 A의 범위) 밖이라 심사 대상이 아니다. Shopping 모듈이 유효하려면 반드시 사용자의 예산·인원 조건을 반영해 "1인당 비용"까지 계산한 뒤 후보를 비교해야 한다 — 이게 빠지면 이 모듈은 만들 이유가 없다.

## 1. 프로젝트 개요 & 선언 위계 (가장 중요)

**SharePie = AI Settlement Agent다.** 이게 유일한 Declared Function이고, README·발표·커밋 메시지 어디서도 이 위계를 흐리지 않는다.

```
                ┌─────────────────────────┐
                │   AI Settlement Agent    │   ← 코어. 이것 하나만 있어도
                │   (정산 — 유일한 메인)      │      서비스가 완성된다.
                └─────────────────────────┘
                    ▲                  │
       [선택적 확장]  │                  │  [선택적 확장]
   AI Shopping Agent │                  │  AI Dispute Agent
   "정산 전에 뭘 살지  │                  │  "정산 후 문제가 생기면
    찾는 걸 도와줌"    │                  │   조사해서 해결함"
   (없어도 정산은 됨)  └──────────────────┘  (없어도 정산은 됨)
```

**핵심**: Shopping과 Dispute는 "층"이 아니라 **정산 코어에 꽂았다 뺐다 할 수 있는 선택적 모듈**이다. 둘 다 없어도 "참여자·품목·예산을 직접 입력 → 정산"이라는 기본 흐름은 완전히 작동해야 한다.

한 문장 선언(README에 그대로 사용):
> SharePie is, at its core, an AI Settlement Agent that interprets users' natural-language cost-sharing conditions, calculates and verifies a compliant settlement, and records the approved result on-chain. Two optional modules extend it: an AI Shopping Agent that helps users find what to buy before settlement, and an AI Dispute Agent that investigates disputes after settlement.

## 2. 개발 우선순위 (반드시 이 순서)

| 순위 | 대상 | 상태 |
|---|---|---|
| **1순위** | **정산 코어** (자연어 이해 → 코드 계산 → 결과 설명) + **PieCoin 블록체인 기록** | 이것부터, 이것만으로도 데모 가능해야 함 |
| 2순위 | Dispute 모듈 연결 (이의제기 조사) | 코어 완성 후 |
| 3순위(시간 남으면만) | Shopping 모듈 연결 (상품 탐색) | 제일 마지막, 없어도 무방 |

## 3. 정산 코어 — 3단계 처리

| 단계 | 담당 | 하는 일 |
|---|---|---|
| Stage 1 | AI | 자연어 비용 분담 조건 → JSON 구조로 변환 |
| Stage 2 | **코드** | 정확한 금액 계산 + 예산 초과 여부 검증 — AI 미사용, token 0 |
| Stage 3 | AI | 계산 결과를 자연어 설명으로 생성 |

모호한 조건은 AI가 임의로 정하지 않고 되묻는다 (예: "'조금 더'가 정확히 몇 %인가요?").

**조건이 대화 중에 바뀌는 경우 (다턴 처리)**: 사용자가 "아, 진주는 5천원 적게 내자"처럼 조건을 도중에 수정하면, AI(Stage 1)는 매 턴마다 최신 상태를 반영한 새 JSON을 다시 만들어 Stage 2로 넘긴다. **Stage 2의 계산 로직(코드) 자체는 절대 바뀌지 않는다** — 매번 "그 시점의 JSON을 정확히 계산한다"는 동일한 함수를 그대로 재실행할 뿐이다. 즉 유연하게 바뀌는 것은 AI가 넘기는 입력(JSON)이고, 고정된 것은 그 입력을 처리하는 계산 로직이다.

## 4. Kiln API 연동 스펙 (확정된 값 — 임의로 바꾸지 말 것)

```
Base URL: https://api.bricksum.com/v1
Endpoint: /chat/completions
Auth: Authorization: Bearer <KILN_API_KEY>   (환경변수로 관리, 코드에 하드코딩 금지)
Model: "gpt-oss-120b"
SDK: OpenAI SDK 그대로 사용 (base_url만 위 값으로 설정)
응답의 usage.prompt_tokens / usage.completion_tokens / usage.cost를 매 호출마다 저장한다.
```

호출 스테이지 태그 (로깅 시 이 이름을 그대로 사용, **정산 코어를 항상 먼저 나열**):
- `settlement.analyze` (Stage 1, 코어)
- `settlement.explain` (Stage 3, 코어)
- `dispute.investigate` (Dispute 모듈)
- `shopping.search` (Shopping 모듈)

Stage 2(계산)는 Kiln API를 호출하지 않는다. 토큰 로그에 `settlement.calculate: 0 tokens (code-only)`로 명시한다.

## 5. 스마트 컨트랙트 함수 시그니처

체인은 아직 미확정(Move 또는 Solidity, 팀 결정 후 이 섹션 업데이트). **정산 코어에 필수인 함수(★)를 먼저 구현한다.**

| 함수 | 파라미터(개념) | 역할 | 우선순위 |
|---|---|---|:---:|
| `charge_token` | user_address, amount | PieCoin 발급(충전) | ★ 코어 |
| `lock_for_settlement` | settlement_id, participant, amount | 승인 시 분담금 잠금. **참여자의 PieCoin 잔액이 amount보다 적으면 잠금을 거부하고 에러를 반환한다 (잔액 부족 시 정산 자체가 진행되지 않음 — 일부만 잠기는 상태를 절대 허용하지 않는다).** | ★ 코어 |
| `release_to_recipient` | settlement_id, recipient | 전원 승인 완료 시 잠긴 금액 지급 | ★ 코어 |
| `refund_participant` | settlement_id, participant | 착오 판정 시 자동 환불 | Dispute 모듈 |
| `raise_dispute` | settlement_id, reason | 이의제기 접수 | Dispute 모듈 |
| `resolve_dispute` | settlement_id, verdict | 판정 결과에 따라 유지/정정/기각 실행 | Dispute 모듈 |
| `mark_offline_payment` | settlement_id, participant, confirmer | 현금 결제 확인 기록 | 후순위 |

PieCoin은 테스트넷 전용 커스텀 토큰이며 실화폐 가치가 없음을 UI 문구에도 명시한다.

## 6. API 엔드포인트 — 정산 코어를 항상 먼저 나열

```
### 정산 코어 (1순위, 이것부터 구현)
POST /settlement/analyze
POST /settlement/calculate
POST /settlement/explain
POST /settlement/approve

### Dispute 모듈 (2순위)
POST /dispute/raise
POST /dispute/investigate
POST /dispute/resolve

### Shopping 모듈 (3순위, 시간 남으면만)
POST /shopping/search   ← 반드시 예산 기준 1인당 비용 계산 포함 (0번 원칙 6 참고). 단순 목록 반환 금지.

### 후순위
POST /settlement/offline-payment
```

각 엔드포인트의 상세 입출력 스키마는 구현 중 이 파일에 추가해 나간다.

## 7. AI Dispute Agent 판정 로직

3가지 판정만 존재한다. 새로운 판정 카테고리를 임의로 추가하지 않는다:
- `NORMAL_APPROVAL` — 정상 승인이었음 → 정산 유지, 이의 기각
- `GENUINE_ERROR` — 진짜 착오·오류 → `refund_participant` 자동 호출
- `BAD_FAITH_DISPUTE` — 악의적 이의제기 → 이의 기각, 근거 기록 공개

Dispute Agent에 넘기는 조사 데이터: 최초요청 → 정산 코어 Stage1/2/3 로그 → 승인기록 → 결제기록(PieCoin/오프라인) → 온체인 기록 전체.

## 8. UI/UX — 별도 담당자가 이미 작업 중 (이 문서 범위 밖)

UI/UX 디자인·화면 제작은 별도 팀원이 전담하며 진행 중이다. 이 문서와 백엔드/블록체인 작업은 화면을 새로 만들지 않는다. 필요한 건 딱 하나: 완성된 화면에서 호출할 수 있도록 6번의 API를 스펙대로 정확히 구현하는 것.

베이스 파일 참고만 할 것(수정 대상 아님): `Share Pie.dc.html`, `support.js`, `.thumbnail`
- 배경색 `#EADFCC`, 텍스트색 `#2E1D12`, 강조색 `#C9531A`

## 9. 조건 2회 실행 데모 (Challenge A 요구조건 — 반드시 구현)

```
Run 1 (정상): 정산 코어만으로 — 예산 내 정산 → 전원 승인 → 온체인 기록 → TxHash 확보
Run 2 (이의제기): Run 1 결과에 이의제기 → Dispute 모듈이 재조사 → 판정 → 자동 실행
```
두 실행 모두 로그(AI 응답, 계산 결과, 판정 근거, TxHash)를 파일 또는 DB에 남겨 제출 자료로 캡처 가능하게 한다. **이 데모는 Shopping 모듈 없이도 완전히 성립해야 한다.**

## 10. 환경 변수

```
KILN_API_KEY=sk-bk-...
KILN_BASE_URL=https://api.bricksum.com/v1
KILN_MODEL=gpt-oss-120b
BLOCKCHAIN_RPC_URL=<확정 후 입력>
CONTRACT_ADDRESS=<배포 후 입력>
```

## 11. 하지 말 것 (반복 강조)

- AI에게 금액을 직접 계산시키지 않는다
- Shopping이나 Dispute를 정산과 동등한 메인 기능처럼 선언하지 않는다
- Shopping 모듈을 정산 코어보다 먼저 만들지 않는다
- Shopping 모듈에서 예산 기준 비교 계산을 생략하고 단순 목록/인기순 나열로 만들지 않는다 (agent finance 범위 이탈)
- Kiln API 호출에서 토큰 로깅을 생략하지 않는다
- 이의제기 판정 카테고리를 3개 밖으로 늘리지 않는다
- 메인넷/실제 결제 코드를 작성하지 않는다
- `lock_for_settlement`에서 잔액 확인을 생략하지 않는다 — 잔액 부족 시 정산이 진행되면 안 된다

## 12. 제출 전 필수 체크리스트 (README 작성 시 반드시 반영)

- README.md에 스테이지별 토큰 사용량 표를 포함할 것 (전체 합계 금지 — settlement.analyze / settlement.explain / settlement.calculate(0 tokens) / dispute.investigate를 각각 구분)
- README.md에 아래 "13번 에너지 절감 논리"를 근거로 한 에너지 소비 추정 문단을 포함할 것 (실측 데이터가 없다는 점을 숨기지 않고 명시)
- Run 1(정상 정산), Run 2(이의제기 재조사)에 더해, Run 1.5로 "예산 초과 조건으로 재호출 시 서버가 거부하는지" 시나리오를 실행하고 그 거부 로그를 캡처할 것
- Run 1/Run 2/Run 1.5 실행 시, 각 Kiln API 호출마다 "응답 값 → 그로 인해 실행된 행동"을 한 줄로 짝지어 로그에 남길 것 (예: needsClarification=false → Stage 2 진행, verdict=GENUINE_ERROR → refund_participant 호출, TxHash: ...). 단순 토큰 수 기록에 그치지 않고, API 응답이 실제 의사결정/행동을 바꾼 지점을 명시적으로 캡처할 것 — 이 로그 캡처 자체가 제출 증거물이 됨

## 13. 에너지 절감 논리 (README 작성 시 이 문단을 근거로 사용, 숫자는 실제 로그 확보 후 교체)

- 비교 기준(baseline): 만약 정산 금액 계산(Stage 2)까지 AI에게 맡겼다면, 정산 1건당 Kiln API 호출이 최소 1회 추가로 필요했을 것이다.
- 실제 설계: Stage 2는 코드로만 처리해 호출 0회(settlement.calculate: 0 tokens, code-only) — 정산 1건당 AI 호출 횟수를 줄인다.
- 다턴(멀티턴) 처리에서도 동일하게 절감된다: 조건이 대화 중 바뀌어도 Stage 2 계산 로직 자체는 그대로 재실행될 뿐 AI를 다시 부르지 않는다 — 매 턴마다 전체를 AI에게 다시 계산시키는 방식 대비 반복 호출이 발생하지 않는다.
- 가정: gpt-oss-120b는 NPU 기반으로 동작하며, 에너지 소비는 처리 토큰 수·호출 횟수에 대략 비례한다고 가정한다. 이 가정 하에 위 호출 감소는 그만큼의 에너지 소비 감소로 이어진다고 추정한다.
- 실측 전력 데이터는 없으며, 이는 명시적 가정에 근거한 추정치임을 README에서도 동일하게 밝힌다.

## 14. 용어 구분 (혼동 금지)

- "PieCoin": 정산에 쓰는 테스트넷 화폐 (스마트컨트랙트, charge_token 등). 챌린지의 토큰 사용량·에너지 항목과 무관하다.
- "AI 토큰(Kiln 토큰)": Kiln API 호출 시 소비되는 input/output 토큰. 토큰 사용량 보고와 에너지 추정은 이것만 다룬다.
- 로그·README·주석에서 그냥 "토큰"이라고만 쓰지 말고, 위 두 가지 중 어느 쪽인지 "PieCoin" 또는 "AI 토큰"으로 구분해서 쓴다.
- 에너지 소비는 실측하지 않는다. AI 토큰 수와 Kiln 호출 횟수를 에너지의 대리 지표(proxy)로 삼고, 비례한다는 가정을 명시한다. (13번 참고)
