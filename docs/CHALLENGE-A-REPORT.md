# SharePie — Challenge A 제출 보고서
GWDC Korea Hackathon · FuriosaAI × Bricksum · Agent Finance Bonus Track
작성 2026-09-29 · 팀 SharePie (최종 시스템: Python 백엔드 v39 + ShareLedger/PieToken on Ethereum Sepolia)

---

## 0. 선언 (Selected Function)

**한 문장(README):** SharePie is, at its core, an AI Settlement Agent that interprets users' natural-language cost-sharing conditions, calculates and verifies a compliant settlement, locks the approved amounts in escrow, releases them after the hold period, and records the result on-chain. Two optional modules extend it: an AI Shopping Agent for pre-settlement discovery, and an AI Dispute Agent for post-settlement investigation.

**한국어:** 사용자가 말로 정한 분담 조건과 지출 한도(1인·총 한도, 허용 판매처)를 AI가 해석하고, 코드가 금액을 계산·검증해 규칙을 통과한 경우에만 참여자가 MetaMask로 직접 Ethereum Sepolia 테스트넷 에스크로(ShareLedger)에 테스트 토큰 PieCoin을 예치하며, 위반 시 결제 없이 중단 기록(Blocked)이, 이의제기 시 AI 판정과 환불 기록(DisputeResolved·Refunded)이 온체인에 남는다.

선언한 기능은 "정산 에이전트(settlement agent)" 하나이며, 브리프의 예시 중 "purchasing agent that respects user conditions"(지출 통제)와 "evidence and dispute tool"(증거·분쟁)의 성격을 정산 흐름 안에 포함한다. 평가는 이 선언 기준으로 받는다.

---

## 1. User Need & Workflow

### 1.1 사용자와 문제
- 사용자: 친구·모임·공동구매에서 돈을 함께 쓰는 일반인(대학생·직장인 모임, 동네 공동구매).
- 문제: "진주는 5천원 적게, 술값은 안 마신 사람 빼고" 같은 조건을 사람이 계산하면 틀리고, 누가 냈는지·왜 그렇게 나눴는지 기록이 남지 않아 나중에 다툼이 생긴다. 총무 한 사람이 돈을 모아 대신 결제하는 구조는 총무를 믿어야만 한다.
- SharePie의 답: 조건은 말로, 계산은 코드로, 돈은 개인 지갑에서 에스크로로, 결과는 블록체인에. 총무를 믿을 필요가 없고 누구든 기록을 검증할 수 있다.

### 1.2 워크플로 (사용자 입력 → 사용 가능한 결과)
1. 그룹방 채팅에 조건을 말한다 — "삼겹살 35,900원, 진주2는 5천원 적게 내고 나머지 셋이 나눠줘".
2. **AI(Stage 1)** 가 조건을 규칙 JSON으로 해석한다. 모호하면 한 가지만 되묻는다("'조금 더'가 얼마인가요?").
3. **코드(Stage 2)** 가 1원 단위로 금액을 계산하고 지출 통제(합계=총액, 1인/총 한도, 허용 판매처, 체인 가용 잔액, 한글 금액 오파싱 가드)를 검사한다. AI 호출 0회.
4. **AI(Stage 3)** 가 결과를 설명하고, 앱이 확인 카드(총액·사람별 금액·방식·근거)를 띄운다.
5. 확인을 누르면 **코드가** 에이전트 지갑으로 `createSettlement`(분담표·조건 해시·목적)를 온체인에 등록한다. 지출 통제 위반이면 등록 대신 `blockSettlement`로 중단을 기록한다.
6. 참여자 각자가 **본인 MetaMask**로 `approve → lockForSettlement`를 서명해 자기 몫을 에스크로에 예치한다(잔액 부족이면 컨트랙트가 거부).
7. 전원 예치 후 이의제기 기간(180초, 베타 설정)이 지나면 코드가 `releaseToRecipient`로 결제자에게 지급하고 **정산 인증서**(TxHash·Etherscan 링크·조건 원문·분담표)가 확정된다.
8. 지급 전이면 이의제기 → **AI**가 온체인 기록과 대조해 3분류 판정 → **코드**가 환불·판정을 온체인에 실행한다.

