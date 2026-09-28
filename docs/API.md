# Share Pie API 연동 계약서 (v2 · 고정)

> 4명이 이 문서만 보고 작업합니다. 필드명을 바꿔야 하면 **AI 담당에게 먼저 말하고** 이 문서를 같이 수정하세요.
> CLAUDE.md 6번 이름을 그대로 쓰고, 앞에 `/api`만 붙였습니다. (백엔드: Python · Starlette, 포트 8000)

- 서버 `http://<주소>:8000` 가 `frontend/`를 `/`로 같이 서빙 → **같은 주소라 CORS 불필요** (다른 포트로 띄우면 `.env`의 `CORS_ORIGINS`에 추가)
- 금액은 전부 **정수 원** (1 PIE = 1원, decimals 0, 테스트넷 전용·실제 가치 없음)
- 사람은 **정산 이름(short)**으로 식별: 가입 이름 `김진주` → `진주`. **같은 이름도 가입 가능** — 겹치면 서버가 자동으로 `김진주`(전체 이름) → `진주2`로 구분. 친구는 Pie ID로 찾음

## 공통 응답 형식

```json
{ "ok": true,  "data": { ... } }
{ "ok": false, "error": { "code": "MEMBER_WALLET_MISSING", "message": "사람이 읽는 한국어", "stage": "settlement.request", "details": {...} } }
```

| code | HTTP | 뜻 |
|---|---|---|
| BAD_REQUEST | 400/422 | 요청 형식 오류 (`details`에 필드 위치) |
| AUTH_FAILED / EMAIL_TAKEN | 401/409 | 로그인 실패 / 이메일 중복 (이름 중복은 허용) |
| UNAUTHORIZED / FORBIDDEN | 401/403 | 토큰 없음·만료 / 본인이 아닌 요청 |
| CODE_REQUIRED · CODE_MISMATCH · CODE_EXPIRED · CODE_LOCKED · CODE_COOLDOWN · CODE_LIMIT · MAIL_FAILED | 400/429/424 | 이메일 인증번호 관련 |
| WEAK_PASSWORD · LOGIN_LOCKED · HAS_ACTIVE_SETTLEMENT · SOCIAL_ACCOUNT | 400/429/409/401 | 비밀번호 규칙 / 로그인 잠금 / 진행 중 정산 있어 탈퇴 불가 |
| SERVER_DOWN (프론트 전용) | 502/530 | JSON이 아닌 응답 = 서버가 꺼졌거나 터널 주소가 바뀜 |
| NOT_FOUND | 404 | 없는 정산·상품·경로 |
| MEMBER_WALLET_MISSING | 409 | 지갑 미연결 멤버 (`details.names`) |
| WALLET_TAKEN | 409 | 다른 사람이 이미 등록한 지갑 |
| POLICY_BLOCKED | 409 | 지갑 미연결 멤버가 있는데 한도·허용 판매처 규칙까지 위반 — 기다려도 풀리지 않아 즉시 거부 (지갑이 다 있으면 `status:'blocked'` + 온체인 Blocked 기록) |
| PROHIBITED_PURPOSE | 403 | 불법 목적(자금세탁·검은돈·마약·불법도박 등) 정산·구매 요청 — 지출 통제로 거부 |
| NOT_DISPUTABLE / NOT_READY | 409 | 이의제기 불가 상태 (지급 완료 등) / 판정 전 resolve |
| NOT_CANCELLABLE / FORBIDDEN | 409/403 | 전원 예치 후에는 취소 불가 / 결제자·참여자가 아닌 사람의 요청 |
| CHARGE_COOLDOWN | 429 | 충전 간격 제한 |
| CHAIN_UNAVAILABLE / CHAIN_TX_FAILED | 502/503 | RPC 실패 / 트랜잭션 revert |
| MOCK_ONLY | 403 | `/api/dev/*`를 실제 체인 모드에서 호출 |
| INTERNAL | 500 | 서버 버그 |

> Kiln 장애는 에러로 내보내지 않고 규칙 기반 응답으로 대체 + `degraded:true` + 말풍선 `meta`에 표시.
> **모델은 `qwen3-32b` 고정** (대회 제공 모델 · `KILN_MODEL_STRICT=1`, `Qwen/Qwen3-32B` 같은 별칭만 허용 · 다른 모델로 자동 전환 안 함). 키에 권한이 없으면 `meta`에 `qwen3-32b 사용 권한 없음(404)`. 평소엔 `/no_think`로 긴 사고를 끄고(토큰 절약) 이의제기 판정 같은 어려운 단계만 사고 모드. 답이 max_tokens에 걸려 비면 한도 2배로 1회 재시도하고 잘린 시도의 토큰도 기록.

## 정산 상태 (Settlement.status)

```
open ──(전원 예치)──▶ locked ──(이의제기 기간 종료)──▶ paid
  │                    └─(이의제기)─▶ disputed ─(판정)─▶ paid | refunded
  └─(지출 통제 위반: 등록 시점)─▶ blocked
```
멤버 상태 `members[].state`: `wait` 대기 · `locked` 예치 · `offline` 현금 · `refunded` 환불 · `payee` 결제자

