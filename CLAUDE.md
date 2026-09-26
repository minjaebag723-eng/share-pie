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

**체인 확정: Solidity + Sepolia 테스트넷** (OpenZeppelin ERC-20, Hardhat — 구현: `contracts/`, 백엔드 연동: `backend/src/blockchain/`). **정산 코어에 필수인 함수(★)를 먼저 구현한다.**

- 서버의 운영자 지갑(`DEPLOYER_PRIVATE_KEY`) 하나가 모든 트랜잭션에 서명하는 데모용 수탁 구조. 멤버 이름 → 주소는 `backend/src/blockchain/members.js`
- PieCoin: `decimals = 0` (1 PIE = 1원). 발행·정산 이동은 정산 컨트랙트만 가능 (멤버 approve 불필요)
- `BLOCKCHAIN_RPC_URL`·`CONTRACT_ADDRESS`·`DEPLOYER_PRIVATE_KEY` 중 하나라도 없으면 MOCK 모드 (`onchain.mock: true`)

| 함수 | 파라미터(개념) | 역할 | 우선순위 |
|---|---|---|:---:|
| `charge_token` | user_address, amount | PieCoin 발급(충전) | ★ 코어 |
| `open_settlement` | settlement_id, participants[], amounts[] | 정산 등록 — 누가 얼마를 잠가야 하는지 기록. lock은 등록 금액과 같아야 하고, release는 전원 잠금 후에만 가능 (팀 합의로 추가) | ★ 코어 |
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
→ `onchain`: `{ mock, recipient, viaEscrow, locks: [{ from, to, amount, txHash }], release }`
(서버가 금액을 다시 계산한다. 전원 승인 / 예산 이내가 아니면 거부)
- **돈을 받는 곳**: 기본은 **Pie(AI 정산 에이전트)의 에스크로** — 요청자 포함 전원의 분담금을 `lock_for_settlement`로 모은 뒤 `release_to_recipient`로 결제처에 지급. 사용자에게 "누가 받을지" 묻지 않는다
- `payer`는 "진우가 먼저 결제했어"처럼 명시된 경우에만 사용 → payer를 뺀 나머지만 잠그고 payer에게 지급

**POST /dispute/investigate** — body `{ originalRequest: { text, structured }, settlementPlan: { members, shares, payer }, approvalRecord, actualTransfer, dispute: { raisedBy, reason } }`
(`payer: null`이면 기록의 `to`는 에스크로(`ESCROW_RECIPIENT`)이고 전원의 송금을 비교한다)
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
⚠️ MOCK: `approvalRecord` / `actualTransfer`의 한 건 = `{ from, to, amount, txHash }` — 블록체인 SDK 확정 후 `backend/src/dispute/compareRecords.js`의 `normalizeRecords()`에서 변환.

**POST /shopping/search** — body `{ text, previousState, members, limit }` (자연어, AI가 조건 구조화) 또는 `{ conditions: { query, headcount, budget: { type: "perPerson"|"total", amount } }, members }` (AI 생략, 0 tokens)
```json
{
  "needsClarification": false, "clarificationQuestion": null,
  "conditions": { "query": "삼겹살 1kg", "headcount": 4, "budget": { "type": "perPerson", "amount": 10000 } },
  "provider": "serpapi",          // "mock"이면 fallbackReason에 이유
  "candidates": [ { "id", "name", "price", "source", "link", "thumbnail",
                    "perPerson": 8975, "shares": [...],
                    "withinBudget": true, "overBudgetBy": 0, "budgetLeft": 1025 } ],
  "bestId": "...", "settlementInput": { members, mode: "EQUAL", itemName, total, participants, totalBudget, payer },  // 그대로 /settlement/calculate에 전달 가능
  "summary": "...", "members": [...], "headcount": 4, "budget": { ... }
}
```
- 1인당 비용은 정산 코어와 같은 규칙(`computeSettlement`)으로 코드가 계산. 1인 예산은 `perPerson`(1원 차이가 나면 많이 내는 쪽 금액) 기준으로 판정
- 정렬: 예산 이내(1인당 낮은 순) → 예산 초과(초과액 적은 순)
- 검색: SerpApi Google Shopping(`SHOPPING_API_KEY`, gl=kr/hl=ko). 키 없음·에러·`SHOPPING_PROVIDER=mock`이면 목 데이터로 대체

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
BLOCKCHAIN_RPC_URL=<Sepolia RPC 주소 (Alchemy/Infura)>
CONTRACT_ADDRESS=<contracts: npm run deploy:sepolia 결과>
DEPLOYER_PRIVATE_KEY=<테스트 전용 지갑 비밀키 — 실제 자산 지갑 절대 금지>
MERCHANT_ADDRESS=<Pie 에스크로가 지급할 테스트 결제처 주소>
SHOPPING_API_KEY=<SerpApi 키 — https://serpapi.com/manage-api-key>   # 선택. 없으면 목 데이터
SHOPPING_PROVIDER=mock   # 선택. 개발 중 SerpApi 한도 아끼기
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
