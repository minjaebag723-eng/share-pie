# SharePie 실제 테스트넷 증거 묶음 (Python 백엔드 + ShareLedger)

- 네트워크: **Sepolia** (chainId 11155111) · 실행 2026-09-28T17:01:04.746Z → 2026-09-28T17:10:06.478Z
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
| 준비 | charge_token (진주2, 100000 PIE) | `0xd91b343290bf7705354a3161412c27459dff48e8bea42193faa8a3a0ecefbc16` | https://sepolia.etherscan.io/tx/0xd91b343290bf7705354a3161412c27459dff48e8bea42193faa8a3a0ecefbc16 |
| 준비 | charge_token (진우2, 100000 PIE) | `0x880cf2c2fdbbfd4e67cb5e93e434d651d935e9f1df6f92ccc8f3c847c8a1cee7` | https://sepolia.etherscan.io/tx/0x880cf2c2fdbbfd4e67cb5e93e434d651d935e9f1df6f92ccc8f3c847c8a1cee7 |
| 준비 | charge_token (민재2, 100000 PIE) | `0x0ca2153acada9266d33017054c003a6b1ec9b3c2b7750552797af902665c09c2` | https://sepolia.etherscan.io/tx/0x0ca2153acada9266d33017054c003a6b1ec9b3c2b7750552797af902665c09c2 |
| 준비 | charge_token (지현2, 100000 PIE) | `0x5a8d4b530be27d7d6a1bfa94da1ce25d112a05b0cdb1522a7ce1897f3e02b300` | https://sepolia.etherscan.io/tx/0x5a8d4b530be27d7d6a1bfa94da1ce25d112a05b0cdb1522a7ce1897f3e02b300 |
| Run 1 | create | `0x51b12f82924fb8917cef3b0b12fe602228dcaa3336e3194fb69d80b0cfa94097` | https://sepolia.etherscan.io/tx/0x51b12f82924fb8917cef3b0b12fe602228dcaa3336e3194fb69d80b0cfa94097 |
| Run 1 | lock (진우2) | `0x49ba580e9ed9c2f4e3b02132afcb5b4c1e47770fa491002e295463190a97dff5` | https://sepolia.etherscan.io/tx/0x49ba580e9ed9c2f4e3b02132afcb5b4c1e47770fa491002e295463190a97dff5 |
| Run 1 | lock (민재2) | `0xe6f60718d8a941df6f448ff38ff9bf23c5ef2e09cfca23aabf3bc543faf4b523` | https://sepolia.etherscan.io/tx/0xe6f60718d8a941df6f448ff38ff9bf23c5ef2e09cfca23aabf3bc543faf4b523 |
| Run 1 | lock (지현2) | `0xf163d3657fcf94df9a7822f358f5c58f0e77236716a7f003898e9099cf452af4` | https://sepolia.etherscan.io/tx/0xf163d3657fcf94df9a7822f358f5c58f0e77236716a7f003898e9099cf452af4 |
| Run 1 | escrow | `0xf163d3657fcf94df9a7822f358f5c58f0e77236716a7f003898e9099cf452af4` | https://sepolia.etherscan.io/tx/0xf163d3657fcf94df9a7822f358f5c58f0e77236716a7f003898e9099cf452af4 |
| Run 1 | release | `0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779` | https://sepolia.etherscan.io/tx/0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779 |
| Run 1 | paid | `0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779` | https://sepolia.etherscan.io/tx/0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779 |
| Run 1.5 | blockSettlement (1인 한도 9,000원) | `0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94` | https://sepolia.etherscan.io/tx/0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94 |
| Run 1.5 | block | `0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94` | https://sepolia.etherscan.io/tx/0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94 |
| Run 1.5 | blockSettlement (총 한도 30,000원) | `0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987` | https://sepolia.etherscan.io/tx/0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987 |
| Run 1.5 | block | `0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987` | https://sepolia.etherscan.io/tx/0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987 |
| Run 2 | create | `0x35aec80f5387b9f5f049c8ea28398dd1a5879bf9663013d89b3a859a9d4717db` | https://sepolia.etherscan.io/tx/0x35aec80f5387b9f5f049c8ea28398dd1a5879bf9663013d89b3a859a9d4717db |
| Run 2 | lock (진우2) | `0x8962ecb77d0057621c83b1be20ec88dff82def616c8d212591204d2f9f9ee2d1` | https://sepolia.etherscan.io/tx/0x8962ecb77d0057621c83b1be20ec88dff82def616c8d212591204d2f9f9ee2d1 |
| Run 2 | lock (민재2) | `0x3b780aff6102b3ab2de616b9fd9f7279ce83de6211e6a6ede9208081529abf78` | https://sepolia.etherscan.io/tx/0x3b780aff6102b3ab2de616b9fd9f7279ce83de6211e6a6ede9208081529abf78 |
| Run 2 | lock (지현2) | `0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb` | https://sepolia.etherscan.io/tx/0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb |
| Run 2 | escrow | `0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb` | https://sepolia.etherscan.io/tx/0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb |
| Run 2 | dispute (진우2) | `0x4cc7d1e6f70d46742b52d9082f6cadc4c405828ea9ead587b44b2b437c07a7d7` | https://sepolia.etherscan.io/tx/0x4cc7d1e6f70d46742b52d9082f6cadc4c405828ea9ead587b44b2b437c07a7d7 |
| Run 2 | refund (진우2) | `0xfe49d45d2cf3811079e24062e35344def33c765af7222b3436cb1aca29d9f783` | https://sepolia.etherscan.io/tx/0xfe49d45d2cf3811079e24062e35344def33c765af7222b3436cb1aca29d9f783 |
| Run 2 | refund (민재2) | `0x487428825b97bc3d216ec89a4894d0011ed8c82ed890a58ac4bb3c45c535e5ac` | https://sepolia.etherscan.io/tx/0x487428825b97bc3d216ec89a4894d0011ed8c82ed890a58ac4bb3c45c535e5ac |
| Run 2 | refund (지현2) | `0xb361afc724efb585e4b7e77cbb5bc7ffb46dda89e681befc906d5aa626eeaecb` | https://sepolia.etherscan.io/tx/0xb361afc724efb585e4b7e77cbb5bc7ffb46dda89e681befc906d5aa626eeaecb |
| Run 2 | resolve | `0x3988da81f4c282f96b9b17b05215e3bddbefbc122f243f7a7049c3ee3501a735` | https://sepolia.etherscan.io/tx/0x3988da81f4c282f96b9b17b05215e3bddbefbc122f243f7a7049c3ee3501a735 |

