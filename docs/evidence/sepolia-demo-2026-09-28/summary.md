# SharePie 데모 증거 묶음

- 모드: **testnet** (sepolia)
- 실행: 2026-09-28T15:34:30.091Z → 2026-09-28T15:40:17.104Z
- 단계: preflight ✅ · Run 1 ✅ · Run 1.5 ✅ · Run 2 ✅ · release ✅ · verify ✅

## 사전 점검 (preflight)
- ✅ 체인 설정 (CHAIN_ID): sepolia (chainId 11155111, 기본 Sepolia)
- ✅ RPC 접속 (BLOCKCHAIN_RPC_URL): 연결됨 — sepolia (chainId 11155111)
- ✅ 운영자 지갑 (DEPLOYER_PRIVATE_KEY): 0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36 — 잔액 0.04766413209354446 ETH (테스트넷)
- ✅ 결제처 주소 (MERCHANT_ADDRESS): 0x39be6b7b0D720eAfCc185581ee277AF68cCad867
- ✅ 컨트랙트 (CONTRACT_ADDRESS): 0x8F7dba19727D5A8808AEe589e6a16482e8e048E9 — 코드 배포됨 (6464 bytes)
- ✅ Kiln 키 (KILN_API_KEY): 설정됨 (sk-bk-…(54자))
- ✅ Kiln 모델 (KILN_MODEL): qwen3-32b
- ✅ 보류 기간 (SETTLEMENT_HOLD_SECONDS): 60초 — Run 1 release 는 이 시간 뒤에 가능

## 트랜잭션 (함수 · TxHash · 탐색기)
| Run | 함수 | TxHash | 탐색기 |
|---|---|---|---|
| Run 1 | open_settlement | `0x47724de554bb33b08d770cb6800043466e43e0979f2087a74767980364aca7f0` | https://sepolia.etherscan.io/tx/0x47724de554bb33b08d770cb6800043466e43e0979f2087a74767980364aca7f0 |
| Run 1 | lock_for_settlement (u0) | `0x6135ee032b642061a151049560015ec2ea89b7308889510a40c99302fbf187a1` | https://sepolia.etherscan.io/tx/0x6135ee032b642061a151049560015ec2ea89b7308889510a40c99302fbf187a1 |
| Run 1 | lock_for_settlement (u1) | `0x639c90ac7ce63b9f66798cca36d34ef5e72558befeac44b2d216957ff4c8e383` | https://sepolia.etherscan.io/tx/0x639c90ac7ce63b9f66798cca36d34ef5e72558befeac44b2d216957ff4c8e383 |
| Run 1 | lock_for_settlement (u2) | `0xd1267524e119a3d1d6e92d344e5decac019933000355254e39ad7d4175d90717` | https://sepolia.etherscan.io/tx/0xd1267524e119a3d1d6e92d344e5decac019933000355254e39ad7d4175d90717 |
| Run 1 | lock_for_settlement (u3) | `0xe49d307a942269d68b902acea481217efc85f4a37c5a899284559e53033c3e8a` | https://sepolia.etherscan.io/tx/0xe49d307a942269d68b902acea481217efc85f4a37c5a899284559e53033c3e8a |
| Run 1 | confirm = 마지막 lock (SettlementConfirmed, 인증서) | `0xe49d307a942269d68b902acea481217efc85f4a37c5a899284559e53033c3e8a` | https://sepolia.etherscan.io/tx/0xe49d307a942269d68b902acea481217efc85f4a37c5a899284559e53033c3e8a |
| Run 1 | release_to_recipient | `0x043796aa5da93f768e0709edeee5aa16812884cddd061c41d286aba7c8fdaf91` | https://sepolia.etherscan.io/tx/0x043796aa5da93f768e0709edeee5aa16812884cddd061c41d286aba7c8fdaf91 |
| Run 2 | open_settlement (주입 정산) | `0x3081fe9bdcef9c4394910420e68a637a032a577ae1f327b312a26f057abf12ef` | https://sepolia.etherscan.io/tx/0x3081fe9bdcef9c4394910420e68a637a032a577ae1f327b312a26f057abf12ef |
| Run 2 | confirm (주입 정산 잠금 확정) | `0x3bcd7f18c2815737d6f332d77d49bbcc3bd63dbd95d0a4332d2e621fa2aa31d9` | https://sepolia.etherscan.io/tx/0x3bcd7f18c2815737d6f332d77d49bbcc3bd63dbd95d0a4332d2e621fa2aa31d9 |
| Run 2 | raise_dispute | `0xe8b61f7f6ce17e23189fd4cd3273e4dc9c6aaca668fca6a81f0f0ea772847adb` | https://sepolia.etherscan.io/tx/0xe8b61f7f6ce17e23189fd4cd3273e4dc9c6aaca668fca6a81f0f0ea772847adb |
| Run 2 | resolve_dispute (GENUINE_ERROR) | `0x0b47441804f43789d5aa82133d418773732a620b7bfc5af97778ab399f4f55db` | https://sepolia.etherscan.io/tx/0x0b47441804f43789d5aa82133d418773732a620b7bfc5af97778ab399f4f55db |
| Run 2 | refund_participant #1 | `0x904fbe4c1ccca8d1f33d6038012fbc43232194ada4a6017a9a245ede2b2d4d67` | https://sepolia.etherscan.io/tx/0x904fbe4c1ccca8d1f33d6038012fbc43232194ada4a6017a9a245ede2b2d4d67 |
| Run 2 | refund_participant #2 | `0x5ebd44491dad820c6997defe086e2af05961280f60152d19249685ccea8d87c8` | https://sepolia.etherscan.io/tx/0x5ebd44491dad820c6997defe086e2af05961280f60152d19249685ccea8d87c8 |
| Run 2 | refund_participant #3 | `0x7f5db134389775980cb6dba120e1c32539d6778c2049377f0e69230fdc275e5d` | https://sepolia.etherscan.io/tx/0x7f5db134389775980cb6dba120e1c32539d6778c2049377f0e69230fdc275e5d |
| Run 2 | refund_participant #4 | `0x14959ada33cbc20bf2c41791e40a1f30872021c750b8653e6e35bdf0675f49d9` | https://sepolia.etherscan.io/tx/0x14959ada33cbc20bf2c41791e40a1f30872021c750b8653e6e35bdf0675f49d9 |
| Run 2 | confirm (정정 정산 잠금 확정) | `0x7143fe572b361591c727e36dc58fca233d49ace9cab92bf823a8106947fd9fe8` | https://sepolia.etherscan.io/tx/0x7143fe572b361591c727e36dc58fca233d49ace9cab92bf823a8106947fd9fe8 |

