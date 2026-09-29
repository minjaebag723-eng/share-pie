# SharePie (쉐어파이) — Claude Code 프로젝트 지침

이 문서는 이 저장소에서 작업할 때마다 먼저 읽어야 하는 핵심 규칙입니다. 아래 원칙과 어긋나는 방식으로 코드를 짜지 마세요.

> **2026-09-29 개정**: 최종 제출 시스템은 풀스택 개발자의 **Python 백엔드(`share-pie-ai` v39)** 와 그 안의 컨트랙트 **`ShareLedger.sol` + `PieToken.sol`(Ethereum Sepolia)** 이다. 이 저장소의 Node 백엔드(`backend/`)와 `SharePieSettlement` 컨트랙트(`contracts/`)는 **참고·부품용**으로만 남긴다. 5~12번은 최종 시스템 기준으로 다시 썼고, 블록체인 도구·증거는 `python-blockchain-kit/`와 `docs/evidence/`에 있다.

## 0. 절대 원칙 (모든 작업에 우선 적용)

1. **SharePie는 정산 서비스다. 그 이상도 이하도 아니다.** 아래 2번 구조를 항상 기준으로 삼는다.
2. **AI는 이해·판단만 한다. 금액 계산은 절대 AI(LLM)가 하지 않는다.** 산술은 항상 일반 코드(최종본: Python `agent/money.py`)로 처리한다. (챌린지 A의 "AI/코드 역할 구분 설명" 및 "불필요한 추론 최소화" 요건을 충족하기 위해 우리 팀이 채택한 설계 원칙 — 챌린지 원문이 직접 강제하는 규칙은 아님)
3. **모든 Kiln API 호출은 어느 Stage에 속하는지 태깅하고, 그 호출의 input/output 토큰 수를 반드시 로깅한다.** (아래 4번 참고)
4. **테스트넷/데브넷 전용.** 실제 화폐, 실제 은행 계좌, 실제 메인넷 트랜잭션을 다루는 코드를 작성하지 않는다. 메인넷 chainId는 배포 스크립트·설정 단계에서 거부한다.
5. UI/UX 팀이 만든 화면(`frontend/index.html`, `sp-bridge.js`)의 색상·구조를 임의로 갈아엎지 않는다.
6. **Shopping 모듈을 만들 때 "예산 기준 비교 계산"을 절대 생략하지 않는다.** 단순히 공동구매 목록을 나열하거나 인기순으로 정렬만 하는 기능은 "agent finance"(챌린지 A의 범위) 밖이라 심사 대상이 아니다. Shopping 모듈이 유효하려면 반드시 사용자의 예산·인원 조건을 반영해 "1인당 비용"까지 계산한 뒤 후보를 비교해야 한다 — 이게 빠지면 이 모듈은 만들 이유가 없다.
7. **AI는 온체인 함수를 직접 부르지 않는다.** AI 응답(규칙 JSON·판정)을 코드가 검증한 뒤 코드가 호출한다.

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

한국어 한 문장(README, 실제 구현 기준):
> 사용자가 말로 정한 분담 조건과 지출 한도(1인·총 한도, 허용 판매처)를 AI가 해석하고, 코드가 금액을 계산·검증해 규칙을 통과한 경우에만 참여자가 MetaMask로 직접 Ethereum Sepolia 테스트넷 에스크로(ShareLedger)에 테스트 토큰 PieCoin을 예치하며, 위반 시 결제 없이 중단 기록(`Blocked`)이, 이의제기 시 AI 판정과 환불 기록(`DisputeResolved`·`Refunded`)이 온체인에 남는다.

## 2. 개발 우선순위 (반드시 이 순서)

| 순위 | 대상 | 상태 |
|---|---|---|
| **1순위** | **정산 코어** (자연어 이해 → 코드 계산 → 결과 설명) + **PieCoin 블록체인 기록** | ✅ 완료 (Sepolia 실체인 Run 1 증거) |
| 2순위 | Dispute 모듈 연결 (이의제기 조사) | ✅ 완료 (Run 2 증거: GENUINE_ERROR → 환불) |
| 3순위 | Shopping 모듈 연결 (상품 탐색, SerpApi 네이버→구글) | ✅ 완료 (1인당 비용 비교 포함) |

