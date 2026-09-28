# 실행 · 배포 · 시연 가이드

## 0. 내 컴퓨터에서 바로 실행 (키·지갑 없이, 모의 체인)

```bash
cd share-pie-ai                      # requirements.txt 가 보이는 폴더
py -m pip install -r requirements.txt          # Mac: pip install -r requirements.txt
py -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```
- `Uvicorn running on http://0.0.0.0:8000` 이 뜨면 **그 창은 건드리지 말고**(Ctrl+C = 서버 종료) 브라우저에서 http://localhost:8000
- `.env` 가 없으면 AI는 규칙 기반(오프라인), 체인은 모의 체인으로 동작
- 회원가입 → MY 탭 **지갑 연결** → **충전**(100,000 PIE) → 홈에서 Pie에게 말 걸기
- 한 PC에서 여러 명 흉내: Chrome 일반 창 / 시크릿 창 / Edge 등 **서로 다른 브라우저 창**에서 각각 가입
- 자동 테스트 (서버를 `DISPUTE_WINDOW_SEC=3` 으로 켠 뒤): `node tests/frontend_logic.test.mjs`
- AI 전용 페이 (가짜 Kiln `python -m uvicorn tests.fake_kiln:app --port 8011` 켠 뒤): `DATA_DIR=/tmp/sp-aipay LLM_MODE=live KILN_API_KEY=x KILN_BASE_URL=http://127.0.0.1:8011/v1 CHARGE_COOLDOWN_SEC=0 py tests/ai_pay_check.py`
- 경계값 회귀 (서버 없이): `DATA_DIR=/tmp/sp-robust LLM_MODE=mock KILN_API_KEY= SERPER_API_KEY= DISPUTE_WINDOW_SEC=2 CHARGE_COOLDOWN_SEC=0 py tests/robustness_check.py`

## 1. Kiln 연결

```bash
copy .env.example .env     # Mac: cp
# .env 에 KILN_API_KEY=sk-bk-...
py scripts/check_kiln.py
```
- `2) tool calling` ✗ → `.env`에 `KILN_TOOL_MODE=json` / `3) reasoning_effort` ✗ → `KILN_REASONING_EFFORT=` (빈 값)
- auto 모드면 코드가 알아서 전환하지만, 고정해 두면 첫 요청의 실패 1회를 없앨 수 있어요
- 채팅 말풍선 아래에 `Kiln qwen3-32b N회 · 토큰 · 초` 가 보이면 성공
- **모델은 qwen3-32b 고정** (대회 제공 모델 · `KILN_MODEL=qwen3-32b`, `KILN_MODEL_STRICT=1`). Kiln 목록 이름이 `Qwen/Qwen3-32B` 처럼 달라도 같은 모델로 인식. 다른 모델로 **자동으로 바꾸지 않아요**
  - `qwen3-32b 사용 권한 없음(404)` 이 보이면 → 그 API 키로 이 모델을 못 씀 (`py scripts/check_kiln.py` 로 쓸 수 있는 모델 목록 확인). 그동안 답변은 규칙 기반으로 계속 동작
- 토큰 절약: 평소엔 `/no_think`로 Qwen3의 긴 사고를 끄고, 이의제기 판정처럼 어려운 단계만 사고 모드. `reasoning_effort`는 gpt-oss 전용이라 qwen3에는 보내지 않아요. 답이 max_tokens에 걸려 비면 한도를 2배로 늘려 1회 재시도하고, **잘린 시도의 토큰도 usage.jsonl에 기록**됩니다
- Pie 채팅은 기본이 대화형 에이전트(`PIE_CHAT=agent`). 모델이 도구 호출을 잘 못하거나 토큰을 줄이고 싶으면 `.env`에 `PIE_CHAT=pipeline`
- **제출용 토큰 보고서를 만들기 전 `data/usage.jsonl` 을 지우고** 시연 시나리오를 새로 돌리세요

## 1-1. 회원가입 인증 메일 보내기 (선택)

`.env`의 SMTP가 비어 있으면 **개발 모드**: 인증번호가 서버 창과 가입 화면에 바로 보여요 (시연은 이걸로 충분).
실제 메일로 보내려면 (Gmail 기준, 5분):
1. 보낼 구글 계정 → https://myaccount.google.com/security → **2단계 인증** 켜기
2. https://myaccount.google.com/apppasswords → 앱 이름 `SharePie` → **16자리 앱 비밀번호** 복사
3. `.env`
   ```
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=보내는주소@gmail.com
   SMTP_PASSWORD=16자리앱비밀번호(띄어쓰기 없이)
   ```
