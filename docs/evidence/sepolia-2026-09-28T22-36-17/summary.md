# SharePie 실제 테스트넷 증거 묶음 (Python 백엔드 + ShareLedger)

- 네트워크: **Sepolia** (chainId 11155111) · 실행 2026-09-28T22:27:23.813Z → 2026-09-28T22:36:17.309Z
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
| 준비 | charge_token (진주2, 100000 PIE) | `0x702b8498d84cacf1dcef303f2f0a7c62a00c316a9d8f219d06a4f0c08b7b016f` | https://sepolia.etherscan.io/tx/0x702b8498d84cacf1dcef303f2f0a7c62a00c316a9d8f219d06a4f0c08b7b016f |
| 준비 | charge_token (진우2, 100000 PIE) | `0x8bbe3112ba00f127692095562c607897362a1de9516fdda79da2c2e530d38aec` | https://sepolia.etherscan.io/tx/0x8bbe3112ba00f127692095562c607897362a1de9516fdda79da2c2e530d38aec |
| 준비 | charge_token (민재2, 100000 PIE) | `0xdfb58a862e6b745c5f42c2e1ff4e7d0d7c2627d5cbff76ac50debbfdf823edde` | https://sepolia.etherscan.io/tx/0xdfb58a862e6b745c5f42c2e1ff4e7d0d7c2627d5cbff76ac50debbfdf823edde |
| 준비 | charge_token (지현2, 100000 PIE) | `0x55a0c2548d3d0c53b3f28bc350099dba050670b8225c831ef76ffd4871680959` | https://sepolia.etherscan.io/tx/0x55a0c2548d3d0c53b3f28bc350099dba050670b8225c831ef76ffd4871680959 |
| Run 1 | create | `0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0` | https://sepolia.etherscan.io/tx/0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0 |
| Run 1 | lock (진우2) | `0xf55e5561095828ffeb8335d70a269386b9709aef71b8471b9ba47aa7badc5ad0` | https://sepolia.etherscan.io/tx/0xf55e5561095828ffeb8335d70a269386b9709aef71b8471b9ba47aa7badc5ad0 |
| Run 1 | lock (민재2) | `0xe9baf799f3fea594bbd70ba69e10a431f84fddb28df4c735e652a2a490db9bba` | https://sepolia.etherscan.io/tx/0xe9baf799f3fea594bbd70ba69e10a431f84fddb28df4c735e652a2a490db9bba |
| Run 1 | lock (지현2) | `0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec` | https://sepolia.etherscan.io/tx/0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec |
| Run 1 | escrow | `0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec` | https://sepolia.etherscan.io/tx/0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec |
| Run 1 | release | `0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6` | https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6 |
| Run 1 | paid | `0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6` | https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6 |
| Run 1.5 | blockSettlement (1인 한도 9,000원) | `0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb` | https://sepolia.etherscan.io/tx/0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb |
| Run 1.5 | block | `0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb` | https://sepolia.etherscan.io/tx/0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb |
| Run 1.5 | blockSettlement (총 한도 30,000원) | `0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc` | https://sepolia.etherscan.io/tx/0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc |
| Run 1.5 | block | `0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc` | https://sepolia.etherscan.io/tx/0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc |
| Run 2 | create | `0x8a75d8a508b63d7a3ef77d536a73374fa30aadb9841be3d70148a19df5d66890` | https://sepolia.etherscan.io/tx/0x8a75d8a508b63d7a3ef77d536a73374fa30aadb9841be3d70148a19df5d66890 |
| Run 2 | lock (진우2) | `0x35433f2b46a7a193dbeaba405f631babf8c188d1ebeaf6548172b47cf985ff73` | https://sepolia.etherscan.io/tx/0x35433f2b46a7a193dbeaba405f631babf8c188d1ebeaf6548172b47cf985ff73 |
| Run 2 | lock (민재2) | `0xa64054797c7bfc57b87435eb72e36c8312a6d91b3c271e49d7e6c2f3e5873edd` | https://sepolia.etherscan.io/tx/0xa64054797c7bfc57b87435eb72e36c8312a6d91b3c271e49d7e6c2f3e5873edd |
| Run 2 | lock (지현2) | `0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97` | https://sepolia.etherscan.io/tx/0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97 |
| Run 2 | escrow | `0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97` | https://sepolia.etherscan.io/tx/0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97 |
| Run 2 | dispute (진우2) | `0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31` | https://sepolia.etherscan.io/tx/0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31 |
| Run 2 | refund (진우2) | `0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228` | https://sepolia.etherscan.io/tx/0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228 |
| Run 2 | refund (민재2) | `0x71715ee7c14b2e2ed0afd94f8110b99f55806f466b84a7d81f7ec52676255b57` | https://sepolia.etherscan.io/tx/0x71715ee7c14b2e2ed0afd94f8110b99f55806f466b84a7d81f7ec52676255b57 |
| Run 2 | refund (지현2) | `0xfb6d3acd7feecee1b170e802d3336e887fb0d0476a65dbb76cdbf8b05c206500` | https://sepolia.etherscan.io/tx/0xfb6d3acd7feecee1b170e802d3336e887fb0d0476a65dbb76cdbf8b05c206500 |
| Run 2 | resolve | `0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3` | https://sepolia.etherscan.io/tx/0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3 |

