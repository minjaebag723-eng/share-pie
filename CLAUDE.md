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

**핵심**: Shopping과 Dispute는 "층"이 아니라 **정산 코어에 꽂았다 뺐다 할 수 있는 선택적 모듈**이다. 둘 다 없어도 "참여자·품목·예산을 직접 입력 → 정산"이라는 기본 흐름은 완전히 작동해야 한다. Dispute는 코어 흐름에는 선택 모듈이지만, **제출용 Run 2 증거에는 필수**다.

한 문장 선언(README에 그대로 사용):
> SharePie is, at its core, an AI Settlement Agent that interprets users' natural-language cost-sharing conditions, calculates and verifies a compliant settlement, locks the approved amounts in escrow, releases them after the hold period, and records the result on-chain. Two optional modules extend it: an AI Shopping Agent for pre-settlement discovery, and an AI Dispute Agent for post-settlement investigation.

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
Model: Qwen3-32B — 환경변수 KILN_MODEL 로만 참조 (현재 사용 중인 ID: qwen3-32b). 아래 "모델 경위" 참고
SDK: OpenAI SDK 그대로 사용 (base_url만 위 값으로 설정)
응답의 usage.prompt_tokens / usage.completion_tokens / usage.cost를 매 호출마다 저장한다.
```

**모델 경위**: 챌린지 브리프 원문은 `gpt-oss-120b`를 명시했으나, 주최측(Bricksum)이 텔레그램 공지로 Kiln API 모델을 **Qwen3-32B**로 교체한다고 알렸다(gpt-oss-120b의 tool-calling이 해커톤에 부적합하다는 이유). 현재 개발 키에서 `gpt-oss-120b`가 404인 것도 이 공지와 일치한다. 따라서 사용 모델은 Qwen3-32B(현재 사용 중인 ID: `qwen3-32b`)이며, README에 "브리프는 gpt-oss-120b, 실제 사용은 주최측 공지에 따른 Qwen3-32B"라고 **공지 출처와 함께** 명시한다.

> ⚠️ TODO(미정): 모델 교체 공지 날짜/캡처를 README 근거 자료로 보관. (모델 ID는 qwen3-32b로 정상 동작 확인 완료)

모델명은 `KILN_MODEL` 환경변수로만 참조하고 코드에 하드코딩하지 않는다. 행사 중 모델이 또 바뀔 수 있으니, **제출 전에 실제 사용 모델로 전체 흐름(Run 1 / 1.5 / 2)을 한 번 돌려본다.**

Kiln API 모델: qwen3-32b, 컨텍스트 한도 32,768 토큰 — 프롬프트와 대화 이력은 이 한도 안에서 짧게 유지할 것

호출 스테이지 태그 (로깅 시 이 이름을 그대로 사용, **정산 코어를 항상 먼저 나열**):
- `settlement.analyze` (Stage 1, 코어)
- `settlement.explain` (Stage 3, 코어)
- `dispute.investigate` (Dispute 모듈)
- `shopping.search` (Shopping 모듈)

Stage 2(계산)는 Kiln API를 호출하지 않는다. 토큰 로그에 `settlement.calculate: 0 tokens (code-only)`로 명시한다.

## 5. 스마트 컨트랙트 함수 시그니처

**체인 확정: Solidity + Sepolia 테스트넷** (OpenZeppelin ERC-20, Hardhat — 구현: `contracts/`, 백엔드 연동: `backend/src/blockchain/`). **정산 코어에 필수인 함수(★)를 먼저 구현한다.**

- 테스트넷 확인 (공식 텔레그램, 9/28 22:29~22:30 KST, Kim | Fractalyze Ryan 답변):
  주최측 전용 테스트넷/데브넷은 없으며, 참가팀이 공개 EVM 호환 테스트넷을 자유롭게 선택해
  배포하고 tx hash + 로그를 제출하면 됨.
  단, 로컬 데브넷을 쓸 경우 주최측이 스크립트로 직접 실행할 수 있어야 함.
  우리는 공개 테스트넷인 Ethereum Sepolia를 사용하므로 해당 조건은 적용되지 않지만,
  README에 배포 스크립트 실행 명령과 컨트랙트 주소를 반드시 포함한다.

- 서버의 운영자 지갑(`DEPLOYER_PRIVATE_KEY`) 하나가 모든 트랜잭션에 서명하는 데모용 수탁 구조. 멤버 uid → 주소는 `backend/src/blockchain/members.js` (uid = UI가 붙이는 고정 사용자 번호 'u0', 'u1', …)
- **표시 이름은 절대 지갑 키로 쓰지 않는다(동명이인 충돌)** — 이름·공백이 들어오면 `INVALID_MEMBER_UID`로 거부 (MOCK 모드 포함)
- PieCoin: `decimals = 0` (1 PIE = 1원). 발행·정산 이동은 정산 컨트랙트만 가능 (멤버 approve 불필요)
- `BLOCKCHAIN_RPC_URL`·`CONTRACT_ADDRESS`·`DEPLOYER_PRIVATE_KEY` 중 하나라도 없으면 MOCK 모드 (`onchain.mock: true`) — MOCK도 같은 상태 머신·같은 에러 코드
- **상태 머신(보류형 에스크로)**: `NONE → OPENED(open) → LOCKED(마지막 lock, holdUntil = 그 시각 + holdSeconds, SettlementConfirmed = 인증서 TxHash) → RELEASED(release, holdUntil 이후)`. 보류 중 `raise_dispute → DISPUTED(동결)`, `resolve_dispute`: `NORMAL_APPROVAL`/`BAD_FAITH_DISPUTE` → LOCKED 복귀(holdUntil 유지), `GENUINE_ERROR` → CANCELLED → `refund_participant`로 각자 환불. 실제 커머스의 "구매확정 전 보류"와 같은 구조
- **판정 코드** (컨트랙트·백엔드·문서 동일): `0 = NORMAL_APPROVAL, 1 = GENUINE_ERROR, 2 = BAD_FAITH_DISPUTE`. 그 밖은 `InvalidVerdict`
- 보류 기간은 팀 결정 대기 → 상수로 박지 않고 env `SETTLEMENT_HOLD_SECONDS`(기본 600), 정산마다 `open_settlement`의 `holdSeconds`로 전달. "단순 변심" 환불은 미구현 — 환불은 오직 `GENUINE_ERROR` 판정을 통해서만

| 함수 | 파라미터(개념) | 역할 | 우선순위 |
|---|---|---|:---:|
| `charge_token` | user_address, amount | PieCoin 발급(충전) | ★ 코어 |
| `open_settlement` | settlement_id, participants[], amounts[], conditions_hash, hold_seconds | 정산 등록 — 누가 얼마를 잠가야 하는지 + 승인 조건의 keccak256 해시 + 보류 기간을 기록 → OPENED. lock은 등록 금액과 같아야 함 (팀 합의로 추가). **조건 해시 없이는 정산을 열 수 없다** (`MissingConditionsHash`), `hold_seconds` 0 허용 | ★ 코어 |
| `lock_for_settlement` | settlement_id, participant, amount | 승인 시 분담금 잠금. **참여자의 PieCoin 잔액이 amount보다 적으면 잠금을 거부하고 에러를 반환한다 (잔액 부족 시 정산 자체가 진행되지 않음 — 일부만 잠기는 상태를 절대 허용하지 않는다).** | ★ 코어 |
| `release_to_recipient` | settlement_id, recipient | LOCKED 이고 `holdUntil`이 지난 뒤에만 잠긴 총액을 지급 → RELEASED. DISPUTED·CANCELLED·RELEASED면 `InvalidStatus`, 보류 전이면 `HoldNotElapsed` | ★ 코어 |
| `refund_participant` | settlement_id, participant | CANCELLED(GENUINE_ERROR)에서만, 잠근 사람에게 잠근 금액을 에스크로에서 환불. 두 번 환불·잠근 적 없는 주소 거부 | Dispute 모듈 |
| `raise_dispute` | settlement_id, reason | LOCKED에서만 접수 → DISPUTED(동결, 지급 불가). `reasonHash` 저장, 원문은 `DisputeRaised` 이벤트에만 | Dispute 모듈 |
| `resolve_dispute` | settlement_id, verdict(0/1/2) | 판정 결과에 따라 **유지 / 환불 / 기각** 실행. DISPUTED에서만. 0·2 → LOCKED 복귀, 1 → CANCELLED(+`SettlementCancelled`). 3 이상 `InvalidVerdict` | Dispute 모듈 |
| `mark_offline_payment` | settlement_id, participant, confirmer | 현금 결제 확인 기록 — **미구현** (컨트랙트에 없음) | 후순위 |
| 조회(view): `getSettlement`, `statusOf`, `holdUntilOf`, `expectedOf`, `isLocked`, `isRefunded`, `conditionsHashOf` | settlement_id (, participant) | 상태·보류 기한·등록 금액·잠금/환불 여부·조건 해시 읽기 (트랜잭션 없음, 제3자 검증용) | 구현됨 |

PieCoin은 테스트넷 전용 커스텀 토큰이며 실화폐 가치가 없음을 UI 문구에도 명시한다.

### 5-1. 정산 상태 머신 (컨트랙트 `enum Status { None, Opened, Locked, Disputed, Released, Cancelled }`)

```
Opened ──(전원 lock 완료 시 자동)──▶ Locked ──(holdUntil 경과 후 release_to_recipient)──▶ Released
   open_settlement                  보류: holdUntil = 잠금 시각 + holdSeconds
                                    SettlementConfirmed 이벤트 = 인증서 TxHash
                                      │
                                      │ raise_dispute
                                      ▼
                                   Disputed(동결) ──resolve_dispute──▶ 0·2: Locked 복귀 (holdUntil 그대로)
                                                                     ▶ 1: Cancelled ──refund_participant × N──▶ (참여자별 환불)