## 1. 회원 · 지갑

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
**로그인 토큰**: signup·login 응답의 `token`을 이후 모든 요청에 `Authorization: Bearer <token>` 으로 보냄 (30일, sp-bridge.js가 자동 처리).
토큰 없으면 `401 UNAUTHORIZED`, 남의 이름으로 결제·충전·취소·이의제기하면 `403 FORBIDDEN`. (공개: health·config·wallet 조회·auth·usage)

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| POST | `/api/auth/email-code` | `{email, purpose: signup\|reset}` | 6자리 인증번호 메일 발송 → `{expires_in: 300(5분), resend_after(다음 재요청까지 초), free_resends_left, send_count}`. **처음 + 재요청 2번은 바로, 그 뒤로는 1분 간격** (`CODE_COOLDOWN`, details.wait), 1시간 10회. 앱은 5분 타이머와 ‘5분 안에 입력해주세요. 메일이 오지 않으면 한번 재요청을 해주세요’ 표시. SMTP 미설정이면 `dev_code` |
| POST | `/api/auth/signup` | `{name, email, password(영문+숫자 8자↑), code, pie_id}` | `{name, short, email, wallet, createdAt, id(Pie ID), address, token}` |
| POST | `/api/auth/login` | `{email, password}` | 위와 같음 (5번 틀리면 5분 잠금 `LOGIN_LOCKED`) |
| GET | `/api/auth/me` | | 토큰 확인 (자동 로그인) |
| POST | `/api/auth/logout` | `{}` | 토큰 폐기 |
| POST | `/api/auth/find-id` | `{name}` | `{emails: ["ji***@gmail.com"]}` |
| POST | `/api/auth/reset-password` | `{email, code, password}` | 메일 인증 후 변경 · 다른 기기 로그인 모두 해제 |
| POST | `/api/auth/change-password` | `{old_password, new_password}` | |
| POST | `/api/auth/withdraw` | `{password}` | 계정 삭제 (진행 중 정산 있으면 `HAS_ACTIVE_SETTLEMENT`) |
| GET | `/api/users?q=` | | 가입자 목록 (이름·Pie ID 검색 · 이메일·동네는 숨김) |
| GET | `/api/users/check-id?id=` | | Pie ID 형식·중복 확인 `{id, available, error}` (가입 화면 · 로그인 불필요) |
| GET | `/api/users/by-id/{pieId}` | | Pie ID로 사용자 찾기 `{id, name(짧은 이름), fullName, isFriend}` · 없으면 404 |
| GET | `/api/friends` | | 내 친구 목록 `[{id, name, fullName, wallet}]` (그룹 만들기 친구 선택에 사용) |
| POST | `/api/friends/request` | `{id}` | **친구 요청** (상대가 수락해야 친구). 상대가 먼저 요청했으면 바로 친구 → `{status: sent\|friends\|pending\|already, user, friends, requestsIn, requestsOut}` |
| POST | `/api/friends/accept` · `/decline` · `/cancel` · `/remove` | `{id}` | 받은 요청 수락/거절 · 보낸 요청 취소 · 친구 삭제(서로 끊김) → 같은 형식. `/api/friends/add`는 예전 이름(=request) |
| GET | `/api/friends/requests` | | `{in:[{id,name,fullName}], out:[…]}` 받은·보낸 친구 요청 |
| POST | `/api/geo/locate` | `{lat, lng, save?}` | 기기 GPS 좌표 → 동네 이름 `{address, changed, source}` (카카오 키 있으면 카카오, 없으면 OpenStreetMap · **좌표는 저장 안 함**, 동 이름만 프로필에 저장) |
| POST | `/api/auth/profile` | `{pie_id?, address?}` | Pie ID 변경(중복 시 `PIE_ID_TAKEN`) · 우리 동네 저장 (Pie가 ‘근처’·배달 추천 때 참고) |

**로그인 화면 이메일 자동 채우기** — 앱이 기기마다 무작위 ID를 만들어 모든 요청에 `X-SP-Device` 헤더로 보냄 (sp-bridge.js 자동).
이메일 **가입·로그인에 성공하면** 서버가 그 기기 ID(해시)에 이메일을 기억 → 다음에 로그인 화면을 열면 채움. 소셜 로그인은 기록하지 않음. 탈퇴하면 삭제.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/api/auth/remembered` | (헤더 `X-SP-Device`) | `{email \| null}` |
| POST | `/api/auth/remembered/forget` | `{}` | 이 기기 기억 지우기 |

**소셜 로그인 (카카오·네이버·Google·Apple, OAuth 2.0 인가 코드)** — `start`·`callback`은 브라우저가 페이지째 이동하는 주소 (JSON 아님)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/auth/social/providers` | `[{id: kakao\|naver\|google\|apple, name, enabled}]` — `enabled:false`면 서버에 키가 없음 → 버튼은 ‘준비 중’ 안내 |
| GET | `/api/auth/social/{p}/start` | 각 사 로그인 화면으로 302 (state는 서버에 1회용 10분 저장) |
| GET·POST | `/api/auth/social/{p}/callback` | 각 사가 돌려보내는 주소 (Apple은 POST form). 성공 → `/#sp_social=<티켓>`, 실패·취소 → `/#sp_social_error=<메시지>` |
| POST | `/api/auth/social/exchange` | `{ticket}` → `{status:'ok', ...user, token}` 로그인 완료 · `{status:'need_profile', providerName, email, emailVerified, name, pieId}` 처음 온 사람 · `{status:'linked', social}` 계정 연결 완료 |
| POST | `/api/auth/social/complete` | `{ticket, name, pie_id, email?, code?}` 가입 마무리 → `{...user, token}`. 각 사에서 **확인된 이메일**을 못 받았으면 `email`+메일 인증번호(`/api/auth/email-code` purpose=signup) 필요 |
| POST | `/api/auth/social/{p}/link` | (로그인 필요) `{url}` → 그 주소로 이동하면 내 계정에 연결 |
| POST | `/api/auth/social/{p}/unlink` | (로그인 필요) 연결 해제 → `{social}`. 비밀번호 없는 계정의 마지막 소셜은 `LAST_LOGIN_METHOD` |

- 계정 연결 규칙: 이미 연결된 소셜 id → 그 계정으로 로그인. 아니면 각 사가 **확인했다고 한 이메일**과 같은 계정이 있으면 자동 연결(네이버는 @naver.com만 확인된 것으로 봄). 확인 안 된 이메일로는 기존 계정에 붙이지 않음 (계정 탈취 방지)
- 사용자 응답(`me`·로그인)에 `social: ['kakao', …]`, `hasPassword` 추가. 소셜로만 가입한 계정은 비밀번호 로그인 시 `SOCIAL_ACCOUNT`(어느 회사로 로그인할지 안내), 비밀번호 만들기는 `change-password`에 `old_password:''`, 탈퇴는 `password:'탈퇴'`
- 에러 코드: `SOCIAL_NOT_CONFIGURED`(409) · `SOCIAL_STATE`·`SOCIAL_CANCELLED`·`SOCIAL_TICKET`(400) · `SOCIAL_TAKEN`(409) · `SOCIAL_TOKEN_FAILED`·`SOCIAL_PROFILE_FAILED`·`SOCIAL_UNREACHABLE`(502, 앱에는 `#sp_social_error`로 전달)

