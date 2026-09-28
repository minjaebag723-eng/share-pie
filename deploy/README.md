# 베타 서버 — 100명 동시 접속 · 데이터 수집

베타를 굴리는 이유는 **데이터**예요. 그래서 이 서버는 두 가지를 먼저 챙겨요.
1. 100명이 동시에 써도 느려지지 않을 것 (아래 부하 테스트로 확인)
2. 모은 데이터가 **한 폴더(`beta-data/`)** 에만 쌓이고, 그 폴더만 따로 보낼 수 있을 것

## 1. 데이터는 어디에 쌓이나요

| 폴더 | 들어 있는 것 | 다루는 법 |
|---|---|---|
| `beta-data/` | 베타 데이터 (비식별): 대화·평가·Kiln 토큰 기록·참여·정산 요약·보고서 | **이 폴더만 보내면 돼요** |
| `data/` | 운영 데이터: 계정·비밀번호 해시·정산 원본·Kiln 원본 기록 | 서버에만 두고 **백업만** |

- 서버를 켜면 로그 첫 줄에 위치가 떠요: `[베타 데이터] 저장 위치: /app/beta-data (대화 N줄 …) ← 이 폴더만 보내면 돼요`
- 폴더 안의 `README.md`가 파일·필드를 설명하고, `manifest.json`에 파일별 줄 수·크기·sha256이 있어요 (받은 쪽에서 빠짐없이 왔는지 확인).
- `report.md`는 10분마다 새로 써져요 (버전 비교 · 미션별 토큰 · 심사 기준 실행 수 · 참여). 발표 자료로 바로 써요.
- 이름은 가명, 사람은 되돌릴 수 없는 id, 이메일·전화번호·지갑 주소·계좌번호·비밀번호는 없어요. 대화 글은 '대화 제공'에 동의한 사람 것만.

### 보내는 법 (셋 중 편한 것)
1. **링크로 내려받기** (서버 접속 없이): 브라우저에서 `https://<주소>/api/beta/bundle.zip?key=<BETA_EXPORT_KEY>`
   - 폴더 위치·용량만 보기: `https://<주소>/api/beta/storage?key=<BETA_EXPORT_KEY>`
2. **서버에서 zip 만들기**: `bash deploy/beta.sh bundle` → `beta-bundles/sharepie-beta-data_beta-1_<시각>.zip`
3. **드라이브로 바로**: rclone으로 구글 드라이브를 한 번 연결(`rclone config`)해 두고 `bash deploy/beta.sh send gdrive:SharePie/beta`
   - 매시간 자동: `crontab -e` → `0 * * * * cd /opt/share-pie && bash deploy/beta.sh send gdrive:SharePie/beta`
   - 폴더를 그대로 복사해도 돼요: `scp -r 서버:/opt/share-pie/beta-data ./받은데이터`

## 2. 서버 만들기 — AWS Lightsail 서울 (추천)

부하 테스트 기준 2코어 · 4GB면 100명 동시 접속에 넉넉해요. 콘솔이 단순하고 월 고정 요금이라 Lightsail을 추천해요.
(요금·플랜은 바뀔 수 있으니 만들 때 콘솔에서 확인. 다른 클라우드도 Ubuntu 2코어·4GB면 똑같이 돼요)

1. https://lightsail.aws.amazon.com → **인스턴스 생성** → 리전 **서울** · Linux/Unix · OS 전용 **Ubuntu 24.04 LTS** · 플랜 **4GB RAM · 2 vCPU**
2. 인스턴스의 **네트워킹** 탭
   - **고정 IP** 만들어 붙이기 (안 하면 껐다 켤 때 IP가 바뀌어 주소·인증서가 깨져요)
   - IPv4 방화벽에 **HTTPS(443)** 추가 (SSH 22 · HTTP 80은 기본으로 열려 있음)
3. **SSH를 사용하여 연결**(브라우저 터미널) → 코드 올리기
   ```bash
   sudo apt update && sudo apt install -y git
   git clone <팀 저장소 주소> share-pie && cd share-pie      # 비공개 저장소면 GitHub 토큰 필요 · 또는 완성본 zip을 scp로 올려 unzip
   ```
4. 한 번에 세팅: `sudo bash deploy/setup_server.sh`
   - 질문 3개: 접속 주소(도메인이 없으면 Enter → `고정IP.sslip.io`로 HTTPS 자동) · Kiln 키 · 관리자 이메일
   - 도커 설치 · 서울 시간 · 스왑 2GB · `.env`(베타 키 자동 생성) · 매일 04시 백업 · 매시간 데이터 zip · 서버 켜기까지 해요