```
- "REFUNDED"라는 상태는 없다. **Cancelled 상태에서 참여자별로 환불**되며 `isRefunded(id, participant)`로 확인한다.
- 에스크로 = 정산 컨트랙트 자신. 백엔드가 수령처 이름으로 쓰는 `"SharePie 정산 에스크로"`는 환경변수가 아니라 코드 상수(`ESCROW_RECIPIENT`, `backend/src/blockchain/errors.js`)다.
- **환불 돈의 출처 — 구현 완료: A안** — 전원 잠금 후 지급을 보류(`holdSeconds`)하고, 보류 중 `GENUINE_ERROR` 판정 시 에스크로(정산 컨트랙트)에서 각자에게 환불한다. **지급(Released) 이후에는 이의제기·환불이 불가능하다.**

> ⚠️ TODO(팀 확정 대기): 보류 기간 길이(`SETTLEMENT_HOLD_SECONDS` 기본 600초)와 "단순 변심" 환불 허용 여부. B(결제처 회수)·C(PieCoin 재발행)로 바꾸려면 컨트랙트 수정이 필요하다. 확정 전에는 README에 보류 기간을 확정 숫자로 쓰지 않는다.

## 6. API 엔드포인트 — 정산 코어를 항상 먼저 나열

```
### 정산 코어 (1순위, 이것부터 구현)
POST /settlement/analyze
POST /settlement/calculate
POST /settlement/explain
POST /settlement/approve
POST /settlement/release   ← 보류 기간 경과 후 지급 (release_to_recipient)