**Pie ID 규칙** (서버·프론트 동일): 영문 소문자로 시작, 소문자·숫자·`.`·`_`, 4~20자, 마침표 연속·끝 금지. 로그인 이메일과 별개인 공개 ID.
Pie ID가 생기기 전 가입한 계정은 서버 시작 시 이메일 앞부분으로 자동 부여 (프로필에서 변경 가능).
| POST | `/api/members/register` | `{name(짧은 이름), wallet}` | 지갑 등록 (mock은 wallet 생략 가능) |
| POST | `/api/wallet/charge` | `{name}` | charge_token: 에이전트가 PIE 100,000 발급 → `{amount, tx_hash, wallet}` |
| GET | `/api/wallet/{address}` | | **실시간 자금추적** `{balance, scheduled(사용 예정), escrow(예치 중), spent(실사용), available(가용), history[{d,t,s(목적),a,note?,pending?}]}` |

## 1-2. 그룹 채팅방 · Pie 대화 기록 (멤버 모두 같은 방)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/groups` | 내가 멤버인 방 + 최근 메시지 200개 (폰이 4초마다 폴링) |
| POST | `/api/groups/create` | `{id, name, members, total, payer, shares, ruleText, purpose, merchant, allowedMalls, status, msgs}` |
| POST | `/api/groups/{id}/update` | 분담표 확정·정산 요청 후 필드 갱신 (`v` 증가 → 다른 폰이 반영) |
| POST | `/api/groups/{id}/messages` | `{id, from:'sys'\|본인, text, kind?, confirmData?, analysis?, meta?}` — 남의 이름으로는 못 씀. 응답 = 저장된 메시지 + `replies[]`(Pie mate 답, 없으면 빈 배열) |
| POST | `/api/groups/{id}/messages/{mid}/resolve` | `{accepted}` 확인 카드 처리 (먼저 누른 사람만 반영, `resolvedBy`) |
| GET · POST | `/api/chats` · `/api/chats/save` · `/api/chats/{id}/delete` | Pie 대화 기록 (다른 기기에서도 이어 보기) |


**그룹방 Pie mate** (서버가 메시지를 받는 즉시 판단 · 답은 방에 저장 → 다른 폰은 폴링으로 받음)
- 무조건 답: 이름 부름 — `Pie · pie mate · 파이(야/님/…) · 파메 · 파이메이트 · 쉐어파이 · 파이봇 · @파이` (‘애플파이·와이파이·파이팅’은 제외)
- 답함: 정산 이야기(금액·나눠·빼고·%·얼마·결제·환불…), 구매 이야기(사자·주문·배달·추천·가격…), Pie가 방금 물은 것에 대한 대답
- 무시: 잡담 (코드 판단, 토큰 0 · `group.pie` 로그)
- 정산 조건이면 Stage1→2로 계산해 확인 카드(`kind:'confirm'`)까지 서버가 올림. 그 외에는 방 정보(멤버·총액·분담표·온체인 상태)와 최근 대화 14개를 읽고 에이전트가 답
- Pie 메시지: `{id, from:'sys', pie:true, text, replyTo(원 메시지 id), to(답한 사람), ask?('settle'|'chat'), meta}` · 방 조회 응답의 `pieTyping:true` = 답 작성 중
- 불법 목적(자금세탁 등)은 항상 거절


## 1-3. 알림함 · 방 관리 · 환불 요청

| 메서드 | 경로 | 요청 | 설명 |
|---|---|---|---|
| GET | `/api/notifs` | | 내 알림 `{items:[{id, cat, text, ts, read, go, req?, action?}], unread}` (폰이 4초마다 폴링) |
| POST | `/api/notifs/read` | `{ids?}` | 읽음 (ids 없으면 전부) |
| POST | `/api/groups/{id}/read` | `{}` | 방 읽음 → `unread` 0 |
| POST | `/api/groups/{id}/mute` | `{muted}` | 이 방 알림 끄기/켜기 (나만) |
| POST | `/api/groups/{id}/rename` | `{name}` | 1~20자, 멤버 모두에게 반영 |
| POST | `/api/groups/{id}/invite` | `{ids:[Pie ID]}` | 서로 친구인 사람만 (`NOT_FRIEND`). 진행 중인 정산에는 0원으로 들어옴 |
| POST | `/api/groups/{id}/join` | `{}` | 알림함 초대 ‘참여’ |
| POST | `/api/groups/{id}/leave` | `{}` · `?declined=1` | 나가기 / 초대 거절. 진행 중인 정산이 있으면 `ALREADY_SETTLING` |
| POST | `/api/settlement/refund-request` | `{settlement_id, reason, note?}` | MY 결제 내역 ‘환불 요청’ = 이의제기 → AI 3분류 판정 (GENUINE_ERROR면 자동 환불, 아니면 기각). 지급 전(에스크로)만 가능 (`NOT_REFUNDABLE`). reason: 단순 변심·금액 착오·인원·참여자 착오·중복 결제·기타 |

