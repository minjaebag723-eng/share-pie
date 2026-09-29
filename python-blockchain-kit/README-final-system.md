# SharePie — AI Settlement Agent (GWDC 2026 챌린지 A)

> SharePie is, at its core, an AI Settlement Agent that interprets users' natural-language cost-sharing conditions, calculates and verifies a compliant settlement, locks the approved amounts in escrow, releases them after the hold period, and records the result on-chain. Two optional modules extend it: an AI Shopping Agent for pre-settlement discovery, and an AI Dispute Agent for post-settlement investigation.

**한 문장 (챌린지 A 선택 기능):** 사용자가 말로 정한 분담 조건과 지출 한도(1인·총 한도, 허용 판매처)를 AI가 해석하고, 코드가 금액을 계산·검증해 규칙을 통과한 경우에만 참여자가 MetaMask로 직접 Ethereum Sepolia 테스트넷 에스크로(ShareLedger)에 테스트 토큰 PieCoin을 예치하며, 위반 시 결제 없이 중단 기록(`Blocked`)이, 이의제기 시 AI 판정과 환불 기록(`DisputeResolved`·`Refunded`)이 온체인에 남는다.

테스트넷 전용이다. PieCoin(PIE)은 실화폐 가치가 없고(1 PIE = 1원 표시), 실제 계좌·카드·메인넷은 다루지 않는다.

## 바로 가기

| 문서 | 내용 |
|---|---|
| [`HOW-TO-RUN.md`](HOW-TO-RUN.md) | 실행 안내 (로컬 · Sepolia 설정 · 검증) |
| [`deploy/README.md`](deploy/README.md) | 베타 서버 — 100명 동시 접속 · 데이터 폴더 · 클라우드 배포 |
| [`docs/BETA-PUBLIC.md`](docs/BETA-PUBLIC.md) | PC + Cloudflare 터널로 외부 공개 · 새 백엔드 버전에 블록체인 얹기 |
| [`docs/user-manual/`](docs/user-manual/) | 베타 참가자용 사용 설명서 (PDF) |
| [`CHANGES-beta-server.md`](CHANGES-beta-server.md) | 베타 서버 병합 · 실제 체인 동시 접속 수정 내역 |
| [`docs/evidence/`](docs/evidence/) | Sepolia 실행 증거 (TxHash · Etherscan 링크 · AI 토큰 표 · 응답→행동 기록) |

## 배포된 컨트랙트 (Ethereum Sepolia, chainId 11155111)