### Dispute 모듈 (2순위)
POST /dispute/raise
POST /dispute/investigate
POST /dispute/resolve

### Shopping 모듈 (3순위, 시간 남으면만)
POST /shopping/search   ← 반드시 예산 기준 1인당 비용 계산 포함 (0번 원칙 6 참고). 단순 목록 반환 금지.

### 후순위
POST /settlement/offline-payment   ← 미구현 (mark_offline_payment 컨트랙트 함수도 없음)
```

각 엔드포인트의 상세 입출력 스키마는 구현 중 이 파일에 추가해 나간다.

### 6-1. 확정된 입출력 스키마 (구현: `backend/`)

**공통 규칙**
- UI 그룹 데이터는 평행 배열이다: `members[i]` ↔ `shares[i]` ↔ `approvals[i]` (`{name, amount}` 객체 배열로 바꾸지 않는다)
- 금액은 모두 원 단위 정수. **1원 단위 + 최대잉여법**(각자 내림 후 모자란 원을 소수점이 큰 사람부터 1원씩, 동점이면 members 순서) — UI `distributeRemainder`와 동일. 합계는 항상 총액과 정확히 일치
- 정산 조건 = UI 확인 카드의 `confirmData`: `{ mode, itemName, total, participants, ratios, adjustments, items }`
  - `mode`: `"EQUAL"` 균등 / `"RATIO"` 비율 / `"ADJUST"` 차등 / `"ITEM"` 항목별 (한 정산에 한 방식만)
  - `participants`: 나눠 낼 사람 ("OO 빼고"면 제외). 빠진 멤버의 `shares`는 0
  - `ratios`: `{ "진우": 60 }` — 말하지 않은 참여자는 (100 − 말한 합)을 똑같이 나눔 (코드가 채움)
  - `adjustments`: `{ "진주": -5000, "진우": 3000 }` — 적게 = 음수, 더 = 양수. `n·X + Σdelta = total`인 공통값 X에 각자 delta를 더함
  - `items`: `[{ name, price, participants }]` — 품목마다 그 참여자끼리 나눈 뒤 합산. ITEM의 `total`은 코드가 합산
- 백엔드 결과가 UI 계산 엔진과 1원까지 같은지는 `backend/test/calculateSettlement.test.js`가 UI HTML에서 계산 함수를 직접 꺼내 무작위 비교한다
- 에러 응답은 항상 `{ "error": { "code": "...", "message": "..." } }`

**POST /settlement/analyze** — body `{ text, previousState }` (첫 턴은 `previousState: { members }`, 이후엔 직전 응답 그대로)
UI의 `parseSettlementText()`(규칙 기반 임시 해석)를 대체한다.
```json
{
  "needsClarification": false,
  "clarificationQuestion": null,
  "confirmData": { "mode": "ADJUST", "itemName": "삼겹살", "total": 35900,
                   "participants": ["진주","진우","민재","지현"],
                   "ratios": null, "adjustments": { "진주": -5000 }, "items": null },
  "members": ["진주","진우","민재","지현"],
  "shares": [5225, 10225, 10225, 10225],   // 코드(Stage 2)가 계산
  "totalBudget": null,
  "payer": null,
  "calculation": { ... }      // /settlement/calculate 결과 전체, 되묻는 중이면 null
}
```

**POST /settlement/calculate** — body `{ members, ...confirmData, totalBudget, payer }` → `{ members, shares, total, mode, modeLabel, itemName, participants, ratios, adjustments, items, totalBudget, withinBudget, overBudgetBy, payer, roundingUnit: 1, rule }`

**POST /settlement/explain** — body `{ calculatedResult }` → `{ explanation, fallback }` (`fallback: true`면 AI 대신 코드 템플릿 문장)

**POST /settlement/approve** — body `{ settlementId, title, settlement: { members, ...confirmData, totalBudget, payer }, approvals }`
→ `{ group: { members, shares, approvals, status: "정산 완료", cert }, cert: { id, kind: "cert", title, date, rows: [[이름, 금액], ...], hash, block, rule }, onchain }`
→ `onchain`: `{ mock, state: "LOCKED", settlementOnchainId, holdSeconds, holdUntil, recipient, viaEscrow, conditionsHash, conditionsCanonical, open, locks: [{ from, to, amount, txHash }], confirm: { txHash, block, holdUntil }, release: null }`, `cert.conditionsHash`
- **승인 시점에는 잠금 확정까지만**: `cert.hash`/`cert.block` = `confirm`(마지막 lock, `SettlementConfirmed`). `release`는 보류 뒤 `/settlement/release`로 따로. `group.status`는 UI 호환을 위해 `"정산 완료"` 유지 (실제 체인 상태는 `onchain.state`). body에 `holdSeconds`(선택)로 보류 기간 지정 가능
- 승인된 정산은 `backend/data/settlements.json`(git 제외, `SETTLEMENT_STORE_DIR`)에 저장된다 — release/raise/resolve/refund가 참여자·payer를 여기서 찾는다
(서버가 금액을 다시 계산한다. 전원 승인 / 예산 이내가 아니면 거부)
- **조건 해시(제3자 검증)**: 해시 대상 = approve가 재계산에 쓴 입력 `{ members, mode, itemName, total, participants, ratios, adjustments, items, totalBudget, payer }` (직접 경로는 `{ members, mode:'DIRECT', shares, payer, rule }`). `backend/src/blockchain/conditionsHash.js`가 키 정렬·공백 없는 JSON으로 정규화한 뒤 keccak256 → `open_settlement`의 `conditions_hash`로 기록. 로그(`events.jsonl`의 `settlement.approve`)에 조건 원문·정규화 문자열·해시를 남긴다
- 검증: `node contracts/scripts/verify-conditions.js <conditions.json> <settlementOnchainId 또는 open txHash>` → 원문을 다시 해시해 체인의 `conditionsHashOf`(또는 `SettlementOpened` 이벤트)와 대조, MATCH/MISMATCH 출력
- `members`·`payer`·`cert.rows`·`onchain.locks[].from`·`recipient`는 **uid 기준**이다 (표시 이름 아님).

> 🚫 통합 전 블로커: analyze/approve 입력을 uid 목록(+표시 이름 맵)으로 전환해야 한다 — 현재는 approve에 표시 이름을 넘기면 `INVALID_MEMBER_UID`(400)로 거부되므로, UI가 uid를 넘기지 않으면 승인 자체가 실패한다.

- **돈을 받는 곳**: 기본은 **Pie(AI 정산 에이전트)의 에스크로**(코드 상수 `ESCROW_RECIPIENT`) — 요청자 포함 전원의 분담금을 `lock_for_settlement`로 모은 뒤 보류가 끝나면 `release_to_recipient`로 결제처(`MERCHANT_ADDRESS`)에 지급. 사용자에게 "누가 받을지" 묻지 않는다
- `payer`는 "진우가 먼저 결제했어"처럼 명시된 경우에만 사용 → payer를 뺀 나머지만 잠그고 payer에게 지급

**POST /settlement/release** — body `{ settlementOnchainId }` → `{ settlementOnchainId, release: { txHash, block, amount }, state: "RELEASED", recipient }`. 보류 전 `409 HOLD_NOT_ELAPSED`, 분쟁 중·취소·이미 지급 `409 INVALID_STATUS`, 저장소에 없으면 `404 SETTLEMENT_NOT_FOUND`. payer가 있으면 payer에게, 없으면 결제처(`MERCHANT_ADDRESS`)로

**POST /dispute/raise** — body `{ settlementOnchainId, raisedBy(uid), reason }` → `{ settlementOnchainId, dispute: { raisedBy, reason, reasonHash, txHash, block, raisedAt }, state: "DISPUTED", txHash, block }` (코드 전용, 체인 동결). 에러: LOCKED가 아니면 `409 INVALID_STATUS`, 저장소에 없으면 `404 SETTLEMENT_NOT_FOUND`, 사유 없음·`raisedBy`가 멤버가 아니면 `400 INVALID_INPUT`, `raisedBy`가 uid 형식이 아니면 `400 INVALID_MEMBER_UID`

**POST /dispute/resolve** — body `{ settlementOnchainId, verdict, investigation? }` (verdict = 7번의 3개 중 하나, 그 밖은 `400 INVALID_VERDICT`) → `{ settlementOnchainId, resolve: { txHash, block, verdict, verdictCode }, refunds: [{ uid, amount, txHash, block, ok: true } | { uid, amount, ok: false, error: { code, message } }], state, verdict }`. `GENUINE_ERROR`면 잠근 참여자 전원에게 `refund_participant`를 순서대로 시도(한 명 실패해도 계속 — 실패 건은 `refunds[].error.code`에 `ALREADY_REFUNDED` / `NOT_LOCKED_PARTICIPANT` / `INVALID_STATUS` 등). DISPUTED가 아니면 `409 INVALID_STATUS`. AI 호출 없음 — 판정 실행은 코드 전용. 실행 결과는 `events.jsonl`에 `dispute.action`(`responseKey: verdict=…`, `action`, `resolveTxHash`, `txHashes`)으로 남긴다 (12번)

> ✅ 확정(코드 반영 완료): `/dispute/resolve`는 실행 전에 **코드의 금액 불일치 확인을 강제**한다. body에 `investigation`(`/dispute/investigate` 결과 — `mismatchDetected` 포함) 또는 investigate 입력(`originalRequest`·`settlementPlan`·`approvalRecord`·`actualTransfer`)이 있어야 하고, 후자는 서버가 `compareRecords`로 다시 확인한다. `GENUINE_ERROR`인데 불일치 없음 → `409 MISMATCH_NOT_FOUND`, 다른 verdict인데 불일치 있음 → `409 MISMATCH_UNRESOLVED`, 둘 다 없음 → `400 INVESTIGATION_REQUIRED`. 검사는 `resolve_dispute` 호출 **전**에 하므로 거부되면 온체인 트랜잭션 0건. `dispute.action` 로그에 `facts`(mismatchDetected·mismatchPoint·expected·actual)가 함께 남는다 (구현: `backend/src/settlement/settlementActions.js`).

**역할 분담**: `/dispute/investigate`는 **AI 판정만** 하고(응답에 txHash 없음 — 설계), 온체인 실행(`resolve_dispute`·`refund_participant`)은 `/dispute/resolve`가 한다.

**POST /dispute/investigate** — body `{ originalRequest: { text, structured }, settlementPlan: { members, shares, payer }, approvalRecord, actualTransfer, dispute: { raisedBy, reason } }`
(`payer: null`이면 기록의 `to`는 에스크로(코드 상수 `ESCROW_RECIPIENT`)이고 전원의 송금을 비교한다)
```json
{
  "verdict": "GENUINE_ERROR",
  "mismatchDetected": true,
  "mismatchPoint": "송금 단계",
  "expectedAmount": 45000,
  "actualAmount": 4500,
  "explanation": "..."
}
```
`mismatchPoint`는 `"계산 단계" | "승인 단계" | "송금 단계" | null`. 금액 필드는 코드가 계산하고 AI는 `verdict`·`explanation`만 만든다.
`approvalRecord` / `actualTransfer`의 한 건 = `{ from, to, amount, txHash }` (`from`·`to`는 uid 또는 에스크로 상수). 체인은 Solidity + Sepolia로 확정됐고 이 기록 형식은 그대로 유지한다 — 온체인 `locks[]`(`onchain.locks`)가 이 형식과 같아서 바로 넘길 수 있다. 형식 검증은 `backend/src/dispute/compareRecords.js`의 `normalizeRecords()`가 한다.

**POST /shopping/search** — body `{ text, previousState, members, limit }` (자연어, AI가 조건 구조화) 또는 `{ conditions: { query, headcount, budget: { type: "perPerson"|"total", amount } }, members }` (AI 생략, 0 tokens)
```json
{
  "needsClarification": false, "clarificationQuestion": null,
  "conditions": { "query": "삼겹살 1kg", "headcount": 4, "budget": { "type": "perPerson", "amount": 10000 } },
  "provider": "serpapi", "engine": "naver", "cached": false,   // "mock"이면 fallbackReason에 이유
  "candidates": [ { "id", "name", "price", "source", "link", "thumbnail",
                    "perPerson": 8975, "shares": [...],
                    "withinBudget": true, "overBudgetBy": 0, "budgetLeft": 1025 } ],
  "bestId": "...", "settlementInput": { members, mode: "EQUAL", itemName, total, participants, totalBudget, payer },  // 그대로 /settlement/calculate에 전달 가능
  "summary": "...", "members": [...], "headcount": 4, "budget": { ... }
}
```
- 1인당 비용은 정산 코어와 같은 규칙(`computeSettlement`)으로 코드가 계산. 1인 예산은 `perPerson`(1원 차이가 나면 많이 내는 쪽 금액) 기준으로 판정
- 정렬: 예산 이내(검색 관련도 순 유지) → 예산 초과(초과액 적은 순). `bestId` = 예산 안에서 가장 관련도 높은 상품, `cheapestId` = 예산 안에서 1인당 가장 싼 상품
- 검색: SerpApi 키 하나로 `SHOPPING_ENGINES`(기본 `naver,google_shopping`) 순서대로 시도, 상품이 나오면 멈춤(한도 1회). 네이버는 기본 `price`(쿠폰가 제외)
- 결과 저장: 같은 엔진+검색어는 `SHOPPING_CACHE_TTL_HOURS`(기본 12)시간 동안 `backend/cache/`에서 재사용 (git 제외)
- 키 없음·에러·결과 없음·`SHOPPING_PROVIDER=mock`이면 목 데이터로 대체

## 7. AI Dispute Agent 판정 로직

3가지 판정만 존재한다. 새로운 판정 카테고리를 임의로 추가하지 않는다:
- `NORMAL_APPROVAL` — 정상 승인이었음 → 정산 유지, 이의 기각
- `GENUINE_ERROR` — 진짜 착오·오류 → `refund_participant` 자동 호출
- `BAD_FAITH_DISPUTE` — 악의적 이의제기 → 이의 기각, 근거 기록 공개

**verdict별 온체인 동작** (컨트랙트 코드 값과 동일):

| verdict | 코드 | `resolve_dispute` 후 상태 | 온체인 동작 |
|---|:---:|---|---|
| `NORMAL_APPROVAL` | 0 | Locked 복귀 | 정산 유지, 이의 기각. 보류가 끝나면 `release_to_recipient` 가능 |
| `GENUINE_ERROR` | 1 | Cancelled | `refund_participant`를 참여자마다 호출 (에스크로 → 각자 지갑). 이후 지급 불가 |
| `BAD_FAITH_DISPUTE` | 2 | Locked 복귀 | 이의 기각, 근거(사유 해시·판정) 온체인 기록 공개 |

- Disputed 상태 동안 `holdUntil`은 **정지·연장 없이 그대로 흐른다**(컨트랙트 `resolve_dispute`는 `holdUntil`을 건드리지 않음). Locked 복귀 시 보류 시간이 남아 있으면 그만큼 더 기다리고, 이미 지났으면 바로 `release` 가능하다.

Dispute Agent에 넘기는 조사 데이터: 최초요청 → 정산 코어 Stage1/2/3 로그 → 승인기록 → 결제기록(PieCoin/오프라인) → 온체인 기록 전체.

## 8. UI/UX — 별도 담당자가 이미 작업 중 (이 문서 범위 밖)

UI/UX 디자인·화면 제작은 별도 팀원이 전담하며 진행 중이다. 이 문서와 백엔드/블록체인 작업은 화면을 새로 만들지 않는다. 필요한 건 딱 하나: 완성된 화면에서 호출할 수 있도록 6번의 API를 스펙대로 정확히 구현하는 것.

베이스 파일 참고만 할 것(수정 대상 아님): `Share Pie.dc.html`, `support.js`, `.thumbnail`
- 배경색 `#EADFCC`, 텍스트색 `#2E1D12`, 강조색 `#C9531A`

