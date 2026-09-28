# SharePie 실제 테스트넷 증거 묶음 (Python 백엔드 + ShareLedger)

- 네트워크: **Sepolia** (chainId 11155111) · 실행 2026-09-28T16:49:25.142Z → 2026-09-28T16:57:41.716Z
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
| 준비 | charge_token (진주2, 100000 PIE) | `0x2089afcfc2e8070845ab425c4207586b4c027016a963ef4e129ed619493a5878` | https://sepolia.etherscan.io/tx/0x2089afcfc2e8070845ab425c4207586b4c027016a963ef4e129ed619493a5878 |
| 준비 | charge_token (진우2, 100000 PIE) | `0x232753681d174eda6b2704651ccade88307805a6c82a2353f7d69a7d95ced9bc` | https://sepolia.etherscan.io/tx/0x232753681d174eda6b2704651ccade88307805a6c82a2353f7d69a7d95ced9bc |
| 준비 | charge_token (민재2, 100000 PIE) | `0x9a5481cbd764e0d4c822457ef6614cf53a8bcd047400b5521c427c7169153367` | https://sepolia.etherscan.io/tx/0x9a5481cbd764e0d4c822457ef6614cf53a8bcd047400b5521c427c7169153367 |
| 준비 | charge_token (지현2, 100000 PIE) | `0x76b2a9f538a050136aefd931428cedd44d91687a6ec2f51ff34cccc97d4792f5` | https://sepolia.etherscan.io/tx/0x76b2a9f538a050136aefd931428cedd44d91687a6ec2f51ff34cccc97d4792f5 |
| Run 1 | create | `0x206e0216bb0ab2ae9499418df693b8701f665226e6108da6fc20a3f5266ef13e` | https://sepolia.etherscan.io/tx/0x206e0216bb0ab2ae9499418df693b8701f665226e6108da6fc20a3f5266ef13e |
| Run 1 | lock (진우2) | `0x7bb6fbecd0ed0180b16c4fba10f28bd716ed4c37b49d773f07455a67be4777fc` | https://sepolia.etherscan.io/tx/0x7bb6fbecd0ed0180b16c4fba10f28bd716ed4c37b49d773f07455a67be4777fc |
| Run 1 | lock (민재2) | `0x3c817d583fec85961e7d99c9f17df2c37ea9d1a816dbe03463dd67d4f73437dc` | https://sepolia.etherscan.io/tx/0x3c817d583fec85961e7d99c9f17df2c37ea9d1a816dbe03463dd67d4f73437dc |
| Run 1 | lock (지현2) | `0x2e702e5328292bb888898804fb632e16f16ba0781e6273ebadbdcbc4e98baf30` | https://sepolia.etherscan.io/tx/0x2e702e5328292bb888898804fb632e16f16ba0781e6273ebadbdcbc4e98baf30 |
| Run 1 | escrow | `0x2e702e5328292bb888898804fb632e16f16ba0781e6273ebadbdcbc4e98baf30` | https://sepolia.etherscan.io/tx/0x2e702e5328292bb888898804fb632e16f16ba0781e6273ebadbdcbc4e98baf30 |
| Run 1 | release | `0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189` | https://sepolia.etherscan.io/tx/0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189 |
| Run 1 | paid | `0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189` | https://sepolia.etherscan.io/tx/0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189 |
| Run 1.5 | create | `0x9d90e808532df1e070b7322886ec880ac9def22ac939a7225c8156f798f8cf82` | https://sepolia.etherscan.io/tx/0x9d90e808532df1e070b7322886ec880ac9def22ac939a7225c8156f798f8cf82 |
| Run 1.5 | blockSettlement (총 한도 30,000원) | `0x656bbf5082866c76903f4c5b5644a8172eeb4cf7de3674bf61815c1ddbcc4f48` | https://sepolia.etherscan.io/tx/0x656bbf5082866c76903f4c5b5644a8172eeb4cf7de3674bf61815c1ddbcc4f48 |
| Run 1.5 | block | `0x656bbf5082866c76903f4c5b5644a8172eeb4cf7de3674bf61815c1ddbcc4f48` | https://sepolia.etherscan.io/tx/0x656bbf5082866c76903f4c5b5644a8172eeb4cf7de3674bf61815c1ddbcc4f48 |
| Run 2 | create | `0x77c56891fea34a55bf1df523f5e6cdd9967ef0cbc2739894f106a461f4eaea78` | https://sepolia.etherscan.io/tx/0x77c56891fea34a55bf1df523f5e6cdd9967ef0cbc2739894f106a461f4eaea78 |
| Run 2 | lock (진우2) | `0xa704bb5f7a009d215f6992804bca90554b74e5eca81675c3692a9f049ff7db7b` | https://sepolia.etherscan.io/tx/0xa704bb5f7a009d215f6992804bca90554b74e5eca81675c3692a9f049ff7db7b |
| Run 2 | lock (민재2) | `0xe8f7b968be2793bdd871cf301e0f54566ecd4a6b2c31351987cb5feb21b1b0df` | https://sepolia.etherscan.io/tx/0xe8f7b968be2793bdd871cf301e0f54566ecd4a6b2c31351987cb5feb21b1b0df |
| Run 2 | lock (지현2) | `0x46e18540023890d5a93e535d7b33c8cabb4b7b4245afce475efed844a14281a0` | https://sepolia.etherscan.io/tx/0x46e18540023890d5a93e535d7b33c8cabb4b7b4245afce475efed844a14281a0 |
| Run 2 | escrow | `0x46e18540023890d5a93e535d7b33c8cabb4b7b4245afce475efed844a14281a0` | https://sepolia.etherscan.io/tx/0x46e18540023890d5a93e535d7b33c8cabb4b7b4245afce475efed844a14281a0 |
| Run 2 | dispute (진우2) | `0x7e1b4dbb9f771c79a8ced56038c41f1d890a53b3f27add7fafdbd0c5a2eda72a` | https://sepolia.etherscan.io/tx/0x7e1b4dbb9f771c79a8ced56038c41f1d890a53b3f27add7fafdbd0c5a2eda72a |
| Run 2 | resolve | `0x6a47d5e0c9cfb1dd6ee8fae84187d4a7f42e9f09b89dc4b29b967ef0dd1eee9b` | https://sepolia.etherscan.io/tx/0x6a47d5e0c9cfb1dd6ee8fae84187d4a7f42e9f09b89dc4b29b967ef0dd1eee9b |
| Run 2 | paid | `0x6a47d5e0c9cfb1dd6ee8fae84187d4a7f42e9f09b89dc4b29b967ef0dd1eee9b` | https://sepolia.etherscan.io/tx/0x6a47d5e0c9cfb1dd6ee8fae84187d4a7f42e9f09b89dc4b29b967ef0dd1eee9b |