## Run 1 — 정상 정산
- 조건: "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘" (총 35,900 · 예산 40,000) → Stage1(AI)+Stage2(코드): [["진주2",5225],["진우2",10225],["민재2",10225],["지현2",10225]]
- 규칙: 진주2는 5천원 적게 내고 나머지 세 명이 나눠줘 · 목적: 삼겹살 공동구매 분담금( 5천원 감면)
- 정산 id `sp-4e2d321988` · chainId `0x35cf3a493d37280c24dd740264e7df172f5ae6b0c09589ce6a98b633c893a22a` · 최종 상태 **paid**
- 인증서 TxHash: `0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779` (https://sepolia.etherscan.io/tx/0x5be053fd629de2cfc99700b0a2f3aa39e26b28ed0ae5f13a07c6c0f0ae05d779)
- 지급 후 PIE 잔액: {"진주2":284525,"진우2":171825,"민재2":171825,"지현2":171825}

## Run 1.5 — 조건 변경 → 지출 통제 중단
- 1인 한도 9,000원: 상태 **blocked** · reason_code 2 · 진우2님 10,225원 > 1인 한도 9,000원 · tx `0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94`
- 총 한도 30,000원: 상태 **blocked** · reason_code 5 · 총액 35,900원이 총 예산 30,000원을 넘어요 · tx `0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987`
- 예치·지급 트랜잭션 없음. 중단 판단은 코드(지출 통제)이며 체인에 Blocked 이벤트로 기록됨.

## Run 2 — 이의제기 → AI 판정 → 자동 실행
- 정산 id `sp-0e977c0a4a` · 이의제기: 진우2 — "판매자가 품절로 주문을 취소했어요. 예치금을 전원 돌려받아야 해요"
- AI 판정(dispute.investigate): **GENUINE_ERROR** (진짜 착오 (환불)) · refund=all
- 설명: 판매자 주문 취소로 인해 거래가 무효화되었으며, 에스크로에 보관 중인 30,675원은 결제자에게 지급되지 않은 상태입니다. 분담 조건과 결제 기록 모두 정상적으로 기록되어 있으나, 공동구매 자체가 취소된 경우 전원 환불이 원칙입니다.
- 실행 후 상태 **refunded** · PIE 잔액 전/후: {"진주2":284525,"진우2":161600,"민재2":161600,"지현2":161600} → {"진주2":284525,"진우2":171825,"민재2":171825,"지현2":171825}

## AI 토큰 사용량 (서버 /api/usage/report.md)
| 단계 | 호출 | 입력 토큰 | 출력 토큰 | 합계 | 평균 | 지연(ms) | 에너지 상한(Wh) |
|---|---|---|---|---|---|---|---|
| assistant.step | 5 | 14408 | 867 | 15275 | 3055.0 | 16099 | 0.67079 |
| assistant.tool | 10 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| chat.route | 1 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| dispute.investigate | 2 | 1584 | 478 | 2062 | 1031.0 | 8467 | 0.35279 |
| dispute.records | 2 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.analyze | 8 | 9972 | 1172 | 11144 | 1393.0 | 21445 | 0.89354 |
| settlement.calculate | 7 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |
| settlement.policy | 8 | 0 | 0 | 0 | 0.0 | 0 | 0.0 |

총 28481 토큰 · Kiln 호출 15회 · 코드 처리 28단계 · 에너지 상한 1.91713 Wh
가정: Wh = W × cards × latency_s / 3600 (배치 공유 미반영 → 상한) / NPU 150.0W × 1.0장

> 한계: 참여자 예치 서명은 실사용에서 MetaMask 가 하지만 이 증거 실행에서는 스크립트가 참여자 지갑으로 서명했다(동일한 컨트랙트 호출). 등록·차단·환불·판정은 에이전트 지갑 하나가 서명하는 데모용 구조. Run 2 의 이의 사유는 시연용 시나리오다.