## 3. 정산 코어 — 3단계 처리

| 단계 | 담당 | 하는 일 |
|---|---|---|
| Stage 1 | AI | 자연어 비용 분담 조건 → JSON 구조로 변환 (`settlement.analyze`) |
| Stage 2 | **코드** | 정확한 금액 계산 + 지출 통제 검증 (합계=총액 · 1인/총 한도 · 허용 판매처 · 체인 가용 잔액 · 한글 금액 오파싱 가드) — AI 미사용, token 0 (`settlement.calculate` / `settlement.policy`) |
| Stage 3 | AI | 계산 결과를 자연어 설명으로 생성 (`settlement.explain`) |

모호한 조건은 AI가 임의로 정하지 않고 되묻는다 (예: "'조금 더'가 정확히 몇 %인가요?"). 되묻기는 **한 번에 한 가지만**.

**조건이 대화 중에 바뀌는 경우 (다턴 처리)**: 사용자가 "아, 진주는 5천원 적게 내자"처럼 조건을 도중에 수정하면, AI(Stage 1)는 매 턴마다 최신 상태를 반영한 새 JSON을 다시 만들어 Stage 2로 넘긴다. **Stage 2의 계산 로직(코드) 자체는 절대 바뀌지 않는다** — 매번 "그 시점의 JSON을 정확히 계산한다"는 동일한 함수를 그대로 재실행할 뿐이다. 즉 유연하게 바뀌는 것은 AI가 넘기는 입력(JSON)이고, 고정된 것은 그 입력을 처리하는 계산 로직이다.

## 4. Kiln API 연동 스펙 (확정된 값 — 임의로 바꾸지 말 것)

```
Base URL: https://api.bricksum.com/v1
Endpoint: /chat/completions
Auth: Authorization: Bearer <KILN_API_KEY>   (환경변수로 관리, 코드에 하드코딩 금지)
Model: Qwen3-32B — 환경변수 KILN_MODEL 로만 참조 (현재 사용 중인 ID: qwen3-32b). 아래 "모델 경위" 참고
응답 형식: KILN_TOOL_MODE=json 고정 — 이 키·모델 조합은 tool calling 응답의 arguments 가 빈 문자열로 와서
           감면 조건 무시·판정 기본값으로 떨어진다 (2026-09-29 실측). auto/tools 로 바꾸지 말 것.
응답의 usage.prompt_tokens / usage.completion_tokens 를 매 호출마다 저장한다.
```

**모델 경위**: 챌린지 브리프 원문은 `gpt-oss-120b`를 명시했으나, 주최측(Bricksum)이 텔레그램 공지로 Kiln API 모델을 **Qwen3-32B**로 교체한다고 알렸다(gpt-oss-120b의 tool-calling이 해커톤에 부적합하다는 이유). 현재 개발 키에서 `gpt-oss-120b`가 404인 것도 이 공지와 일치한다. 따라서 사용 모델은 Qwen3-32B(현재 사용 중인 ID: `qwen3-32b`)이며, README에 "브리프는 gpt-oss-120b, 실제 사용은 주최측 공지에 따른 Qwen3-32B"라고 **공지 출처와 함께** 명시한다.

> ⚠️ TODO(미정): 모델 교체 공지 날짜/캡처를 README 근거 자료로 보관. (모델 ID는 qwen3-32b로 정상 동작 확인 완료)

모델명은 `KILN_MODEL` 환경변수로만 참조하고 코드에 하드코딩하지 않는다. 행사 중 모델이 또 바뀔 수 있으니, **제출 전에 실제 사용 모델로 전체 흐름(Run 1 / 1.5 / 2)을 한 번 돌려본다.**

Kiln API 모델: qwen3-32b, 컨텍스트 한도 32,768 토큰 — 프롬프트와 대화 이력은 이 한도 안에서 짧게 유지할 것. 사용자별 AI 구독 한도(`agent/quota.py`, Free 5시간)는 베타 동안 `BETA_PLAN=max20`으로 해제한다.

호출 스테이지 태그 (로깅 시 이 이름을 그대로 사용, **정산 코어를 항상 먼저 나열**):
- `settlement.analyze` (Stage 1, 코어)
- `settlement.explain` (Stage 3, 코어)
- `dispute.investigate` (Dispute 모듈)
- `shopping.search` / `shopping.explain` (Shopping 모듈)
- `assistant.step` (Pie 대화 에이전트)

