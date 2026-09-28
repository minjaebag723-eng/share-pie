# SharePie — AI Settlement Agent (GWDC 2026 챌린지 A)

> SharePie is, at its core, an AI Settlement Agent that interprets users' natural-language cost-sharing conditions, calculates and verifies a compliant settlement, and records the approved result on-chain. Two optional modules extend it: an AI Shopping Agent that helps users find what to buy before settlement, and an AI Dispute Agent that investigates disputes after settlement.

**한 문장 (챌린지 A 선택 기능):** 사용자가 말로 정한 분담 조건과 지출 한도를 AI가 해석하고, 코드가 금액을 계산·검증해 한도·잔액·가맹점 규칙을 통과한 경우에만 참여자가 MetaMask로 직접 Ethereum Sepolia 테스트넷 에스크로에 예치하며, 위반 시 결제 없이 중단 기록이, 이의제기 시 AI 판정과 환불 기록이 온체인에 남는다.

## 바로 가기

| 문서 | 내용 |
|---|---|
| [`HOW-TO-RUN.md`](HOW-TO-RUN.md) | 실행 안내 (로컬 · Sepolia 설정 · 검증) |
| [`deploy/README.md`](deploy/README.md) | 베타 서버 — 100명 동시 접속 · 데이터 폴더 · 클라우드 배포 |
| [`docs/BETA-PUBLIC.md`](docs/BETA-PUBLIC.md) | PC + Cloudflare 터널로 외부 공개 |
| [`docs/user-manual/`](docs/user-manual/) | 베타 참가자용 사용 설명서 (PDF) |
| [`CHANGES-beta-server.md`](CHANGES-beta-server.md) | 베타 서버 병합 · 실제 체인 동시 접속 수정 내역 |
| [`docs/evidence/`](docs/evidence/) | Sepolia 실행 증거 (TxHash · Etherscan 링크 · AI 토큰 표) |

## 배포된 컨트랙트 (Ethereum Sepolia, chainId 11155111)