- 알림 `cat`: 친구 · 그룹 초대 · 승인 요청(`action:true`, 주황 강조) · 정산 완료 · 환불 · 정산 중단 · 이의제기. `req = {type: friend|invite, key: Pie ID|그룹 id, status: pending|accepted|declined|left}` → pending이면 수락/거절 버튼. `go`: `['gchat', gid]` · `['friends']` · `['tab','settle']`
- 방 조회(`/api/groups`)에 보는 사람별 값: `unread`(사람·Pie 메시지와 승인 요청만, 시스템 안내 제외) · `muted` · `lastAt` · `pending`(초대 수락 전)
- 정산이 온체인에 등록되면 서버가 방에 `kind:'approveReq'` 메시지(`from`=결제자, `total`, `sid`)를 올리고 멤버 알림함에 ‘승인 요청’을 보냄. 카드의 ‘승인하기’ = 내 몫 예치(결제) · 구매 대행이면 인출 승인
- 지갑 내역(`/api/wallet/{addr}`.history) 항목에 `id, sid, groupId, kind(pay|refund), refundable` 추가
- 앱: 새 메시지 → 배너(알림 끈 방 제외, 승인 요청은 항상) · 앱이 백그라운드면 브라우저 알림(허용한 경우) · 그룹 탭 배지(안 읽은 수) · MY 탭 배지(받은 친구 요청)

## 1-4. AI 요금제 (Claude 벤치마킹: 월 구독이 사용 한도를 정함) · 방 나가기

쓴 만큼 정산(후불)하지 않는다. **월 구독 요금제가 5시간 세션 한도와 주간 한도를 정하고**, 넘으면 Kiln을 부르지 않는다 (`agent/quota.py`).
사용량 = 내 요청에서 일어난 Kiln 호출의 **실제 토큰 수**(응답 `usage.prompt_tokens + completion_tokens`). 1:1 Pie = 보낸 사람, 그룹방 Pie mate 답장 = 그 답을 부른 메시지를 보낸 사람.
금액 계산(`settlement.calculate`)·지출 통제·결제·승인·환불·충전은 코드라 0 토큰.

| 요금제 (`id`) | 월 가격 (PIE) | 5시간 세션 한도 | 주간 한도 | 기준 |
|---|---|---|---|---|
| Free (`free`) | 0 | 25,000 | 100,000 | Pro의 1/5 |
| Pie Pro (`pro`) | 4,900 | 125,000 | 500,000 | 기준 (`AI_PRO_SESSION_TOKENS` · `AI_PRO_WEEK_TOKENS`) |
| Pie Max 5x (`max`) | 24,500 | 625,000 | 2,500,000 | Pro의 5배 가격 = 5배 한도 |
| Pie Max 20x (`max20`) | 49,000 | 2,500,000 | 10,000,000 | Max 5x의 2배 가격 = Pro의 20배 한도 |

- 세션: 첫 AI 사용부터 `AI_SESSION_HOURS`(5)시간. 끝난 뒤 다음 AI 사용 때 새 세션. 주간: 첫 사용 시각부터 `AI_WEEK_DAYS`(7)일마다 초기화.
- 한도를 넘으면: `llm._post`가 Kiln을 부르지 않고 `AI_LIMIT` → 규칙 기반 대체(0 토큰). 1:1 응답 맨 앞에 한도 안내 메시지(`limit:{plan,label,which,resetsAt,resetText}`), 그룹방은 초기화 전까지 한 번만 안내. 정산 계산·결제·승인은 그대로.
- 이미 시작한 턴은 끝까지 한다 (턴 시작 때 한도 안이면 그 턴의 호출은 허용 — 답 도중에 끊지 않음).
- **분쟁 조사(`dispute.*`)는 한도 밖** — 증거·분쟁 도구가 요금제 때문에 막히지 않게.
- 요금제 변경: 높은 요금제는 **바로 결제·바로 적용**(새 30일 주기, 남은 기간 환불 없음) · 낮은 요금제·Free는 **다음 결제일부터**(결제 없음, `nextPlan`) · 해지하면 결제일까지 이용 후 Free (`cancelAt`) · 같은 요금제를 다시 고르면 예약 취소.
- 갱신: 모의 체인은 결제일에 Pie Pay 가용 잔액에서 자동 갱신, 실제 체인은 지갑 서명이 필요해 Free로 바뀌고 알림(다시 구독).

| 메서드 | 경로 | 요청 | 응답 `data` |
|---|---|---|---|
| GET | `/api/ai/usage` | — | `{items[], tokens, total(=tokens), inTok, outTok, calls, energyWh, quota, sub, plans[], cycleDays, measured, model, energy(가정), paid(예전 방식 기록), unpaid:0}` |
| GET | `/api/ai/sub` | — | `{plans[], cycleDays, sub, quota, items[]}` |
| POST | `/api/ai/subscribe` | `{plan, tx_hash?}` — 모의 체인은 서버가 transfer, 실제 체인은 MetaMask `PieToken.transfer(feeWallet)` 후 `tx_hash` | `{sub, usage, wallet}` |
| POST | `/api/ai/sub/cancel` | `{}` | `{sub, usage, wallet}` (해지 예약) |
| POST | `/api/ai/pay` | — | **410 `BILLING_CHANGED`** (쓴 만큼 송금하는 방식은 없어짐) |

- `quota`: `{plan, label, blocked, which:'session'|'week'|null, resetsAt, resetText, session:{start,used,limit,left,pct,resetsAt}, week:{…}, sessionHours, weekDays}`
- `plans[]`: `{id, label, price, desc, mult, sessionLimit, weekLimit}` · `sub`: `{plan, label, price, cycleStart, renewsAt, cancelAt, nextPlan, nextLabel, startedAt} | null`
- `items[]`: `{id, at(ms), ai, stage, tag, inTok, outTok, where, title, ctx, note, model, latencyMs, flow, counted(한도 포함), plan, energyWh, decision?(Kiln 응답 → 행동), limited?(한도로 규칙 답), amount?, txHash?}`
- 에러: `MEMBER_WALLET_MISSING`(409) · `ALREADY_SUBSCRIBED`(409) · `INSUFFICIENT_BALANCE`(409, `details.available`) · `TX_REQUIRED`(400) · `TX_NOT_VERIFIED`(409) · `ALREADY_RECORDED`(409) · `NOT_FOUND`(404, Free에서 해지) · `BILLING_CHANGED`(410)

