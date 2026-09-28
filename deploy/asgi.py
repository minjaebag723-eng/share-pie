"""베타 서버 진입점 — `python -m uvicorn deploy.asgi:app --host 0.0.0.0 --port 8000 --workers 1`

backend/app.py를 고치지 않고 감싸서, 100명 동시 접속용 운영 설정과 관리자용 데이터 경로만 더한다.
  - 운영 기본값: db.json 저장 모아 하기(1초) · Kiln 동시 호출 상한(24) · 베타 폴더 스냅샷(10분) — .env에 적으면 그 값이 우선
  - 요청 처리 스레드 200개 (Kiln 응답을 기다리는 사람이 많아도 폴링·화면 요청이 밀리지 않게)
  - API(JSON) 응답만 gzip 압축 — 큰 화면 파일(index.html)은 앞단 프록시(Caddy·Cloudflare)가 압축 (파이썬이 압축하면 동시 접속 때 멈칫함)
  - /healthz (도커·모니터링용)
  - 관리자: GET /api/beta/storage (데이터 폴더 위치·파일·용량) · GET /api/beta/bundle.zip (폴더를 zip으로 내려받기)
    · GET /api/beta/chain (실제 체인일 때: 에이전트 지갑 잔액 · 가스비 · 시간당 소모 · 바닥까지 남은 시간 · 막힌 트랜잭션)
    권한: ?key=BETA_EXPORT_KEY 또는 X-Beta-Key 헤더 또는 BETA_ADMIN_EMAILS 계정으로 로그인한 토큰
  - 종료할 때 모아 둔 저장을 바로 쓰고 스냅샷을 남긴다.
주의: --workers 1 (계정·방 상태를 한 프로세스 메모리에 두는 구조라 여러 프로세스로 띄우면 안 됨).
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env_file() -> None:
    """agent/config.py와 같은 규칙으로 .env를 먼저 읽는다 (그래야 아래 운영 기본값보다 .env가 우선)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env_file()
SERVER_DEFAULTS = {"STORE_SAVE_DELAY": "1", "KILN_MAX_CONCURRENCY": "24", "KILN_QUEUE_WAIT": "20", "BETA_SNAPSHOT_SEC": "600"}
for _k, _v in SERVER_DEFAULTS.items():
    if not (os.environ.get(_k) or "").strip():      # .env에 빈 값(예: STORE_SAVE_DELAY=)으로 있어도 운영 기본값을 넣는다
        os.environ[_k] = _v
THREADS = int(os.environ.get("SERVER_THREADS") or 200)

import anyio  # noqa: E402
from starlette.background import BackgroundTask  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import FileResponse, JSONResponse  # noqa: E402

from agent import beta, config, service, store  # noqa: E402
from backend.app import app as inner  # noqa: E402

STARTED = time.time()
_stop = threading.Event()

# ── 에이전트 지갑 감시 (실제 체인 모드: 에이전트가 모든 가스를 내므로 잔액이 바닥나면 체인 기능이 전부 멈춘다) ──
CHAIN_MONITOR_SEC = int(float(os.environ.get("CHAIN_MONITOR_SEC") or 60))
CHAIN_MIN_BALANCE = float(os.environ.get("CHAIN_MIN_BALANCE") or 0.05)          # 이 밑이면 경고 (ETH)
GAS_PER_SETTLEMENT = int(float(os.environ.get("CHAIN_GAS_PER_SETTLEMENT") or 1_500_000))   # 4명 정산 + 충전 4번 (v35 실측 약 1.5M)
_chain_hist: deque = deque(maxlen=720)       # (시각, 잔액)
_chain_last: dict = {"mode": "unknown"}
_chain_warned: dict = {}


def _chain_client():
    try:
        from agent import chain as chainmod
        c = chainmod.get()
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    return (c, None) if hasattr(c, "w3") and hasattr(c, "acct") else (None, "mock")