| 컨트랙트 | 주소 |
|---|---|
| ShareLedger (에스크로·자금추적·이의제기) | [`0xF297240957c3aB10458Dc1A4C6eC2eA18292529E`](https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E) — 배포 블록 11801645 |
| PieToken (PIE, decimals 0, 테스트넷 전용) | [`0xF5cB871A8890bd1D34bf36E749F012D95589E0fD`](https://sepolia.etherscan.io/address/0xF5cB871A8890bd1D34bf36E749F012D95589E0fD) |
| 에이전트(Pie) 지갑 | [`0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36`](https://sepolia.etherscan.io/address/0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36) — 충전·등록·중단·판정·환불·지급 서명 (테스트 전용 지갑) |
| 이의제기 기간 (`disputeWindow`) | 180초 (베타 설정 · `.env DISPUTE_WINDOW_SEC`와 동일값) |

주최측 공용 테스트넷이 없어(텔레그램 확인 2026-09-28) 공개 EVM 테스트넷인 Sepolia를 팀이 선택했다.

배포·검증 명령 (`hardhat/`):
```bash
cd hardhat && npm install
npm test                                   # ShareLedger·PieToken 테스트 30개 (로컬 체인)
npm run deploy -- --network sepolia        # 배포 → contracts/abi/*.json, hardhat/deployments/sepolia.json (메인넷 chainId는 거부)
npm run smoke                              # 서버·.env·권한·해석·가드·체인 쓰기 스모크 (🔴 0 이어야 통과)
npm run evidence                           # Run 1 / 1.5 / 2 실제 체인 실행 → docs/evidence/<시각>/summary.md
```

## 실행

```bash
py -3.14 -m pip install -r requirements.txt && py -3.14 -m pip install "web3>=6.15"   # Python 3.14
py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1             # → http://localhost:8000 (베타 서버 진입점)
```
- 외부 공개(폰·다른 PC)는 `run-public.cmd` (Cloudflare 터널) — `docs/BETA-PUBLIC.md`
- 키는 `.env`에만 (`.env.example` 복사 → 채우기). `.env`는 `.gitignore`에 있어 올라가지 않는다.
- 실제 체인은 `.env`에 `CHAIN_MODE=bsc`(Sepolia) + `AGENT_PRIVATE_KEY`가 있어야 한다. `CHAIN_MODE=mock`이면 모의 체인(가스·키 불필요, 온체인 기록 없음 — 심사 증거 아님). AI는 `KILN_TOOL_MODE=json` 고정.

자세한 순서·폰 접속은 **`HOW-TO-RUN.md`**, 팀 연동 규격은 **`docs/API.md`**, 팀 규칙은 **`CLAUDE.md`**.

## 구조

```
agent/        AI 에이전트 (프레임워크 무관 파이썬)
  settlement.py  정산 코어 Stage1 해석(AI) · Stage3 설명(AI)
  money.py       Stage2 계산 + 지출 통제 (코드 전용, 0 tokens)
  dispute.py     Dispute 모듈: 코드 대조 → AI 3분류 판정 → 코드 가드
  shopping.py    Shopping 모듈: 조건 해석(AI) → 검색·1인당 비용 계산(코드) → 비교 설명(AI)
  websearch.py   상품 검색 (SerpApi 네이버→구글 쇼핑 · Serper · 네이버 API · Tavily · 상품 페이지) — 코드 전용
  llm.py         Kiln 클라이언트 (JSON 응답 모드, 단계 태그·토큰 로깅, 동시 호출 상한)
  chain.py       Ethereum Sepolia 테스트넷(web3.py) / 모의 체인 — 같은 인터페이스. 가스 자동 지급·tx 파이프라인·체인 감시
  service.py     백엔드가 부르는 진입점
backend/app.py  HTTP API (:8000) + 프론트 서빙
deploy/         베타 서버 진입점(asgi.py) · 클라우드 세팅 · 부하 테스트
contracts/      PieToken.sol (PieCoin, 테스트넷 전용) · ShareLedger.sol (에스크로·자금추적·이의제기)
hardhat/        컨트랙트 테스트 30개 · 배포 스크립트 · 스모크 · 증거 실행기
frontend/       UI/UX 팀 디자인 + sp-bridge.js (API · MetaMask)
tests/          폰 4대 E2E 시뮬레이션 · 대화형 에이전트 점검 · 경계값 회귀 · 가짜 Kiln/웹 서버
```

## AI가 한 일 vs 코드가 한 일

| 단계 | 담당 | 태그 |
|---|---|---|
| 자연어 분담 조건 → 규칙 JSON, 모호하면 되묻기, 송금 목적 문구 | AI | `settlement.analyze` |
| 금액 계산 · 합계=총액 검증 · 1인/총 한도 · 가맹점 · 체인 가용 잔액 · 한글 금액 오파싱 가드 | **코드** | `settlement.calculate` / `settlement.policy` (0 tokens) |
| 계산 결과 설명 | AI | `settlement.explain` |
| 요청→계산→등록→예치→결제 기록 대조 | **코드** | `dispute.records` (0 tokens) |
| 이의 사유 + 대조 결과 → 3분류 판정 (코드가 모순 보정) | AI | `dispute.investigate` |
| 구매 조건 해석 + 검색어 계획 / 비교 설명 | AI | `shopping.search` / `shopping.explain` |
| SerpApi(네이버→구글 쇼핑)·네이버·Tavily·쿠팡·상품 페이지 병렬 검색, 관련성 필터, 버전(최저가/가성비/대량/프리미엄) 선정 | **코드** | `shopping.web` (0 tokens) |
| 팩·인분 수, 배송·배달비 포함 1인당 비용, 예산 초과 판정 | **코드** | `shopping.calculate` (0 tokens) |
| 배달 메뉴 조합 3개 설계 (인원·예산·선호) | AI | `shopping.plan` |
| AI 조합 검증: 없는 메뉴·예산 초과·인분 부족 기각, 부족하면 코드 조합으로 채움 | **코드** | `shopping.calculate` (0 tokens) |
| **AI 구매 대행**: 전원 ‘인출 승인’ 후 결제 직전 지출 통제 재검사 → 각자 지갑에서 몫만큼 가상 계좌로 인출 → 가맹점 결제 (executePurchase) | 코드 + 체인 | `purchase.policy` / `purchase.execute` (0 tokens) |
| **Pie 대화형 에이전트** (기본 `PIE_CHAT=agent`): 고정 질문 없이 모델이 대화 맥락을 보고 도구(상품 검색·웹 검색·배달 메뉴표·조합 검증·비용 분할)를 스스로 골라 쓰고 답함. 최대 5걸음 | AI | `assistant.step` |
| 에이전트 도구 실행: 가격·합계·예산·인분 계산과 검증 (모델은 숫자를 만들지 않음) | **코드** | `assistant.tool` (0 tokens) |
| 정산(이름+금액+나누기)·이의제기 확정 신호는 전용 흐름 유지 (체인 기록·분담표 카드) | AI + 코드 | `settlement.*` / `dispute.*` |
| 온체인 등록·중단·판정·환불·지급 호출 | **코드** (에이전트 지갑) | `chain.*` (0 tokens) — AI는 온체인 함수를 직접 부르지 않는다 |

## 블록체인 — 체인이 워크플로에서 하는 일 (읽기 · 쓰기 · 정산)

| 단계 | 함수 (Solidity) | 서명 | 체인 상태 |
|---|---|---|---|
| PIE 충전 | `PieToken.chargeToken(to, amount)` | 에이전트 | 잔액 |
| 정산 등록 (조건 해시 + 목적 포함) | `ShareLedger.createSettlement(id, token, payee, members[], shares[], conditionHash, purpose)` | 에이전트 | `Open` · `SettlementCreated` |
| 참여자 예치 | `PieToken.approve` → `ShareLedger.lockForSettlement(id)` (잔액 부족이면 revert — 일부만 잠기는 상태 없음) | **참여자 본인 (MetaMask)** | `Locked` · `FullyLocked(releaseAfter)` |
| 지급 (보류 기간 후) | `releaseToRecipient(id)` → 결제자(payee) | 에이전트(감시 루프 자동) | `Paid` = 정산 인증서 TxHash |
| 지출 통제 위반 시 중단 | `blockSettlement(id, member, reasonCode, note)` | 에이전트 | `Blocked` (트랜잭션 0건으로 조용히 끝내지 않고 기록) |
| 이의제기 | `raiseDispute(id, by, reason)` (지급 전까지만) | 참여자 / 에이전트 대행 | `Disputed` (동결) |
| 판정 실행 | `refundParticipant(id, p)` × N → `resolveDispute(id, verdict 1·2·3, note)` | 에이전트 | `Refunded` 또는 `Paid` |
| 읽기 | `getSettlement` · `getMembers` · `releaseAt` · `committedOf/escrowOf/spentOf` | — | 화면 자금추적 · 감시 루프(5초) |

상태 머신: `Open → Locked → Paid`, 위반·취소 `Blocked`, 이의제기 `Disputed → Refunded | Paid`. 판정 코드 1=NORMAL_APPROVAL, 2=GENUINE_ERROR, 3=BAD_FAITH_DISPUTE.

## 조건 2회 변경 실행 — 온체인 증거 (2026-09-28, v39, 실제 Sepolia)

전체 트랜잭션 표·Etherscan 링크·AI 토큰 표·응답→행동 기록: `docs/evidence/sepolia-2026-09-28T22-36-17/summary.md`

| Run | 조건 | 결과 | 대표 TxHash |
|---|---|---|---|
| **1 정상** | "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘", 총 35,900, 예산 40,000 → 코드 계산 [5,225 / 10,225 × 3] | 등록 → 3명 예치 → 보류 180s → **지급 (paid)** | 등록 [`0xb5d5…60c0`](https://sepolia.etherscan.io/tx/0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0) · 지급(인증서) [`0x932d…d7c6`](https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6) |
| **1.5 조건 변경 ①** | 같은 조건에 1인 한도 9,000원 | 코드 `OVER_PERSON_CAP` → **등록·예치·지급 0건, `Blocked` 기록** (AI 호출 0회) | [`0x4e77…f5cb`](https://sepolia.etherscan.io/tx/0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb) |
| **1.5 조건 변경 ②** | 총 한도 30,000원 | 코드 `OVER_TOTAL_CAP` → 중단, `Blocked` 기록 | [`0x8367…33fc`](https://sepolia.etherscan.io/tx/0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc) |
| **2 이의제기** | 예치 완료 후 "판매자 품절 취소" → AI `dispute.investigate` = **GENUINE_ERROR** (refund=all) | 코드가 환불 3건 + 판정 실행 → **refunded**, 잔액 전액 복구 | 이의제기 [`0x156e…8d31`](https://sepolia.etherscan.io/tx/0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31) · 환불 [`0xfa90…f228`](https://sepolia.etherscan.io/tx/0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228) · 판정 [`0x9a21…55a3`](https://sepolia.etherscan.io/tx/0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3) |

허용 판매처 위반(`MERCHANT_NOT_ALLOWED`) 케이스도 증거 실행기 Run 1.5에 포함돼 있으며(“쿠팡만 허용인데 네이버스토어”), 베타 실사용에서 2건 발생해 `Blocked`로 기록됐다.

**Kiln 응답 → 행동** (로그 `events.jsonl` · `summary.md`):
- `settlement.analyze` → `status: ok` + 규칙 JSON → 코드 계산·지출 통제 → 통과 시 `createSettlement`, 위반 시 `blockSettlement` (AI 재호출 없음)
- `settlement.analyze` → `need_info` → 되묻기 (체인 호출 없음)
- `dispute.investigate` → `GENUINE_ERROR` → `refundParticipant` × N → `resolveDispute(2)` / `NORMAL_APPROVAL`·`BAD_FAITH_DISPUTE` → `resolveDispute(1|3)` 후 지급

함수별 실측 가스 (Sepolia 영수증): 정산 등록 513,574 · 예치 128,725 · 지급 146,673 · 차단 51,378 · 이의제기 39,426 · 환불 61,997 · 판정 65,226 · 충전 38,317. 정산 1건(등록+지급) ≈ 0.0014 ETH, 참가자 1명 준비(가스 자동 지급 0.002 + 충전) ≈ 0.0021 ETH (시세 ~2 gwei).

### 제3자 검증 — 기록만 보고 조건을 지켰는지 판단하기

1. 정산 인증서(앱 '정산 인증서 보기' / `summary.md`)의 **조건 원문**과 분담표를 본다.
2. Etherscan에서 등록 트랜잭션의 `SettlementCreated` 이벤트 → `conditionHash`, `shares[]`, `purpose`를 읽는다.
3. 조건 원문을 같은 방식(코드 `chain.condition_hash(text)`, keccak256)으로 해시해 `conditionHash`와 대조한다 — 일치하면 "이 온체인 정산은 그 조건으로 만들어졌다".
4. `Locked` / `Paid` / `Blocked` / `Refunded` 이벤트로 누가 얼마를 예치했고 어디로 지급됐는지(또는 왜 중단·환불됐는지) 본다. 목적 문자열은 이름·연락처를 지운 뒤 60자 이내로 기록된다.

### 코드 안전장치 (AI 우회 불가)

- 잔액 부족 예치 revert(컨트랙트) · 합계=총액 · 1인/총 한도 · 허용 판매처 · 가용 잔액 검사(등록 전, 코드)
- 가드 A — 한글 금액 오파싱 방어: 문장에 '만/억'이 있는데 총액이 그보다 작으면 등록 거부(`AMOUNT_SUSPECT`)
- 가드 B — 판정-환불 일관성: `GENUINE_ERROR`인데 환불 대상이 없으면 제기자 환불로 보정
- 가드 C — 온체인 목적 문자열 60자 제한 · 가스 가격 시세×2 + 영수증 대기 300초(테스트넷 혼잡 대비)

## 역할 분리 (보안)

- **참여자 돈을 에스크로에 잠그는 서명은 항상 참여자 본인** (MetaMask `approve` → `lockForSettlement`). 컨트랙트가 `msg.sender`의 토큰만 옮기므로 에이전트는 참여자 지갑에서 돈을 뺄 권한이 없다
- 에이전트 지갑은 충전·등록·중단·판정·환불·지급·현금 확인만 서명한다
- 체인에는 실명 대신 지갑 주소만, 송금 목적 문구의 이름·연락처는 코드가 제거
- Kiln 키·에이전트 개인키는 서버 `.env`에만

## 가정 (발표 시 명시)

- 1인 적정량: 고기 300g · 과일 500g, 배달은 메뉴별 인분 기준
- 인터넷 검색은 공식 API(SerpApi · 네이버 · Tavily · 쿠팡 파트너스)와 상품 페이지의 공개 구조화 데이터만 사용 (사이트 차단 우회·무단 크롤링 없음). 키가 없거나 검색이 안 되면 상품 가격을 지어내지 않고 못 찾았다고 답함. 예시 데이터는 전혀 없음: 공동구매 탭은 GPS 근처 사용자가 올린 실제 모집글만, 배달 메뉴 조합은 AI가 검색한 실제 브랜드 판매가로만 만듦
- 에너지: RNGD TDP 150W (FuriosaAI 공식), 서빙 카드 수는 대회 측 확인 전까지 1장 — 아래 "에너지 추정" 참고

## AI 토큰 · 추론 절감 · 에너지 추정 (심사 제출용)

### 단계별 AI 토큰 (실측, v39 증거 실행 2026-09-28 · 모델 qwen3-32b · 서버 `GET /api/usage/report.md`)

| 구간 | 단계 | 처리 | Kiln 호출 | 코드 처리 | 토큰 합계 | 호출당 평균 | 평균 지연(ms) | 에너지 상한(Wh) |
|---|---|---|---|---|---|---|---|---|
| 정산 코어 | Stage 1 조건 해석 `settlement.analyze` | AI | 48 | 4 | 74,853 | 1,559 | 2,816 | 5.633 |
| 정산 코어 | Stage 2 금액 계산 `settlement.calculate` | 코드 | 0 | 45 | 0 | 0 | 0 | 0 |
| 정산 코어 | 지출 통제 검사 `settlement.policy` | 코드 | 0 | 26 | 0 | 0 | 0 | 0 |
| 정산 코어 | Stage 3 결과 설명 `settlement.explain` | AI | 2 | 0 | 658 | 329 | 1,748 | 0.146 |
| 분쟁·증거 | 분쟁 기록 대조 `dispute.records` | 코드 | 0 | 5 | 0 | 0 | 0 | 0 |
| 분쟁·증거 | 분쟁 판정 `dispute.investigate` | AI | 5 | 0 | 5,282 | 1,056 | 4,970 | 1.036 |
| 공동구매·추천 | 상품 검색 `shopping.web` · 1인 비용 `shopping.calculate` | 코드 | 0 | 11 | 0 | 0 | 0 | 0 |
| 공동구매·추천 | 조건 해석 `shopping.search` · 설명 `shopping.explain` | AI | 8 | 0 | 8,083 | 1,010 | 3,084 | 1.028 |
| Pie 대화 | 의도 파악 `chat.route` · 도구 실행 `assistant.tool` | 코드 | 0 | 37 | 0 | 0 | 0 | 0 |
| Pie 대화 | 에이전트 판단 `assistant.step` | AI | 22 | 0 | 63,376 | 2,881 | 2,203 | 2.019 |

베타 실사용(사용자 6명 · 92턴): 턴당 평균 3,815 토큰(중앙값 2,987), Kiln 호출 턴당 1.33회 — `docs/evidence/`의 베타 보고서.

### 불필요한 추론을 줄이는 설계 (baseline 대비)

- **baseline**: 금액 계산(Stage 2)·지출 통제·기록 대조·검색·1인 비용 계산까지 AI에게 맡겼다면 정산 1건당 Kiln 호출이 최소 1회 이상 추가된다.
- **실제**: 그 단계는 전부 코드(0 tokens)다. 위 실측에서 정산 코어는 Kiln 50회 대 코드 처리 75회, 분쟁은 5 대 5, 추천은 8 대 11이다.
- 다턴에서도 같다: 조건이 바뀌면 Stage 1만 다시 부르고 Stage 2는 같은 함수를 재실행한다.
- 그룹방 잡담은 코드가 의도를 판단해 AI를 부르지 않고(`chat.route`), 불법 목적·지출 통제 위반은 AI 호출 전에 코드가 차단한다. 사용자별 AI 한도를 넘으면 규칙 응답으로 대체한다.

### 에너지 추정 (측정값 + 명시된 가정)

- **측정한 것**: 호출마다 Kiln 응답의 토큰 수와 실측 지연시간(ms).
- **가정한 것**: Kiln 모델은 FuriosaAI RNGD NPU(TDP 150W) 1장에서 서빙된다고 가정하며, 에너지는 추론 시간에 비례한다고 가정한다. 배치 공유(여러 요청이 한 카드를 나눠 쓰는 것)는 반영하지 않으므로 **상한 추정**이다.
- **공식**: 에너지(Wh) = 지연시간(s) × 150 W × 카드 수 ÷ 3600. 예: 조건 해석 1회 2.8초 → 약 0.12 Wh, 위 실행 전체(85회 호출) → 약 9.9 Wh 상한.
- **실측 전력 데이터는 없다.** 토큰 수와 호출 횟수를 에너지의 대리 지표(proxy)로 쓰며, 위 설계로 줄인 호출 수만큼 에너지도 줄어든다고 추정한다.

모델: `KILN_MODEL=qwen3-32b`. 챌린지 브리프는 `gpt-oss-120b`를 명시했으나 주최측(Bricksum)이 2026-09-28 텔레그램 공지로 제공 모델을 Qwen3-32B로 변경했다(개발 키에서 gpt-oss-120b는 404). 보고서 머리줄에 실제 모델·엔드포인트·실측 여부가 찍힌다. 응답 형식은 `KILN_TOOL_MODE=json` 고정(이 키·모델 조합은 tool calling 인자가 빈 값으로 와서 JSON 모드를 쓴다).

**AI 요금제 (Claude 벤치마킹)**: 쓴 만큼 정산하지 않고 월 구독(Free · Pie Pro · Pie Max 5x · Pie Max 20x)이 5시간 세션 한도와 주간 한도를 정한다. 한도를 넘으면 Kiln을 부르지 않고 규칙으로 답하며, 정산 계산·결제·승인은 코드라 그대로 동작한다. 베타 동안은 `BETA_PLAN=max20`으로 전원 해제. 자세한 규칙: `docs/API.md` 1-4. 보고서: `GET /api/usage/report.md` · `GET /api/usage/calls.csv` · 앱 MY → AI 토큰 세부내용.

## 한계 (명시)

- 충전·등록·중단·판정·환불·지급은 **에이전트 지갑 하나**가 서명하는 데모용 구조다. 참여자 예치만 본인 MetaMask 서명이다.
- 증거 실행기(`npm run evidence`)는 참여자 예치를 스크립트가 참여자 테스트 지갑으로 대신 서명한다(같은 컨트랙트 호출). 실제 사용자 MetaMask 예치 기록은 베타 실체인 데이터에서 확보한다.
- Run 2의 착오("판매자 품절 취소")는 시연용 시나리오다. 판정은 AI가, 환불 실행은 코드가 한다.
- 가스 실측은 Sepolia 값이며 다른 EVM 테스트넷에서는 시세에 따라 달라진다.
- 에너지는 실측이 아닌 상한 추정이다(위 가정).

## Pie 두뇌 적용 · 베타 데이터 수집

- **Pie 두뇌 (`agent/brain.py` ← `agent/pie_brain/`)**: 1:1 Pie와 그룹방 Pie mate의 시스템 프롬프트를 'Pie mate 학습 가이드라인' 순서로 조립한다 — persona → 모드 규칙(chat|group) → 도구 쓰는 법(코드) → 상황 정보 → 관련 지식 최대 2조각(800자) → 태그가 맞는 예시 최대 3개(750자). 파일을 고치면 다음 호출부터 반영. 정산 해석·설명·분쟁 판정·구매 조건 해석은 전용 프롬프트 그대로. 턴마다 0토큰 기록(`assistant.brain`)에 태그·넣은 지식·예시·프롬프트 글자 수가 남는다.
- **베타 미션 13개 (홈 · MY → 베타 테스트 참여)**: 필요한 데이터를 얻도록 만든 기능 예시. 학습용(태그를 고루 · 까다로운 말투), 버전 비교용 기준 과제 6개(같은 문장), 심사 기준용(지출 통제 중단 → 조건 바꿔 재실행, 이의제기로 기록 검토). 답마다 ‘도움 됐어요 · 아쉬워요(+이유)’.
- **동의**: 대화 글은 ‘대화 제공’에 동의한 사람만 비식별 저장. 동의하지 않아도 미션은 되고 토큰 통계만 남는다. 철회하면 저장된 것도 삭제.
- **보고서**: `GET /api/beta/report.md` (버전 비교 · 시나리오별 턴당 토큰 · 심사 기준 실행 수 · 참여), 학습·평가 후보는 관리자만 `GET /api/beta/export.jsonl?kind=train|eval`.
- **정식 버전과 비교**: 베타는 `APP_VERSION=beta-1`, 정식은 `APP_VERSION=1.0`으로 배포 — 같은 `data/usage.jsonl`에 쌓이면 보고서가 버전별로 나눠 보여 준다(서버를 옮기면 두 파일을 합쳐서).
- **계산 조건 해석 (가이드라인 ⑥)**: 정산 해석 프롬프트에 유형별 예시(`agent/pie_brain/calc_examples.jsonl`)가 붙고, 해석 결과에 금액 조각·1인당 금액·일부만 나누는 항목·단위 맞춤·% 종류 필드가 있다. 코드 안전망이 AI가 놓친 조건을 다시 읽는다. 한국어 금액은 한글 숫자·앞자리 생략까지 읽는다(만2천원 → 12,000 · 만오천원 → 15,000 · 삼만오천원 · 이십만원 · 천오백원). '민재는 진우 두 배'처럼 조정된 사람을 다시 기준으로 삼으면 되묻는다.
- 계산 평가: `DATA_DIR=/tmp/sp-calc LLM_MODE=mock KILN_API_KEY= python tests/calc_check.py` (코드 안전망 51문제 100%) · 실제 Kiln은 `LLM_MODE=live`로 같은 명령 (목표 분담표 95%·되묻기 100%). 베타에서 👎 받은 계산 문장은 `tests/calc_eval.jsonl`에 추가한다.
- **베타 서버 (`deploy/`)**: 100명 동시 접속 설정 · 데이터는 `beta-data/` 한 폴더에(이 폴더만 보내면 됨) · 도커+Caddy(HTTPS)·Windows 실행 · 부하 테스트 → **`deploy/README.md`**. 베타 정산은 실체인(`CHAIN_MODE=bsc`)에서 모아야 온체인 증거가 된다.
- 테스트: `tests/brain_check.py` · `tests/beta_check.py` (실행 방법은 각 파일 맨 위), 화면은 `tests/frontend_logic.test.mjs`.