### 1.3 AI가 하는 일 vs 코드가 하는 일
| 단계 | 담당 | 태그 |
|---|---|---|
| 자연어 조건 → 규칙 JSON, 되묻기, 송금 목적 문구 | AI | `settlement.analyze` |
| 금액 계산·합계 검증·한도·판매처·잔액·오파싱 가드 | 코드 (0 tokens) | `settlement.calculate` / `settlement.policy` |
| 결과 설명 | AI | `settlement.explain` |
| 요청→계산→등록→예치→결제 기록 대조 | 코드 (0 tokens) | `dispute.records` |
| 이의 사유 + 대조 결과 → 3분류 판정 (코드가 모순 보정) | AI | `dispute.investigate` |
| 구매 조건 해석·비교 설명 | AI | `shopping.search` / `shopping.explain` |
| 상품 검색(SerpApi 네이버→구글)·관련성 필터·1인당 비용·예산 판정 | 코드 (0 tokens) | `shopping.web` / `shopping.calculate` |
| Pie 대화 에이전트(도구 선택) / 도구 실행(계산·검증) | AI / 코드 | `assistant.step` / `assistant.tool` |
| 온체인 등록·중단·판정·환불·지급 호출 | 코드(에이전트 지갑) | `chain.*` |

원칙: AI는 이해·판단만 하고 금액을 계산하지 않으며, 온체인 함수를 직접 부르지 않는다. AI 응답은 코드가 검증한 뒤 코드가 실행한다.

---

## 2. Kiln API Integration & Efficiency

### 2.1 모델
- 브리프는 `gpt-oss-120b`를 명시했으나, 주최측(Bricksum)이 2026-09-28 텔레그램 공지로 제공 모델을 **Qwen3-32B(`qwen3-32b`)** 로 변경했다(개발 키에서 gpt-oss-120b는 404). 모델명은 `KILN_MODEL` 환경변수로만 참조한다. (공지 캡처 첨부 예정)
- 엔드포인트 `https://api.bricksum.com/v1/chat/completions`, 응답 형식 JSON 모드(`KILN_TOOL_MODE=json`) — 이 키·모델 조합은 tool calling 인자가 빈 값으로 오는 것을 실측해 JSON 모드로 고정했다.

### 2.2 실제 호출과 "응답 → 행동" 반영
모든 호출은 단계 태그와 입력·출력 토큰을 기록한다(`GET /api/usage/report.md`, `docs/evidence/*/summary.md`, `events.jsonl`).
- `settlement.analyze` → `status: ok` + 규칙 JSON → 코드 계산·지출 통제 → 통과 시 `createSettlement`, 위반 시 `blockSettlement`(AI 재호출 없음)
- `settlement.analyze` → `need_info` → 되묻기(체인 호출 없음)
- `dispute.investigate` → `GENUINE_ERROR`(refund=all) → `refundParticipant` × N → `resolveDispute(2)`; `NORMAL_APPROVAL` / `BAD_FAITH_DISPUTE` → `resolveDispute(1|3)` 후 지급
- 실제 예(2026-09-28 22:35, Sepolia): 이의제기 "판매자가 품절로 주문을 취소했어요" → AI 판정 GENUINE_ERROR → 환불 tx 0xfa90…f228 / 0x7171…5b57 / 0xfb6d…6500 → 판정 tx 0x9a21…55a3

