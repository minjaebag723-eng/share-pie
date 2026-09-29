## 블록체인 (Ethereum Sepolia 테스트넷) — 배포 · 온체인 증거 · 제3자 검증

> 챌린지 A "Blockchain Integration / Condition Checks & Evidence" 대응. 테스트넷 전용이며 실제 화폐·메인넷은 다루지 않는다.

### 배포 정보

| 항목 | 값 |
|---|---|
| 네트워크 | Ethereum Sepolia (chainId 11155111) — 주최측 공용 테스트넷이 없어 팀이 선택 (텔레그램 확인, 2026-09-28) |
| ShareLedger (에스크로·자금추적·이의제기) | [`0xF297240957c3aB10458Dc1A4C6eC2eA18292529E`](https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E) (배포 블록 11801645) |
| PieToken (PieCoin, decimals 0, 1 PIE = 1원 표시, 실화폐 가치 없음) | [`0xF5cB871A8890bd1D34bf36E749F012D95589E0fD`](https://sepolia.etherscan.io/address/0xF5cB871A8890bd1D34bf36E749F012D95589E0fD) |
| 에이전트(Pie) 지갑 | `0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36` — 등록·중단·판정·환불·지급을 서명 (테스트 전용 지갑) |
| 이의제기 기간 (`disputeWindow`) | 180초 (베타 설정, `.env DISPUTE_WINDOW_SEC`·컨트랙트 `setDisputeWindow` 동일값) |

배포·검증 명령 (`hardhat/`):
```bash
cd hardhat && npm install
npm test                                   # 컨트랙트 테스트 30개 (로컬 체인)
npm run deploy -- --network sepolia        # PieToken + ShareLedger 배포 → contracts/abi/*.json, hardhat/deployments/sepolia.json
npm run smoke                              # 서버·.env·권한·해석·가드·체인 쓰기 스모크 (🔴 0 이어야 통과)
npm run evidence                           # Run 1 / 1.5 / 2 실제 체인 실행 → docs/evidence/<시각>/summary.md
```

### 체인이 워크플로에서 하는 일 (읽기 · 쓰기 · 정산)

| 단계 | 함수 (Solidity) | 서명 | 체인 상태 |
|---|---|---|---|
| PIE 충전 | `PieToken.chargeToken(to, amount)` | 에이전트 | 잔액 |
| 정산 등록 (조건 해시 + 목적 포함) | `ShareLedger.createSettlement(id, token, payee, members[], shares[], conditionHash, purpose)` | 에이전트 | `Open` · `SettlementCreated` |
| 참여자 예치 | `PieToken.approve` → `ShareLedger.lockForSettlement(id)` (잔액 부족이면 revert — 일부만 잠기는 상태 없음) | **참여자 본인** | `Locked` · `FullyLocked(releaseAfter)` |
| 지급 (보류 기간 후) | `releaseToRecipient(id)` | 에이전트(자동) | `Paid` = 정산 인증서 TxHash |
| 지출 통제 위반 시 중단 | `blockSettlement(id, member, reasonCode, note)` | 에이전트 | `Blocked` (트랜잭션 0건으로 조용히 끝내지 않고 기록) |
| 이의제기 | `raiseDispute(id, by, reason)` (지급 전까지만) | 참여자 / 에이전트 대행 | `Disputed` (동결) |
| 판정 실행 | `refundParticipant(id, p)` × N → `resolveDispute(id, verdict 1/2/3, note)` | 에이전트 | `Refunded` 또는 `Paid` |
| 읽기 | `getSettlement` · `getMembers` · `releaseAt` · `committedOf/escrowOf/spentOf` | — | 화면 자금추적·감시 루프(5초) |

AI는 이 표의 어떤 함수도 직접 부르지 않는다. AI 응답(규칙 JSON · 판정)을 코드가 검증한 뒤 코드가 호출한다.

### 조건 2회 변경 실행 — 온체인 증거 (2026-09-28, v39, 실제 Sepolia)

전체 표·Etherscan 링크·AI 토큰 표: `docs/evidence/sepolia-2026-09-28T22-36-17/summary.md`

| Run | 조건 | 결과 | 대표 TxHash |
|---|---|---|---|
| **1 정상** | "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘", 총 35,900, 예산 40,000 → 코드 계산 [5,225 / 10,225 × 3] | 등록 → 3명 예치 → 보류 → **지급 (paid)** | 등록 [`0xb5d5…60c0`](https://sepolia.etherscan.io/tx/0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0) · 지급(인증서) [`0x932d…d7c6`](https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6) |
| **1.5 조건 변경 ①** | 같은 조건에 1인 한도 9,000원 | 코드 `OVER_PERSON_CAP` → **등록 없이 중단**, `Blocked` 기록 | [`0x4e77…f5cb`](https://sepolia.etherscan.io/tx/0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb) |
| **1.5 조건 변경 ②** | 총 한도 30,000원 | 코드 `OVER_TOTAL_CAP` → 중단, `Blocked` 기록 | [`0x8367…33fc`](https://sepolia.etherscan.io/tx/0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc) |
| **2 이의제기** | 예치 완료 후 "판매자 품절 취소" 이의제기 → AI `dispute.investigate` = **GENUINE_ERROR** (refund=all) | 코드가 환불 3건 + 판정 실행 → **refunded**, 잔액 전액 복구 | 이의제기 [`0x156e…8d31`](https://sepolia.etherscan.io/tx/0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31) · 환불 [`0xfa90…f228`](https://sepolia.etherscan.io/tx/0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228) · 판정 [`0x9a21…55a3`](https://sepolia.etherscan.io/tx/0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3) |

AI 응답 → 행동 대응 (로그 `events.jsonl` / `summary.md`):
- `settlement.analyze` → `status: ok` + 규칙 JSON → 코드 계산·지출 통제 → 통과 시 `createSettlement`, 위반 시 `blockSettlement` (AI 호출 0회로 중단)
- `settlement.analyze` → `need_info` → 되묻기, 체인 호출 없음
- `dispute.investigate` → `GENUINE_ERROR` → `refundParticipant` × N → `resolveDispute(2)`; `NORMAL_APPROVAL`/`BAD_FAITH_DISPUTE` → `resolveDispute(1|3)` 후 지급

함수별 실측 가스 (Sepolia 영수증): 정산 등록 513,574 · 예치 128,725 · 지급 146,673 · 차단 51,378 · 이의제기 39,426 · 환불 61,997 · 판정 65,226 · 충전 38,317. 정산 1건(등록+지급) ≈ 0.0014 ETH, 참가자 1명 준비(가스 자동 지급 0.002 + 충전) ≈ 0.0021 ETH (시세 ~2 gwei 기준).

### 제3자 검증 — 기록만 보고 조건을 지켰는지 판단하기

1. 정산 인증서(앱 '정산 인증서 보기' / `summary.md`)의 **조건 원문**과 분담표를 본다.
2. Etherscan에서 등록 트랜잭션의 `SettlementCreated` 이벤트 → `conditionHash`, `shares[]`, `purpose`를 읽는다.
3. 조건 원문을 같은 방식(코드 `chain.condition_hash(text)`, keccak256)으로 해시해 `conditionHash`와 대조한다 — 일치하면 "이 온체인 정산은 그 조건으로 만들어졌다".
4. `Locked`/`Paid`/`Blocked`/`Refunded` 이벤트로 누가 얼마를 예치했고 어디로 지급됐는지(또는 왜 중단·환불됐는지) 본다. 지급 목적 문자열은 이름·연락처를 지운 뒤 60자 이내로 기록된다.

### 안전장치 (코드에서 강제, AI 우회 불가)

- 잔액 부족 예치 revert (컨트랙트) · 합계=총액 · 1인/총 한도 · 허용 판매처 · 가용 잔액 검사 (등록 전, 코드)
- 한글 금액 오파싱 방어: 문장에 '만/억'이 있는데 총액이 그보다 작으면 등록 거부 (`AMOUNT_SUSPECT`)
- 판정-환불 일관성: `GENUINE_ERROR`인데 환불 대상이 없으면 제기자 환불로 보정
- 온체인 목적 문자열 60자 제한 · 가스 가격 시세×2 + 영수증 대기 300초 (테스트넷 혼잡 대비)

### 한계 (명시)

- 등록·중단·판정·환불·지급은 **에이전트 지갑 하나**가 서명하는 데모용 수탁 구조. 참여자 예치만 본인 MetaMask 서명.
- 증거 실행기(`npm run evidence`)는 참여자 예치를 스크립트가 참여자 테스트 지갑으로 대신 서명한다(같은 컨트랙트 호출).
- Run 2의 착오는 시연용으로 주입한 시나리오("판매자 품절 취소")이며 판정은 AI가, 환불 실행은 코드가 한다.
- 가스 실측은 Sepolia 값이며 다른 EVM 테스트넷에서는 시세에 따라 달라진다.