4. 서버 재시작 → 가입 화면에서 ‘인증번호 받기’ → 메일 도착 확인 (스팸함도)
- 네이버: 메일 → 환경설정 → POP3/SMTP 사용 → `SMTP_HOST=smtp.naver.com`, `SMTP_PORT=587`, 네이버 아이디@naver.com / 비밀번호
- 기존 비밀번호가 6자리 숫자인 계정도 로그인은 되지만, 새로 가입·변경할 때는 **영문+숫자 8자 이상**

## 1-2. 인터넷 상품 검색 켜기 (한정선 같은 실제 상품 비교)

`.env` 에 키를 넣은 소스만 자동으로 켜져요. 하나도 없으면 상품·메뉴 가격을 찾지 않고 “찾을 수 없다”고 솔직하게 답해요 (예시 데이터 없음).

| 소스 | 발급 | 무료 한도 | 얻는 것 |
|---|---|---|---|
| 네이버 검색 API | https://developers.naver.com/apps/#/register → 사용 API **검색** → 환경 **WEB 설정** `http://localhost` → Client ID/Secret | 하루 25,000회 | 여러 쇼핑몰 최저가·판매처·링크 + 뉴스·블로그 문맥 |
| **Serper** (네이버 대체) | https://serper.dev 가입 → API Key | 가입 시 2,500회 (카드 불필요) | 구글 쇼핑: 쿠팡·컬리·11번가 등 가격·판매처·링크 + 구글 웹 검색 |
| Tavily | https://app.tavily.com 가입 → API Key | 월 1,000회 (카드 불필요) | 공식몰·쿠팡·기사 등 일반 웹 (상품 페이지의 구조화 가격을 코드가 직접 읽음) |
| 쿠팡 파트너스 | 누적 판매 15만원 이상 최종 승인 후 | 시간당 8회 | 쿠팡 상품·가격 (승인 전엔 Tavily로 쿠팡 페이지 링크만) |

```
NAVER_CLIENT_ID=...          # 발급이 안 되면 비워 두고
NAVER_CLIENT_SECRET=...
SERPER_API_KEY=...           # ← 대신 이것 (하나만 있어도 동작)
TAVILY_API_KEY=tvly-...
```
확인: 서버 재시작 → Pie에게 “한정선 공동구매 20만원” → 판매처가 다른 후보 3~5개(최저가/가성비/대량/프리미엄)가 나오면 성공.
같은 검색어는 10분 동안 캐시돼서 무료 한도를 아껴요.

## 1-3. 소셜 로그인 켜기 (카카오·네이버·Google·Apple, 선택)

키를 넣은 회사 버튼만 실제로 동작하고, 없는 회사 버튼은 “준비 중” 안내만 떠요. 키는 **.env에만** 넣고 채팅·깃허브에 올리지 마세요.

**먼저 서버 주소를 고정하세요.** 각 사 콘솔에 “이 주소로 돌려보내라(Redirect URI)”를 등록해야 하는데, cloudflared 빠른 터널은 켤 때마다 주소가 바뀌어요.
- 내 컴퓨터에서만 시연: `http://localhost:8000` (구글·카카오·네이버는 localhost 허용)
- 다른 기기·다른 인터넷에서: 이름 있는 터널(도메인 고정) 또는 배포 주소 → `.env`에 `PUBLIC_BASE_URL=https://그주소`

등록할 Redirect URI (회사 이름만 바뀜): `<서버 주소>/api/auth/social/kakao/callback` · `…/naver/callback` · `…/google/callback` · `…/apple/callback`

| 회사 | 어디서 | .env |
|---|---|---|
| 카카오 | developers.kakao.com → 내 애플리케이션 → 앱 추가 → **카카오 로그인 활성화 ON** + Redirect URI 등록 → 동의항목: 닉네임(필수), 카카오계정 이메일(선택) | `KAKAO_CLIENT_ID=REST API 키` (보안 탭에서 Client Secret을 켰다면 `KAKAO_CLIENT_SECRET`도) |
| 네이버 | developers.naver.com → Application 등록 → 사용 API: 네이버 로그인 → 이름·이메일 체크 → 서비스 URL + Callback URL 등록 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` |
| Google | console.cloud.google.com → API 및 서비스 → OAuth 동의 화면(외부, 테스트 사용자에 팀원 Gmail 추가) → 사용자 인증 정보 → OAuth 클라이언트 ID(웹 애플리케이션) → 승인된 리디렉션 URI 등록 | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Apple | Apple Developer(유료 계정 필요) → Identifiers에서 Services ID 만들고 Sign in with Apple 켬 → **https 도메인**과 Return URL 등록 → Keys에서 Sign in with Apple 키(.p8) 발급 | `APPLE_CLIENT_ID=Services ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY=AuthKey_XXXX.p8 경로` (+ `pip install cryptography`) |

- 카카오는 이메일 동의항목이 비즈 앱 전환 전엔 막혀 있을 수 있어요 → 이메일을 못 받으면 가입 마무리 화면에서 메일 인증을 한 번 더 해요 (정상 동작)
- 구글 동의 화면이 “테스트” 상태면 등록한 테스트 사용자만 로그인돼요
- 설정 확인: 서버를 다시 켠 뒤 `http://localhost:8000/api/auth/social/providers` 에서 `enabled: true`
- 로고: UI 파일이 `frontend/assets/social/kakao.png` 등 각 사 공식 로고를 쓰게 돼 있어요. 파일이 없으면 이름 첫 글자로 보여요 (각 사 가이드에서 받아 넣기)