## 9. 조건 2회 실행 데모 (Challenge A 요구조건 — 반드시 구현)

```
Run 1 (정상):        정산 코어 — 예산 내 정산 → 전원 승인 → open / lock × N / confirm 온체인 기록 → TxHash 확보(인증서 = SettlementConfirmed).
                    보류 기간(holdUntil)이 지난 뒤 release까지 실행하면 Released
                    (contracts: npm run run1:sepolia → 보류 뒤 npm run release:sepolia -- <settlementOnchainId>)
Run 1.5 (조건 변경 → 코드 중단): ① 예산 40,000→30,000으로 재호출 → OVER_BUDGET(409) ② u3 잔액 100 PIE만 충전 후 승인 → 잠금 전 잔액 선확인에서 INSUFFICIENT_BALANCE(409)
                    → 둘 다 온체인 트랜잭션 0건, AI 호출 0회. events.jsonl에 settlement.abort("… → 코드 판정 OVER_BUDGET → 중단 (잠금 0건)") 캡처
                    (contracts: npm run run1.5:sepolia)
Run 2 (이의제기):    별도 정산 — 합의 조건 해시는 그대로, 등록·잠금 금액만 [8975×4]로 주입(계산 단계 착오 시뮬레이션, 12번 확정 참고)
                    → raise_dispute(동결) → dispute.investigate(계산 단계 불일치: u0 5,225 vs 8,975 → GENUINE_ERROR)
                    → resolve_dispute(코드가 불일치 확인 강제) → Cancelled → refund_participant × 4 → 부족분 충전 → 올바른 조건으로 정정 정산(LOCKED)
                    (contracts: npm run run2:sepolia — Run 1 로그 없이 단독 실행)
일괄:               npm run preflight(배포 전 점검, 트랜잭션 없음) → npm run demo:all(preflight → Run 1 → 1.5 → 2 → 보류 지났으면 release → verify)
                    → backend/logs/demo-<timestamp>/summary.md (트랜잭션 표+탐색기 링크, 단계별 AI 토큰 표, AI 응답→행동 로그, verify MATCH). MOCK 모드에서도 끝까지 돈다
```
- **지급(Released) 이후에는 이의제기가 불가능**하다. Run 1의 정산을 Run 2에 재사용하려면 release 전에 이의제기해야 하므로, 그 경우 Run 1은 Released로 끝나지 않는다. → **Run 2는 별도 정산으로 실행하는 것을 기본**으로 한다 (Run 1은 Released까지, Run 2는 새 정산을 Locked 상태에서).