def chain_sample(c) -> dict:
    """읽기만 한다 (트랜잭션 안 보냄)."""
    w3, addr = c.w3, c.acct.address
    now = time.time()
    bal = w3.eth.get_balance(addr) / 1e18
    latest, pending = w3.eth.get_transaction_count(addr, "latest"), w3.eth.get_transaction_count(addr, "pending")
    gwei = w3.eth.gas_price / 1e9
    _chain_hist.append((now, bal))
    hist = [h for h in _chain_hist if h[0] >= now - 3660]          # 최근 1시간(+여유 1분)
    spent = sum(max(0.0, a[1] - b[1]) for a, b in zip(hist, hist[1:]))        # 충전(입금)은 빼고 줄어든 만큼만
    hours = (hist[-1][0] - hist[0][0]) / 3600 if len(hist) > 1 else 0
    per_hour = spent / hours if hours >= 0.05 else None
    per_settle = GAS_PER_SETTLEMENT * gwei / 1e9
    s = {"mode": "chain", "network": (c.info() or {}).get("network"), "agent": addr, "balanceEth": round(bal, 6),
         "gasGwei": round(gwei, 3), "pendingTx": pending - latest, "spentPerHourEth": round(per_hour, 6) if per_hour else None,
         "hoursLeft": round(bal / per_hour, 1) if per_hour else None,
         "settlementsLeft": int(bal / per_settle) if per_settle > 0 else None, "at": now}
    warn = []
    if bal < CHAIN_MIN_BALANCE:
        warn.append(f"잔액 {bal:.4f} ETH — {CHAIN_MIN_BALANCE} 아래. 테스트 ETH를 채워 주세요")
    if s["hoursLeft"] is not None and s["hoursLeft"] < 3:
        warn.append(f"지금 속도면 {s['hoursLeft']}시간 뒤 바닥")
    if s["pendingTx"] >= 3:
        warn.append(f"확정 안 된 트랜잭션 {s['pendingTx']}건 (가스비가 낮아 막혔을 수 있음)")
    s["warnings"] = warn
    _chain_last.clear()
    _chain_last.update(s)
    return s


def _chain_line(s: dict) -> str:
    left = f" · 이 가스비면 정산 약 {s['settlementsLeft']:,}건 분량" if s.get("settlementsLeft") is not None else ""
    return f"[체인] {s.get('network')} · 에이전트 {s['agent'][:10]}… · 잔액 {s['balanceEth']} ETH · 가스 {s['gasGwei']} gwei{left}"


def _chain_loop(c) -> None:
    while not _stop.wait(max(15, CHAIN_MONITOR_SEC)):
        try:
            s = chain_sample(c)
        except Exception as e:  # noqa: BLE001
            print(f"[체인] 상태를 읽지 못했어요: {e}", flush=True)
            continue
        for w in s["warnings"]:                                        # 같은 경고는 10분에 한 번만
            if time.time() - _chain_warned.get(w.split(" ")[0], 0) > 600:
                _chain_warned[w.split(" ")[0]] = time.time()
                print(f"[체인 경고] {w}  ({_chain_line(s)})", flush=True)


def _snapshot_loop() -> None:
    while not _stop.wait(max(60, config.BETA_SNAPSHOT_SEC)):
        try:
            beta.snapshot()
        except Exception as e:  # noqa: BLE001
            print(f"[beta] 스냅샷 실패: {e}", flush=True)


