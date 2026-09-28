# START — SharePie 개발 시작 가이드

이 문서는 팀원이 **개발을 처음 시작할 때** 순서대로 따라 하는 체크리스트입니다. `CLAUDE.md`는 "무엇을 만들지"의 규칙이고, 이 문서는 "어떻게 첫 삽을 뜨는지"입니다.

## 0. 시작 전 확인할 것

- [ ] GitHub 저장소 Pull 완료 (`Share Pie.dc.html`, `support.js`, `.thumbnail` 로컬에 있는지 확인)
- [ ] `CLAUDE.md`, `TASK.md`를 저장소 루트에 커밋해둠
- [ ] Node.js, VS Code, GitHub Desktop 설치 완료
- [ ] `CLAUDE.md` 1번(선언 위계)과 0번(절대 원칙)을 한 번 정독 — 특히 "정산이 유일한 메인, Shopping·Dispute는 선택적 모듈"이라는 구조를 헷갈리지 않기

## 1. Kiln API 키 발급

1. `https://docs.bricksum.com` (또는 콘솔 링크)에서 회원가입
2. "Get an API key" 버튼으로 키 발급 → `sk-bk-...` 형태
3. 프로젝트 루트에 `.env` 파일 생성:
   ```
   KILN_API_KEY=sk-bk-여기에_발급받은_키
   KILN_BASE_URL=https://api.bricksum.com/v1
   KILN_MODEL=qwen3-32b
   ```
4. `.env`는 반드시 `.gitignore`에 추가 — 절대 커밋하지 않는다

## 2. Kiln API 최소 동작 테스트 (제일 먼저 할 것)

아래 curl이 정상 응답(`Hello!`에 대한 답변)을 반환하는지 확인:
```bash
curl https://api.bricksum.com/v1/chat/completions \
  -H "Authorization: Bearer $KILN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-32b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```
✅ 응답 안에 `usage` 객체(토큰 수)가 포함되는지도 함께 확인 — `CLAUDE.md` 0번 원칙 3 및 4번(Kiln API 연동 스펙)의 로깅 요구조건에 필요.

## 3. 블록체인 환경 세팅

- [x] 체인 확정: **BNB Smart Chain Testnet (Solidity/EVM)** — 배포는 `docs/DEPLOY.md` 2번 (Remix)
- [ ] CLI 설치 (Aptos CLI 또는 Hardhat/Foundry)
- [ ] 테스트넷 지갑 생성 + 테스트넷 토큰(faucet) 받기
- [ ] `CLAUDE.md` 5번의 함수 7개(`charge_token` 등)를 골격만 먼저 컴파일되게 작성 → devnet 배포 → 컨트랙트 주소를 `CLAUDE.md` 10번(환경변수)에 채워넣기
- [ ] **`lock_for_settlement` 구현 시 잔액 부족 체크(`CLAUDE.md` 5번 참고)를 처음부터 넣기** — 나중에 추가하려면 테스트를 다시 해야 해서, 골격 단계에서부터 포함하는 게 안전함

## 4. UI/UX — 별도 담당자 진행 중, 여기서는 참고만

화면 제작은 별도 담당자가 진행하므로 이 가이드에서 다루지 않는다. 백엔드/블록체인 담당자는 `Share Pie.dc.html`을 열어 **API가 어떤 화면과 이어질지 감만 잡고**, 실제 작업은 5번(API 스텁)부터 시작한다.

## 5. 백엔드 서버 뼈대

1. ~~Node.js(Express)~~ → **확정: Python 백엔드가 이미 있음** (`py -m uvicorn backend.app:app --port 8000`, `docs/DEPLOY.md` 0번)
2. `CLAUDE.md` 6번의 엔드포인트를 "정산 코어 → Dispute 모듈 → Shopping 모듈" 순서 그대로 빈 함수(스텁)로 먼저 다 만들어두기 — 나중에 하나씩 채움
3. Kiln API 클라이언트 모듈 하나 만들어서(`kilnClient.js`) 모든 엔드포인트가 이걸 공유해서 쓰게 함 (Stage 태깅·토큰 로깅을 여기서 공통 처리)
4. **정산 코어(Stage 1~3)를 다턴(multi-turn) 대화로 설계** — 사용자가 조건을 도중에 바꾸면 Stage 1이 최신 JSON을 다시 만들어 Stage 2로 넘기는 구조를 처음부터 염두에 둘 것 (`CLAUDE.md` 3번 참고)

## 6. 첫 번째로 완성해야 할 최소 흐름 (Day 1 목표)

```
[정산방 생성] → [자연어 조건 입력] → Stage1(AI) → Stage2(코드계산·예산검증) → Stage3(AI설명) 
→ [승인(잔액확인 후 잠금)] → [온체인 기록] → Transaction Hash 화면에 표시
```
이 흐름 하나가 끝까지 돌아가면 Run 1(정상 정산) 데모가 완성된 것입니다. 이 시점에는 Shopping·Dispute 모듈이 없어도 완전히 성립해야 합니다. 그다음 Dispute 모듈을 붙입니다.

## 7. 막히면

- Kiln API 응답 형식이 예상과 다르면 → `/llms.txt` 문서를 Claude Code에게 붙여넣고 다시 물어보기
- 컨트랙트 컴파일 에러 → 함수 시그니처가 `CLAUDE.md` 5번과 정확히 일치하는지부터 확인
- 무엇을 먼저 해야 할지 헷갈리면 → `TASK.md` 확인
- "이게 정산 메인 기능인가 Shopping/Dispute 모듈인가" 헷갈리면 → `CLAUDE.md` 1번 구조도로 돌아가기