### Kiln 사용 보고서 (심사 제출용 · 로그인 불필요 · 개인정보 없음)

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/api/usage?flow=` | `{stages[], phases[], runs[], savings, energy, decisions, plans[], model, endpoint, live, …예전 필드(llm_calls, total_tokens, energy_wh_upper_bound, assumptions)}` |
| GET | `/api/usage/report.md?flow=` | README용 마크다운 6절: 단계별 토큰 · 구간별 합계 · 실행(정산)별 조건·결과·tx 해시·단계 순서 · 추론 절감 · 에너지 근거 · 요금제 |
| GET | `/api/usage/calls.csv?flow=` | Kiln 호출 한 줄 = 한 행 (구간·단계·처리·토큰·지연·에너지·한도 포함·요금제·채널·응답 반영). 이메일·대화 제목 없음 |

- 실행 = 정산 1건. 그 정산의 흐름(`sid`)과, 등록 직전까지 방(`group_id`)에서 일어난 해석·대화를 묶는다 → 조건을 바꾼 두 실행(예: 총 한도 2만원 → 지출 통제 중단 + Blocked tx)을 한 표로 비교.
- `usage.jsonl` 기록마다 `energy_wh`(= NPU W × 카드 수 × 지연초 / 3600, 상한) · `plan` · `counted`가 붙고, Kiln 응답 뒤 `mode:"decision"` 0토큰 기록이 “응답 → 도구 호출 / 규칙 JSON → 코드 계산 / 판정 → 환불 tx”를 남긴다.

**방 나가기**: 그룹 목록 카드의 ‘나가기’ 버튼은 `정산 완료` 방에만 보이고 → `POST /api/groups/{gid}/leave` (기존과 같음, 진행 중 정산이 있으면 `ALREADY_SETTLING` 409). 정산 끝난 방은 목록 맨 아래로 정렬.

## 1-5. 베타 — 기능 예시(미션) · 대화 제공 동의 · 답 평가 · 버전 비교 (`agent/beta.py`)

(예전 1-4b '혼합 구독'은 1-4절 요금제로 통합됨)

베타에서 모으는 데이터는 세 가지다: ① 학습 데이터(동의한 사람의 대화, 비식별) ② 토큰 효율(베타 ↔ 정식 버전 비교, 텍스트 없음) ③ 심사 기준 실행 수.
`APP_VERSION`(기본 `beta-1`)이 `beta`로 시작하면 베타가 켜진다(`BETA_ENABLED`로 덮어쓰기).

| 메서드 | 경로 | 요청 | 응답 `data` |
|---|---|---|---|
| GET | `/api/beta` | — | `{enabled, version, consent: true|false|null, done, total, categories[], reasons[], scenarios[{id, cat, where:'chat'|'group'|'action', title, text, follow?, desc, bench, done}]}` |
| POST | `/api/beta/consent` | `{agree}` | 위와 같음. `agree:false`면 그 사람의 저장된 대화·의견을 지운다 |
| POST | `/api/beta/feedback` | `{turn, rating:'up'|'down', reason?, note?}` | `{ok, turn, rating}` — `reason`은 `reasons[]` 중 하나, `note`(자유 의견)는 동의한 사람만 저장 |
| GET | `/api/beta/report` · `/api/beta/report.md` | — | 공개 요약(대화 글 없음): 버전별 합계, 시나리오 × 버전별 턴당 토큰·호출·지연·Wh·대체 비율·👍/👎, 심사 기준 실행 수, 참여 현황 |
| GET | `/api/beta/export.jsonl?kind=train|eval|raw` | 관리자(`BETA_ADMIN_EMAILS` 로그인) 또는 `?key=BETA_EXPORT_KEY` | train: 👎 아닌 턴 → examples.jsonl 형식 후보 · eval: 👎 턴 → pie_eval.jsonl 형식 후보(must 비어 있음) · raw: 전부 |

- `POST /api/chat`에 `{scenario?, edited?}`, `POST /api/groups/{gid}/messages` 본문에 `{scenario?, edited?}`를 함께 보내면 그 턴이 미션으로 기록된다. `edited`는 예시 문장을 고쳐 보냈는지 — **버전 비교는 `edited:false`(그대로 보낸) 턴끼리** 한다.
- 응답: `/api/chat`은 `beta:{turn, scenario, tokens, calls}`와 메시지마다 `turn`, 그룹 Pie mate 답은 메시지에 `turn` (👍/👎를 보낼 id).
- `usage.jsonl` 기록마다 `version` · `turn` · `scenario` · `edited`가 붙는다 → 같은 시나리오의 턴당 토큰을 버전별로 비교.
- 저장(동의한 사람만, `data/beta_dialogs.jsonl`): 가입자 실명·짧은 이름·방 멤버 이름은 한 사람당 같은 가명으로, 이메일·전화번호·지갑 주소·10자리 넘는 번호는 `[이메일]`·`[전화번호]`·`[지갑]`·`[번호]`로 바꾼다. 가입하지 않은 사람 이름은 알 수 없어 남을 수 있으니 내보낸 뒤 사람이 검토한다. 사용자 id는 `BETA_SALT`로 되돌릴 수 없게 바꾼 값.
- 미션 완료: 미션으로 보낸 턴(1:1·그룹), S07은 이의제기를 제출하면 완료.
- `BETA_PLAN=pro`면 베타 동안 구독 없는 사용자도 Pro 한도 (`quota.beta:true`, 라벨 '(베타 무료)') — 한도 때문에 베타 데이터가 끊기지 않게.

## 1-5. 정산 캘린더 (실제 날짜 · KST)

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/api/calendar` | | `{today:'YYYY-MM-DD', tz:'Asia/Seoul (KST)', events:[{date, ts, sid, groupId, name, total, myShare, payer, status, purchase, paidDate}]}` |

