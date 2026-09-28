# python-blockchain-kit — Python 백엔드(share-pie-ai)용 블록체인 키트

최종 시스템은 풀스택 개발자의 Python 백엔드(`share-pie-ai` v35)이고, 온체인은 그 안의 `contracts/ShareLedger.sol`·`PieToken.sol`을
**Ethereum Sepolia**에 배포한 것입니다. 이 폴더는 그 백엔드에 얹는 블록체인 쪽 도구·패치·가이드입니다 (백엔드 코드 자체는 여기 없음).

| 항목 | 값 |
|---|---|
| 네트워크 | Sepolia (chainId 11155111) |
| ShareLedger | `0xF297240957c3aB10458Dc1A4C6eC2eA18292529E` (deploy block 11801645) |
| PieToken | `0xF5cB871A8890bd1D34bf36E749F012D95589E0fD` |
| 에이전트 지갑 | `0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36` (테스트 전용, 비밀키는 .env 에만) |
| 탐색기 | https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E |

## 새 백엔드 버전에 얹기 (10분)
```
py tools/apply_blockchain_patches.py --target "<새 백엔드 폴더>"   # 파일 복사 + 코드 패치 + .env 이관 (멱등)
cd <새 백엔드 폴더>; py -3.14 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
cd hardhat; npm install; npm run smoke        # 체인 스모크 (🔴 0 이어야 통과)
npm run evidence                              # Run 1 / 1.5 / 2 실제 체인 증거 (10분, 가스 ~0.006 ETH)
npm run deploy -- --network sepolia           # 컨트랙트(.sol)가 바뀐 경우에만 재배포
```
패치 내용: 가스 가격 v2(시세×2, 대기 300초) · 가스 자동 지급(지갑 등록 시 0.002 ETH) · 가드 A(한글 금액 오파싱 등록 거부) ·
가드 B(착오 판정인데 환불 없음 → 보정) · 가드 C(온체인 목적 60자). 자세한 절차·베타 공개(터널)는 `docs/BETA-PUBLIC.md`.

## 증거
`../docs/evidence/python-v35-sepolia-2026-09-28/summary.md` — v35 기준 Run 1 paid / Run 1.5 blocked×2 / Run 2 GENUINE_ERROR → refunded (TxHash·Etherscan 링크·AI 토큰 표).