## Run 1 — 정상 정산
- 정산 id: `0x78173f19a07317bf2f4554959c99695eb4ba7a22d6d5067f2c531d5b0a69030d`
- 조건 해시(conditionsHash): `0xb31f16323ac656a1ca5773c977ccd33b786aa505eba6f9c6389b226ebe215f80`
- 분담: 진주(u0) 5225 · 진우(u1) 10225 · 민재(u2) 10225 · 지현(u3) 10225 = 35900 PIE (예산 40000)
- 상태: LOCKED(보류) → holdUntil 1790609808 (60초). 인증서 TxHash = `0xe49d307a942269d68b902acea481217efc85f4a37c5a899284559e53033c3e8a`
- release: ✅ 지급 완료 → `0x043796aa5da93f768e0709edeee5aa16812884cddd061c41d286aba7c8fdaf91` (SharePie 정산 에스크로)

## Run 1.5 — 조건 변경 → 코드 중단 (온체인 트랜잭션 0건)
- ✅ 1. 예산 변경 (40,000 → 30,000) → OVER_BUDGET — 예산 40,000→30,000 변경 → overBudgetBy 5900 → 승인 거부(OVER_BUDGET), 잠금 0건
- ✅ 2. 잔액 부족 (u3: 100 PIE < 10,225) → INSUFFICIENT_BALANCE — u3 잔액 100 PIE < 분담금 10225 → 잠금 전 잔액 선확인에서 거부(INSUFFICIENT_BALANCE), 잠금 0건
- AI는 조건 해석(Stage 1)에만 쓰인다. 중단 판단은 코드(Stage 2 예산 검증 / 잠금 전 잔액 선확인)가 한다. 이 스크립트는 AI를 호출하지 않는다.