- **날짜는 서버 시계 기준 한국(KST)** — 기기 시계가 틀려도 캘린더는 실제 연·월·일. 앱은 `today`로 이번 달을 연다
- `events` = 내가 참여한 정산 전부(최근 500건), `date` = 정산 등록 날짜 · `paidDate` = 지급 완료 날짜(없으면 null)
- 정산 탭 캘린더: 날짜 칸에 상태색 점(완료 초록 · 진행 주황 · 환불 회색 · 중단 빨강, 최대 3개) → 날짜를 누르면 그날 정산 목록(이름·내 몫·상태) → 누르면 방(나간 방은 인증서)으로 이동
- 조회 전용 · AI 미사용 (0 tokens)

## 2. 정산 코어 (1순위)

| 메서드 | 경로 | 역할 | 토큰 |
|---|---|---|---|
| POST | `/api/settlement/analyze` | Stage1 자연어→규칙 JSON (+Stage2 계산 결과 포함) | `settlement.analyze` |
| POST | `/api/settlement/calculate` | Stage2 규칙 JSON → 금액 (코드 전용) | **0 (code-only)** |
| POST | `/api/settlement/explain` | Stage3 결과 설명 | `settlement.explain` |
| POST | `/api/settle/calculate` | 그룹 채팅용: Stage1→2→3 한 번에 | 위 합계 |
| POST | `/api/settlement/request` | 지출 통제 검사 → 에이전트가 체인 등록 (위반 시 `blocked` + `Blocked` tx) | 0 |
| POST | `/api/settlement/approve` | `{settlement_id, name, tx_hash?}` MetaMask 예치 후 확정 (mock은 서버가 예치) | 0 |
| POST | `/api/settlement/offline-payment` | `{settlement_id, participant, confirmer(결제자)}` 현금 결제 기록 | 0 |
| POST | `/api/settlement/cancel` | `{settlement_id, name(결제자)}` 전원 예치 전(open) 취소 → 컨트랙트 `blockSettlement(reason 9)`가 이미 예치한 사람에게 즉시 환불 | 0 |
| POST | `/api/settlement/{id}/sync` | `{tx_hash?}` 체인 재조회 (기간 끝났으면 자동 지급) | 0 |
| GET | `/api/settlement/{id}` · `/api/settlements?member=진주` | 단건 / 내 정산 목록 (폰이 4초마다 폴링) | 0 |

**analyze 요청/응답**
```json
{ "text": "진주는 5천원 적게 내고 나머지 세 명이 나눠줘", "members": ["진주","진우","민재","지현"],
  "total": 38900, "payer": "진주", "subject": "삼겹살 1.2kg 공동구매", "history": ["이전 조건 문장"], "flow": "g123" }
→ { "status": "ok", "rule": {"adjustments":[{"name":"진주","kind":"less","value":5000}], "per_person_cap":null, "total_cap":null},
    "total": 38900, "payer": "진주", "members": [...], "shares": [["진주",5975],["진우",10975],...],
    "ruleText": "...", "purpose": "삼겹살 1.2kg 공동구매 분담금(주문자 5,000원 감면)", "warnings": [], "meta": "..." }
→ { "status": "need_info", "question": "‘조금 더’가 정확히 얼마인가요? ..." }   // 모호하면 되묻기
→ { "status": "refused", "code": "PROHIBITED_PURPOSE", "question": "불법 자금(...)과 관련된 돈은 정산을 도와드릴 수 없어요..." }  // 불법 목적 (코드 판정, 토큰 0)
// 금액: '100억', '1억 5천만원', '3천만원' 인식. '100억의 15%'처럼 비율로 말하면 rule.total_note에 근거를 남기고 총액은 코드가 계산
```
조건이 대화 중에 바뀌면 **같은 analyze를 최신 문장 + history로 다시 호출** (다턴). Stage2 로직은 고정.

**request 요청**
```json
{ "group_name": "삼겹살 1.2kg 공동구매", "group_id": "g123", "members": ["진주","진우","민재","지현"],
  "shares": [["진주",5975],["진우",10975],["민재",10975],["지현",10975]], "total": 38900, "payer": "진주",
  "rule_text": "...", "purpose": "...", "per_person_cap": null, "total_cap": null, "merchant": "Share Pie 공동구매", "mode": "EQUAL",
  "allowed_merchants": ["쿠팡"] }   // 선택: 사용자가 "쿠팡에서만"처럼 말한 경우 이 목록으로 가맹점 검사
```
지출 통제(코드): 합계=총액 · 1인 한도 · 총 한도 · 허용 가맹점 · **체인에서 읽은 가용 잔액**
- 결제자 몫은 0원 가능 ("진주 빼고 둘이 나눠") → 체인 멤버에서 빠지고 받는 사람으로만 기록
- `merchant` 생략 시 `Share Pie 공동구매`로 검사. 짧은 영문 가맹점(CU·SSG)은 단어 단위로만 일치
- **정산 시작 대기**: `/api/settlement/request`에 `group_id`가 있고 지갑 미연결·PIE 부족 멤버가 있으면 체인에 올리지 않고 `{status:'waiting', noWallet:[], short:[], message}` 반환 + 방에 보관(`pendingPropose`) · 안내 메시지 · 해당 멤버 알림. 그 멤버가 **지갑 연결(`/api/members/register`)·충전(`/api/wallet/charge`)하는 순간 서버가 자동으로 정산을 시작**하고 방에 알림. 방 조회에 `pendingPropose: {noWallet, short} | null`. 단 **한도·허용 판매처 위반은 충전으로 안 풀리므로 대기하지 않고** 바로 `blocked`(또는 `POLICY_BLOCKED`)
- 체인에 올라가는 목적·이의 사유는 코드가 이름·전화번호·이메일을 지운 뒤 기록

## 2-1. 분담표 승인 (정산 대상 전원 동의 → 온체인 정산)