Stage 2(계산)와 지출 통제·기록 대조·검색·1인 비용 계산은 Kiln API를 호출하지 않는다. 토큰 로그에 `settlement.calculate: 0 tokens (code-only)` 식으로 명시한다. 보고서: `GET /api/usage/report.md` (단계별 표 · 응답→행동 기록 · 에너지 상한).

## 5. 스마트 컨트랙트 (최종본: `ShareLedger.sol` + `PieToken.sol`, Ethereum Sepolia)

**체인 확정: Solidity 0.8.24 + OpenZeppelin, Ethereum Sepolia 테스트넷 (chainId 11155111)**. 주최측 공용 테스트넷은 없고(텔레그램 확인 9/28) 팀이 공개 테스트넷을 선택해 tx hash + 로그를 제출하면 된다. 로컬 데브넷이 아니므로 "주최측이 스크립트로 직접 실행" 조건은 해당 없지만, README에 배포 명령과 주소를 반드시 적는다.

| 항목 | 값 |
|---|---|
| ShareLedger | `0xF297240957c3aB10458Dc1A4C6eC2eA18292529E` (배포 블록 11801645) |
| PieToken | `0xF5cB871A8890bd1D34bf36E749F012D95589E0fD` (decimals 0, 1 PIE = 1원 표시, 실화폐 가치 없음) |
| 에이전트(Pie) 지갑 | `0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36` — 테스트 전용. 비밀키는 `.env`(`AGENT_PRIVATE_KEY`)에만, git·채팅·zip 금지 |
| 이의제기 기간 | 컨트랙트 전역 `disputeWindow` = 180초 (베타 설정). `.env DISPUTE_WINDOW_SEC`와 **항상 같은 값**으로, 바꾸면 `setDisputeWindow`도 같이 |
| 도구 | `hardhat/` — `npm test`(30개) · `npm run deploy -- --network sepolia` · `npm run smoke` · `npm run evidence` |
| 새 백엔드 버전에 얹기 | `py tools/apply_blockchain_patches.py --target <새폴더>` (멱등) → `send_gas` 2개 확인 → smoke → evidence |

**서명 구조 (수탁 아님)**: 에이전트 지갑은 충전·등록·중단·판정·환불·지급·현금 확인만 서명한다. **참여자 예치는 참여자 본인 MetaMask 서명**(`approve` → `lockForSettlement`)이며, 컨트랙트가 `msg.sender`의 토큰을 옮기므로 에이전트는 참여자 돈을 뺄 권한이 없다. 지갑 등록 시 에이전트가 가스(Sepolia ETH 0.002)를 자동 지급해 사용자가 Faucet 없이 예치할 수 있게 한다(`GAS_DRIP_*`). 모의 체인(`CHAIN_MODE=mock`)에서만 서버가 예치를 대신 처리한다.

**멤버 식별**: 앱 계정에 등록한 **지갑 주소**. 표시 이름은 앱 안에서만 쓰고(동명이인은 앱이 `진주2`처럼 구분) 체인에는 주소만 올린다. 조건 문장의 이름은 members 목록 글자 그대로 써야 한다(접미사 떼면 조건이 사라진 채 등록됨).

