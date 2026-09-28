# 베타·데모용 서버 공개 가이드 (터널)

> 작성: 블록체인 담당. 이 PC에서 돌아가는 SharePie 서버를 팀원·베타 사용자가 자기 폰/집에서 쓰게 여는 방법.
> 준비물은 이미 들어 있음: `tools/cloudflared.exe`(관리자 권한 불필요), `run-public.cmd`.

## 0. 어떤 방식을 쓸지

| 방식 | 누가 접속 | 주소 | 언제 |
|---|---|---|---|
| A. 같은 Wi-Fi | 같은 공간의 팀원·폰 | `http://<이 PC IP>:8000` | 대회장 데모 |
| **B. 빠른 터널** (기본) | 인터넷 어디서나 | `https://xxxx.trycloudflare.com` (켤 때마다 바뀜) | 베타, 원격 테스트 |
| B-2. 이름 있는 터널 | 인터넷 어디서나 | 고정 도메인 | 소셜 로그인(카카오 등)을 쓸 때 |
| C. 클라우드 배포 | 24시간 | 고정 도메인 | 베타 이후 |

## 1. 빠른 터널로 열기 (B) — 3분

1. `.env` 확인: `CHAIN_MODE=bsc`(실제 체인) 또는 `mock`, `KILN_TOOL_MODE=json`, 에이전트 지갑 ETH 잔액(`py scripts/check_chain.py`).
2. 폴더에서 **`run-public.cmd`** 더블클릭 (또는 터미널에서 실행).
   - 서버 창이 하나 뜨고(`Uvicorn running on http://0.0.0.0:8000`), 현재 창에 터널 로그가 흐른다.
   - 로그 중 `https://….trycloudflare.com` 한 줄이 주소. **처음 접속은 DNS 전파 때문에 약 1분 걸릴 수 있음** — "사이트에 연결할 수 없음"이 나오면 1분 뒤 새로고침.
3. 주소를 참가자에게 공유. 폰 브라우저(Chrome/Safari)에서 열면 앱이 그대로 뜬다.
4. (권장) `.env`에 `PUBLIC_BASE_URL=https://그주소`를 넣고 서버 창을 재시작 — 알림·초대 링크가 이 주소로 나감.

**종료**: 터널 창과 서버 창을 각각 닫기(Ctrl+C). 다시 켜면 주소가 바뀐다 → 다시 공유.

## 2. 같은 Wi-Fi로 열기 (A)

1. 관리자 PowerShell에서 한 번만: `New-NetFirewallRule -DisplayName "SharePie 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow`
2. 서버를 `--host 0.0.0.0`으로 실행 (`run-public.cmd`가 이미 그렇게 켬).
3. `ipconfig`의 IPv4 주소(예: `192.168.0.238`) → `http://192.168.0.238:8000` 공유.

## 3. 이름 있는 터널 (B-2) — 소셜 로그인이 필요할 때

1. Cloudflare 계정(무료) + 도메인 1개 필요. `tools\cloudflared.exe tunnel login` → 브라우저 인증.
2. `tools\cloudflared.exe tunnel create sharepie` → `tools\cloudflared.exe tunnel route dns sharepie beta.<도메인>`
3. `tools\cloudflared.exe tunnel run --url http://127.0.0.1:8000 sharepie`
4. `.env`의 `PUBLIC_BASE_URL=https://beta.<도메인>`, 각 소셜 콘솔의 Redirect URI도 이 주소로 등록 (DEPLOY.md 1-3 참고).

## 4. 베타 운영 체크리스트

- [ ] PC 잠자기·절전 끄기 (전원 옵션). 노트북이면 덮개 닫아도 켜짐으로.
- [ ] 서버 창·터널 창 닫지 않기. 끊기면 `run-public.cmd` 다시 실행 → 새 주소 공유.
- [ ] 에이전트 지갑 ETH: 새 지갑 1개당 가스 자동 지급 0.002 ETH + 등록·차단·환불 tx. 참가자 수 × 0.003 정도 미리 확보.
  주소 `0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36`, Faucet: Google Cloud Web3 Faucet(하루 0.05) 등.
- [ ] 참가자 안내문: "MetaMask 설치 → 앱에서 지갑 연결(자동으로 Sepolia 전환·가스 지급) → MY 탭 충전 → 정산". Faucet 안내 불필요.
- [ ] 데이터는 이 PC의 `~/.sharepie-data`(db.json, usage.jsonl)에 쌓임. 베타 후 학습용으로 쓸 거면 폴더째 백업.
- [ ] 문제 생기면: `curl http://127.0.0.1:8000/api/health`(서버) → `py scripts/check_chain.py`(체인) → 터널 로그 순으로 확인.

## 5. 한계

- 빠른 터널은 Cloudflare가 "실험용"으로 제공. 대량 트래픽·장시간엔 끊길 수 있음 → 베타 이후엔 C(클라우드 배포)로.
- 이 PC가 꺼지면 서비스도 꺼짐. 데모 당일엔 예비로 A(같은 Wi-Fi) 주소도 함께 준비.

## 6. 새 백엔드 버전이 왔을 때 (블록체인 얹기 — 10분)

```
# 이전 폴더(share-pie-ai)에서 실행. 새 폴더로 파일 복사 + 코드 패치 + .env 값 이관 (멱등)
py tools/apply_blockchain_patches.py --target "..\share-pie-ai-NEW"

cd ..\share-pie-ai-NEW
py -m uvicorn backend.app:app --host 127.0.0.1 --port 8000     # 서버
cd hardhat && npm install && npm run smoke                       # 체인 스모크 (🔴 0 이어야 통과)
npm run evidence                                                 # Run 1/1.5/2 실제 체인 증거 (10분)
```
- 패치 내용: 가스 가격 v2(시세×2, 대기 300초) · 가스 자동 지급 · 가드 A(한글 금액 오파싱 등록 거부) · 가드 B(착오 판정인데 환불 없음 → 보정) · 가드 C(온체인 목적 60자)
- 스모크가 "앵커 불일치 → 수동 확인"을 내면 그 파일의 해당 코드가 바뀐 것 — 블록체인 담당에게 알려 주세요.
- 컨트랙트(.sol)가 바뀌었으면 재배포: `cd hardhat && npm run deploy -- --network sepolia` → 출력된 주소를 .env 에 반영.