확인 카드의 **‘확인 · 승인 요청’은 바로 체인에 올리지 않는다.** 정산 대상(내 몫이 1원 이상인 사람 + 받는 사람) **전원이 각자 승인**해야 서버가 `/api/settlement/request`와 같은 처리(`propose_request`: 지출 통제 검사 · 준비 안 된 멤버 보관)를 실행한다. 승인은 코드만 사용(0 tokens, 로그 `settlement.approve_split`).

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| POST | `/api/groups/{gid}/split/start` | `/api/settlement/request`와 같은 본문 | `{room, rec}` 요청한 사람이 대상이면 그 사람은 승인한 것으로 셈. 대상이 요청자 한 명뿐이면 바로 시작(`rec`) |
| POST | `/api/groups/{gid}/split/approve` | `{split_id?}` | `{room, rec}` 내 승인. 마지막 승인이면 `rec` = 정산 기록(또는 `{status:'waiting',…}`) · 대상 아니면 `403 FORBIDDEN` · 끝난 요청이면 `404` |
| POST | `/api/groups/{gid}/split/reject` | `{reason}` | 동의 안 함 → 요청 취소·방 기록·요청자 알림. 요청자가 `reason:'요청 취소'`면 취소 |

- 방 조회에 `splitApproval: {id, by, at, targets[], approved[], total, shares[[이름,금액]], payer, mid} | null`
- 방 메시지 `kind:'splitReq'` = 승인 카드 `{from, total, shares, payer, targets, approved, splitId, resolved, outcome: started|rejected|superseded|cancelled|failed, outcomeBy}`
- 알림: 대상에게 `cat:'승인 요청'`(분담표) · 온체인 시작 후 결제 요청은 `cat:'결제 요청'`
- 새 분담표로 다시 요청하면 이전 요청은 `superseded` · 대기 중 대상이 방을 나가면 `cancelled`
- 방 상태 문구: 분담표 승인 중 `승인 대기` → 온체인 시작 후 `결제 대기` → `결제 진행` …

## 2-2. AI 구매 대행 (가상 결제 계좌 → 가맹점 자동 결제)

상품(공동구매·인터넷 검색 상품·배달 조합)에서 만든 정산방은 **구매 대행**으로 등록돼요. 결제자가 따로 사지 않아요.

```
settlement/request {…, purchase:true, merchant:"쿠팡", product:{name,url,units}}
  → 지출 통제(합계·한도·허용 가맹점·잔액) 통과 → createPurchase (payee = 가맹점 데모 지갑, 가상계좌 SP-xxxx-xxxx-xxxx)
각 참여자(결제자 포함): MetaMask ① PIE.approve(ledger, 기존 한도+내 몫) ② approvePurchase(id)   ← 돈은 아직 안 움직임
마지막 승인이 들어오면 서버(AI 에이전트)가 즉시: 결제 직전 지출 통제 재검사 → executePurchase(id, orderRef)
  = 각자 지갑에서 정확히 자기 몫만 transferFrom → 가상 계좌 → 가맹점 지갑으로 결제 (한 트랜잭션: 전부 성공 or 전부 취소)
  재검사에서 걸리면 결제 없이 blockSettlement (Blocked 기록)
```
- `public(settlement).purchase` = `{merchant, merchantWallet, va, status: approving|paid|blocked, orderNo, orderRef, txHash, url, approved, needed, product}`
- 멤버 상태 `approved` = 인출 승인함(돈은 그대로), 결제 후 `locked`(인출됨)
- 전원 승인 전 결제자 취소: `/api/settlement/cancel` (인출된 돈 없음)
- 가맹점 지갑은 테스트넷 데모용으로 서버가 가맹점별 자동 생성 (`db.json → merchants`). 실제 쇼핑몰 주문은 하지 않아요 (테스트넷 전용 규칙)
- 이벤트: `PurchaseApproved · Withdrawn · Paid · PurchaseExecuted(id, merchant, total, orderRef)`

## 3. Dispute 모듈 (2순위)

| 메서드 | 경로 | 요청 | 설명 |
|---|---|---|---|
| POST | `/api/dispute/raise` | `{settlement_id, by, reason}` | `locked`(지급 전)일 때만. 체인 `DisputeRaised` |
| POST | `/api/dispute/investigate` | `{settlement_id}` | 코드 대조(0토큰) + AI 3분류 판정 → `{verdict, verdict_ko, refund, explanation, guard, findings[]}` |
| POST | `/api/dispute/resolve` | `{settlement_id}` | 판정 실행: GENUINE_ERROR면 `refundParticipant` 후 `resolveDispute(2)` |

판정은 `NORMAL_APPROVAL` / `GENUINE_ERROR` / `BAD_FAITH_DISPUTE` 3개뿐 (CLAUDE.md 7번). `guard`는 AI 판정이 기록과 모순될 때 코드가 보정한 이유.
Pie 채팅에서는 `context: {settlement_id, dispute: "start"}` → 사유 질문 → 다음 메시지로 raise→investigate→resolve 자동 실행.
context 없이 채팅 문장("정산 금액이 잘못됐어")으로 시작하면 **어느 정산인지 먼저 확인**(`needs_info`) 후 실행 (되돌릴 수 없는 체인 기록이라서).
판정 실행 중 실패해 `disputed`에 멈춘 정산은 investigate → resolve 를 다시 부르면 이어서 처리 (이미 판정·실행된 건 다시 판정하지 않음).
컨트랙트: 이의제기는 잠금 시점에 정해진 지급 시각(`releaseAfterOf`) 전까지만 가능.

## 4. Shopping 모듈 (3순위)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/shopping/search` | `{query, history}` → 조건 해석 → **1인당 비용(배송·배달비 포함) 계산 후** 후보 비교. 목록에 없으면 `status:"no_match"` + 예산 조언 |
| | (인터넷 검색) | 네이버/Tavily/쿠팡 키가 있으면 `status:"ok_web"`: AI가 검색어 2~3개 계획 → 코드가 여러 사이트 병렬 검색·관련성 필터·예산 내 수량·개당 가격 계산 → **최저가/가성비/대량/프리미엄** 등 성격이 다른 3~5개 → AI 설명. 가격은 소스 원본(네이버 lprice, 페이지 schema.org)만 사용, 본문 가격은 `verified:false` |
| | (배달 조합) | 예시 메뉴표 없음. Pie 채팅의 AI 비서가 실제 브랜드 메뉴 판매가를 검색(`menu_price_search`)해 조합하고 코드가 인분·배달비·예산 검증(`check_delivery_combos`) → 카드 `isCombo:true`, 가격 출처 표시. AI·웹 검색을 못 쓰면 `status:"no_match"`로 솔직하게 안내 (가격을 지어내지 않음) |
| (삭제) | `/api/shopping/home` · `/api/shopping/{id}/join` | 예시 상품 카탈로그를 없애면서 제거 → 4-2 동네 공동구매로 대체 |