> ⚠️ TODO(미정): 데모용 보류 기간(`SETTLEMENT_HOLD_SECONDS`)을 어떻게 잡을지 — Run 1의 release를 발표 중에 보이려면 짧게, 실사용 시나리오를 설명하려면 길게. 팀 결정 후 README에 반영.

세 실행 모두 로그(AI 응답, 계산 결과, 판정 근거, TxHash)를 파일 또는 DB에 남겨 제출 자료로 캡처 가능하게 한다. **이 데모는 Shopping 모듈 없이도 완전히 성립해야 한다.**

## 10. 환경 변수

```
# Kiln (필수)
KILN_API_KEY=sk-bk-...
KILN_BASE_URL=https://api.bricksum.com/v1
KILN_MODEL=qwen3-32b            # 주최측 공지에 따른 Qwen3-32B (브리프는 gpt-oss-120b) — 4번 참고

# 블록체인 (Sepolia 테스트넷 전용) — 셋 중 하나라도 비어 있으면 MOCK 모드
BLOCKCHAIN_RPC_URL=<Sepolia RPC 주소 (Alchemy/Infura)>
CONTRACT_ADDRESS=<contracts: npm run deploy:sepolia 결과>
DEPLOYER_PRIVATE_KEY=<테스트 전용 지갑 비밀키 — 실제 자산 지갑 절대 금지>
MERCHANT_ADDRESS=<Pie 에스크로가 지급할 테스트 결제처 주소>   # payer 없는 정산의 release 수령처. 실제 체인 모드에서 필수
SETTLEMENT_HOLD_SECONDS=600     # 선택(기본 600). 전원 잠금 후 지급까지 보류(초). 보류 기간·"단순 변심" 환불은 팀 결정 대기 — 정해지면 여기만 바꾼다
SETTLEMENT_STORE_DIR=           # 선택(기본 backend/data). 승인된 정산 기록(settlements.json) 저장 폴더 — 테스트는 임시 폴더로

# Shopping 모듈 (선택)
SHOPPING_API_KEY=<SerpApi 키 — https://serpapi.com/manage-api-key>   # 선택. 없으면 목 데이터
SHOPPING_PROVIDER=mock          # 선택. 개발 중 SerpApi 한도 아끼기
SHOPPING_ENGINES=naver,google_shopping   # 선택(기본 naver,google_shopping). 검색 엔진 시도 순서
SHOPPING_CACHE_TTL_HOURS=12     # 선택(기본 12). 같은 엔진+검색어 결과 재사용 시간
SHOPPING_CACHE_DIR=             # 선택(기본 backend/cache). 검색 캐시 폴더

# 서버·로그 (선택)
PORT=3000                       # 선택(기본 3000)
LOG_DIR=                        # 선택(기본 backend/logs). token-usage.jsonl · events.jsonl 위치
UI_FILE=                        # 선택. 서버가 / 에서 보여줄 UI HTML 파일명 (없으면 루트의 Share*.html 중 최신)
```
- `ESCROW_RECIPIENT`는 환경변수가 아니라 코드 상수다 (5-1 참고).
- `NODE_ENV=test`는 테스트 실행 시에만 쓰인다(콘솔 로그 억제).

