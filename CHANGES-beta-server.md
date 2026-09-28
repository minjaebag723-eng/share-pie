# 베타 서버 병합 + 실제 체인 동시 접속 수정

기준: 블록체인 담당 완성본 `share-pie-ai-v35-final` · 이 문서는 블록체인 담당이 무엇이 바뀌었는지 확인하는 용도예요.

## 1. 합친 것 (베타 서버 준비물)
- 새 폴더 `deploy/` — 베타 서버 진입점(`asgi.py`), 서버 한 번에 세팅(`setup_server.sh`, AWS Lightsail), 도커·Caddy(HTTPS), 데이터 묶기, 부하 테스트, 체인 점검, 안내서(`deploy/README.md`)
- 베타 데이터 폴더 분리(`agent/beta.py`) · db.json 저장 모아 하기(`agent/store.py`) · 사용량 메모리 캐시(`agent/usage.py`) · Kiln 동시 호출 상한(`agent/llm.py`)
- `run-public.cmd`가 `deploy.asgi:app`으로 켜요 (터널 베타도 같은 설정 · 베타 데이터는 `~/.sharepie-data/beta/`)
- `.env.example`: 실제 `BETA_EXPORT_KEY`·`BETA_SALT` 값을 비움 (GitHub에 올라가는 파일이라서 — 실제 값은 `.env`에만)

## 2. 블록체인 쪽 파일에서 바꾼 것
스모크 테스트가 찾는 표식(`def _gas_price` · `def send_gas` · `PURPOSE_MAX` · `AMOUNT_SUSPECT` · `REFUND_GUARD`)은 그대로예요.

| 파일 | 바꾼 것 | 끄는 법 |
|---|---|---|
| `agent/chain.py` | `_broadcast()` 추가 — nonce 배정·서명·전송만 `_send_lock` 안, 영수증 대기는 밖. `_send`·`send_gas`가 이걸 씀. nonce가 어긋나면(증거 스크립트가 같은 지갑 사용 등) 체인에서 다시 읽고 재시도 | `CHAIN_TX_PIPELINE=0` |
| `agent/chain.py` | `_gas_price()` 끝에 상한 | `CHAIN_MAX_GAS_GWEI=0` (기본 0) |
| `agent/service.py` | `register_member`의 가스 지급을 `_gas_drip_async`(뒤에서)로. 같은 지갑 중복 지급 막음. 결과 기록·로그는 예전과 같음 | `GAS_DRIP_ASYNC=0` |
| `agent/service.py` | `charge` — `@_locked` 대신 확인·쿨다운 예약만 잠금 안, 체인 확정은 밖, 실패하면 예약 취소 | (없음) |
| `agent/service.py` | 체인 감시 `chain_watch_start/_watch_loop/_watch_one` + `_refresh(rec, on=, release_tx=)` — `list_for`는 실제 체인이면 저장된 상태만, 감시가 5초마다 읽고 지급(release)도 잠금 밖에서 | `CHAIN_WATCH=0` |
| `agent/config.py` | 위 설정값 · `agent/store.py` `set_charge(name, at=None)` | — |

`tools/apply_blockchain_patches.py`를 이 버전에 다시 돌리면 `_send` 쪽 앵커가 달라 "수동 확인"이 나올 수 있어요 — 패치는 이미 들어 있어요.

## 3. 측정 (로컬 체인 · 같은 컨트랙트 · 블록 12초 · 체인 읽기 150ms)
| 상황 | 완성본 그대로 | 지금 |
|---|---|---|
| 새 사용자 8명 지갑 연결·충전 중 다른 20명 | 지갑 연결 10~112초 · 최대 59초 멈춤 · 40%가 1초 넘게 | 지갑 연결 0초 · 최대 0.02초 |
| 정산 있는 24명 4초 새로고침 | 중앙값 33.6초 · 다른 사람 요청 중앙값 24.8초 | 0초 |
| 정산 만들기 1건 | 블록 확정 동안 모두 대기 | 그대로 (최대 약 9초) |

## 4. 남은 한계
- 전역 잠금 안에서 체인 확정을 기다리는 것: 정산 만들기(`propose`) · 이의제기 판정·환불 · 지출 통제 중단 · 공동구매 실행. 드물지만 그때마다 다른 사람 요청이 블록 1개(약 9~12초)만큼 기다려요.
  고치려면 정산 만들기·그룹 분담 승인 흐름을 '처리 중' 상태로 나눠야 해서(중복 생성 방지 포함) 이번엔 손대지 않았어요.
- 멤버 예치 확인(`approve` → `sync`)은 잠금 안에서 체인을 두 번 읽어요 (한 번에 0.3~0.5초).

## 5. 확인 방법
- 로컬: `python tests/chain_local_check.py` (anvil 또는 `npx hardhat node` + `npm run compile`) → "✓ 실제 체인 점검 통과"
- 블록체인 담당 PC: 서버를 켜고 `cd hardhat && npm run smoke` (실제 Kiln·참여자 지갑 파일 필요) — 이 환경에선 못 돌렸어요
- 모의 체인 회귀: 백엔드 테스트 11종 통과 · 폰 4대 화면 테스트 175 통과 / 2 실패(예전부터 있던 쇼핑 2건) · 100명 60초 부하 0건 실패

## 6. 보안
- 받은 완성본 zip에 `.env`(Kiln 키 · 검색 키 · 에이전트 지갑 비밀키)가 들어 있었어요. 이 병합본에는 없어요.
  zip을 다른 곳에 올렸거나 공유했다면: 새 에이전트 지갑 → `setAgent`·`setMinter`로 권한 이전 · 옛 지갑 권한 해제 · Kiln 키 교체.