| 함수 (Solidity) | 서명 | 역할 | 우선순위 |
|---|---|---|:---:|
| `PieToken.chargeToken(to, amount)` | 에이전트(minter) | PieCoin 발급(충전). 앱 충전 100,000 PIE / 60초 1회 | ★ 코어 |
| `createSettlement(id, token, payee, members[], shares[], conditionHash, purpose)` | 에이전트 | 정산 등록 — 분담표·조건 해시·목적(60자 이내, 개인정보 제거) 기록 → `Open`. 결제자(payee) 몫은 즉시 확보 | ★ 코어 |
| `lockForSettlement(id)` | **참여자** | 승인 시 분담금 예치. **잔액·한도 부족이면 revert — 일부만 잠기는 상태 없음.** 마지막 예치에서 `Locked` + `FullyLocked(releaseAfter)` | ★ 코어 |
| `releaseToRecipient(id)` | 에이전트(감시 루프 자동, 누구나 가능) | `releaseAfter` 지난 뒤 에스크로를 **결제자(payee)** 에게 지급 → `Paid`(=인증서 TxHash) | ★ 코어 |
| `blockSettlement(id, member, reasonCode, note)` | 에이전트 | 지출 통제 위반 시 등록 없이(또는 Open 상태에서) 중단 기록 → `Blocked`, 이미 예치한 사람은 즉시 환불. **조용히 끝내지 않고 온체인에 남긴다** | ★ 코어 |
| `raiseDispute(id, by, reason)` | 참여자 또는 에이전트 대행 | `Locked`이고 지급 전까지만 → `Disputed`(동결) | Dispute |
| `refundParticipant(id, participant)` | 에이전트 | `Disputed`에서 예치한 사람에게 환불. 두 번 환불 불가 | Dispute |
| `resolveDispute(id, verdict, note)` | 에이전트 | **verdict 1=NORMAL_APPROVAL, 2=GENUINE_ERROR, 3=BAD_FAITH_DISPUTE** (0·4 거부). 1·3 → 결제자 지급(`Paid`), 2 → 전원 환불이면 `Refunded`, 일부만이면 나머지 지급(`Paid`). 현금(OFFLINE) 멤버가 있으면 `Refunded`로 끝나지 않는다 | Dispute |
| `markOfflinePayment(id, participant)` | 에이전트(결제자 확인 후) | 현금 결제 기록 — 토큰 이동 없이 확보액에 포함 | 구현됨 |
| `createPurchase` / `approvePurchase` / `executePurchase` | 에이전트 / **참여자** / 에이전트 | AI 구매 대행: 전원 인출 승인 후 한 번에 인출·가맹점 결제, 하나라도 실패하면 전체 취소. 이의제기 기간 없음 | Shopping |
| 조회 `getSettlement` · `getMembers` · `releaseAt` · `committedOf/escrowOf/spentOf` · `isAgent` | — | 화면 자금추적·감시 루프(5초) | 구현됨 |

### 5-1. 정산 상태 머신 (`enum Status { None, Open, Locked, Paid, Blocked, Disputed, Refunded }`)

```
Open ──(전원 예치, 마지막 lock)──▶ Locked ──(releaseAfter 경과, releaseToRecipient)──▶ Paid
 │  createSettlement               보류: releaseAfter = 마지막 예치 시각 + disputeWindow
 │                                 FullyLocked 이벤트 · Paid 이벤트 = 인증서 TxHash
 └─(지출 통제 위반 / 결제자 취소)──▶ Blocked (예치자 즉시 환불)
                                      │ raiseDispute (지급 전까지)
                                      ▼
                                   Disputed(동결) ──resolveDispute──▶ 1·3: Paid (결제자 지급)
                                                                    ▶ 2: refundParticipant×N → Refunded (전원) / Paid (일부)
```
- 에스크로 = ShareLedger 컨트랙트 자신. 지급 수령처는 **항상 결제자(payee)**; 구매 대행은 가맹점 주소.
- `Disputed` 동안 `releaseAfter`는 그대로 흐른다. 판정 1·3은 보류 기간과 무관하게 즉시 지급한다.
- 지급(`Paid`) 이후에는 이의제기·환불 불가(기록 조사만).
- 지출 통제 위반은 트랜잭션 0건으로 조용히 끝내지 않고 `Blocked`로 온체인에 남긴다(챌린지 "stopping should be recorded").

## 6. API 엔드포인트 (최종본 Python 백엔드, `docs/API.md`가 원본)