def _startup() -> None:
    anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
    try:
        man = beta.snapshot() if beta.enabled() else {}
    except Exception as e:  # noqa: BLE001
        man = {}
        print(f"[beta] 첫 스냅샷 실패: {e}", flush=True)
    files = man.get("files") or {}
    print(f"[베타 서버] 앱 버전 {config.APP_VERSION} · 요청 스레드 {THREADS} · Kiln 동시 상한 {config.KILN_MAX_CONCURRENCY or '없음'}"
          f" · db.json 저장 간격 {config.STORE_SAVE_DELAY:g}초", flush=True)
    print(f"[베타 데이터] 저장 위치: {config.BETA_DATA_DIR}  (대화 {(files.get('dialogs.jsonl') or {}).get('lines') or 0}줄 · "
          f"평가 {(files.get('feedback.jsonl') or {}).get('lines') or 0}줄 · Kiln 기록 {(files.get('usage.jsonl') or {}).get('lines') or 0}줄)"
          f"  ← 이 폴더만 보내면 돼요", flush=True)
    print(f"[운영 데이터] 계정·정산 원본: {config.DATA_DIR} (보내지 말 것 · 백업만)", flush=True)
    if beta.enabled() and config.BETA_SNAPSHOT_SEC > 0:
        threading.Thread(target=_snapshot_loop, name="beta-snapshot", daemon=True).start()
    c, why = _chain_client()
    if c is None:
        _chain_last.update({"mode": "mock" if why == "mock" else "error", "error": None if why == "mock" else why})
        print("[체인] 모의 체인 — 가스비 없음" if why == "mock" else f"[체인] 연결 안 됨: {why}", flush=True)
    else:
        try:
            print(_chain_line(chain_sample(c)), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[체인] 첫 상태 읽기 실패: {e}", flush=True)
        threading.Thread(target=_chain_loop, args=(c,), name="chain-monitor", daemon=True).start()
        if hasattr(service, "chain_watch_start"):     # 아무도 새로고침하지 않아도 지급 시각이 된 정산을 처리
            service.chain_watch_start()


def _shutdown() -> None:
    _stop.set()
    store.flush()
    if beta.enabled():
        try:
            beta.snapshot()
        except Exception as e:  # noqa: BLE001
            print(f"[beta] 종료 스냅샷 실패: {e}", flush=True)
    print("[베타 서버] 저장을 마치고 종료해요", flush=True)


def _is_admin(req: Request) -> bool:
    key = req.query_params.get("key") or req.headers.get("x-beta-key") or ""
    if config.BETA_EXPORT_KEY and key == config.BETA_EXPORT_KEY:
        return True
    auth = req.headers.get("authorization") or ""
    tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    u = service.session_user(tok) if tok else None
    return bool(u and (u.get("email") or "").lower() in config.BETA_ADMIN_EMAILS)


def _forbidden() -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": "FORBIDDEN", "message": "베타 데이터는 관리자만 볼 수 있어요."}}, status_code=403)


class BetaServer:
    """ASGI 감싸개: 운영 설정 + 관리자 데이터 경로. 나머지 요청은 그대로 backend.app으로."""

    def __init__(self, app) -> None:
        self.app = app
        self.gz = GZipMiddleware(app, minimum_size=1024, compresslevel=6)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "lifespan":
            async def recv():
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    _startup()
                elif msg["type"] == "lifespan.shutdown":
                    await anyio.to_thread.run_sync(_shutdown)
                return msg
            return await self.app(scope, recv, send)
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if path == "/healthz":
                return await JSONResponse({"ok": True, "version": config.APP_VERSION, "uptimeSec": int(time.time() - STARTED)})(scope, receive, send)
            if path in ("/api/beta/storage", "/api/beta/bundle.zip", "/api/beta/chain"):
                req = Request(scope, receive)
                if not await anyio.to_thread.run_sync(_is_admin, req):
                    return await _forbidden()(scope, receive, send)
                if path == "/api/beta/chain":
                    return await JSONResponse({"ok": True, "data": dict(_chain_last)})(scope, receive, send)
                if path == "/api/beta/storage":
                    info = await anyio.to_thread.run_sync(beta.storage_info)
                    return await JSONResponse({"ok": True, "data": info})(scope, receive, send)
                zp = await anyio.to_thread.run_sync(beta.bundle_file)
                resp = FileResponse(zp, media_type="application/zip", filename=zp.name,
                                    background=BackgroundTask(lambda: zp.unlink(missing_ok=True)))
                return await resp(scope, receive, send)
            if path.startswith("/api/"):
                return await self.gz(scope, receive, send)
        await self.app(scope, receive, send)


app = BetaServer(inner)
