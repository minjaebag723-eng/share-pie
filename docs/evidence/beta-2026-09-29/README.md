# Share Pie 베타 데이터 폴더

이 폴더에는 **베타에서 모은 데이터만** 들어 있어요. 사람은 되돌릴 수 없는 id(`uid`)로, 대화 속 이름은 가명으로 바뀌어 있고
이메일·전화번호·지갑 주소·계좌번호·비밀번호는 없어요. 계정·정산 원본(`db.json`)은 서버의 data 폴더에 따로 있고 여기로 오지 않아요.

**보내는 법**: 이 폴더를 통째로 복사하거나, 관리자 링크 `/api/beta/bundle.zip?key=…` 또는 `python deploy/beta_bundle.py`로 zip을 만들어요.
받은 쪽은 `manifest.json`의 줄 수·sha256으로 빠짐없이 왔는지 확인해요.

| 파일 | 무엇 | 쓰는 곳 |
|---|---|---|
| dialogs.jsonl | '대화 제공'에 동의한 사람의 턴 (비식별) | 학습: 예시·평가 문제 후보 |
| feedback.jsonl | 답 평가 👍/👎와 이유 | 좋은 답 / 나쁜 답 라벨 |
| usage.jsonl | Kiln 호출 기록 사본 (토큰·지연·에너지·버전·턴·미션) | 토큰 효율 · 베타↔정식 비교 |
| events.jsonl | 동의 · 철회 · 미션 완료 | 참여 분석 |
| settlements.jsonl | 정산 요약 (상태·금액·한도·중단 코드·이의제기 판정·트랜잭션 해시) | 심사 기준 증거 |
| report.md · report.json | 요약 보고서 (버전 비교 · 미션별 토큰 · 심사 기준 실행 수 · 참여) | 발표 |
| manifest.json | 파일별 줄 수 · 크기 · sha256 · 기간 · 만든 시각 | 받은 데이터 확인 |

## 필드
- 공통: `ts`(초 단위 시각) · `version`(앱 버전: beta-1 / 1.0 …) · `uid`(사람) · `turn`(한 번의 질문-답) · `scenario`(베타 미션 S01~S13, 자유 입력이면 없음)
- dialogs: `channel`(chat 1:1 · group 그룹방) `edited`(미션 예시를 고쳐 보냈는지) `tags`(말 유형) `knowledge`·`examples`(프롬프트에 들어간 지식·예시)
  `user`·`history`·`reply`(비식별 글) `tokens`·`calls`(이 턴의 Kiln 토큰·호출) `limited`(구독 한도로 규칙 답)
- feedback: `rating`(up/down) `reason`(아쉬운 이유) `note`(자유 의견, 동의한 사람만)
- usage: `stage`(워크플로 단계) `mode`(tools·json·text = Kiln 호출 · code = 코드만 · fallback = 규칙 답 · decision = 응답→결정 기록)
  `prompt_tokens`·`completion_tokens`·`total_tokens` `latency_ms` `energy_wh`(추정) `plan` `counted`(구독 한도에 들어감) `note`
- 동의를 철회하면 그 사람의 dialogs·feedback 줄은 지워져요. usage·events는 글 없는 통계라 남아요.

## 버전 비교
같은 미션을 '예시 그대로'(`edited: false`) 보낸 턴끼리 `version`별 턴당 토큰을 비교해요 (report.md 2번 표).