```
### 정산 코어
POST /api/settlement/analyze      Stage1 해석 (+Stage2 계산) · settlement.analyze
POST /api/settlement/calculate    Stage2 계산 (코드 전용, 0 tokens)
POST /api/settlement/explain      Stage3 설명 · settlement.explain
POST /api/settlement/request      지출 통제 검사 → 에이전트가 체인 등록 (위반 시 blocked + Blocked tx)
POST /api/settlement/approve      {settlement_id, name, tx_hash} — 참여자가 MetaMask 예치 후 확정 (mock은 서버가 예치)
POST /api/settlement/cancel       결제자, 전원 예치 전 → blockSettlement(reason 9), 예치자 자동 환불
POST /api/settlement/{id}/sync    체인 재조회 (보류 끝났으면 자동 지급)
POST /api/settlement/offline-payment   현금 결제 확인 (결제자만)

### Dispute 모듈
POST /api/dispute/raise           {settlement_id, by, reason} — locked(지급 전)일 때만
POST /api/dispute/investigate     코드 대조(0 tokens) + AI 3분류 → {verdict, refund, explanation, guard, findings[]}
POST /api/dispute/resolve         GENUINE_ERROR면 refundParticipant×N 후 resolveDispute(2), 그 외 resolveDispute(1|3)

### Shopping 모듈
POST /api/shopping/search         {query, history} → AI 조건 해석 → 코드 검색(SerpApi 네이버→구글) → 1인당 비용 계산 후 비교 (ok_web 결과 포함)
POST /api/chat                    Pie 대화 에이전트 (화면이 실제로 쓰는 경로) — 정산·추천·이의제기 확정 신호는 전용 흐름

### 보고
GET  /api/usage/report.md         단계별 토큰·에너지 · 응답→행동 기록
GET  /api/beta/report.md          베타 참여·시나리오·심사 기준 실행 수
```

### 6-1. 확정 규칙
- 금액은 원 단위 정수, 1원 단위 최대잉여법, 합계는 항상 총액과 일치.
- 조건 = `rule` JSON: `adjustments[{name, kind: less|more, value}]`, `per_person_cap`, `total_cap`, 비율·항목·1인당 금액 등 (`docs/API.md` 2번).
- 에러 응답은 항상 `{ ok:false, error:{ code, message, stage, details } }`.
- **조건 해시(제3자 검증)**: 조건 원문 → `chain.condition_hash(text)`(keccak256) → `createSettlement`의 `conditionHash`로 기록 → Etherscan `SettlementCreated`의 값과 대조하면 "그 조건으로 만든 정산"임이 증명된다.
- 코드 안전장치(AI 우회 불가): 잔액 부족 revert · 합계=총액 · 1인/총 한도 · 허용 판매처 · 가용 잔액 · **가드 A** 한글 금액 오파싱(문장에 '만/억'인데 총액이 그보다 작으면 `AMOUNT_SUSPECT` 거부) · **가드 B** GENUINE_ERROR인데 refund=none이면 제기자 환불로 보정 · **가드 C** 목적 문자열 60자 · 가스 시세×2 + 영수증 대기 300초.
- 대조 기록 형식(`/api/dispute/investigate`): 최초 요청 → Stage1/2 결과 → 온체인 등록(분담표·조건 해시) → 예치(누가 본인 서명했나) → 결제 상태. `findings[]`로 반환.

## 7. AI Dispute Agent 판정 로직

3가지 판정만 존재한다. 새로운 판정 카테고리를 임의로 추가하지 않는다:
- `NORMAL_APPROVAL` (verdict 1) — 정상 승인이었음 → 정산 유지, 이의 기각, 결제자 지급
- `GENUINE_ERROR` (verdict 2) — 진짜 착오·오류 → `refundParticipant` 자동 호출(refund=all 전원 / disputer 제기자) 후 `resolveDispute(2)`
- `BAD_FAITH_DISPUTE` (verdict 3) — 악의적 이의제기 → 이의 기각, 근거(사유·판정 note) 온체인 공개, 결제자 지급

코드 가드: 기록 불일치가 있으면 GENUINE_ERROR로 보정, 불일치 없고 거래 문제 아니면 NORMAL_APPROVAL로 보정, 본인 서명 기록 없이는 BAD_FAITH 판정 불가, GENUINE_ERROR인데 refund=none이면 disputer로 보정. Dispute Agent에 넘기는 조사 데이터: 최초 요청 → 정산 코어 Stage1/2/3 로그 → 온체인 등록·예치·결제 기록 전체.

## 8. UI/UX — 별도 담당자 (이 문서 범위 밖)

