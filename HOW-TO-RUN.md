# SharePie 최종본 (v35 + Sepolia 블록체인) — 실행 안내

## 1. 준비 (한 번만)
- Python 3.14 (`py -3.14 --version`) → `py -3.14 -m pip install -r requirements.txt` 및 `py -3.14 -m pip install "web3>=6.15"`
- Node.js 20+ (컨트랙트 테스트·증거 실행용. 서버만 쓸 거면 생략) → `cd hardhat && npm install`
- `.env` 만들기: `.env.example`을 복사해 `.env`로 저장하고 아래 값을 채움 (블록체인 담당에게 받기)
  - `KILN_API_KEY` (팀 Kiln 키), `KILN_TOOL_MODE=json`
  - `CHAIN_MODE=bsc`, `BSC_RPC_URL=https://ethereum-sepolia-rpc.publicnode.com`, `BSC_CHAIN_ID=11155111`, `BSC_EXPLORER=https://sepolia.etherscan.io`
  - `LEDGER_ADDRESS=0xF297240957c3aB10458Dc1A4C6eC2eA18292529E`, `TOKEN_ADDRESS=0xF5cB871A8890bd1D34bf36E749F012D95589E0fD`, `LEDGER_DEPLOY_BLOCK=11801645`
  - `AGENT_PRIVATE_KEY=<에이전트 지갑 비밀키 — 블록체인 담당에게 직접>` (테스트 전용 지갑)
  - 모의 체인으로만 돌려볼 땐 `CHAIN_MODE=mock` (가스·비밀키 불필요)

## 2. 실행
```
py -3.14 -m uvicorn backend.app:app --host 127.0.0.1 --port 8000     # 로컬만
run-public.cmd                                                       # 외부 공개(터널) — docs/BETA-PUBLIC.md 참고 (베타 서버 진입점으로 켬)
py -3.14 -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1   # 베타 서버 (100명 동시 접속 설정 · 베타 데이터 폴더)
```
브라우저: http://localhost:8000

## 3. 검증 (선택)
```
py -3.14 scripts/check_chain.py          # 체인 연결·권한 9항목
cd hardhat && npm test                   # 컨트랙트 테스트 30개 (로컬 체인)
npm run smoke                            # 서버+체인 스모크 (🔴 0 이어야 통과)
npm run evidence                         # Run 1/1.5/2 실제 Sepolia 증거 (가스 ~0.006 ETH)
```

## 4. 이미 확보된 증거
`docs/evidence/sepolia-2026-09-28T20-27-05/summary.md` — v35 기준 Run 1 paid / 1.5 blocked×2 / 2 GENUINE_ERROR refunded (TxHash·Etherscan 링크·AI 토큰 표)

## 5. 이 zip에 없는 것 (의도적으로 제외)
`.env`(비밀키) · `hardhat/node_modules` · `tools/cloudflared.exe`(터널 프로그램, 필요 시 https://github.com/cloudflare/cloudflared/releases 에서 windows-amd64.exe 받아 tools/ 에 넣기) · `hardhat/deployments/members-*.json`(테스트 지갑 키)

## 6. 베타 서버 (100명 동시 접속 · 데이터 수집)
- 클라우드(AWS Lightsail) 한 번에 세팅: `sudo bash deploy/setup_server.sh` → **`deploy/README.md`** 2번
- 베타 데이터(비식별)는 `beta-data/` 한 폴더에만 (PC 실행이면 `~/.sharepie-data/beta/`) — 이 폴더만 보내면 돼요
- 실제 체인 동시 접속 설정(끄면 예전 방식): `CHAIN_TX_PIPELINE` · `GAS_DRIP_ASYNC` · `CHAIN_WATCH` · 가스 상한 `CHAIN_MAX_GAS_GWEI` — `CHANGES-beta-server.md`