### 2.3 단계별 토큰 (실측, v39 증거 실행)
| 구간 | 단계 | 처리 | Kiln 호출 | 코드 처리 | 토큰 합계 | 호출당 평균 | 평균 지연(ms) | 에너지 상한(Wh) |
|---|---|---|---|---|---|---|---|---|
| 정산 코어 | Stage 1 해석 `settlement.analyze` | AI | 48 | 4 | 74,853 | 1,559 | 2,816 | 5.633 |
| 정산 코어 | Stage 2 계산 `settlement.calculate` | 코드 | 0 | 45 | 0 | 0 | 0 | 0 |
| 정산 코어 | 지출 통제 `settlement.policy` | 코드 | 0 | 26 | 0 | 0 | 0 | 0 |
| 정산 코어 | Stage 3 설명 `settlement.explain` | AI | 2 | 0 | 658 | 329 | 1,748 | 0.146 |
| 분쟁·증거 | 기록 대조 `dispute.records` | 코드 | 0 | 5 | 0 | 0 | 0 | 0 |
| 분쟁·증거 | 판정 `dispute.investigate` | AI | 5 | 0 | 5,282 | 1,056 | 4,970 | 1.036 |
| 공동구매·추천 | 검색·1인 비용 (코드) | 코드 | 0 | 11 | 0 | 0 | 0 | 0 |
| 공동구매·추천 | 조건 해석·설명 (AI) | AI | 8 | 0 | 8,083 | 1,010 | 3,084 | 1.028 |
| Pie 대화 | 의도 파악·도구 실행 (코드) | 코드 | 0 | 37 | 0 | 0 | 0 | 0 |
| Pie 대화 | 에이전트 판단 `assistant.step` | AI | 22 | 0 | 63,376 | 2,881 | 2,203 | 2.019 |

베타 실사용(2026-09-29, 사용자 6명·92턴): 턴당 평균 3,815 토큰(중앙값 2,987), Kiln 호출 턴당 1.33회.

### 2.4 불필요한 추론을 줄이는 설계 (baseline 대비)
- baseline: 계산·지출 통제·기록 대조·검색·1인 비용까지 AI에게 맡기면 정산 1건당 Kiln 호출이 최소 1회 이상 추가된다.
- 실제: 그 단계는 전부 코드다. 위 실측에서 정산 코어는 Kiln 50회 대 코드 처리 75회, 분쟁 5 대 5, 추천 8 대 11.
- 다턴: 조건이 바뀌면 Stage 1만 다시 부르고 Stage 2는 같은 함수를 재실행한다.
- 그룹방 잡담은 코드가 의도를 판단해 AI를 부르지 않고, 불법 목적·지출 통제 위반은 AI 호출 전에 코드가 차단한다. 사용자별 AI 한도를 넘으면 규칙 응답으로 대체한다.

### 2.5 에너지 추정 (측정값 + 명시된 가정)
- 측정한 것: 호출마다 토큰 수와 실측 지연시간.
- 가정한 것: Kiln 모델은 FuriosaAI RNGD NPU(TDP 150W) 1장에서 서빙되며, 에너지는 추론 시간에 비례한다. 배치 공유는 반영하지 않으므로 상한 추정이다.
- 공식: 에너지(Wh) = 지연시간(s) × 150W × 카드 수 ÷ 3600. 예: 조건 해석 1회 2.8초 → 약 0.12 Wh, 위 실행 전체(85회 호출) → 약 9.9 Wh 상한.
- 실측 전력 데이터는 없다. 토큰 수와 호출 횟수를 에너지의 대리 지표로 쓰며, 설계로 줄인 호출 수만큼 에너지도 줄어든다고 추정한다.

---

## 3. Blockchain Integration

### 3.1 네트워크·배포
| 항목 | 값 |
|---|---|
| 네트워크 | Ethereum Sepolia 테스트넷 (chainId 11155111). 주최측 공용 테스트넷이 없어 팀이 선택(텔레그램 확인 2026-09-28) |
| ShareLedger (에스크로·자금추적·이의제기) | 0xF297240957c3aB10458Dc1A4C6eC2eA18292529E (배포 블록 11801645) |
| PieToken (PIE, decimals 0, 1 PIE = 1원 표시, 실화폐 가치 없음) | 0xF5cB871A8890bd1D34bf36E749F012D95589E0fD |
| 에이전트(Pie) 지갑 | 0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36 (테스트 전용) |
| 배포 명령 | `cd hardhat && npm run deploy -- --network sepolia` (메인넷 chainId 거부) · 테스트 `npm test`(30개) · `npm run smoke` · `npm run evidence` |