화면은 `frontend/index.html` + `sp-bridge.js`(API · MetaMask). 블록체인 작업은 화면을 새로 만들지 않는다. 화면에 반영해야 할 문구: PIE는 테스트넷 토큰(실화폐 아님), 가스는 지갑 연결 시 자동 지급(Faucet 안내는 부족할 때만), 인증서에 조건 원문·Etherscan 링크, 체인명은 `/api/config`의 network(Sepolia)로 표시.

## 9. 조건 2회 실행 데모 (Challenge A 요구조건 — 구현·증거 확보 완료)

```
Run 1 (정상):   "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘", 총 35,900, 예산 40,000
                → 코드 계산 [5,225 / 10,225 ×3] → createSettlement → 참여자 3명 예치 → 보류 180s → releaseToRecipient (paid)
Run 1.5 (조건 변경 → 코드 중단): ① 1인 한도 9,000원 → OVER_PERSON_CAP  ② 총 한도 30,000원 → OVER_TOTAL_CAP
                → 둘 다 등록·예치·지급 0건, blockSettlement로 Blocked 온체인 기록, AI 호출 0회
                (③ 허용 판매처 위반 MERCHANT_NOT_ALLOWED 케이스를 증거 실행기에 추가 예정)
Run 2 (이의제기): 별도 정산 → 전원 예치(Locked) → "판매자 품절 취소" raiseDispute → dispute.investigate = GENUINE_ERROR(refund=all)
                → refundParticipant ×3 → resolveDispute(2) → Refunded, 잔액 전액 복구
실행:           서버 켠 뒤  cd hardhat && npm run evidence  → docs/evidence/<시각>/summary.md (트랜잭션 표·Etherscan·AI 토큰 표·응답→행동)
최신 증거:       docs/evidence/python-v35-sepolia-2026-09-28/ (저장소) · share-pie-ai-v39b/docs/evidence/sepolia-2026-09-28T22-36-17/ (v39)
```
- 지급(`Paid`) 이후에는 이의제기가 불가능하므로 **Run 2는 별도 정산**으로 실행한다.
- Run 2의 착오는 시연용으로 주입한 시나리오이며, 판정은 AI가·환불 실행은 코드가 한다. README에 명시.
- 증거 실행기는 참여자 예치를 참여자 테스트 지갑으로 스크립트가 서명한다(MetaMask 대체, 같은 컨트랙트 호출). README "한계"에 명시.
- **베타 데이터는 실체인(`CHAIN_MODE=bsc`)에서 모아야 증거가 된다.** 모의 체인 기록(network="모의 체인")은 심사 증거가 아니다. 실체인 서버는 한 곳(같은 에이전트 지갑을 두 서버가 쓰면 nonce 충돌).

## 10. 환경 변수 (최종본 `.env`, `.env.example` 참고)

```
# Kiln (필수)
KILN_API_KEY=sk-bk-...
KILN_BASE_URL=https://api.bricksum.com/v1
KILN_MODEL=qwen3-32b            # 주최측 공지에 따른 Qwen3-32B (브리프는 gpt-oss-120b) — 4번
KILN_TOOL_MODE=json             # 고정 — 4번
LLM_MODE=live
BETA_PLAN=max20                 # 베타 동안 구독 없는 사용자도 이 한도

# 블록체인 (Ethereum Sepolia 테스트넷 전용)
CHAIN_MODE=bsc                  # bsc = 실제 체인(이름은 호환용), mock = 모의 체인
BSC_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com   # 혼잡 대비 Alchemy/Infura 키 권장
BSC_CHAIN_ID=11155111
BSC_EXPLORER=https://sepolia.etherscan.io
LEDGER_ADDRESS=0xF297240957c3aB10458Dc1A4C6eC2eA18292529E
TOKEN_ADDRESS=0xF5cB871A8890bd1D34bf36E749F012D95589E0fD
LEDGER_DEPLOY_BLOCK=11801645
AGENT_PRIVATE_KEY=<에이전트 지갑 비밀키 — .env에만, 실제 자산 지갑 절대 금지>
DISPUTE_WINDOW_SEC=180          # 컨트랙트 disputeWindow와 동일값
GAS_DRIP_ETH=0.002              # 지갑 등록 시 가스 자동 지급 (0=끔) · GAS_DRIP_MIN_ETH=0.001 · GAS_DRIP_COOLDOWN_SEC=86400
CHAIN_TX_TIMEOUT_SEC=300        # 영수증 대기 · GAS_PRICE_MULTIPLIER=2 · CHAIN_MAX_GAS_GWEI=0(상한 없음)
CHAIN_TX_PIPELINE=1 · GAS_DRIP_ASYNC=1 · CHAIN_WATCH=1   # 베타 서버 동시 접속 설정 (v39)

# 검색 (Shopping)
SERPAPI_API_KEY=<serpapi.com 키>   # 있으면 SerpApi (네이버 → 구글 쇼핑). SERPER_API_KEY는 비워 둘 것(둘 다 있으면 Serper 우선)
SERPER_API_KEY=
```
- `.env`는 zip·git·채팅에 넣지 않는다. 팀 내부 전달은 개인 DM. 대회 후 Kiln·SerpApi 키 재발급 + 에이전트 지갑 교체(`setAgent`·`setMinter`).
- 서버 실행: `py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000` (베타 진입점), 외부 공개는 `run-public.cmd`(cloudflared) — `docs/BETA-PUBLIC.md`.

