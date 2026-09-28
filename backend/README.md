# SharePie Backend — AI Settlement Agent

정산 코어(Stage 1~3) + Dispute 조사 API. 입출력 스키마는 루트 [CLAUDE.md](../CLAUDE.md) 6-1번 참고.

## 실행

```bash
cd backend
npm install
cp .env.example .env     # 그리고 .env 안의 KILN_API_KEY 채우기 (절대 커밋 금지)
npm start                # http://localhost:3000
npm test                 # API 키 없이도 전체 테스트 가능 (Kiln은 가짜 응답)
```

`GET /health`에서 `kilnConfigured: true`가 나오면 키가 정상적으로 읽힌 것.

## 폴더 구조

```
src/
  server.js                      Express 앱, 공통 에러 응답
  kilnClient.js                  Kiln API 호출 (stage 태그, 토큰 로깅, JSON 파싱·재요청)
  logger.js                      logs/token-usage.jsonl, logs/events.jsonl
  agents/
    interpretConditions.js       Stage 1  settlement.analyze   (AI)
    explainSettlement.js         Stage 3  settlement.explain   (AI)
    investigateDispute.js        Dispute  dispute.investigate  (AI)
  settlement/
    calculateSettlement.js       Stage 2  settlement.calculate (코드, 0 tokens)
    approveSettlement.js         전원 승인 → 온체인 기록 → 인증서
  dispute/compareRecords.js      기록 4종 비교 (코드)
  blockchain/blockchainClient.js ⚠️ MOCK — 블록체인 담당이 실제 SDK로 교체
```

## AI와 코드의 역할

| 하는 일 | 담당 |
|---|---|
| 자연어 → items / adjustments / payer 구조화 | AI |
| 1인 금액(shares), 예산 초과, 잔돈 처리 | 코드 |
| 계산 결과 설명 문장 | AI (문장 속 숫자는 코드가 검사 — 계산 결과에 없는 숫자면 재요청) |
| 기록 비교: 어느 단계에서 얼마나 차이 났는지 | 코드 |
| 판정(3종) + 설명 | AI (코드가 찾은 사실과 모순되는 판정은 거부) |

AI 응답이 JSON이 아니거나 형식이 틀리면 에러를 로그에 남기고 최대 3번 다시 요청한다.

## 블록체인 담당에게 (교체할 곳)

- `src/blockchain/blockchainClient.js` — `lockForSettlement`, `releaseToRecipient`의 내부만 실제 SDK 호출로 교체. 반환 모양 `{ txHash, block }` 유지.
- `src/dispute/compareRecords.js`의 `normalizeRecords()` — 실제 승인·송금 기록을 `{ from, to, amount, txHash }`로 변환.
- `TODO(블록체인 연동)`으로 검색하면 교체 지점이 모두 나온다.

## 로그 (제출 자료용)

- `logs/token-usage.jsonl` — Kiln 호출 1회당 1줄 (stage, promptTokens, completionTokens, cost)
- `logs/events.jsonl` — AI 응답, 계산 결과, 판정 근거, TxHash
- `GET /logs/tokens` — 흐름(stage)별 합계

`logs/`는 git에 올라가지 않는다. 데모 Run 1 / Run 2 로그는 끝난 뒤 따로 복사해서 보관.
