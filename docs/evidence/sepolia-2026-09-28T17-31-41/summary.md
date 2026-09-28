# SharePie 실제 테스트넷 증거 묶음 (Python 백엔드 + ShareLedger)

- 네트워크: **Sepolia** (chainId 11155111) · 실행 2026-09-28T17:22:31.873Z → 2026-09-28T17:31:41.620Z
- ShareLedger `0xF297240957c3aB10458Dc1A4C6eC2eA18292529E` · PieToken `0xF5cB871A8890bd1D34bf36E749F012D95589E0fD` · 에이전트 `0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36` · 이의제기 기간 180s
- 컨트랙트: https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E
- AI: Kiln qwen3-32b (llm_mode=live) · 서명 모델: 등록·차단·환불·판정 = 에이전트, 예치 = 참여자 지갑(스크립트가 MetaMask 대신 서명)

## 참여자 지갑 (테스트 전용)
- 진주(진주2) `0xAfae051463173d910a48F122BE1FB5807cdcAAC2` — https://sepolia.etherscan.io/address/0xAfae051463173d910a48F122BE1FB5807cdcAAC2
- 진우(진우2) `0x09FA021a7BeE1Cb9B0bC54Dd5B2159Dfc08be2fd` — https://sepolia.etherscan.io/address/0x09FA021a7BeE1Cb9B0bC54Dd5B2159Dfc08be2fd
- 민재(민재2) `0xCDBe8648a551bEb8A51988274931C2842f8Fc871` — https://sepolia.etherscan.io/address/0xCDBe8648a551bEb8A51988274931C2842f8Fc871
- 지현(지현2) `0xb8E7BCFdE023692652D65Bb68D32345714B71F90` — https://sepolia.etherscan.io/address/0xb8E7BCFdE023692652D65Bb68D32345714B71F90

## 트랜잭션
| Run | 종류 | TxHash | 탐색기 |
|---|---|---|---|
| 준비 | charge_token (진주2, 100000 PIE) | `0xa9c9ef8fe051050226b065bbf8f025a68b363e5c8702edb829158836e278a106` | https://sepolia.etherscan.io/tx/0xa9c9ef8fe051050226b065bbf8f025a68b363e5c8702edb829158836e278a106 |
| 준비 | charge_token (진우2, 100000 PIE) | `0x60f71f0e027b09597f3ea267c8305f90a0aab8427d19ef3a824a599090d1ff59` | https://sepolia.etherscan.io/tx/0x60f71f0e027b09597f3ea267c8305f90a0aab8427d19ef3a824a599090d1ff59 |
| 준비 | charge_token (민재2, 100000 PIE) | `0x2aab184ef54ffc9b4c44720f971b039eb2f33a00f44b33eb8bc5958135676b96` | https://sepolia.etherscan.io/tx/0x2aab184ef54ffc9b4c44720f971b039eb2f33a00f44b33eb8bc5958135676b96 |
| 준비 | charge_token (지현2, 100000 PIE) | `0x2c411195a7f6d8e6b06cf22bd49a4e5169c067aecdd62c522f7740f32d23c531` | https://sepolia.etherscan.io/tx/0x2c411195a7f6d8e6b06cf22bd49a4e5169c067aecdd62c522f7740f32d23c531 |
| Run 1 | create | `0x568c30648aabcdb103f598a045dd255ea943e2eb00390215aa467aac60b3b789` | https://sepolia.etherscan.io/tx/0x568c30648aabcdb103f598a045dd255ea943e2eb00390215aa467aac60b3b789 |
| Run 1 | lock (진우2) | `0xae559cb491a600b79514346e37e754a3c42b37187a66257f748ab98224e759f6` | https://sepolia.etherscan.io/tx/0xae559cb491a600b79514346e37e754a3c42b37187a66257f748ab98224e759f6 |
| Run 1 | lock (민재2) | `0x72c6904298dd78577e3ec1daeace5fb027a1a62a8db52b7b5890508a10e66220` | https://sepolia.etherscan.io/tx/0x72c6904298dd78577e3ec1daeace5fb027a1a62a8db52b7b5890508a10e66220 |
| Run 1 | lock (지현2) | `0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386` | https://sepolia.etherscan.io/tx/0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386 |
| Run 1 | escrow | `0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386` | https://sepolia.etherscan.io/tx/0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386 |
| Run 1 | release | `0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02` | https://sepolia.etherscan.io/tx/0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02 |
| Run 1 | paid | `0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02` | https://sepolia.etherscan.io/tx/0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02 |
| Run 1.5 | blockSettlement (1인 한도 9,000원) | `0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66` | https://sepolia.etherscan.io/tx/0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66 |
| Run 1.5 | block | `0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66` | https://sepolia.etherscan.io/tx/0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66 |
| Run 1.5 | blockSettlement (총 한도 30,000원) | `0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162` | https://sepolia.etherscan.io/tx/0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162 |
| Run 1.5 | block | `0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162` | https://sepolia.etherscan.io/tx/0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162 |
| Run 2 | create | `0x48323fb903f7c8141be80ddb71ebf531b7c75e40f1de3f28631ef75e77a37a97` | https://sepolia.etherscan.io/tx/0x48323fb903f7c8141be80ddb71ebf531b7c75e40f1de3f28631ef75e77a37a97 |
| Run 2 | lock (진우2) | `0x0112ef7575d374886c24be2636a8832cb5e3b1617d90ebc363d742481a7ce3a5` | https://sepolia.etherscan.io/tx/0x0112ef7575d374886c24be2636a8832cb5e3b1617d90ebc363d742481a7ce3a5 |
| Run 2 | lock (민재2) | `0xd7df4f7b8811487da0f27af06128a48949726146f07e7030800d7539613ad487` | https://sepolia.etherscan.io/tx/0xd7df4f7b8811487da0f27af06128a48949726146f07e7030800d7539613ad487 |
| Run 2 | lock (지현2) | `0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2` | https://sepolia.etherscan.io/tx/0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2 |
| Run 2 | escrow | `0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2` | https://sepolia.etherscan.io/tx/0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2 |
| Run 2 | dispute (진우2) | `0xcce569f05c3cbbfc065a6c4ac92aef3cbc18fa5b556905aac2a7fd83a5cad789` | https://sepolia.etherscan.io/tx/0xcce569f05c3cbbfc065a6c4ac92aef3cbc18fa5b556905aac2a7fd83a5cad789 |
| Run 2 | refund (진우2) | `0x6c7e13d56f9612ed82c77c69b9f09c163fcbb2a00bb274d8a7e37328b8441085` | https://sepolia.etherscan.io/tx/0x6c7e13d56f9612ed82c77c69b9f09c163fcbb2a00bb274d8a7e37328b8441085 |
| Run 2 | refund (민재2) | `0xea9a151a64d743fb5792bce6fd1a28557e24b1dc57ac6889f40295c3335b07b3` | https://sepolia.etherscan.io/tx/0xea9a151a64d743fb5792bce6fd1a28557e24b1dc57ac6889f40295c3335b07b3 |
| Run 2 | refund (지현2) | `0x4035b5f08794f5707ff6282ba566a40216df45cef1e4f0b79006503fd2eacf24` | https://sepolia.etherscan.io/tx/0x4035b5f08794f5707ff6282ba566a40216df45cef1e4f0b79006503fd2eacf24 |
| Run 2 | resolve | `0x576abdb7c8862d013640ab204616f927f18ba44dfa92caa17a0812062b0e9ba2` | https://sepolia.etherscan.io/tx/0x576abdb7c8862d013640ab204616f927f18ba44dfa92caa17a0812062b0e9ba2 |

