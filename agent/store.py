"""아주 작은 JSON 저장소 (해커톤용). 참여자 지갑 등록부 + 정산 기록.
풀스택이 DB(SQLite 등)로 바꿀 때는 이 파일의 함수 시그니처만 유지하면 됩니다."""
from __future__ import annotations

import atexit
import json
import threading
import time
from typing import Any

from . import config

_FILE = config.DATA_DIR / "db.json"
_lock = threading.RLock()


def _load() -> dict[str, Any]:
    if _FILE.exists():
        return json.loads(_FILE.read_text(encoding="utf-8"))
    return {"members": {}, "settlements": {}, "users": {}, "charges": {}}


_db = _load()
for _k in ("users", "charges", "codes", "sessions", "groups", "chats", "attempts", "merchants",
           "devices", "oauth_states", "social_tickets", "social_ids", "listings", "notifs"):
    _db.setdefault(_k, {})


_SAVE_DELAY = config.STORE_SAVE_DELAY
_timer: threading.Timer | None = None
_dirty = False


def _write() -> None:
    tmp = _FILE.with_suffix(".tmp")
    text = json.dumps(_db, ensure_ascii=False, separators=(",", ":")) if _SAVE_DELAY > 0 else \
        json.dumps(_db, ensure_ascii=False, indent=1)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(_FILE)


def _save() -> None:
    """바뀐 내용을 db.json에 쓴다. STORE_SAVE_DELAY>0(베타 서버)이면 그 시간 동안 모아서 한 번에 —
    메시지 하나마다 파일 전체를 다시 쓰면 100명이 동시에 쓸 때 서버가 멈칫한다. 메모리가 원본이라 읽기는 늘 최신."""
    global _dirty, _timer
    if _SAVE_DELAY <= 0:
        _write()
        return
    with _lock:
        _dirty = True
        if _timer is None:
            _timer = threading.Timer(_SAVE_DELAY, _flush_later)
            _timer.daemon = True
            _timer.start()


def _flush_later() -> None:
    global _timer
    with _lock:
        _timer = None
        _flush_now()


def _flush_now() -> None:
    global _dirty, _timer
    if not _dirty:
        return
    try:
        _write()
        _dirty = False
    except (RuntimeError, ValueError, OSError) as e:   # 쓰는 중에 다른 스레드가 값을 바꿨으면 잠시 뒤 다시
        print(f"[store] 저장 재시도: {e}", flush=True)
        if _timer is None:
            _timer = threading.Timer(0.2, _flush_later)
            _timer.daemon = True
            _timer.start()


def flush() -> None:
    """모아 둔 변경을 지금 저장 (서버 종료·백업 전)."""
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
            _timer = None
        _flush_now()


atexit.register(flush)


# ── 참여자 지갑 ──
def set_member(name: str, wallet: str) -> dict[str, Any]:
    with _lock:
        _db["members"][name] = {"name": name, "wallet": wallet, "updated_at": time.time()}
        _save()
        return _db["members"][name]


def get_member(name: str) -> dict[str, Any] | None:
    return _db["members"].get(name)


def members() -> list[dict[str, Any]]:
    return list(_db["members"].values())


def name_of(wallet: str) -> str | None:
    for m in _db["members"].values():
        if m["wallet"].lower() == (wallet or "").lower():
            return m["name"]
    return None


# ── 정산 ──
def put(rec: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        rec["updated_at"] = time.time()
        _db["settlements"][rec["id"]] = rec
        _save()
        return rec


def get(sid: str) -> dict[str, Any] | None:
    return _db["settlements"].get(sid)


def all_settlements() -> list[dict[str, Any]]:
    return sorted(_db["settlements"].values(), key=lambda r: -r.get("created_at", 0))


# ── 사용자 (회원가입/로그인) ──
def add_user(user: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        _db["users"][user["email"]] = user
        _save()
        return user


def user_by_email(email: str) -> dict[str, Any] | None:
    return _db["users"].get((email or "").strip().lower())


def user_by_short(short: str) -> dict[str, Any] | None:
    return next((u for u in _db["users"].values() if u["short"] == short), None)


def users() -> list[dict[str, Any]]:
    return list(_db["users"].values())


# ── 충전 기록 (충전 간격 제한) ──
def last_charge(name: str) -> float:
    return _db["charges"].get(name, 0)


def set_charge(name: str, at: float | None = None) -> None:
    """충전 시각 기록 (at을 주면 그 값으로 — 체인 실패 때 예약을 되돌리는 용도)."""
    with _lock:
        _db["charges"][name] = time.time() if at is None else at
        _save()


def users_raw() -> list[dict[str, Any]]:
    return list(_db["users"].values())


def delete_user(email: str) -> None:
    with _lock:
        _db["users"].pop((email or "").lower(), None)
        for t in [t for t, x in _db["sessions"].items() if x.get("email") == email]:
            _db["sessions"].pop(t, None)
        _save()


def update_user(email: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    with _lock:
        u = _db["users"].get((email or "").lower())
        if u:
            u.update(patch)
            _save()
        return u


# ── 인증번호 / 세션 / 로그인 시도 ──
def kv_get(table: str, key: str) -> dict[str, Any] | None:
    return _db.get(table, {}).get(key)


def kv_put(table: str, key: str, value: dict[str, Any] | None) -> None:
    with _lock:
        t = _db.setdefault(table, {})   # 새 테이블도 자동 생성
        if value is None:
            t.pop(key, None)
        else:
            t[key] = value
        _save()


def kv_all(table: str) -> dict[str, Any]:
    return _db.setdefault(table, {})


def user_by_pie(pie_id: str) -> dict[str, Any] | None:
    pid = (pie_id or "").strip().lstrip("@").lower()
    return next((u for u in _db["users"].values() if u.get("pie_id") == pid), None)