## 11. 하지 말 것 (반복 강조)

- AI에게 금액을 직접 계산시키지 않는다
- Shopping이나 Dispute를 정산과 동등한 메인 기능처럼 선언하지 않는다
- Shopping 모듈을 정산 코어보다 먼저 만들지 않는다
- Shopping 모듈에서 예산 기준 비교 계산을 생략하고 단순 목록/인기순 나열로 만들지 않는다 (agent finance 범위 이탈)
- Kiln API 호출에서 토큰 로깅을 생략하지 않는다
- 이의제기 판정 카테고리를 3개 밖으로 늘리지 않는다
- 메인넷/실제 결제 코드를 작성하지 않는다
- `lock_for_settlement`에서 잔액 확인을 생략하지 않는다 — 잔액 부족 시 정산이 진행되면 안 된다
- 모델명을 코드에 하드코딩하지 않는다 (`KILN_MODEL` 환경변수로만 참조)
- 코드의 금액 불일치 확인(`compareRecords`) 없이 AI verdict만으로 환불을 실행하지 않는다

> ✅ 확정(코드 반영 완료): 위 두 규칙은 코드에서 강제된다. ① 모델명 기본값 삭제 — `KILN_MODEL`이 비어 있으면 `kilnClient`가 `KilnConfigError`를 던져 AI 엔드포인트가 `503 KILN_NOT_CONFIGURED`로 거부되고, `/health`에 `kilnModelConfigured: false, model: null`로 드러난다 (서버 시작 시 경고 출력). ② `/dispute/resolve`의 불일치 확인 강제는 6-1 참고. 테스트: `backend/test/api.test.js`(모델 미설정 503), `backend/test/blockchain.test.js`(MISMATCH_NOT_FOUND / MISMATCH_UNRESOLVED / INVESTIGATION_REQUIRED / compareRecords 경로).