## Run 1 — 정상 정산
- 조건: "진주2는 5천원 적게 내고 나머지 세 명이 나눠줘" (총 35,900 · 예산 40,000) → Stage1(AI)+Stage2(코드): [["진주2",3975],["진우2",10642],["민재2",10642],["지현2",10641]]
- 규칙: 진주2는 5천원 적게 내고 나머지 세 명이 나눠줘 · 목적: 삼겹살 공동구매 정산
- 정산 id `sp-dddf6e186e` · chainId `0x608d803096a9e031843a8331a333cd14455de2c6e3d2bed2aca8c4ecc5d0ec04` · 최종 상태 **paid**
- 인증서 TxHash: `0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6` (https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6)
- 지급 후 PIE 잔액: {"진주2":677800,"진우2":440733,"민재2":440733,"지현2":440734}

## Run 1.5 — 조건 변경 → 지출 통제 중단
- 1인 한도 9,000원: 상태 **blocked** · reason_code 2 · 진우2님 10,642원 > 1인 한도 9,000원 · tx `0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb`
- 총 한도 30,000원: 상태 **blocked** · reason_code 5 · 총액 35,900원이 총 예산 30,000원을 넘어요 · tx `0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc`
- 예치·지급 트랜잭션 없음. 중단 판단은 코드(지출 통제)이며 체인에 Blocked 이벤트로 기록됨.

## Run 2 — 이의제기 → AI 판정 → 자동 실행
- 정산 id `sp-edccf95f19` · 이의제기: 진우2 — "판매자가 품절로 주문을 취소했어요. 예치금을 전원 돌려받아야 해요"
- AI 판정(dispute.investigate): **GENUINE_ERROR** (진짜 착오 (환불)) · refund=all
- 설명: 판매자 측에서 주문을 취소했고 정산금 31,925원이 에스크로 상태로 보관 중인 것으로 확인됨. 분담 조건 원문과 온체인 기록 모두 정산 절차는 완료되었으나, 공동구매 자체가 무효화된 상황이므로 전원 환불 처리가 필요함.
- 실행 후 상태 **refunded** · PIE 잔액 전/후: {"진주2":677800,"진우2":430091,"민재2":430091,"지현2":430093} → {"진주2":677800,"진우2":440733,"민재2":440733,"지현2":440734}