5. 폰에서 `https://<주소>` 접속 → 가입 → 홈에 '베타 미션' 카드가 보이면 끝

## 3. 운영 명령 (서버의 코드 폴더에서)

| 명령 | 하는 일 |
|---|---|
| `bash deploy/beta.sh status` | 켜져 있는지 · 서버 응답 |
| `bash deploy/beta.sh logs` | 로그 (Ctrl+C로 나가기) |
| `bash deploy/beta.sh data` | 베타 데이터 폴더 위치 · 파일 · 용량 |
| `bash deploy/beta.sh bundle` | 베타 데이터 zip → `beta-bundles/` (최근 24개 유지) |
| `bash deploy/beta.sh chain` | 실제 체인일 때: 에이전트 지갑 잔액 · 가스비 · 정산 몇 건 분량 남았나 |
| `bash deploy/beta.sh backup` | 운영+베타 데이터 전체 백업 → `backups/` |
| `bash deploy/beta.sh up` | 코드를 새 버전으로 바꾼 뒤 다시 빌드해서 켜기 (데이터는 그대로) |

## 4. 켜기 — 도커 없이

- **Windows PC**: `.env`를 채우고 `deploy\run_beta.bat` 더블클릭 → 밖에서 접속하려면 다른 창에서
  `cloudflared tunnel --url http://localhost:8000` (https://…trycloudflare.com 주소가 나와요. 켤 때마다 바뀌니 고정하려면 Cloudflare 도메인 + named tunnel).
  PC가 꺼지면 베타도 멈추니 짧은 테스트용으로만.
- **Linux 직접**: `deploy/sharepie-beta.service`(systemd) + Caddy 설치. 파일 맨 위 설명대로.
- 어느 쪽이든 실행 명령은 같아요: `python -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1`
  (**`--workers`는 꼭 1** — 계정·방 상태를 한 프로세스 메모리에 두는 구조라 여러 개로 띄우면 데이터가 갈라져요)

## 5. 100명 동시 접속 — 무엇을 바꿨고 어떻게 확인했나

| 병목 | 예전 | 지금 |
|---|---|---|
| db.json 저장 | 메시지 하나마다 파일 전체를 다시 씀 (1주 규모 27MB → 1회 337ms) | 1초 동안 모아 한 번 (113ms, 초당 최대 1회) · 종료 때 바로 저장 |
| AI 사용량 화면 | 요청마다 usage.jsonl 전체를 다시 읽음 (15만 줄 → 1,124ms) | 메모리에 두고 18ms |
| 요청 처리 | 스레드 40개 — Kiln 응답을 기다리는 사람이 40명이면 폴링까지 밀림 | 200개 |
| Kiln 동시 호출 | 제한 없음 | 24개까지 (넘으면 20초 기다리고, 그래도 없으면 규칙 기반으로 먼저 답함) |
| 화면 파일 | 파이썬이 전부 | Caddy가 직접 · API만 파이썬 |

이 설정은 `deploy.asgi`로 켤 때만 켜져요 (로컬 실행·테스트는 예전 그대로). 값은 `.env`로 바꿀 수 있어요.

**부하 테스트** (가짜 Kiln 응답 1.2~2.8초, 100명 × 90초: 4초마다 새로고침 · 20~40초마다 Pie 대화 · 30~60초마다 그룹방 메시지)

| 요청 | 건수 | 실패 | p50 | p95 |
|---|---|---|---|---|
| 새로고침(방·알림·친구·정산·사용량) | 9,796 | 0 | 2~4ms | 8~9ms |
| Pie 1:1 대화 | 272 | 0 | 2.0초 | 2.8초 |
| 그룹방 메시지(+Pie mate) | 180 | 0 | 1.3초 | 2.7초 |
| 전체 | 10,622 (초당 113) | 0 | | |

Pie 대화 시간은 거의 Kiln 응답 시간이에요. 직접 해 보기: 서버를 켠 뒤
`python deploy/loadtest.py --base https://<주소> --users 100 --duration 90 --prefix load` (테스트 계정이 생기니 베타 시작 전에 하고, 끝나면 `data/`·`beta-data/`를 비우거나 다시 설치).

## 6. 베타 시작 전 체크리스트
- [ ] `.env`: Kiln 키 · `APP_VERSION=beta-1` · `BETA_EXPORT_KEY`·`BETA_SALT`(무작위) · `BETA_ADMIN_EMAILS` · 체인 모드(8번)
- [ ] `bash deploy/beta.sh status` 가 ok · 폰에서 https 주소로 가입 → 홈에 '베타 미션' 카드가 보임
- [ ] 부하 테스트 · 연습 데이터를 지우고 시작 (`beta-data/`, `data/usage.jsonl`)
- [ ] 백업 crontab · 데이터 전송(rclone) 설정
- [ ] 베타가 끝나면 `APP_VERSION=1.0`으로 정식 버전을 같은 서버에 — `BETA_SALT`는 바꾸지 않기 (같은 사람 id로 비교)

## 7. 문제 해결
- 접속이 안 돼요 → `bash deploy/beta.sh logs` · 80/443 포트 · DNS(도메인이 서버 IP를 가리키는지)
- 'Pie를 부르는 사람이 많아요' 안내가 자주 떠요 → `KILN_MAX_CONCURRENCY`를 올리기 (팀 키 한도 안에서)
- 디스크 → `bash deploy/beta.sh data`로 용량 확인. usage 기록은 하루 수십 MB 정도라 30GB면 베타 기간 충분

## 8. 실제 체인(Sepolia)으로 베타 — 에이전트가 가스를 낼 때

모든 체인 트랜잭션이 에이전트 지갑 하나에서 나가요. 완성본을 로컬 체인(블록 12초 = Sepolia, 체인 읽기마다 150ms 지연 = 공용 RPC)에서 재고 고쳤어요.

| 상황 | 완성본 그대로 | 지금 |
|---|---|---|
| 새 사용자 8명 지갑 연결·충전 중 다른 사람 요청 | 지갑 연결 10~112초 · 최대 **59초** 멈춤 · 40%가 1초 넘게 | 지갑 연결 **0초** · 최대 0.02초 |
| 정산 있는 사람들의 4초 새로고침 (24명) | 중앙값 **33.6초** · 다른 사람 요청 중앙값 24.8초 | **0초** |
| 정산 만들기 1건 | 블록 확정 동안 모두 대기 | 그대로 — 최대 약 9초 (**남은 한계**) |

바꾼 것 — `.env`에서 0으로 끄면 예전 방식 (자세히: `CHANGES-beta-server.md`):
- `CHAIN_TX_PIPELINE=1` 에이전트 트랜잭션을 여러 건 동시에 (nonce 직접 관리 · 다른 곳이 같은 지갑을 쓰면 다시 맞춤)
- `GAS_DRIP_ASYNC=1` 새 지갑 가스 지급을 뒤에서 — 지갑 연결이 바로 끝나요
- 충전: 쿨다운을 먼저 예약하고 체인 확정은 잠금 밖에서 (두 번 눌러도 한 번, 실패하면 예약 취소)
- `CHAIN_WATCH=1` 4초 새로고침은 저장된 상태만 돌려주고, 체인 감시가 5초마다 열린 정산을 읽고 지급까지
- `CHAIN_MAX_GAS_GWEI=50` 가스 가격 상한 — 시세×2가 튀어도 지갑이 바닥나지 않게 (로컬에선 되먹임으로 6천만 gwei까지 올랐음)

가스 예산 (대략 · 실제는 `bash deploy/beta.sh chain`과 서버 경고로 확인):
- 새 지갑 가스 지급 0.002 ETH × 참가자 (멤버 예치 가스는 여기서) + 정산 1건당 에이전트 약 70만 gas(만들기+지급, 추정) + 충전 1회 4~6만 gas
- 400명 · 정산 200건이면 시세 1 gwei에서 약 1.1 ETH, 5 gwei에서 약 2.5 ETH (가격 배수 2 포함)

점검 도구:
- `python tests/chain_local_check.py` — 로컬 노드(anvil · `npx hardhat node`)에 새로 배포해 흐름(가스 지급·충전·정산·예치·자동 지급·중단)과 멈춤을 한 번에. 체인 코드를 바꾸면 베타 전에 꼭
- `python deploy/chain_bench.py status | cost` — 에이전트 잔액 · 정산 몇 건 분량 · 지금까지 쓴 실제 가스 (읽기만)
- 서버가 1분마다 에이전트 지갑을 확인해 잔액 부족 · 3시간 안에 바닥 · 막힌 트랜잭션을 로그에 경고 · 관리자 `https://<주소>/api/beta/chain?key=<BETA_EXPORT_KEY>`