### 3.2 체인이 워크플로에서 읽고·쓰고·정산하는 상태
| 단계 | 함수 | 서명 | 상태·이벤트 |
|---|---|---|---|
| PIE 충전 | `PieToken.chargeToken` | 에이전트 | 잔액 |
| 정산 등록 | `createSettlement(id, token, payee, members[], shares[], conditionHash, purpose)` | 에이전트 | `Open` · `SettlementCreated` |
| 참여자 예치 | `approve` → `lockForSettlement(id)` (잔액 부족 revert) | **참여자 본인** | `Locked` · `FullyLocked(releaseAfter)` |
| 지급 | `releaseToRecipient(id)` → 결제자 | 에이전트(자동) | `Paid` = 인증서 TxHash |
| 지출 통제 중단 | `blockSettlement(id, member, reasonCode, note)` | 에이전트 | `Blocked` (조용히 끝내지 않고 기록) |
| 이의제기 | `raiseDispute(id, by, reason)` | 참여자/대행 | `Disputed` |
| 판정 실행 | `refundParticipant` × N → `resolveDispute(id, 1·2·3, note)` | 에이전트 | `Refunded` / `Paid` |
| 읽기 | `getSettlement` · `getMembers` · `releaseAt` · `committedOf/escrowOf/spentOf` | — | 화면 자금추적·감시 루프(5초) |

상태 머신: `Open → Locked → Paid`, 위반·취소 `Blocked`, 이의제기 `Disputed → Refunded | Paid`.

### 3.3 End-to-end 온체인 트랜잭션 (실제 Sepolia, 2026-09-28)
Run 1(정상): 등록 0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0 → 예치 3건 → 지급(인증서) 0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6
매칭 로그: `docs/evidence/sepolia-2026-09-28T22-36-17/summary.md`, `run1.json` (AI 해석 결과·분담표·tx 종류별 해시·잔액 전후).

함수별 실측 가스: 등록 513,574 · 예치 128,725 · 지급 146,673 · 차단 51,378 · 이의제기 39,426 · 환불 61,997 · 판정 65,226 · 충전 38,317. 정산 1건(등록+지급) ≈ 0.0014 ETH.

---

## 4. Condition Checks & Evidence

### 4.1 조건을 바꿔 반복 실행 (2회 이상)
| Run | 조건 | 결과 | 대표 TxHash |
|---|---|---|---|
| 1 정상 | "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘", 총 35,900, 예산 40,000 → [5,225 / 10,225 × 3] | 등록 → 3명 예치 → 보류 → 지급(paid) | 0xb5d5…60c0 / 0x932d…d7c6 |
| 1.5 ① 예산 축소 | 같은 조건에 1인 한도 9,000원 | 코드 `OVER_PERSON_CAP` → 등록·예치·지급 0건, `Blocked` 온체인 기록, AI 호출 0회 | 0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb |
| 1.5 ② 예산 축소 | 총 한도 30,000원 | 코드 `OVER_TOTAL_CAP` → 중단, `Blocked` 기록 | 0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc |
| 1.5 ③ 판매처 불허 | "쿠팡만 허용"인데 네이버스토어 | 코드 `MERCHANT_NOT_ALLOWED` → 중단 (증거 실행기에 포함, 베타 실사용에서 2건 발생) | 다음 증거 실행 시 기록 |
| 2 이의제기 | 예치 완료 후 "판매자 품절 취소" → AI `GENUINE_ERROR`(refund=all) | 환불 3건 + 판정 → `Refunded`, 잔액 전액 복구 | 이의제기 0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31 · 환불 0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228 · 판정 0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3 |

지출 통제는 AI가 아니라 코드가 강제하며, 중단은 트랜잭션 0건으로 조용히 끝내지 않고 `Blocked`로 온체인에 남긴다.

### 4.2 제3자가 기록만 보고 조건 준수를 판단하는 방법
1. 정산 인증서(앱 '정산 인증서 보기' 또는 `summary.md`)의 조건 원문과 분담표를 본다.
2. Etherscan에서 등록 트랜잭션의 `SettlementCreated` 이벤트 → `conditionHash`, `shares[]`, `purpose`를 읽는다.
3. 조건 원문을 같은 방식(keccak256, `chain.condition_hash(text)`)으로 해시해 `conditionHash`와 대조한다 — 일치하면 이 온체인 정산은 그 조건으로 만들어진 것이다.
4. `Locked` / `Paid` / `Blocked` / `Refunded` 이벤트로 누가 얼마를 예치했고 어디로 지급됐는지(또는 왜 중단·환불됐는지) 본다. 목적 문자열은 이름·연락처를 지운 뒤 60자 이내로 기록된다.