## Run 2 — 이의제기 재조사 (계산 단계 착오 시뮬레이션)
- 주입: 합의 분담 [5225, 10225, 10225, 10225] 대신 [8975, 8975, 8975, 8975] 잠금 (INJECTED_ERROR: shares replaced). 조건 해시는 합의 조건 그대로 `0xb31f16323ac656a1ca5773c977ccd33b786aa505eba6f9c6389b226ebe215f80`
- 이의제기: u0 — "진주(u0)가 5,000원 적게 내기로 했는데 같은 금액이 잠겼어요"
- AI 재조사(dispute.investigate): mismatchDetected=true, mismatchPoint=계산 단계, expected=5225, actual=8975 → verdict=**GENUINE_ERROR**
- 실행: mismatchDetected=true, mismatchPoint=계산 단계 → verdict=GENUINE_ERROR → refund_participant × 4/4 → 상태 CANCELLED
- 정정 정산: `0x3205db22871abf524c31698fab7a41f4f97e1d5c38f76dedcd863b2fc05551c9` (LOCKED, 올바른 분담 [5225, 10225, 10225, 10225])

## AI 응답 → 코드 판정 → 행동 (events.jsonl)
- [settlement.abort] 총액 35900 > 예산 30000 (overBudgetBy 5900) → 코드 판정 OVER_BUDGET → 중단 (잠금 0건)
- [settlement.abort] u3 PieCoin 잔액 부족 (u3님의 PieCoin 잔액(100 PIE)이 분담금 10225 PIE보다 적어 잠금이 거부됐어요.) → 코드 판정 INSUFFICIENT_BALANCE → 중단 (잠금 0건)
- [run2.injected_error] INJECTED_ERROR: shares replaced (calculation-stage error simulation)
- [dispute.raise] raise_dispute 호출 → 체인 동결(DISPUTED) `0xe8b61f7f6ce17e23189fd4cd3273e4dc9c6aaca668fca6a81f0f0ea772847adb`
- [dispute.action] mismatchDetected=true, mismatchPoint=계산 단계 → verdict=GENUINE_ERROR → refund_participant × 4/4 · resolve `0x0b47441804f43789d5aa82133d418773732a620b7bfc5af97778ab399f4f55db` · refunds `0x904fbe4c1ccca8d1f33d6038012fbc43232194ada4a6017a9a245ede2b2d4d67`, `0x5ebd44491dad820c6997defe086e2af05961280f60152d19249685ccea8d87c8`, `0x7f5db134389775980cb6dba120e1c32539d6778c2049377f0e69230fdc275e5d`, `0x14959ada33cbc20bf2c41791e40a1f30872021c750b8653e6e35bdf0675f49d9`
- [settlement.release] release_to_recipient 호출 `0x043796aa5da93f768e0709edeee5aa16812884cddd061c41d286aba7c8fdaf91`

## AI 토큰 사용량 (단계별, /logs/tokens 와 같은 집계 — 누적)
| stage | 호출 | 입력 AI 토큰 | 출력 AI 토큰 | cost(USD) |
|---|---:|---:|---:|---:|
| settlement.analyze | 9 | 10508 | 3729 | 0.0015192 |
| settlement.calculate | 15 (code-only) | 0 | 0 | 0 |
| settlement.explain | 2 | 1160 | 1061 | 0.00036516 |
| dispute.investigate | 4 | 7512 | 2543 | 0.0011236 |
| shopping.search | 14 | 9664 | 9074 | 0.0029653200000000005 |

## 제3자 검증 (verify-conditions)
- ✅ MATCH — 로컬 `0xb31f16323ac656a1ca5773c977ccd33b786aa505eba6f9c6389b226ebe215f80` vs 체인 `0xb31f16323ac656a1ca5773c977ccd33b786aa505eba6f9c6389b226ebe215f80`

> 한계: 운영자 지갑 하나(DEPLOYER_PRIVATE_KEY)가 모든 트랜잭션에 서명하는 데모용 수탁 구조. Run 2 의 착오는 의도적으로 주입한 시뮬레이션이며, 온체인 금액이 아니라 "합의 조건 해시 ≠ 잠긴 금액"으로 만들어진다.