## 11. 하지 말 것 (반복 강조)

- AI에게 금액을 직접 계산시키지 않는다 (설명 문장에서도 암산 숫자 금지, 카드 숫자만 인용)
- 검색 결과가 없을 때 AI가 가격·상품을 지어내게 두지 않는다 ("못 찾았어요" + 본 금액 묻기)
- Shopping이나 Dispute를 정산과 동등한 메인 기능처럼 선언하지 않는다
- Shopping 모듈에서 예산 기준 비교 계산을 생략하고 단순 목록/인기순 나열로 만들지 않는다
- Kiln API 호출에서 토큰 로깅을 생략하지 않는다 · `KILN_TOOL_MODE`를 json 외로 바꾸지 않는다
- 이의제기 판정 카테고리를 3개 밖으로 늘리지 않는다 · 부분 환불을 만들지 않는다
- 메인넷/실제 결제 코드를 작성하지 않는다
- `lockForSettlement`에서 잔액 확인을 생략하지 않는다 — 잔액 부족 시 정산이 진행되면 안 된다
- 모델명을 코드에 하드코딩하지 않는다 (`KILN_MODEL` 환경변수로만)
- 코드의 기록 대조 없이 AI verdict만으로 환불을 실행하지 않는다
- 컨트랙트(.sol)를 Remix 등으로 임의 배포하지 않는다 — `npm run deploy` 스크립트만, 바뀌면 재검증(테스트 30·smoke·evidence)
- 같은 에이전트 지갑으로 실체인 서버를 두 곳에서 동시에 켜지 않는다
- `agent/chain.py`·`service.py`·`config.py`의 `[blockchain 담당]` 블록은 블록체인 담당과 상의 없이 바꾸지 않는다

## 12. 제출 전 필수 체크리스트 (README 반영 상태)

- [x] README에 스테이지별 토큰 사용량 표 (settlement.analyze / explain / calculate 0 / dispute.investigate / shopping.* / assistant.step 각각) — `/api/usage/report.md`
- [x] README에 13번 에너지 추정 문단 (실측 없음, NPU 150W × 지연 × 카드 수 상한, 가정 명시)
- [x] Run 1 / Run 1.5(조건 변경 2건) / Run 2 실제 Sepolia 실행 + 거부·환불 로그 캡처 — `docs/evidence/`
- [x] Kiln 응답 → 행동 대응 한 줄 로그 (needsClarification → 되묻기 / 규칙 JSON → 코드 계산 / verdict → refund 호출 + TxHash) — `summary.md`, `events.jsonl`
- [x] Sepolia Etherscan 링크: 등록·예치(전원)·지급·차단·이의제기·환불(각자)·판정 — README 블록체인 절
- [x] README에 배포 명령(`npm run deploy -- --network sepolia`)과 컨트랙트 주소 2개
- [x] README에 한계 명시: 에이전트 지갑 하나가 등록·중단·판정·환불·지급을 서명하는 데모용 구조(참여자 예치만 본인 서명), 증거 실행기는 참여자 지갑을 스크립트가 서명, Run 2 착오는 시연용 주입
- [x] README에 제3자 검증 절차 (조건 원문 → keccak256 → 온체인 conditionHash 대조)
- [x] README에 "브리프는 gpt-oss-120b, 실제는 주최측 공지에 따른 qwen3-32b" — 공지 캡처 첨부는 TODO
- [ ] 정산 인증서 화면에 조건 원문·조건 해시·Etherscan 링크가 같이 보이는지 확인 (UI)
- [ ] 증거 실행기에 허용 판매처 위반(MERCHANT_NOT_ALLOWED) 케이스 추가 후 재실행
- [ ] 베타 실체인 데이터 재수집 (모의 체인 기록은 증거 아님)