## 12. 제출 전 필수 체크리스트 (README 작성 시 반드시 반영)

- README.md에 스테이지별 토큰 사용량 표를 포함할 것 (전체 합계 금지 — settlement.analyze / settlement.explain / settlement.calculate(0 tokens) / dispute.investigate를 각각 구분)
- README.md에 아래 "13번 에너지 절감 논리"를 근거로 한 에너지 소비 추정 문단을 포함할 것 (실측 데이터가 없다는 점을 숨기지 않고 명시)
- Run 1(정상 정산), Run 2(이의제기 재조사)에 더해, Run 1.5로 "예산 초과 조건으로 재호출 시 서버가 거부하는지" 시나리오를 실행하고 그 거부 로그를 캡처할 것
- Run 1/Run 2/Run 1.5 실행 시, 각 Kiln API 호출마다 "응답 값 → 그로 인해 실행된 행동"을 한 줄로 짝지어 로그에 남길 것 (예: needsClarification=false → Stage 2 진행, verdict=GENUINE_ERROR → refund_participant 호출, TxHash: ...). 단순 토큰 수 기록에 그치지 않고, API 응답이 실제 의사결정/행동을 바꾼 지점을 명시적으로 캡처할 것 — 이 로그 캡처 자체가 제출 증거물이 됨
- Run 2 로그에서 `events.jsonl`의 `dispute.action` 한 줄(`verdict=GENUINE_ERROR → refund_participant × N → txHashes`)을 캡처할 것
- `node contracts/scripts/verify-conditions.js <조건 JSON> <settlementOnchainId>`의 `✅ MATCH` 출력을 캡처할 것 (제3자 검증 증거)
- Sepolia Etherscan 링크를 트랜잭션별로 남길 것: open, lock(전원), confirm(마지막 lock), release, raise, resolve, refund(각자)
- README에 Sepolia 배포 스크립트 실행 명령(npx hardhat run ... --network sepolia)과 배포된 컨트랙트 주소(PieCoin, SharePieSettlement)를 포함했는지 확인
- README에 한계로 명시: "운영자 지갑 하나(`DEPLOYER_PRIVATE_KEY`)가 모든 트랜잭션에 서명하는 데모용 수탁 구조" (멤버가 직접 서명하지 않음)
- README에 "Run 2의 착오는 의도적으로 주입한 시뮬레이션"임을 명시할 것. 단, 컨트랙트는 lock 금액을 등록 금액과 같게 강제하므로 "조건과 다른 금액이 온체인에 잠긴다"고 쓰면 모순이다 — 착오는 온체인 금액이 아니라 **조사 입력**(이의제기 사유·비교 기록) 쪽에 있다고 서술한다