## 2. 컨트랙트 배포 (Remix, 약 15분)

1. **에이전트 전용 MetaMask 계정** 새로 만들기 (실제 자산 있는 계정 금지)
2. BNB Testnet faucet 에서 tBNB 받기 → https://www.bnbchain.org/en/testnet-faucet
   - **참여자 4명도 소량 tBNB 필요** (approve + lockForSettlement 가스비). 에이전트 계정에서 0.01씩 보내 줘도 됨
   - PIE 충전은 에이전트가 발급하므로 참여자 가스비 불필요
3. https://remix.ethereum.org → `contracts/PieToken.sol`, `contracts/ShareLedger.sol` 붙여넣기
4. Solidity Compiler **0.8.24**, Optimization **ON (200)** — `Stack too deep` 이 나면 Advanced → **viaIR** 체크
5. Deploy & Run → Environment **Injected Provider - MetaMask** (체인 97 확인) → **에이전트 계정으로** 두 개 배포
   - `PieToken` (배포 계정이 자동으로 minter = chargeToken 권한)
   - `ShareLedger` (배포 계정이 자동으로 agent)
   - (선택) `ShareLedger.setDisputeWindow(초)` — 기본 180초. 시연용으로 60 정도 권장
6. `.env`
   ```
   CHAIN_MODE=bsc
   TOKEN_ADDRESS=0x…      LEDGER_ADDRESS=0x…
   AGENT_PRIVATE_KEY=0x…  (MetaMask → 계정 세부정보 → 개인 키 내보내기)
   LEDGER_DEPLOY_BLOCK=… (BscScan에서 ShareLedger 배포 tx 블록)
   ```
7. (권장) Remix ABI를 `contracts/abi/ShareLedger.json`, `contracts/abi/PieToken.json` 으로 저장 → web3.py가 우선 사용
8. `py scripts/check_chain.py` → 전부 ✓

## 3. 폰 4대 (각자 MetaMask 앱)

```bash
py -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
cloudflared tunnel --url http://localhost:8000     # https://xxxx.trycloudflare.com 발급
```
- 각 폰: **MetaMask 앱 → 브라우저 탭 → 터널 주소** (일반 브라우저로 열면 앱이 “MetaMask로 열기”를 안내)
- 각자 회원가입 (김진주 / 박진우 / 이민재 / 최지현) → MY → 지갑 연결 → 충전
- 같은 Wi-Fi + 모의 체인이면 터널 없이 `http://<PC IP>:8000` 도 가능 (Windows 방화벽 허용)

## 4. 시연 시나리오

**Run 1 — 정상 정산 (정산 코어만)**
1. 진주: 공동구매 → 삼겹살 1.2kg → 참여 → 친구 3명 선택 → 정산방 (총 38,900원 = 35,900 + 배송 3,000)
2. 그룹 채팅: “진주는 주문하는 사람이니까 5천원 적게 내고 나머지 세 명이 나눠줘” → Stage1(AI)→Stage2(코드)→Stage3(AI) · 5,975 / 10,975 ×3
3. **분담표 확정 · 온체인 정산 요청** → `SettlementCreated`
4. 진우·민재·지현: **내 몫 결제하기** → MetaMask 2번 서명 (approve, lockForSettlement)
5. 전원 예치 → **지급 대기**(에스크로) → 기간 종료 후 `Paid` → 정산 인증서 (BscScan 링크)

**Run 2 — 조건 변경 → 지출 통제 중단 (챌린지 A "범위 초과 시 중단")**
1. 목살 1.5kg(39,900원) 정산방 → “1인 9천원 넘으면 안 돼. 똑같이 나눠줘” → 사전 경고
2. 온체인 정산 요청 → 결제 없이 `Blocked(reasonCode=2)` → 모든 폰에 ‘중단됨’