## Run 1 — 정상 정산
- 조건: "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘" (총 35,900 · 예산 40,000) → Stage1(AI)+Stage2(코드): [["진주2",8975],["진우2",8975],["민재2",8975],["지현2",8975]]
- 규칙: 진주2는 5천원 적게 내고 나머지 세 명이 나눠줘 · 목적: 삼겹살 1.2kg 공동구매 분담금(균등)
- 정산 id `sp-739a23e28a` · chainId `0x2487f9347ae953942b4cd89897e2d7909b864a9859b97e2a3ef18fa25c9b5ea4` · 최종 상태 **paid**
- 인증서 TxHash: `0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189` (https://sepolia.etherscan.io/tx/0x6511a5be7088364e9f891e301879e81dcc47c5155de8e59d3943dc50e1ca3189)
- 지급 후 PIE 잔액: {"진주2":126925,"진우2":91025,"민재2":91025,"지현2":91025}

## Run 1.5 — 조건 변경 → 지출 통제 중단
- 1인 한도 9,000원: 상태 **open**
- 총 한도 30,000원: 상태 **blocked** · reason_code 5 · 총액 35,900원이 총 예산 30,000원을 넘어요 · tx `0x656bbf5082866c76903f4c5b5644a8172eeb4cf7de3674bf61815c1ddbcc4f48`
- 예치·지급 트랜잭션 없음. 중단 판단은 코드(지출 통제)이며 체인에 Blocked 이벤트로 기록됨.

## Run 2 — 이의제기 → AI 판정 → 자동 실행
- 정산 id `sp-ad7eae84df` · 이의제기: 진우2 — "판매자가 품절로 주문을 취소했어요. 예치금을 전원 돌려받아야 해요"
- AI 판정(dispute.investigate): **NORMAL_APPROVAL** (정상 승인 (정산 유지)) · refund=none
- 설명: 
- 실행 후 상태 **paid** · PIE 잔액 전/후: {"진주2":126925,"진우2":82050,"민재2":82050,"지현2":82050} → {"진주2":153850,"진우2":82050,"민재2":82050,"지현2":82050}

## AI 토큰 사용량 (서버 /api/usage/report.md)
| 단계 | 호출 | 입력 토큰 | 출력 토큰 | 합계 | 평균 | 지연(ms) | 에너지 상한(Wh) |
|---|---|---|---|---|---|---|---|
| assistant.step | 5 | 14408 | 867 | 15275 | 3055.0 | 16099 | 0.67079 |
| assistant.tool | 10 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| chat.route | 1 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| dispute.investigate | 1 | 842 | 108 | 950 | 950.0 | 2200 | 0.09167 |
| dispute.records | 1 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.analyze | 1 | 1316 | 151 | 1467 | 1467.0 | 2992 | 0.12467 |
| settlement.calculate | 1 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.policy | 4 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |

총 17692 토큰 · Kiln 호출 7회 · 코드 처리 17단계 · 에너지 상한 0.88713 Wh
가정: Wh = W × cards × latency_s / 3600 (배치 공유 미반영 → 상한) / NPU 150.0W × 1.0장

> 한계: 참여자 예치 서명은 실사용에서 MetaMask 가 하지만 이 증거 실행에서는 스크립트가 참여자 지갑으로 서명했다(동일한 컨트랙트 호출). 등록·차단·환불·판정은 에이전트 지갑 하나가 서명하는 데모용 구조. Run 2 의 이의 사유는 시연용 시나리오다.