| 컨트랙트 | 주소 |
|---|---|
| ShareLedger (에스크로·자금추적·이의제기) | [`0xF297240957c3aB10458Dc1A4C6eC2eA18292529E`](https://sepolia.etherscan.io/address/0xF297240957c3aB10458Dc1A4C6eC2eA18292529E) |
| PieToken (PIE, 테스트넷 전용) | [`0xF5cB871A8890bd1D34bf36E749F012D95589E0fD`](https://sepolia.etherscan.io/address/0xF5cB871A8890bd1D34bf36E749F012D95589E0fD) |
| 에이전트 지갑 | [`0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36`](https://sepolia.etherscan.io/address/0x33f446E980bd8F1CeeAEFA43B2FfDB5e45c46C36) |

## 실행

```bash
py -m pip install -r requirements.txt           # Mac: pip install -r requirements.txt
py -m uvicorn backend.app:app --host 0.0.0.0 --port 8000   # → http://localhost:8000
```
베타 서버(동시 접속 설정 · 베타 데이터 폴더): `py -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1` · 외부 공개는 `run-public.cmd`
키는 `.env`에만 넣어요 (`.env.example` 복사 → 채우기). `.env`는 `.gitignore`에 있어 올라가지 않아요.

자세한 순서·폰 접속·컨트랙트 배포는 **`docs/DEPLOY.md`**, 팀 연동 규격은 **`docs/API.md`**, 팀 규칙은 **`CLAUDE.md`**.

## 구조

```
agent/        AI 에이전트 (프레임워크 무관 파이썬)
  settlement.py  정산 코어 Stage1 해석(AI) · Stage3 설명(AI)
  money.py       Stage2 계산 + 지출 통제 (코드 전용, 0 tokens)
  dispute.py     Dispute 모듈: 코드 대조 → AI 3분류 판정 → 코드 가드
  shopping.py    Shopping 모듈: 조건 해석(AI) → 1인당 비용 계산(코드) → 비교 설명(AI)
  llm.py         Kiln 클라이언트 (tool calling → JSON 자동 전환, 단계 태그·토큰 로깅)
  chain.py       EVM 테스트넷(Ethereum Sepolia · web3.py) / 모의 체인 — 같은 인터페이스
  service.py     백엔드가 부르는 진입점
backend/app.py  HTTP API (:8000) + 프론트 서빙
contracts/      PieToken.sol (PieCoin, 테스트넷 전용) · ShareLedger.sol (에스크로·자금추적·이의제기)
frontend/       UI/UX 팀 디자인 + sp-bridge.js (API · MetaMask)
tests/          폰 4대 E2E 시뮬레이션 · 대화형 에이전트 점검(agent_check.py) · 경계값 회귀(robustness_check.py) · 가짜 Kiln/웹 서버
```

## AI가 한 일 vs 코드가 한 일

| 단계 | 담당 | 태그 |
|---|---|---|
| 자연어 분담 조건 → 규칙 JSON, 모호하면 되묻기, 송금 목적 문구 | AI | `settlement.analyze` |
| 금액 계산 · 합계=총액 검증 · 1인/총 한도 · 가맹점 · 체인 가용 잔액 검사 | **코드** | `settlement.calculate` / `settlement.policy` (0 tokens) |
| 계산 결과 설명 | AI | `settlement.explain` |
| 요청→계산→등록→예치→결제 기록 대조 | **코드** | `dispute.records` (0 tokens) |
| 이의 사유 + 대조 결과 → 3분류 판정 (코드가 모순 보정) | AI | `dispute.investigate` |
| 구매 조건 해석 + 검색어 계획 / 비교 설명 | AI | `shopping.search` / `shopping.explain` |
| 네이버·Tavily·쿠팡·상품 페이지 병렬 검색, 관련성 필터, 버전(최저가/가성비/대량/프리미엄) 선정 | **코드** | `shopping.web` (0 tokens) |
| 팩·인분 수, 배송·배달비 포함 1인당 비용, 예산 초과 판정 | **코드** | `shopping.calculate` (0 tokens) |
| 배달 메뉴 조합 3개 설계 (인원·예산·선호) | AI | `shopping.plan` |
| AI 조합 검증: 없는 메뉴·예산 초과·인분 부족 기각, 부족하면 코드 조합으로 채움 | **코드** | `shopping.calculate` (0 tokens) |
| **AI 구매 대행**: 전원 ‘인출 승인’ 후 결제 직전 지출 통제 재검사 → 각자 지갑에서 몫만큼 가상 계좌로 인출 → 가맹점 결제 (executePurchase) | 코드 + 체인 | `purchase.policy` / `purchase.execute` (0 tokens) |
| **Pie 대화형 에이전트** (기본 `PIE_CHAT=agent`): 고정 질문 없이 모델이 대화 맥락을 보고 도구(상품 검색·웹 검색·배달 메뉴표·조합 검증·비용 분할)를 스스로 골라 쓰고 답함. 최대 5걸음 | AI | `assistant.step` |
| 에이전트 도구 실행: 가격·합계·예산·인분 계산과 검증 (모델은 숫자를 만들지 않음) | **코드** | `assistant.tool` (0 tokens) |
| 정산(이름+금액+나누기)·이의제기 확정 신호는 전용 흐름 유지 (체인 기록·분담표 카드) | AI + 코드 | `settlement.*` / `dispute.*` |

토큰·지연·에너지 상한: `GET /api/usage/report.md` (RNGD TDP 150W × 카드 수 × 지연시간 — 배치 공유 미반영 상한)

## 시연 (docs/DEPLOY.md §4)

| Run | 내용 | 온체인 증거 |
|---|---|---|
| 1 정상 | 자연어 조건 → 계산 → 등록 → 4명 예치 → 에스크로 → 지급 | `SettlementCreated` · `Locked` · `FullyLocked` · `Paid(목적)` |
| 2 조건 변경 | 1인 9천원 한도 → 결제 없이 중단 | `Blocked(reasonCode=2)` |
| 3 이의제기 | 지급 전 “품절로 취소” → `GENUINE_ERROR` → 전원 환불 / “승인 안 했다” → `BAD_FAITH_DISPUTE` 기각 | `DisputeRaised` · `Refunded` · `DisputeResolved` |

## 역할 분리 (보안)

- **돈이 움직이는 서명은 항상 사람** (MetaMask `approve` → `lockForSettlement`)
- 에이전트 지갑은 등록·중단·판정·지급만. 참여자 지갑에서 돈을 뺄 권한 없음
- 체인에는 실명 대신 지갑 주소만, 송금 목적 문구의 이름은 코드가 제거
- Kiln 키·에이전트 개인키는 서버 `.env`에만

## 가정 (발표 시 명시)

- 1인 적정량: 고기 300g · 과일 500g, 배달은 메뉴별 인분 기준
- 인터넷 검색은 공식 API(네이버·Tavily·쿠팡 파트너스)와 상품 페이지의 공개 구조화 데이터만 사용 (사이트 차단 우회·무단 크롤링 없음). 키가 없으면 상품 가격을 찾지 않고 모른다고 답함. 예시 데이터는 전혀 없음: 공동구매 탭은 GPS 근처 사용자가 올린 실제 모집글만, 배달 메뉴 조합은 AI가 검색한 실제 브랜드 판매가로만 만듦 (검색이 안 되면 지어내지 않고 못 찾았다고 답함)
- 에너지: RNGD TDP 150W (FuriosaAI 공식), 서빙 카드 수는 대회 측 확인 전까지 1장

## AI 요금제 · Kiln 사용 보고서 (심사 제출용)

- **요금제 (Claude 벤치마킹)**: 쓴 만큼 정산하지 않고, 월 구독(Free · Pie Pro 4,900 · Pie Max 5x 24,500 · Pie Max 20x 49,000 PIE)이 **5시간 세션 한도와 주간 한도**를 정한다. 한도를 넘으면 Kiln을 부르지 않고 규칙으로 답하며, 정산 계산·결제·승인은 코드라 그대로 동작한다. 분쟁 조사는 한도 밖. 자세한 규칙: `docs/API.md` 1-4.
- **보고서**: 서버를 켠 뒤 `GET /api/usage/report.md` (README에 그대로 붙이는 표), `GET /api/usage/calls.csv` (호출별 원자료), `GET /api/usage` (JSON). 앱에서는 MY → AI 토큰 세부내용 → ‘보고서’.

| 심사 기준 | 보고서에서 보는 곳 |
|---|---|
| 토큰을 워크플로 단계별로 (단순 합계 아님) | 1절 단계별 표 (입력·출력·호출당 평균·지연·비중) + 2절 구간별 합계 |
| 실제 API 호출 · 응답이 의사결정·행동에 반영되는 방식 | 3절 실행별 단계 순서의 `[응답 반영]` 줄 (예: Kiln 응답 → 도구 호출 / 규칙 JSON → 코드 계산 / 판정 → 환불 tx) · CSV ‘응답 반영’ 열 |
| 불필요한 추론·에너지를 줄이는 설계 | 4절 절감 표 (잡담 무시·불법 목적 차단·코드 보정·한도 차단 건수와 최소 절감 토큰, 계산 근거) + 설계 목록 |
| 에너지 추정의 측정 데이터·가정 | 5절 (호출마다 실측 지연시간 × NPU 150W × 카드 수 → Wh 상한, 공식·출처) |
| 조건을 바꿔 end-to-end 2회 실행 + 기록 검증 | 3절 실행 비교 표 (조건: 총액·인원·1인/총 한도·허용 판매처 → 결과: 지급/지출 통제 중단, 온체인 tx 해시) |

모델: `KILN_MODEL=qwen3-32b` (CLAUDE.md — 대회 측이 2026-09-28 gpt-oss-120b에서 변경한 제공 모델). 보고서 머리줄에 실제 모델·엔드포인트·실측 여부가 찍힌다.

테스트: `tests/ai_sub_check.py` (요금제·한도·보고서, 모의) · `tests/ai_limit_check.py` (가짜 Kiln으로 한도 초과 시 호출이 실제로 멈추는지) — 실행 방법은 각 파일 맨 위.

## Pie 두뇌 적용 · 베타 데이터 수집

- **Pie 두뇌 (`agent/brain.py` ← `agent/pie_brain/`)**: 1:1 Pie와 그룹방 Pie mate의 시스템 프롬프트를 'Pie mate 학습 가이드라인' 순서로 조립한다 — persona → 모드 규칙(chat|group) → 도구 쓰는 법(코드) → 상황 정보 → 관련 지식 최대 2조각(800자) → 태그가 맞는 예시 최대 3개(750자). 파일을 고치면 다음 호출부터 반영. 정산 해석·설명·분쟁 판정·구매 조건 해석은 전용 프롬프트 그대로. 턴마다 0토큰 기록(`assistant.brain`)에 태그·넣은 지식·예시·프롬프트 글자 수가 남는다.
- **베타 미션 13개 (홈 · MY → 베타 테스트 참여)**: 필요한 데이터를 얻도록 만든 기능 예시. 학습용(태그를 고루 · 까다로운 말투), 버전 비교용 기준 과제 6개(같은 문장), 심사 기준용(지출 통제 중단 → 조건 바꿔 재실행, 이의제기로 기록 검토). 답마다 ‘도움 됐어요 · 아쉬워요(+이유)’.
- **동의**: 대화 글은 ‘대화 제공’에 동의한 사람만 비식별 저장. 동의하지 않아도 미션은 되고 토큰 통계만 남는다. 철회하면 저장된 것도 삭제.
- **보고서**: `GET /api/beta/report.md` (버전 비교 · 시나리오별 턴당 토큰 · 심사 기준 실행 수 · 참여), 학습·평가 후보는 관리자만 `GET /api/beta/export.jsonl?kind=train|eval`.
- **정식 버전과 비교**: 베타는 `APP_VERSION=beta-1`, 정식은 `APP_VERSION=1.0`으로 배포 — 같은 `data/usage.jsonl`에 쌓이면 보고서가 버전별로 나눠 보여 준다(서버를 옮기면 두 파일을 합쳐서).
- **계산 조건 해석 (가이드라인 ⑥)**: 정산 해석 프롬프트에 유형별 예시(`agent/pie_brain/calc_examples.jsonl`)가 붙고, 해석 결과에 금액 조각·1인당 금액·일부만 나누는 항목·단위 맞춤·% 종류 필드가 있다. 코드 안전망이 AI가 놓친 조건을 다시 읽는다. 한국어 금액은 한글 숫자·앞자리 생략까지 읽는다(만2천원 → 12,000 · 만오천원 → 15,000 · 삼만오천원 · 이십만원 · 천오백원). '민재는 진우 두 배'처럼 조정된 사람을 다시 기준으로 삼으면 되묻는다.
- 계산 평가: `DATA_DIR=/tmp/sp-calc LLM_MODE=mock KILN_API_KEY= python tests/calc_check.py` (코드 안전망 51문제 100%) · 실제 Kiln은 `LLM_MODE=live`로 같은 명령 (목표 분담표 95%·되묻기 100%). 베타에서 👎 받은 계산 문장은 `tests/calc_eval.jsonl`에 추가한다.
- **베타 서버 (`deploy/`)**: 100명 동시 접속 설정 · 데이터는 `beta-data/` 한 폴더에(이 폴더만 보내면 됨) · 도커+Caddy(HTTPS)·Windows 실행 · 부하 테스트 → **`deploy/README.md`**. 켜는 명령은 `python -m uvicorn deploy.asgi:app --workers 1`
- 테스트: `tests/brain_check.py` · `tests/beta_check.py` (실행 방법은 각 파일 맨 위), 화면은 `tests/frontend_logic.test.mjs`.