## Run 1 — 정상 정산
- 조건: "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘" (총 35,900 · 예산 40,000) → Stage1(AI)+Stage2(코드): [["진주2",5225],["진우2",10225],["민재2",10225],["지현2",10225]]
- 규칙: 진주2는 5천원 적게 내고 나머지 세 명이 나눠줘 · 목적: 삼겹살 공동구매 분담금( 5천원 감면)
- 정산 id `sp-a2f2ac6f3f` · chainId `0xf8189a018935cbad8c96d7b01ceaf76a551034a0cc58f3f8cb76597c7371f022` · 최종 상태 **paid**
- 인증서 TxHash: `0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02` (https://sepolia.etherscan.io/tx/0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02)
- 지급 후 PIE 잔액: {"진주2":415200,"진우2":261600,"민재2":261600,"지현2":261600}

## Run 1.5 — 조건 변경 → 지출 통제 중단
- 1인 한도 9,000원: 상태 **blocked** · reason_code 2 · 진우2님 10,225원 > 1인 한도 9,000원 · tx `0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66`
- 총 한도 30,000원: 상태 **blocked** · reason_code 5 · 총액 35,900원이 총 예산 30,000원을 넘어요 · tx `0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162`
- 예치·지급 트랜잭션 없음. 중단 판단은 코드(지출 통제)이며 체인에 Blocked 이벤트로 기록됨.

## Run 2 — 이의제기 → AI 판정 → 자동 실행
- 정산 id `sp-a9217d3b42` · 이의제기: 진우2 — "판매자가 품절로 주문을 취소했어요. 예치금을 전원 돌려받아야 해요"
- AI 판정(dispute.investigate): **GENUINE_ERROR** (진짜 착오 (환불)) · refund=all
- 설명: 판매자 주문취소로 인한 공동구매 실패. 결제금 30,675원은 에스크로 상태로 결제자에게 지급되지 않았으며, 분담금 환불 대상은 전원 해당됩니다. 분담 조건 원문과 정산 코드 모두 무결성 검증 통과.
- 실행 후 상태 **refunded** · PIE 잔액 전/후: {"진주2":415200,"진우2":251375,"민재2":251375,"지현2":251375} → {"진주2":415200,"진우2":261600,"민재2":261600,"지현2":261600}

## AI 토큰 사용량 (서버 /api/usage/report.md)
| 단계 | 호출 | 입력 토큰 | 출력 토큰 | 합계 | 평균 | 지연(ms) | 에너지 상한(Wh) |
|---|---|---|---|---|---|---|---|
| assistant.step | 5 | 14408 | 867 | 15275 | 3055.0 | 16099 | 0.67079 |
| assistant.tool | 10 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| chat.route | 1 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| dispute.investigate | 3 | 2326 | 790 | 3116 | 1038.7 | 13685 | 0.57021 |
| dispute.records | 3 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.analyze | 9 | 11122 | 1352 | 12474 | 1386.0 | 24762 | 1.03175 |
| settlement.calculate | 8 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.policy | 12 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |

총 30865 토큰 · Kiln 호출 17회 · 코드 처리 34단계 · 에너지 상한 2.27275 Wh
가정: Wh = W × cards × latency_s / 3600 (배치 공유 미반영 → 상한) / NPU 150.0W × 1.0장

> 한계: 참여자 예치 서명은 실사용에서 MetaMask 가 하지만 이 증거 실행에서는 스크립트가 참여자 지갑으로 서명했다(동일한 컨트랙트 호출). 등록·차단·환불·판정은 에이전트 지갑 하나가 서명하는 데모용 구조. Run 2 의 이의 사유는 시연용 시나리오다.