### 4.3 코드 안전장치 (AI 우회 불가)
- 잔액 부족 예치 revert(컨트랙트) · 합계=총액 · 1인/총 한도 · 허용 판매처 · 가용 잔액(등록 전, 코드)
- 가드 A: 문장에 '만/억'이 있는데 총액이 그보다 작으면 등록 거부(`AMOUNT_SUSPECT`) — 한글 금액 오파싱이 온체인에 가는 것 방지
- 가드 B: `GENUINE_ERROR`인데 환불 대상이 없으면 제기자 환불로 보정
- 가드 C: 온체인 목적 문자열 60자 제한 · 가스 시세×2 + 영수증 대기 300초

### 4.4 실사용 증거 (베타, 2026-09-29)
- 사용자 6명 · 92턴 · 피드백 41건(👍 28 · 👎 13) · 정산 11건(지급 6 · 지출 통제 중단 3 · 진행 2)
- 중단 3건: 허용 판매처 위반 2, 잔액 부족 1 — 지출 통제가 실제 사용자 조건에서 동작
- 베타 데이터는 비식별(가명·이메일/지갑 없음)로 `beta-data/` 폴더에 수집. 이 기간 정산은 모의 체인 모드였으며, 이후 실체인 모드로 전환해 실사용 온체인 기록을 추가 수집한다.

---

## 5. 한계와 정직한 기술

- 충전·등록·중단·판정·환불·지급은 에이전트 지갑 하나가 서명하는 데모용 구조다. 참여자 예치만 본인 MetaMask 서명이다.
- 증거 실행기(`npm run evidence`)는 참여자 예치를 스크립트가 참여자 테스트 지갑으로 대신 서명한다(같은 컨트랙트 호출). 실제 사용자 MetaMask 예치 기록은 베타 실체인 데이터에서 확보한다.
- Run 2의 착오("판매자 품절 취소")는 시연용 시나리오다. 판정은 AI가, 환불 실행은 코드가 한다.
- 모델은 주최측 공지에 따라 gpt-oss-120b가 아닌 qwen3-32b다.
- 에너지는 실측이 아닌 상한 추정이다(2.5의 가정).
- 테스트넷 전용이며 실제 화폐·메인넷은 다루지 않는다.

---

## 6. 재현 방법
```
py -3.14 -m pip install -r requirements.txt && py -3.14 -m pip install "web3>=6.15"
# .env: KILN_API_KEY · KILN_MODEL=qwen3-32b · KILN_TOOL_MODE=json · CHAIN_MODE=bsc · BSC_CHAIN_ID=11155111
#       LEDGER_ADDRESS/TOKEN_ADDRESS(위 주소) · AGENT_PRIVATE_KEY(테스트 지갑)
py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1
cd hardhat && npm install && npm test && npm run smoke && npm run evidence   # → docs/evidence/<시각>/summary.md
```
검증 도구: `py scripts/check_chain.py`(체인 연결·권한 9항목) · `npm run smoke`(서버·env·해석·가드·체인 쓰기 29항목) · `GET /api/usage/report.md`(토큰·에너지) · `GET /api/beta/report.md`(베타 참여·심사 기준 실행 수).

## 7. 자료 위치
- README.md (선언·구조·역할·블록체인·증거·에너지·한계)
- docs/evidence/sepolia-2026-09-28T22-36-17/ — summary.md · run1.json · run1_5.json · run2.json · usage-report.md · wallets.json
- docs/evidence/ 베타 데이터 보고서 — report.md · dialogs.jsonl · feedback.jsonl · settlements.jsonl · usage.jsonl
- contracts/ShareLedger.sol · contracts/PieToken.sol · hardhat/test/ShareLedger.test.js(30개)
- Etherscan: https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E