**Run 3 — 이의제기 (CLAUDE.md 9번 Run 2)**
1. 새 정산을 전원 예치 → **지급 대기** 중에 민재: **이의제기** → “공동구매가 품절로 취소됐어요”
2. AI Dispute Agent: 코드 대조 + 3분류 → `GENUINE_ERROR` → `refundParticipant` × 3 → `resolveDispute(2)` → 환불 완료
3. (대조군) “승인한 적 없어요” → 본인 서명 기록 근거로 `BAD_FAITH_DISPUTE` → 기각 · 지급

**Run 4 — AI 구매 대행 (챌린지 A “에이전트가 지시 범위 안에서만 결제”)**
1. 진주: Pie에게 “한정선 공동구매 20만원” → 후보 카드 → **이 상품으로 정산방 만들기** → 친구 선택 → 그룹 채팅 “셋이 똑같이 나눠줘” → 확인
2. 가상계좌 `SP-xxxx-xxxx-xxxx`가 생기고 각자 **내 몫 인출 승인** (MetaMask 2번: 한도 승인 → 구매 참여)
3. 마지막 승인 순간 AI가 결제 직전 검사 → 각자 지갑에서 몫만큼 인출 → 가맹점 지갑으로 결제 → 주문번호·영수증
4. (대조) 허용 판매처가 아닌 상품(“쿠팡에서만”인데 컬리) → 등록 단계에서 `Blocked(4)` · 돈 이동 없음

**제출물**: 각 Run의 tx hash (BscScan) + `GET /api/usage/report.md` + `data/usage.jsonl` + `data/db.json`

## 5. 문제 해결

- **친구 추가에서 ‘이 Pie ID를 쓰는 사용자가 없어요’**: 친구가 **같은 서버 주소**로 가입했는지 확인하세요. 각자 자기 PC의 localhost나 예전 터널 주소로 가입하면 다른 서버라 안 보여요. 서버 PC에서 `py scripts/list_users.py 친구ID` 로 이 서버의 가입자를 볼 수 있어요. (계정은 `~/.sharepie-data`에 저장돼 새 zip을 다른 폴더에 풀어도 유지돼요)

| 증상 | 해결 |
|---|---|
| `ERR_CONNECTION_REFUSED` | 서버 창이 꺼졌거나 Ctrl+C로 종료됨 → 다시 실행하고 창을 그대로 두기 |
| `No module named backend` | `requirements.txt` 가 있는 폴더에서 실행 |
| 화면이 하얗게만 나옴 | 인터넷 필요 (React를 CDN에서 불러옴) |
| 지갑 연결 반응 없음 (폰) | MetaMask 앱 브라우저로 열기 |
| `가스비(tBNB)가 필요해요` | faucet 또는 에이전트 계정에서 tBNB 송금 |
| `MEMBER_WALLET_MISSING` | 해당 멤버가 MY → 지갑 연결을 안 함 |
| `CHAIN_UNAVAILABLE` | 공개 RPC 혼잡 → `BSC_RPC_URL` 을 `https://data-seed-prebsc-2-s1.bnbchain.org:8545` 로 교체 |
| 말풍선에 “오프라인 규칙 모드” | 정상 (Kiln 키 전). 키를 넣고 서버 재시작 |
| 위치 권한 창이 안 뜸 / “https에서만” | 위치(GPS)는 **https(cloudflared 터널 주소)나 localhost**에서만 동작. `http://192.168…` 로 열면 브라우저가 막음 |
| 위치를 거부해 버림 | 브라우저 주소창 자물쇠 → 사이트 설정 → 위치 허용 (MetaMask 앱: 설정 → 권한) 후 ‘자동 추적 켜기’ |
| 가입 화면 ‘인증번호 받기’ 후 메일이 안 옴 | 스팸함 확인 → 서버 창에 `[메일 발송 실패]` 있으면 SMTP 설정·앱 비밀번호 확인 |
| 갑자기 로그인 화면으로 튕김 | 로그인이 만료(30일)됐거나 다른 기기에서 비밀번호를 재설정함 → 다시 로그인 |
| 한 명이 결제를 안 해서 정산이 멈춤 | 결제자 폰의 정산 카드 → ‘정산 취소’ (예치한 사람은 자동 환불) |
| 이의제기가 ‘조사 중’에서 멈춤 | 정산 카드 → ‘조사·판정 이어서 진행’ |
| 컨트랙트 수정 후 | Remix에서 **다시 배포**하고 `.env` 주소 교체 (구매 대행 `createPurchase/approvePurchase/executePurchase` 추가됨) · Remix ABI를 `contracts/abi/`에 저장했다면 그것도 갱신 |