## AI 토큰 사용량 (서버 /api/usage/report.md)
# Share Pie · Kiln API 사용 보고서
생성 2026-09-29 07:36:14 KST · 모델 `qwen3-32b` (api.bricksum.com) · 실측 (LLM_MODE=live) · Kiln 호출 85회 · 응답 반영 기록 32건

## 1. 워크플로 단계별 토큰

| 구간 | 단계 | 처리 | Kiln 호출 | 코드 처리 | 입력 | 출력 | 합계 | 호출당 평균 | 평균 지연(ms) | 에너지 상한(Wh) | 비중 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 정산 코어 | Stage 1 조건 해석 `settlement.analyze` | AI | 48 | 4 | 67,546 | 7,307 | 74,853 | 1,559.4 | 2,816 | 5.63287 | 49.2% |
| 정산 코어 | Stage 2 금액 계산 `settlement.calculate` | 코드 | 0 | 45 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| 정산 코어 | 지출 통제 검사 `settlement.policy` | 코드 | 0 | 26 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| 정산 코어 | Stage 3 결과 설명 `settlement.explain` | AI | 2 | 0 | 462 | 196 | 658 | 329.0 | 1,748 | 0.14567 | 0.4% |
| 분쟁·증거 | 분쟁 기록 대조 `dispute.records` | 코드 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| 분쟁·증거 | 분쟁 판정 `dispute.investigate` | AI | 5 | 0 | 3,810 | 1,472 | 5,282 | 1,056.4 | 4,970 | 1.03550 | 3.5% |
| 공동구매·추천 | 상품 검색 `shopping.web` | 코드 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| 공동구매·추천 | 공동구매 비교 `shopping.search` | AI | 4 | 0 | 3,352 | 619 | 3,971 | 992.8 | 2,778 | 0.46308 | 2.6% |
| 공동구매·추천 | 1인 비용 계산 `shopping.calculate` | 코드 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| 공동구매·추천 | 비교 결과 설명 `shopping.explain` | AI | 4 | 0 | 3,299 | 813 | 4,112 | 1,028.0 | 3,390 | 0.56504 | 2.7% |
| Pie 대화 (1:1·그룹) | 요청 의도 파악 `chat.route` | 코드 | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| Pie 대화 (1:1·그룹) | Pie 에이전트 판단 `assistant.step` | AI | 22 | 0 | 60,864 | 2,512 | 63,376 | 2,880.7 | 2,203 | 2.01900 | 41.6% |
| Pie 대화 (1:1·그룹) | assistant.brain `assistant.brain` | 코드 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |
| Pie 대화 (1:1·그룹) | assistant.tool `assistant.tool` | 코드 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 0.00000 | 0.0% |

## 2. 구간별 합계

| 구간 | Kiln 호출 | 코드 처리 | 토큰 | 에너지 상한(Wh) |
|---|---|---|---|---|
| 정산 코어 | 50 | 75 | 75,511 | 5.77854 |
| 분쟁·증거 | 5 | 5 | 5,282 | 1.03550 |
| 공동구매·추천 | 8 | 11 | 8,083 | 1.02812 |
| Pie 대화 (1:1·그룹) | 22 | 37 | 63,376 | 2.01900 |

## 3. 실행(정산)별 기록 — 조건을 바꾼 실행 비교