> ✅ 확정 — Run 2 주입 방식 = **A안(계산 단계 착오 시뮬레이션)**, 구현 `contracts/scripts/run2-dispute.js`. 합의 조건(ADJUST, 진주(u0) −5,000 → 올바른 분담 [5225, 10225, 10225, 10225], 예산 40,000)의 **해시는 그대로** `open_settlement`에 기록하고, **등록·잠금 금액만** 균등 [8975 × 4]로 바꿔 넣는다 (`INJECTED_ERROR: shares replaced`, `events.jsonl`에 `run2.injected_error`). lock 금액 = 등록 금액 규칙은 그대로 지켜지므로 컨트랙트와 모순이 없다. 조사 입력은 `originalRequest.structured` = 합의 조건, `settlementPlan.shares` = 주입값, `approvalRecord`·`actualTransfer` = 온체인 locks → `compareRecords`가 **"계산 단계"** 불일치(u0 기대 5,225 vs 실제 8,975)를 검출 → AI는 기존 규칙대로 `GENUINE_ERROR`만 낼 수 있음(규칙 확장 없음) → `resolve_dispute` → `refund_participant` × 4 → 부족분 충전 후 올바른 조건으로 정정 정산(LOCKED, 같은 조건 해시 → verify MATCH). README 문장(코드·문서 동일): **"Run 2의 착오는 의도적으로 주입한 시뮬레이션이며, 온체인에 잠긴 금액이 합의 조건(해시)과 다르게 등록된 '계산 단계 착오'로 만들어진다."** 위 항목의 "조사 입력 쪽" 서술은 A안에서는 이 문장으로 대체해 읽는다. 검증: `contracts/test/SharePieSettlement.test.js`(A안 통합), `backend/test/blockchain.test.js`(demo-all MOCK).

## 13. 에너지 절감 논리 (README 작성 시 이 문단을 근거로 사용, 숫자는 실제 로그 확보 후 교체)

- 비교 기준(baseline): 만약 정산 금액 계산(Stage 2)까지 AI에게 맡겼다면, 정산 1건당 Kiln API 호출이 최소 1회 추가로 필요했을 것이다.
- 실제 설계: Stage 2는 코드로만 처리해 호출 0회(settlement.calculate: 0 tokens, code-only) — 정산 1건당 AI 호출 횟수를 줄인다.
- 다턴(멀티턴) 처리에서도 동일하게 절감된다: 조건이 대화 중 바뀌어도 Stage 2 계산 로직 자체는 그대로 재실행될 뿐 AI를 다시 부르지 않는다 — 매 턴마다 전체를 AI에게 다시 계산시키는 방식 대비 반복 호출이 발생하지 않는다.
- 가정: Kiln API가 제공하는 모델은 NPU 기반으로 동작한다고 **가정**하며, 에너지 소비는 처리 AI 토큰 수·호출 횟수에 대략 비례한다고 **가정**한다. 이 가정 하에 위 호출 감소는 그만큼의 에너지 소비 감소로 이어진다고 추정한다. (모델은 4번 경위대로 바뀔 수 있으므로 특정 모델명에 묶지 않는다)
- 실측 전력 데이터는 없으며, 이는 명시적 가정에 근거한 추정치임을 README에서도 동일하게 밝힌다.

## 14. 용어 구분 (혼동 금지)

| 용어 | 뜻 |
|---|---|
| SharePie | 서비스/앱 전체 이름 |
| Pie(정산 에이전트) | 정산 코어 AI 에이전트. 에스크로 계정의 주체 |
| PieMate | UI 챗봇 마스코트 이름 (화면 표기용. 백엔드·컨트랙트 식별자로 쓰지 않음) |
| PieCoin(PIE) | Sepolia 테스트넷 ERC-20. decimals 0, 1 PIE = 1원 표시, 실화폐 가치 없음. 챌린지의 토큰 사용량·에너지 항목과 무관 |
| AI 토큰 | Kiln API 호출의 input/output 토큰. 토큰 사용량 보고·에너지 추정은 이것만 다룬다 |

- 로그·README·주석에서 그냥 "토큰"이라고만 쓰지 말고, "PieCoin" 또는 "AI 토큰"으로 구분해서 쓴다.
- 에너지 소비는 실측하지 않는다. AI 토큰 수와 Kiln 호출 횟수를 에너지의 대리 지표(proxy)로 삼고, 비례한다는 가정을 명시한다. (13번 참고)

> ⚠️ TODO(미정): "파이 페이(Pie Pay)" 용어 정의 — UI는 파이페이, 코드·문서는 PieCoin만 쓰고 있어 관계 정의 필요.

## 15. 심사 배점 (DRAFT — 변경 가능)

출처: 현장 킥오프(9/28) 발표 슬라이드('DRAFT' 표시). 챌린지 원문 문서에는 배점이 없고, 현장 공지가 바뀌면 이 표도 바꾼다.

| 항목 | 배점 | 보는 것 |
|---|:---:|---|
| Technical | 30 | Kiln & on-chain, conditions(조건 준수·검증 가능성) |
| Task fit | 25 | README 선언과의 일치 |
| Innovation | 20 | 에이전트라서 새로운 것 |
| Usability | 15 | 실제 사용자, 실제 문제 |
| Presentation | 10 | README·데모 명확성 |