## 13. 에너지 절감 논리 (README 근거, 숫자는 실제 로그로 교체)

- 비교 기준(baseline): 만약 정산 금액 계산(Stage 2)까지 AI에게 맡겼다면, 정산 1건당 Kiln API 호출이 최소 1회 추가로 필요했을 것이다.
- 실제 설계: Stage 2·지출 통제·기록 대조·검색·1인 비용 계산은 코드로만 처리해 호출 0회 — 정산 1건당 AI 호출 횟수를 줄인다. 실측(v39 증거): 정산 코어 Kiln 50회 vs 코드 처리 75회, 분쟁 5 vs 5, 추천 8 vs 11.
- 다턴 처리에서도 동일하게 절감된다: 조건이 대화 중 바뀌어도 Stage 2 계산 로직은 그대로 재실행될 뿐 AI를 다시 부르지 않는다.
- 추가 절감: 그룹방 잡담은 AI를 부르지 않음(chat.route 코드 판단), 불법 목적·지출 통제 위반은 AI 호출 전에 코드가 차단.
- 가정: Kiln 모델은 NPU(RNGD, TDP 150W) 기반이라고 **가정**하며, 에너지는 실측 지연시간 × 150W × 카드 수의 **상한**으로 추정한다(배치 공유 미반영). 실측 전력 데이터는 없으며 명시적 가정임을 README에 밝힌다.

## 14. 용어 구분 (혼동 금지)

| 용어 | 뜻 |
|---|---|
| SharePie | 서비스/앱 전체 이름 |
| Pie(정산 에이전트) | 정산 코어 AI 에이전트. 에이전트 지갑의 주체 |
| Pie mate | 그룹방에서의 Pie 이름 (화면 표기용. 백엔드·컨트랙트 식별자 아님) |
| Pie Pay | 앱 MY 탭의 PieCoin 지갑 카드 이름 (충전·잔액·자금추적·AI 사용료 송금). 별도 토큰이 아니라 PieCoin을 다루는 화면 |
| PieCoin(PIE) | Sepolia 테스트넷 ERC-20(`PieToken`). decimals 0, 1 PIE = 1원 표시, 실화폐 가치 없음. 챌린지의 토큰 사용량·에너지 항목과 무관 |
| AI 토큰 / AI원 | Kiln API 호출의 input/output 토큰. 앱에서는 사용료 표시 단위 'AI원'(1토큰=1AI원). 토큰 사용량 보고·에너지 추정은 이것만 다룬다 |
| 에스크로 | ShareLedger 컨트랙트가 예치금을 보관하는 상태. 별도 지갑이 아님 |

- 로그·README·주석에서 그냥 "토큰"이라고만 쓰지 말고, "PieCoin" 또는 "AI 토큰"으로 구분해서 쓴다.
- 에너지 소비는 실측하지 않는다. AI 토큰 수와 Kiln 호출 횟수를 에너지의 대리 지표(proxy)로 삼고, 비례한다는 가정을 명시한다. (13번 참고)

## 15. 심사 배점 (DRAFT — 변경 가능)

출처: 현장 킥오프(9/28) 발표 슬라이드('DRAFT' 표시). 챌린지 원문 문서에는 배점이 없고, 현장 공지가 바뀌면 이 표도 바꾼다.

| 항목 | 배점 | 보는 것 |
|---|---|---|
| Technical | 30 | Kiln & on-chain, conditions(조건 준수·검증 가능성) |
| Task fit | 25 | README 선언과의 일치 |
| Innovation | 20 | 에이전트라서 새로운 것 |
| Usability | 15 | 실제 사용자, 실제 문제 |
| Presentation | 10 | README·데모 명확성 |