## 4-2. 동네 공동구매 모집 (GPS 근처 · 예시 상품 없음)

공동구매 탭은 **실제 사용자가 올린 모집글만** 보여 줘요 (예시 상품·가짜 참여 인원 삭제). 모집글 = 그룹 채팅방 + 모집 위치·인원.

| 메서드 | 경로 | 요청 | 설명 |
|---|---|---|---|
| GET | `/api/groupbuy/nearby?lat&lng&radius=1\|3\|5\|10` | | 보는 사람 위치(저장 안 함) 기준 반경 안의 모집글, 가까운 순. 좌표가 없으면 프로필 동네와 같은 동만. → `{items[], mode: gps\|dong\|none, radiusKm, radii, dong}` |
| POST | `/api/groupbuy/create` | `{group_id, cap(2~30, 나 포함), lat?, lng?, deadline_hours?(기본 48), note?}` | 그룹을 만든 사람만. 위치가 없고 프로필 동네도 없으면 `NEED_LOCATION` |
| POST | `/api/groupbuy/{gid}/join` | `{lat?, lng?}` | 모집 위치에서 10km 이내(또는 같은 동)만 참여 가능 (`TOO_FAR`·`NEED_LOCATION`). 참여하면 그 그룹 채팅방 멤버가 됨 (`members`·분담표 칸 추가, `v` 증가) |
| POST | `/api/groupbuy/{gid}/leave` | | 정산 시작 전, 모집자가 아닌 사람만 |
| POST | `/api/groupbuy/{gid}/close` | | 모집자가 마감 |

- 모집글 항목: `{id(=그룹 id), name, host, dong, distanceM(100m 단위), distanceLabel('약 400m'·'바로 근처'·'같은 동네'), joined, cap, total, perPerson(다 모였을 때 1인, 코드 계산), status: open|full|closed, deadlineLabel, note, product, isMine, isMember}`
- 좌표 공개 없음: 모집 위치는 약 100m 단위로만 저장하고, 다른 사람에게는 동 이름과 거리만 보냄
- 자동 마감: 인원이 다 차면 `full`(참여자에게만 보임) · 기간이 지나면 / 그룹이 정산을 시작(온체인 등록)하면 `closed`
- 그룹 조회(`/api/groups`) 응답에 `listing: {cap, status, dong, deadlineLabel} | null`
- 불법 목적(자금세탁 등) 모집은 `PROHIBITED_PURPOSE`

## 5. Pie 채팅 · 기록

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/chat` | `{message, chat_id, user, history[{role,text,intent,needs_info}], context}` → 키가 있으면 **대화형 에이전트**(`PIE_CHAT=agent`)가 도구를 골라 답함 (정산·이의제기 확정 신호만 전용 흐름). 응답 `intent`: `shop`(후보 카드 포함) · `ask` · `settle` · `dispute`. 키가 없거나 에이전트 실패 시 규칙 기반 흐름으로 자동 대체. `ask`는 대화 맥락으로 답하고 필요하면 웹 검색 후 출처와 함께 답함. `messages[]`는 프론트 msg 형식 그대로 (+`meta`, `compare`, `compareData`, `split`, `settle`, `verdict`) |
| GET | `/api/usage` · `/api/usage/report.md` | 단계별 토큰·지연·에너지 상한 (CLAUDE.md 4번 태그 그대로) |
| GET | `/api/config` · `/api/health` | 체인 주소·ABI·모델 / 상태 |
| POST | `/api/dev/mock-lock` · `/api/dev/fast-forward` · `/api/dev/tamper` | mock 전용: MetaMask 없이 예치 / 이의제기 기간 즉시 종료 / 불일치 만들기 |

## 6. 컨트랙트 함수 (CLAUDE.md 5번 ↔ 실제 이름)

| CLAUDE.md | Solidity | 누가 서명 |
|---|---|---|
| charge_token | `PieToken.chargeToken(to, amount)` | 에이전트 |
| lock_for_settlement | `ShareLedger.lockForSettlement(id)` (잔액 부족 시 revert) | **참여자 MetaMask** |
| release_to_recipient | `releaseToRecipient(id)` (이의제기 기간 후, 누구나) | 에이전트(자동) |
| refund_participant | `refundParticipant(id, participant)` | 에이전트 |
| raise_dispute | `raiseDispute(id, by, reason)` | 참여자 또는 에이전트 대행 |
| resolve_dispute | `resolveDispute(id, verdict 1·2·3, note)` | 에이전트 |
| mark_offline_payment | `markOfflinePayment(id, participant)` | 에이전트 (결제자 확인 후) |
| (추가) 등록 / 중단 | `createSettlement(...)` / `blockSettlement(id, member, reasonCode, note)` | 에이전트 |
| (추가) AI 구매 대행 | `createPurchase(...)` · `approvePurchase(id)` · `executePurchase(id, orderRef)` | 에이전트 · **참여자 MetaMask** · 에이전트 |

이벤트: `SettlementCreated · ShareAssigned · Locked · OfflinePaid · FullyLocked · Paid(from,to,amount,purpose) · Blocked · Refunded · DisputeRaised · DisputeResolved`
사용자별 조회: `committedOf`(사용 예정) · `escrowOf`(예치 중) · `spentOf`(실사용) + `PIE.balanceOf`(잔액)