| 실행 | 정산 | 조건 | 결과 | Kiln 호출 | 토큰 | 에너지 상한(Wh) | 온체인 기록 |
|---|---|---|---|---|---|---|---|
| Run 6 | `sp-cdb1f9c046` | 총 35,900원 · 4명 · 1인 한도 9,000원 · 위반 OVER_PERSON_CAP,OVER_PERSON_CAP,OVER_PERSON_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0xd7f265c0…`](https://sepolia.etherscan.io/tx/0xd7f265c020cca78d57ca2fea751e344d93cc539080ebd66c19551f6ef7e39c94) |
| Run 7 | `sp-96cfd33f3f` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0xa22de2e4…`](https://sepolia.etherscan.io/tx/0xa22de2e43e8002ebad7ffb905042d23dd2da7da183adc9264aaa33ad49e58987) |
| Run 8 | `sp-0e977c0a4a` | 총 35,900원 · 4명 · 총 한도 40,000원 | 이의제기 → GENUINE_ERROR · 환불 | 1 | 1,112 | 0.26112 | 정산 등록 [`0x35aec80f…`](https://sepolia.etherscan.io/tx/0x35aec80f5387b9f5f049c8ea28398dd1a5879bf9663013d89b3a859a9d4717db) 예치 [`0x8962ecb7…`](https://sepolia.etherscan.io/tx/0x8962ecb77d0057621c83b1be20ec88dff82def616c8d212591204d2f9f9ee2d1) 예치 [`0x3b780aff…`](https://sepolia.etherscan.io/tx/0x3b780aff6102b3ab2de616b9fd9f7279ce83de6211e6a6ede9208081529abf78) 예치 [`0x0f3ab995…`](https://sepolia.etherscan.io/tx/0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb) 전원 예치 [`0x0f3ab995…`](https://sepolia.etherscan.io/tx/0x0f3ab995c0636662f2c2e4b7fb522f7cb7f485e96eadd4e79789715948025bcb) 이의제기 [`0x4cc7d1e6…`](https://sepolia.etherscan.io/tx/0x4cc7d1e6f70d46742b52d9082f6cadc4c405828ea9ead587b44b2b437c07a7d7) |
| Run 9 | `sp-a2f2ac6f3f` | 총 35,900원 · 4명 · 총 한도 40,000원 | 결제자에게 지급 완료 | 0 | 0 | 0.00000 | 정산 등록 [`0x568c3064…`](https://sepolia.etherscan.io/tx/0x568c30648aabcdb103f598a045dd255ea943e2eb00390215aa467aac60b3b789) 예치 [`0xae559cb4…`](https://sepolia.etherscan.io/tx/0xae559cb491a600b79514346e37e754a3c42b37187a66257f748ab98224e759f6) 예치 [`0x72c69042…`](https://sepolia.etherscan.io/tx/0x72c6904298dd78577e3ec1daeace5fb027a1a62a8db52b7b5890508a10e66220) 예치 [`0xf1c3fa6d…`](https://sepolia.etherscan.io/tx/0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386) 전원 예치 [`0xf1c3fa6d…`](https://sepolia.etherscan.io/tx/0xf1c3fa6dd02afdc5244d676432430f21c5ce1b64e4bcd7f88bb692087c9d7386) release [`0x56e083cd…`](https://sepolia.etherscan.io/tx/0x56e083cdabd7adf56be5993c5a9a4811fffb5c2da13474d548622ce3564e7f02) |
| Run 10 | `sp-87051a7018` | 총 35,900원 · 4명 · 1인 한도 9,000원 · 위반 OVER_PERSON_CAP,OVER_PERSON_CAP,OVER_PERSON_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x58996bc6…`](https://sepolia.etherscan.io/tx/0x58996bc68dc304732cd2b51d97177282e4df635891b3a06f3906d99d7dbcba66) |
| Run 11 | `sp-eeda05de02` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x84ed29a0…`](https://sepolia.etherscan.io/tx/0x84ed29a0cfff37efda3c9f0de1c73e472a6ca32bb44a3c9b4c27ba9113ec4162) |
| Run 12 | `sp-a9217d3b42` | 총 35,900원 · 4명 · 총 한도 40,000원 | 이의제기 → GENUINE_ERROR · 환불 | 1 | 1,054 | 0.21742 | 정산 등록 [`0x48323fb9…`](https://sepolia.etherscan.io/tx/0x48323fb903f7c8141be80ddb71ebf531b7c75e40f1de3f28631ef75e77a37a97) 예치 [`0x0112ef75…`](https://sepolia.etherscan.io/tx/0x0112ef7575d374886c24be2636a8832cb5e3b1617d90ebc363d742481a7ce3a5) 예치 [`0xd7df4f7b…`](https://sepolia.etherscan.io/tx/0xd7df4f7b8811487da0f27af06128a48949726146f07e7030800d7539613ad487) 예치 [`0x2ff00813…`](https://sepolia.etherscan.io/tx/0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2) 전원 예치 [`0x2ff00813…`](https://sepolia.etherscan.io/tx/0x2ff00813657ed868ecaa80c2bd249a81b5f20b0df932b80f1401ab1e50691bb2) 이의제기 [`0xcce569f0…`](https://sepolia.etherscan.io/tx/0xcce569f05c3cbbfc065a6c4ac92aef3cbc18fa5b556905aac2a7fd83a5cad789) |
| Run 13 | `sp-a97571b166` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0xa8677d14…`](https://sepolia.etherscan.io/tx/0xa8677d146ded906d8975ccf0133536028cb4e60a367df5c4bfc99e26aa1c76f7) |
| Run 14 | `sp-38a5e2b88a` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x928a3058…`](https://sepolia.etherscan.io/tx/0x928a3058bfeb8ec32e949aa359bd8c98572464fba1ebd4a436297acd8952a564) |
| Run 15 | `sp-21356b2fbd` | 총 35,900원 · 4명 · 총 한도 40,000원 | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 정산 등록 [`0x70cc4dac…`](https://sepolia.etherscan.io/tx/0x70cc4dac2af0123d0203a805e99a36221983afb21e5cfc2789203a7acefcc9a9) 지출 통제 중단 [`0xad20b72d…`](https://sepolia.etherscan.io/tx/0xad20b72dc09c0fa060b2db4310e80eda572a925e14463e6001b7c03fb1986a3f) |
| Run 16 | `sp-4ea1730e98` | 총 35,900원 · 4명 · 총 한도 40,000원 | 결제자에게 지급 완료 | 0 | 0 | 0.00000 | 정산 등록 [`0x1b2fc461…`](https://sepolia.etherscan.io/tx/0x1b2fc46198f8d2d7c2c88033d146c5e26d0475559a421ebc952d906659f401f3) 예치 [`0xdcb2b0f4…`](https://sepolia.etherscan.io/tx/0xdcb2b0f494d91bdc002e6a8df880f47c4ed62b32ee390b1f5a137d1925aed700) 예치 [`0x17d60997…`](https://sepolia.etherscan.io/tx/0x17d6099703a05b4be2ba528d52e88a3ea990bffb35495a4404d5a4f9e0771c69) 예치 [`0x0c28a50d…`](https://sepolia.etherscan.io/tx/0x0c28a50db5f144e5f45b000ff44cd2c4c54020a3a27c253fd098a15e1c2bdcd0) 전원 예치 [`0x0c28a50d…`](https://sepolia.etherscan.io/tx/0x0c28a50db5f144e5f45b000ff44cd2c4c54020a3a27c253fd098a15e1c2bdcd0) release [`0x54611015…`](https://sepolia.etherscan.io/tx/0x5461101574c706f997e6a5d52b60e62c6bc5c712fe623b724d1701eff7484ac3) |
| Run 17 | `sp-f45780c795` | 총 35,900원 · 4명 · 1인 한도 9,000원 · 위반 OVER_PERSON_CAP,OVER_PERSON_CAP,OVER_PERSON_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x453179d1…`](https://sepolia.etherscan.io/tx/0x453179d15eac18400ad0fd4b308d942fe95039892ca3ce224f0d7f54ddd7b1a5) |
| Run 18 | `sp-f7190048f9` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x1df4455b…`](https://sepolia.etherscan.io/tx/0x1df4455b28f9a23986aec8a4f20a8aed9e9d3b7c0a82d804fa3cfe448e409a4d) |
| Run 19 | `sp-122477344b` | 총 35,900원 · 4명 · 총 한도 40,000원 | 이의제기 → GENUINE_ERROR · 환불 | 1 | 1,094 | 0.23929 | 정산 등록 [`0xcd46ed47…`](https://sepolia.etherscan.io/tx/0xcd46ed47523ed987b153f2d1989e8663a53c94fe6d54994cb301ca2d4301ec7c) 예치 [`0x2d20b31e…`](https://sepolia.etherscan.io/tx/0x2d20b31eb68aa1323f43819289428d9f1d2ac77bc5ebaadd0ad8eaa16cdd1a01) 예치 [`0x6992e10f…`](https://sepolia.etherscan.io/tx/0x6992e10fc7a1a3569e83809431e4bee5812b91284ad6c7fe3ed69bd36a59af37) 예치 [`0xeca997a5…`](https://sepolia.etherscan.io/tx/0xeca997a59fed164183db803e7dfce95e0272680c63c9fbd0e01ed5c5fa69eca7) 전원 예치 [`0xeca997a5…`](https://sepolia.etherscan.io/tx/0xeca997a59fed164183db803e7dfce95e0272680c63c9fbd0e01ed5c5fa69eca7) 이의제기 [`0x89e70df3…`](https://sepolia.etherscan.io/tx/0x89e70df35219d1eea3c4677e576b8eacce7361ddad2c472df2a21a90d3422d42) |
| Run 20 | `sp-c8123d5f12` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0xeaec2da4…`](https://sepolia.etherscan.io/tx/0xeaec2da472faaeb1670b85408e5487a2b95088c09a69f59359128b3188c4981f) |
| Run 21 | `sp-8c672cfb84` | 총 35,900원 · 4명 · 총 한도 40,000원 | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 정산 등록 [`0xc7344a55…`](https://sepolia.etherscan.io/tx/0xc7344a553dd691e7c1c433ad33eae11d415c736cfe8be037782b8d60aa86e49c) 지출 통제 중단 [`0x4538196a…`](https://sepolia.etherscan.io/tx/0x4538196af29d52ebf9c07c0d1a8e8d66c12ac4f67f94cc028d29a5aebbe67d5a) |
| Run 22 | `sp-dddf6e186e` | 총 35,900원 · 4명 · 총 한도 40,000원 | 결제자에게 지급 완료 | 0 | 0 | 0.00000 | 정산 등록 [`0xb5d5158f…`](https://sepolia.etherscan.io/tx/0xb5d5158f878c219c67421af295727c4ee3e3f7c9934e2e925bceffd6e1fb60c0) 예치 [`0xf55e5561…`](https://sepolia.etherscan.io/tx/0xf55e5561095828ffeb8335d70a269386b9709aef71b8471b9ba47aa7badc5ad0) 예치 [`0xe9baf799…`](https://sepolia.etherscan.io/tx/0xe9baf799f3fea594bbd70ba69e10a431f84fddb28df4c735e652a2a490db9bba) 예치 [`0xaf31a0ea…`](https://sepolia.etherscan.io/tx/0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec) 전원 예치 [`0xaf31a0ea…`](https://sepolia.etherscan.io/tx/0xaf31a0ea5180afda72da2d005172b0592aa4924924ca64d075d1a9c9f0b4c0ec) release [`0x932d4af1…`](https://sepolia.etherscan.io/tx/0x932d4af1317b1caf49304e2e660585e48c09bf38ba040ef60c3d7d7745b4d7c6) |
| Run 23 | `sp-9693efee69` | 총 35,900원 · 4명 · 1인 한도 9,000원 · 위반 OVER_PERSON_CAP,OVER_PERSON_CAP,OVER_PERSON_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x4e779d27…`](https://sepolia.etherscan.io/tx/0x4e779d27db4761eacad55636783b3b9482434df50a2e9641aecf7937f86ff5cb) |
| Run 24 | `sp-3800c9b03a` | 총 35,900원 · 4명 · 총 한도 30,000원 · 위반 OVER_TOTAL_CAP | 지출 통제로 중단 (온체인 Blocked 기록) | 0 | 0 | 0.00000 | 지출 통제 중단 [`0x8367cb18…`](https://sepolia.etherscan.io/tx/0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc) |
| Run 25 | `sp-edccf95f19` | 총 35,900원 · 4명 · 총 한도 40,000원 | 이의제기 → GENUINE_ERROR · 환불 | 1 | 1,072 | 0.22600 | 정산 등록 [`0x8a75d8a5…`](https://sepolia.etherscan.io/tx/0x8a75d8a508b63d7a3ef77d536a73374fa30aadb9841be3d70148a19df5d66890) 예치 [`0x35433f2b…`](https://sepolia.etherscan.io/tx/0x35433f2b46a7a193dbeaba405f631babf8c188d1ebeaf6548172b47cf985ff73) 예치 [`0xa6405479…`](https://sepolia.etherscan.io/tx/0xa64054797c7bfc57b87435eb72e36c8312a6d91b3c271e49d7e6c2f3e5873edd) 예치 [`0x684f8008…`](https://sepolia.etherscan.io/tx/0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97) 전원 예치 [`0x684f8008…`](https://sepolia.etherscan.io/tx/0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97) 이의제기 [`0x156e42e2…`](https://sepolia.etherscan.io/tx/0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31) |

**Run 24 단계 순서** (`sp-3800c9b03a` · 지출 통제로 중단 (온체인 Blocked 기록))

1. [코드] `settlement.policy` — 0 tokens (code-only): 1 violations
- [체인] 지출 통제 중단 `0x8367cb18e439e8e9062a451c1ef15d347032dc576001098b11dae3d5fa8f33fc` (블록 11803537)

**Run 25 단계 순서** (`sp-edccf95f19` · 이의제기 → GENUINE_ERROR · 환불)

1. [코드] `settlement.policy` — 0 tokens (code-only): 0 violations
2. [코드] `dispute.records` — 0 tokens (code-only): 단계별 기록 대조
3. [Kiln] `dispute.investigate` · 1,072토큰 · 5424ms
4. [응답 반영] `dispute.investigate` — Kiln 응답 → 판정 GENUINE_ERROR → 전원 환불 트랜잭션 실행
- [체인] 정산 등록 `0x8a75d8a508b63d7a3ef77d536a73374fa30aadb9841be3d70148a19df5d66890` (블록 11803538)
- [체인] 예치 `0x35433f2b46a7a193dbeaba405f631babf8c188d1ebeaf6548172b47cf985ff73` (블록 11803540)
- [체인] 예치 `0xa64054797c7bfc57b87435eb72e36c8312a6d91b3c271e49d7e6c2f3e5873edd` (블록 11803542)
- [체인] 예치 `0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97` (블록 11803544)
- [체인] 전원 예치 `0x684f8008115736b95c15c8037eec13928ef1f6a916ef835ca59f03590918bc97` (블록 11803544)
- [체인] 이의제기 `0x156e42e2a5812795f53c214ddf4ce21d7baaf009861b9e0e0ef2a1cc41738d31` (블록 11803545)
- [체인] 환불 `0xfa901750cb327e9d40fff252627e9ee1eb99583e769f6abe3faec55a4c56f228` (블록 11803546)
- [체인] 환불 `0x71715ee7c14b2e2ed0afd94f8110b99f55806f466b84a7d81f7ec52676255b57` (블록 11803547)
- [체인] 환불 `0xfb6d3acd7feecee1b170e802d3336e887fb0d0476a65dbb76cdbf8b05c206500` (블록 11803548)
- [체인] 판정 기록 `0x9a217542ee35079eb9b07a4ed33d4f61ecdc8cac3be7f608c86d03805e3955a3` (블록 11803549)

## 4. 불필요한 추론을 줄인 방법과 효과

| 방법 | 건수 | 최소 절감 추정(토큰) | 계산 근거 |
|---|---|---|---|
| 그룹방 잡담에는 Pie가 끼지 않음 (답할지 코드가 먼저 판단) | 0 | 0 | 잡담 1건 = Kiln 최소 1회(그룹방 호출 평균 1,791토큰)를 안 부른 것으로 계산 |
| 불법 목적 요청은 AI 호출 전에 코드가 거절 | 0 | 0 | 1건 = Kiln 최소 1회(호출 평균 1,791토큰) |
| AI가 놓친 금액을 코드가 읽어 되묻기·재호출을 막음 | 4 | 7,164 | 1건 = 재호출 1회(호출 평균 1,791토큰) |
| 구독 한도를 넘어 Kiln 없이 규칙으로 답함 | 5 | 8,955 | 1건 = Kiln 최소 1회(호출 평균 1,791토큰) |
| 금액 계산·합계 검증·지출 통제는 코드로만 (Stage 2) | 76 | - | 설계상 이 단계는 처음부터 AI를 부르지 않아 추정치에 넣지 않음 (0 토큰) |

최소 절감 추정 합계 16,119토큰 (호출 평균 1,791토큰 기준, 실제로는 한 번에 여러 걸음이라 더 크다)

- 금액 계산·합계 검증·지출 통제는 코드(0 토큰). AI는 조건 해석(Stage 1)과 설명(Stage 3)만 한다.
- 그룹방은 답할지를 코드가 먼저 정한다(이름 부름·정산·구매 이야기만). 잡담은 AI 호출 0회.
- qwen3-32b: 평소엔 긴 사고를 끄고(/no_think), 판단이 어려운 단계(shopping.plan, dispute.investigate)만 사고 모드.
- 답이 max_tokens에 걸리면 한도를 늘려 한 번만 다시 부르고, 잘린 시도의 토큰도 빠짐없이 기록한다.
- 구독 한도: 5시간 세션·주간 한도를 넘으면 Kiln을 부르지 않는다(정산·결제는 코드로 계속). 분쟁 조사는 한도 밖.

## 5. 에너지 추정 근거

- 측정값: Kiln 요청부터 응답까지 걸린 시간(latency_ms)을 호출마다 실측
- 가정: NPU 전력 150W × 카드 1장 (RNGD TDP 150W — developer.furiosa.ai/latest/en/overview/rngd.html)
- 공식: Wh = NPU 전력(W) × 카드 수 × 응답 지연(초) / 3600 — 배치 처리로 여러 요청이 카드를 나눠 쓰는 효과를 빼서 실제보다 큰 값(상한)
- 결과: 총 9.86116 Wh 상한 · Kiln 호출 1회당 0.116014 Wh · 1,000토큰당 0.064769 Wh

## 6. 구독 요금제와 사용 한도

| 요금제 | 월 가격 (PIE) | 5시간 세션 한도 (토큰) | 주간 한도 (토큰) |
|---|---|---|---|
| Free | 0 | 25,000 | 100,000 |
| Pie Pro | 4,900 | 125,000 | 500,000 |
| Pie Max 5x | 24,500 | 625,000 | 2,500,000 |
| Pie Max 20x | 49,000 | 2,500,000 | 10,000,000 |

PIE는 테스트넷 토큰이라 실제 가치가 없다. 구독료 결제는 PieToken.transfer 온체인 기록으로 남는다.

> 한계: 참여자 예치 서명은 실사용에서 MetaMask 가 하지만 이 증거 실행에서는 스크립트가 참여자 지갑으로 서명했다(동일한 컨트랙트 호출). 등록·차단·환불·판정은 에이전트 지갑 하나가 서명하는 데모용 구조. Run 2 의 이의 사유는 시연용 시나리오다.
