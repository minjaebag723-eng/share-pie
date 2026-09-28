"""백엔드가 부르는 유일한 진입점. HTTP 프레임워크와 무관.

구조 (CLAUDE.md 1번): 정산 코어가 유일한 메인, Shopping·Dispute는 꽂았다 뺐다 하는 선택 모듈.
  정산 코어  : analyze(Stage1 AI) → calculate(Stage2 코드, 0 tokens) → explain(Stage3 AI) → request(온체인 등록)
              → approve(참여자 예치) → 에스크로 보관(이의제기 기간) → release(지급)
  Dispute    : raise → investigate(3분류) → resolve(환불/유지/기각)
  Shopping   : search(예산 기준 1인당 비용 비교) → 선택 시 정산방 생성
에러는 ServiceError(code, message, stage, status) → 백엔드가 공통 에러 JSON으로 변환.
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib
import math
import threading
import re
import secrets
import time
import uuid
from typing import Any

from . import abi, assistant, beta, chain as chainmod, geo, mailer, social, config, dispute, llm, money, quota, report, settlement, shopping, store, usage, websearch
from . import textutil
from .textutil import won


class ServiceError(Exception):
    def __init__(self, code: str, message: str, stage: str = "", status: int = 400, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.stage, self.status, self.details = code, message, stage, status, details


STATE_LOCK = threading.RLock()


def _locked(fn):
    """정산 상태·체인 트랜잭션을 바꾸는 함수는 한 번에 하나씩 (폴링·결제·이의제기 동시 요청 시 중복 지급·기록 방지)."""
    @functools.wraps(fn)
    def inner(*a, **k):
        with STATE_LOCK:
            return fn(*a, **k)
    return inner


def _chain():
    try:
        return chainmod.get()
    except chainmod.ChainError as e:
        raise ServiceError(e.code, e.message, "chain", 503) from e


def _wrap_chain(fn, stage):
    try:
        return fn()
    except chainmod.ChainError as e:
        raise ServiceError(e.code, e.message, stage, 502) from e


def unique_short(name: str) -> str:
    """정산·채팅에서 쓰는 이름(서버 안에서 사람을 구분하는 값). 이름이 같아도 가입할 수 있게,
    겹치면 성까지 붙인 전체 이름 → 그래도 겹치면 숫자를 붙인다 (예: 진주 → 김진주 → 진주2)."""
    base, full = short_name(name), (name or "").strip()
    for cand in [base, full] + [f"{base}{i}" for i in range(2, 1000)]:
        if cand and not store.user_by_short(cand) and not store.get_member(cand):
            return cand
    return f"{base}{secrets.randbelow(10**6)}"


def short_name(name: str) -> str:
    """'김진주' → '진주' (한글 3글자만 성을 뗌). 'Alice'·'남궁민수'·'진주'는 그대로."""
    n = (name or "").strip()
    return n[1:] if len(n) == 3 and re.fullmatch(r"[가-힣]{3}", n) else n


# ───────────── 설정/상태 ─────────────
def config_info() -> dict[str, Any]:
    ch = _chain()
    return {"chain": ch.info(), "abi": {"ledger": abi.LEDGER_ABI, "token": abi.TOKEN_ABI},
            "llm": {"mode": llm.client.mode, "model": config.KILN_MODEL, "label": llm.model_label()},
            "allowed_merchants": config.ALLOWED_MERCHANTS, "charge_amount": config.CHARGE_AMOUNT,
            "ai_pay": {"won_per_token": config.AI_WON_PER_TOKEN, "fee_wallet": config.AI_FEE_WALLET or ch.info()["agent"]}}


def health() -> dict[str, Any]:
    info = {"llm_mode": llm.client.mode, "model": config.KILN_MODEL, "chain_mode": config.CHAIN_MODE,
            "accounts": len(store.users())}   # 가입자 수 (다른 서버·데이터 폴더를 보고 있는지 확인용)
    try:
        info["chain"] = _chain().info()["network"]
    except ServiceError as e:
        info["chain_error"] = e.message
    return info


# ───────────── 회원가입 / 로그인 ─────────────
_EMAIL = re.compile(r"^\S+@\S+\.\S+$")


def _hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()


def _public_user(u: dict[str, Any]) -> dict[str, Any]:
    m = store.get_member(u["short"])
    return {"name": u["name"], "short": u["short"], "email": u["email"], "wallet": m["wallet"] if m else None,
            "createdAt": u["created_at"], "id": u.get("pie_id"), "address": u.get("address") or "",
            "social": sorted((u.get("social") or {}).keys()), "hasPassword": bool(u.get("pw"))}


# ───────────── Pie ID (친구가 나를 찾는 공개 아이디) ─────────────
_PIE_ID = re.compile(r"^[a-z][a-z0-9._]{3,19}$")


def pie_id_error(pid: str) -> str:
    """프론트와 같은 규칙: 영문 소문자로 시작 · 소문자/숫자/./_ · 4~20자 · 마침표 연속·끝 금지."""
    if not pid:
        return "Pie ID를 입력해 주세요"
    if len(pid) < 4 or len(pid) > 20:
        return "Pie ID는 4~20자로 만들어 주세요"
    if not re.match(r"^[a-z]", pid):
        return "Pie ID는 영문 소문자로 시작해야 해요"
    if not _PIE_ID.match(pid):
        return "영문 소문자, 숫자, 마침표(.), 밑줄(_)만 쓸 수 있어요"
    if ".." in pid or pid.endswith("."):
        return "마침표는 연속으로 쓰거나 끝에 쓸 수 없어요"
    return ""


def _norm_pie(pid: str) -> str:
    return (pid or "").strip().lstrip("@").lower()


def check_pie_id(pid: str) -> dict[str, Any]:
    pid = _norm_pie(pid)
    err = pie_id_error(pid) or ("이미 사용 중인 Pie ID예요" if store.user_by_pie(pid) else "")
    return {"id": pid, "available": not err, "error": err}


def _auto_pie_id(email: str) -> str:
    base = re.sub(r"[^a-z0-9._]", "_", email.split("@")[0].lower()).strip("._") or "pie"
    if not base[0].isalpha():
        base = "u" + base
    base = re.sub(r"\.{2,}", ".", base)[:16].rstrip(".")
    while len(base) < 4:
        base += "0"
    cand, n = base, 1
    while store.user_by_pie(cand):
        n += 1
        cand = f"{base[:16]}{n}"
    return cand


def _migrate_pie_ids() -> None:
    """Pie ID가 생기기 전 가입한 계정에 이메일 앞부분으로 자동 부여 (프로필에서 바꿀 수 있음)."""
    for u in store.users():
        if not u.get("pie_id"):
            store.update_user(u["email"], {"pie_id": _auto_pie_id(u["email"])})


_migrate_pie_ids()


def user_by_pie_public(pid: str, me: dict[str, Any] | None) -> dict[str, Any]:
    pid = _norm_pie(pid)
    err = pie_id_error(pid)
    if err:
        raise ServiceError("BAD_REQUEST", err, "users.lookup")
    u = store.user_by_pie(pid)
    if not u:
        raise ServiceError("NOT_FOUND", "이 Pie ID를 쓰는 사용자가 없어요. 아직 가입 전이라면 초대 링크를 보내 주세요.", "users.lookup", 404)
    if me and u["email"] == me["email"]:
        raise ServiceError("BAD_REQUEST", "내 Pie ID예요. 친구의 ID를 입력해 주세요.", "users.lookup")
    return {"id": u["pie_id"], "name": u["short"], "fullName": u["name"],
            "isFriend": bool(me and u["pie_id"] in (me.get("friends") or []))}


def friends_list(me: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pid in me.get("friends") or []:
        u = store.user_by_pie(pid)
        if u:
            m = store.get_member(u["short"])
            out.append({"id": pid, "name": u["short"], "fullName": u["name"], "wallet": m["wallet"] if m else None})
    return out


# ───────────── 친구 (요청 → 수락해야 서로 친구) ─────────────
def _fresh(me: dict[str, Any]) -> dict[str, Any]:
    return store.user_by_email(me["email"]) or me


def _pub_brief(u: dict[str, Any]) -> dict[str, Any]:
    m = store.get_member(u["short"])
    return {"id": u.get("pie_id"), "name": u["short"], "fullName": u["name"], "wallet": m["wallet"] if m else None}


def friend_requests(me: dict[str, Any]) -> dict[str, Any]:
    me = _fresh(me)
    side = lambda k: [_pub_brief(u) for u in (store.user_by_pie(p) for p in (me.get(k) or [])) if u]   # noqa: E731
    return {"in": side("req_in"), "out": side("req_out")}


def _friend_state(me: dict[str, Any]) -> dict[str, Any]:
    me = _fresh(me)
    return {"friends": friends_list(me), **{("requestsIn" if k == "in" else "requestsOut"): v for k, v in friend_requests(me).items()}}


def _lst(u: dict[str, Any], k: str) -> list[str]:
    return list(u.get(k) or [])


@_locked
def friend_request(me: dict[str, Any], pid: str) -> dict[str, Any]:
    """Pie ID로 친구 요청. 상대가 이미 나에게 요청했으면 바로 서로 친구."""
    me = _fresh(me)
    f = user_by_pie_public(pid, me)
    other = store.user_by_pie(f["id"])
    mine = me["pie_id"]
    if f["id"] in _lst(me, "friends") and mine in _lst(other, "friends"):
        return {"status": "already", "user": f, **_friend_state(me)}
    if f["id"] in _lst(me, "req_in"):                      # 상대가 먼저 요청 → 수락 처리
        return _accept(me, other)
    if f["id"] in _lst(me, "req_out"):
        return {"status": "pending", "user": f, **_friend_state(me)}
    store.update_user(me["email"], {"req_out": _lst(me, "req_out") + [f["id"]]})
    store.update_user(other["email"], {"req_in": [x for x in _lst(other, "req_in") if x != mine] + [mine]})
    notify(other["email"], "친구", f"{me['short']}(@{mine})님이 친구 요청을 보냈어요.", go=["friends"],
           req={"type": "friend", "key": mine, "status": "pending"})
    return {"status": "sent", "user": f, **_friend_state(me)}


def _accept(me: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    mine, theirs = me["pie_id"], other["pie_id"]
    store.update_user(me["email"], {"friends": list(dict.fromkeys(_lst(me, "friends") + [theirs])),
                                    "req_in": [x for x in _lst(me, "req_in") if x != theirs],
                                    "req_out": [x for x in _lst(me, "req_out") if x != theirs]})
    store.update_user(other["email"], {"friends": list(dict.fromkeys(_lst(other, "friends") + [mine])),
                                       "req_in": [x for x in _lst(other, "req_in") if x != mine],
                                       "req_out": [x for x in _lst(other, "req_out") if x != mine]})
    _req_done(me["email"], "friend", theirs, "accepted")
    notify(other["email"], "친구", f"{me['short']}(@{mine})님이 친구 요청을 수락했어요.", go=["friends"])
    return {"status": "friends", "user": _pub_brief(other), **_friend_state(me)}


@_locked
def friend_accept(me: dict[str, Any], pid: str) -> dict[str, Any]:
    me, pid = _fresh(me), _norm_pie(pid)
    other = store.user_by_pie(pid)
    if not other or pid not in _lst(me, "req_in"):
        raise ServiceError("NOT_FOUND", "받은 친구 요청이 없어요 (상대가 취소했을 수 있어요).", "friends", 404)
    return _accept(me, other)


@_locked
def friend_decline(me: dict[str, Any], pid: str) -> dict[str, Any]:
    me, pid = _fresh(me), _norm_pie(pid)
    other = store.user_by_pie(pid)
    store.update_user(me["email"], {"req_in": [x for x in _lst(me, "req_in") if x != pid]})
    if other:
        store.update_user(other["email"], {"req_out": [x for x in _lst(other, "req_out") if x != me["pie_id"]]})
    _req_done(me["email"], "friend", pid, "declined")      # 거절은 상대에게 알리지 않는다
    return {"status": "declined", **_friend_state(me)}


@_locked
def friend_cancel(me: dict[str, Any], pid: str) -> dict[str, Any]:
    me, pid = _fresh(me), _norm_pie(pid)
    other = store.user_by_pie(pid)
    store.update_user(me["email"], {"req_out": [x for x in _lst(me, "req_out") if x != pid]})
    if other:
        store.update_user(other["email"], {"req_in": [x for x in _lst(other, "req_in") if x != me["pie_id"]]})
        _notif_drop(other["email"], "friend", me["pie_id"])   # 상대 알림함의 요청도 지움
    return {"status": "cancelled", **_friend_state(me)}


@_locked
def friend_remove(me: dict[str, Any], pid: str) -> dict[str, Any]:
    me, pid = _fresh(me), _norm_pie(pid)
    store.update_user(me["email"], {"friends": [x for x in _lst(me, "friends") if x != pid]})
    other = store.user_by_pie(pid)
    if other:                                               # 친구 관계는 서로 끊긴다 (그룹·정산 기록은 유지)
        store.update_user(other["email"], {"friends": [x for x in _lst(other, "friends") if x != me["pie_id"]]})
    return {"friends": friends_list(_fresh(me)), **_friend_state(me)}


def friend_add(me: dict[str, Any], pid: str) -> dict[str, Any]:
    """(예전 이름) 이제는 친구 요청을 보낸다. 상대가 수락해야 친구."""
    r = friend_request(me, pid)
    return {**r, "added": r.get("user")}


# ───────────── 알림함 (사용자별 서버 저장) ─────────────
_NOTIF_MAX = 150


def notify(email: str, cat: str, text: str, *, go: list | None = None, req: dict | None = None, action: bool = False,
           key: str | None = None) -> None:
    """알림 추가. key가 같으면 이전 것을 교체 (같은 방 승인 요청이 바뀐 경우 등)."""
    if not email:
        return
    with STATE_LOCK:
        lst = [n for n in (store.kv_get("notifs", email) or {}).get("items", []) if not (key and n.get("key") == key)]
        lst.insert(0, {"id": "n" + uuid.uuid4().hex[:10], "cat": cat, "text": text[:300], "ts": time.time(), "read": False,
                       "go": go or [], **({"req": req} if req else {}), **({"action": True} if action else {}), **({"key": key} if key else {})})
        store.kv_put("notifs", email, {"items": lst[:_NOTIF_MAX]})


def notify_short(short: str, *a, **k) -> None:
    u = store.user_by_short(short)
    if u:
        notify(u["email"], *a, **k)


def _req_done(email: str, typ: str, key: str, status: str) -> None:
    with STATE_LOCK:
        rec = store.kv_get("notifs", email) or {}
        items = [({**n, "read": True, "req": {**n["req"], "status": status}}
                  if n.get("req") and n["req"].get("type") == typ and n["req"].get("key") == key and n["req"].get("status") == "pending" else n)
                 for n in rec.get("items", [])]
        store.kv_put("notifs", email, {"items": items})


def _notif_drop(email: str, typ: str, key: str) -> None:
    with STATE_LOCK:
        rec = store.kv_get("notifs", email) or {}
        store.kv_put("notifs", email, {"items": [n for n in rec.get("items", [])
                                                 if not (n.get("req") and n["req"].get("type") == typ and n["req"].get("key") == key
                                                         and n["req"].get("status") == "pending")]})


def notifs_for(me: dict[str, Any]) -> dict[str, Any]:
    items = (store.kv_get("notifs", me["email"]) or {}).get("items", [])
    return {"items": items, "unread": sum(1 for n in items if not n.get("read"))}


def notifs_read(me: dict[str, Any], ids: list[str] | None = None) -> dict[str, Any]:
    with STATE_LOCK:
        rec = store.kv_get("notifs", me["email"]) or {}
        items = [({**n, "read": True} if ids is None or n["id"] in ids else n) for n in rec.get("items", [])]
        store.kv_put("notifs", me["email"], {"items": items})
    return notifs_for(me)


def locate(me: dict[str, Any], lat: float, lng: float, save: bool = True) -> dict[str, Any]:
    """기기 GPS 좌표 → 동네 이름. 좌표는 저장하지 않고 동 단위 이름만 프로필에 저장 (개인정보 최소화)."""
    try:
        r = geo.reverse(float(lat), float(lng))
    except (geo.GeoError, TypeError, ValueError) as e:
        raise ServiceError("GEO_FAILED", str(e) or "위치를 동네 이름으로 바꾸지 못했어요.", "geo", 502) from e
    changed = bool(r["address"]) and r["address"] != (me.get("address") or "")
    if save and changed:
        with STATE_LOCK:
            store.update_user(me["email"], {"address": r["address"], "address_source": "gps", "address_at": time.time()})
    return {"address": r["address"] or me.get("address") or "", "changed": changed, "source": r["source"]}


@_locked
def update_profile(me: dict[str, Any], pie_id: str | None = None, address: str | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if pie_id is not None:
        pid = _norm_pie(pie_id)
        if pid != me.get("pie_id"):
            c = check_pie_id(pid)
            if not c["available"]:
                raise ServiceError("PIE_ID_TAKEN" if "사용 중" in c["error"] else "BAD_REQUEST", c["error"], "profile", 409 if "사용 중" in c["error"] else 400)
            patch["pie_id"] = pid
            for u in store.users():   # 나를 친구·친구 요청으로 가진 사람들의 목록도 새 ID로
                upd = {k: [pid if x == me["pie_id"] else x for x in (u.get(k) or [])]
                       for k in ("friends", "req_in", "req_out") if me.get("pie_id") in (u.get(k) or [])}
                if upd:
                    store.update_user(u["email"], upd)
    if address is not None:
        a = re.sub(r"\s+", " ", address).strip()
        if len(a) < 2 or len(a) > 40:
            raise ServiceError("BAD_REQUEST", "동네는 2~40자로 입력해 주세요. 예: 서울 성동구 성수동", "profile")
        patch["address"] = a
    if patch:
        store.update_user(me["email"], patch)
    return _public_user(store.user_by_email(me["email"]))


PW_RULE = "비밀번호는 8자 이상, 영문과 숫자를 모두 넣어 주세요."


def _check_pw(pw: str) -> None:
    pw = pw or ""
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise ServiceError("WEAK_PASSWORD", PW_RULE, "auth")


def _norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL.match(e):
        raise ServiceError("BAD_REQUEST", "올바른 이메일 형식이 아니에요.", "auth")
    return e


def _code_key(purpose: str, email: str) -> str:
    return f"{purpose}:{email}"


@_locked
def send_code(email: str, purpose: str = "signup") -> dict[str, Any]:
    """이메일 인증번호 발송 (6자리 · 10분 유효 · 60초 재발송 제한 · 1시간 5회)."""
    email = _norm_email(email)
    if purpose not in ("signup", "reset", "withdraw"):
        raise ServiceError("BAD_REQUEST", "알 수 없는 인증 목적이에요.", "auth.code")
    exists = bool(store.user_by_email(email))
    if purpose == "signup" and exists:
        raise ServiceError("EMAIL_TAKEN", "이미 가입된 이메일이에요. 로그인해 주세요.", "auth.code", 409)
    now = time.time()
    key = _code_key(purpose, email)
    old = store.kv_get("codes", key) or {}
    sends = [t for t in old.get("sends", []) if now - t < 3600]
    # 처음 1번 + 재요청 2번까지는 바로, 그 뒤로는 마지막 발송 1분 후부터
    if len(sends) > config.CODE_FREE_RESENDS and now - old.get("sent_at", 0) < config.CODE_RESEND_SEC:
        wait = int(config.CODE_RESEND_SEC - (now - old["sent_at"])) + 1
        raise ServiceError("CODE_COOLDOWN", f"재요청은 {wait}초 뒤에 할 수 있어요.", "auth.code", 429, {"wait": wait})
    if len(sends) >= config.CODE_HOURLY_MAX:
        raise ServiceError("CODE_LIMIT", "인증번호 요청이 너무 많아요. 1시간 뒤에 다시 시도해 주세요.", "auth.code", 429)
    n = len(sends) + 1                                           # 이번이 몇 번째 발송인지
    out = {"sent": True, "email": email, "expires_in": config.CODE_TTL_SEC,
           "resend_after": config.CODE_RESEND_SEC if n > config.CODE_FREE_RESENDS else 0,   # 다음 재요청까지 기다릴 초
           "free_resends_left": max(0, config.CODE_FREE_RESENDS + 1 - n), "send_count": n}
    if purpose == "reset" and not exists:
        if mailer.dev_echo():   # 개발 모드(메일 서버 미설정)에서는 헷갈리지 않게 알려 줌
            raise ServiceError("EMAIL_NOT_FOUND", "이 서버에 가입된 이메일이 아니에요. (개발 모드 안내 · 실제 메일 설정 시에는 가입 여부를 알려 주지 않아요)",
                               "auth.code", 404)
        return out   # 가입 여부를 노출하지 않음 (메일은 보내지 않음)
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        via = mailer.send_code(email, code, purpose)
    except mailer.MailError as e:
        raise ServiceError("MAIL_FAILED", f"인증 메일을 보내지 못했어요: {e}", "auth.code", 424) from e
    salt = secrets.token_hex(4)
    store.kv_put("codes", key, {"hash": _hash_pw(code, salt), "salt": salt, "exp": now + config.CODE_TTL_SEC,
                                "sent_at": now, "sends": sends + [now], "tries": 0})
    out["via"] = via
    if mailer.dev_echo():
        out["dev_code"] = code   # SMTP 미설정 시연용: 화면에 표시 (메일 설정하면 사라짐)
    return out


def _use_code(email: str, purpose: str, code: str) -> None:
    key = _code_key(purpose, email)
    rec = store.kv_get("codes", key)
    if not rec:
        raise ServiceError("CODE_REQUIRED", "먼저 인증번호를 받아 주세요.", "auth.code", 400)
    if time.time() > rec["exp"]:
        store.kv_put("codes", key, None)
        raise ServiceError("CODE_EXPIRED", "인증번호 유효 시간이 지났어요. 다시 받아 주세요.", "auth.code", 400)
    if rec["tries"] >= 5:
        store.kv_put("codes", key, None)
        raise ServiceError("CODE_LOCKED", "인증번호를 5번 틀렸어요. 새로 받아 주세요.", "auth.code", 429)
    if _hash_pw(re.sub(r"\D", "", code or ""), rec["salt"]) != rec["hash"]:
        rec["tries"] += 1
        store.kv_put("codes", key, rec)
        raise ServiceError("CODE_MISMATCH", f"인증번호가 맞지 않아요. ({rec['tries']}/5)", "auth.code", 400)
    store.kv_put("codes", key, None)   # 한 번 쓰면 폐기


def _new_session(email: str) -> str:
    token = secrets.token_urlsafe(32)
    store.kv_put("sessions", hashlib.sha256(token.encode()).hexdigest(),
                 {"email": email, "exp": time.time() + config.SESSION_DAYS * 86400, "created": time.time()})
    return token


def session_user(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    key = hashlib.sha256(token.encode()).hexdigest()
    sess = store.kv_get("sessions", key)
    if not sess or sess["exp"] < time.time():
        if sess:
            store.kv_put("sessions", key, None)
        return None
    return store.user_by_email(sess["email"])


@_locked
def signup(name: str, email: str, password: str, code: str | None = None, pie_id: str | None = None) -> dict[str, Any]:
    name = (name or "").strip()
    email = _norm_email(email)
    if not name or len(name) > 12 or not re.fullmatch(r"[가-힣A-Za-z0-9 ]+", name):
        raise ServiceError("BAD_REQUEST", "이름은 12자 이하 한글·영문·숫자로 입력해 주세요.", "auth")
    _check_pw(password)
    if store.user_by_email(email):
        raise ServiceError("EMAIL_TAKEN", "이미 가입된 이메일이에요. 로그인해 주세요.", "auth", 409)
    short = unique_short(name)            # 같은 이름도 가입 가능 (친구는 Pie ID로 구분)
    if pie_id is not None:
        c = check_pie_id(pie_id)
        if not c["available"]:
            raise ServiceError("PIE_ID_TAKEN" if "사용 중" in c["error"] else "BAD_REQUEST", c["error"], "auth", 409 if "사용 중" in c["error"] else 400)
    _use_code(email, "signup", code or "")
    salt = secrets.token_hex(8)
    u = store.add_user({"name": name, "short": short, "email": email, "salt": salt, "pw": _hash_pw(password, salt),
                        "created_at": time.time(), "verified": True,
                        "pie_id": _norm_pie(pie_id) if pie_id else _auto_pie_id(email), "friends": [], "address": ""})
    return {**_public_user(u), "token": _new_session(email)}


@_locked
def login(email: str, password: str) -> dict[str, Any]:
    email = (email or "").strip().lower()
    now = time.time()
    att = store.kv_get("attempts", email) or {"fails": 0, "until": 0}
    if att.get("until", 0) > now:
        raise ServiceError("LOGIN_LOCKED", f"로그인을 5번 실패해서 {int(att['until'] - now) // 60 + 1}분 동안 잠겼어요.", "auth", 429)
    u = store.user_by_email(email)
    if u and not u.get("pw") and u.get("social"):   # 소셜로만 가입한 계정
        names = "·".join(social.NAMES.get(p, p) for p in u["social"])
        raise ServiceError("SOCIAL_ACCOUNT", f"이 이메일은 {names} 계정으로 가입했어요. 아래 {names} 버튼으로 로그인해 주세요. "
                           "(비밀번호를 만들려면 ‘비밀번호 재설정’)", "auth", 401, {"providers": sorted(u["social"])})
    if not u or not u.get("pw") or u["pw"] != _hash_pw(password or "", u["salt"]):
        fails = att.get("fails", 0) + 1
        store.kv_put("attempts", email, {"fails": 0, "until": now + 300} if fails >= 5 else {"fails": fails, "until": 0})
        raise ServiceError("AUTH_FAILED", "이메일 또는 비밀번호가 맞지 않아요." + (f" ({fails}/5)" if fails >= 3 else ""), "auth", 401)
    store.kv_put("attempts", email, None)
    return {**_public_user(u), "token": _new_session(email)}


def me(user: dict[str, Any]) -> dict[str, Any]:
    return _public_user(user)


def logout(token: str | None) -> dict[str, Any]:
    if token:
        store.kv_put("sessions", hashlib.sha256(token.encode()).hexdigest(), None)
    return {"logged_out": True}


@_locked
def reset_password(email: str, code: str, password: str) -> dict[str, Any]:
    email = _norm_email(email)
    _check_pw(password)
    _use_code(email, "reset", code)
    u = store.user_by_email(email)
    if not u:
        raise ServiceError("CODE_MISMATCH", "인증번호가 맞지 않아요.", "auth.code", 400)
    salt = secrets.token_hex(8)
    store.update_user(email, {"salt": salt, "pw": _hash_pw(password, salt)})
    for t, x in list(store.kv_all("sessions").items()):   # 다른 기기 로그인 모두 해제
        if x.get("email") == email:
            store.kv_put("sessions", t, None)
    store.kv_put("attempts", email, None)
    return {"reset": True}


@_locked
def change_password(user: dict[str, Any], old: str, new: str) -> dict[str, Any]:
    if user.get("pw") and user["pw"] != _hash_pw(old or "", user["salt"]):   # 소셜 가입자는 처음 만들 때 현재 비밀번호 없음
        raise ServiceError("AUTH_FAILED", "현재 비밀번호가 맞지 않아요.", "auth", 401)
    _check_pw(new)
    salt = secrets.token_hex(8)
    store.update_user(user["email"], {"salt": salt, "pw": _hash_pw(new, salt)})
    return {"changed": True}


def find_id(name: str) -> dict[str, Any]:
    """이름으로 가입 이메일 찾기 (가운데를 가려서)."""
    n = (name or "").strip()
    if not n:
        raise ServiceError("BAD_REQUEST", "가입할 때 쓴 이름을 입력해 주세요.", "auth")

    def mask(e):
        local, _, dom = e.partition("@")
        return (local[:2] + "*" * max(1, len(local) - 2)) + "@" + dom
    hits = [mask(u["email"]) for u in store.users() if u["name"] == n or u["short"] == n]
    return {"emails": hits}


@_locked
def withdraw(user: dict[str, Any], password: str) -> dict[str, Any]:
    if not user.get("pw"):
        if (password or "").strip() != "탈퇴":
            raise ServiceError("AUTH_FAILED", "소셜 가입 계정은 확인란에 ‘탈퇴’라고 입력해 주세요.", "auth", 401)
    elif user["pw"] != _hash_pw(password or "", user["salt"]):
        raise ServiceError("AUTH_FAILED", "비밀번호가 맞지 않아요.", "auth", 401)
    active = [r["name"] for r in store.all_settlements()
              if r["status"] in ("open", "locked", "disputed") and any(m["name"] == user["short"] for m in r["members"])]
    if active:
        raise ServiceError("HAS_ACTIVE_SETTLEMENT", f"진행 중인 정산이 있어 탈퇴할 수 없어요: {', '.join(active[:3])}. 정산이 끝난 뒤 다시 시도해 주세요.",
                           "auth", 409, {"settlements": active})
    for p, sub in (user.get("social") or {}).items():
        store.kv_put("social_ids", f"{p}:{sub}", None)
    for k, v in list(store.kv_all("devices").items()):
        if v and v.get("email") == user["email"]:
            store.kv_put("devices", k, None)
    store.delete_user(user["email"])
    return {"withdrawn": True, "note": "계정 정보는 삭제했어요. 블록체인에 남은 정산 기록(지갑 주소·금액)은 지울 수 없어요."}


# ───────────── 이 기기에서 마지막으로 쓴 이메일 (로그인 화면 자동 채우기) ─────────────
# 기기마다 앱이 만든 무작위 ID(X-SP-Device)를 해시로만 저장 → 가입·이메일 로그인 때 기록, 로그인 화면에서 불러옴
_DEVICE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def _device_key(device: str | None) -> str | None:
    return hashlib.sha256(device.encode()).hexdigest() if device and _DEVICE.match(device) else None


def remember_device(device: str | None, email: str) -> None:
    k = _device_key(device)
    if k and email:
        store.kv_put("devices", k, {"email": email, "at": time.time()})


def remembered(device: str | None) -> dict[str, Any]:
    k = _device_key(device)
    rec = store.kv_get("devices", k) if k else None
    email = rec.get("email") if rec else None
    if email and not store.user_by_email(email):
        email = None                      # 탈퇴·삭제된 계정은 채우지 않음
    return {"email": email}


def forget_device(device: str | None) -> dict[str, Any]:
    k = _device_key(device)
    if k:
        store.kv_put("devices", k, None)
    return {"forgotten": True}


# ───────────── 소셜 로그인 (agent/social.py가 각 사와 통신, 여기서는 계정 연결·가입) ─────────────
_TICKET_TTL = 600


def social_providers() -> list[dict[str, Any]]:
    return social.providers()


def _check_provider(provider: str) -> None:
    if provider not in social.NAMES:
        raise ServiceError("NOT_FOUND", "지원하지 않는 소셜 로그인이에요.", "auth.social", 404)
    if not social.configured(provider):
        raise ServiceError("SOCIAL_NOT_CONFIGURED", f"{social.NAMES[provider]} 로그인은 아직 준비 중이에요. "
                           "(서버 .env에 키가 없어요 — 이메일로 가입해 주세요)", "auth.social", 409)


@_locked
def social_start(provider: str, redirect_uri: str, link_email: str | None = None) -> str:
    _check_provider(provider)
    now = time.time()
    for k, v in list(store.kv_all("oauth_states").items()):   # 만료된 state 청소
        if v and v.get("exp", 0) < now:
            store.kv_put("oauth_states", k, None)
    state = secrets.token_urlsafe(24)
    store.kv_put("oauth_states", state, {"provider": provider, "redirect_uri": redirect_uri, "exp": now + 600, "link": link_email})
    return social.authorize_url(provider, redirect_uri, state)


@_locked
def _pop_state(state: str) -> dict[str, Any] | None:
    st = store.kv_get("oauth_states", state or "") if state else None
    if st:
        store.kv_put("oauth_states", state, None)   # 1회용 (재사용·CSRF 방지)
    return st if st and st.get("exp", 0) >= time.time() else None


def _new_ticket(data: dict[str, Any]) -> str:
    t = secrets.token_urlsafe(24)
    store.kv_put("social_tickets", hashlib.sha256(t.encode()).hexdigest(), {**data, "exp": time.time() + _TICKET_TTL})
    return t


def social_callback(provider: str, code: str | None, state: str | None, error: str | None = None,
                    apple_user: str | None = None) -> str:
    """각 사가 돌려보낸 요청 처리 → 앱에 넘길 1회용 티켓. 실패하면 ServiceError."""
    st = _pop_state(state or "")
    if not st or st["provider"] != provider:
        raise ServiceError("SOCIAL_STATE", "로그인 요청이 만료됐거나 올바르지 않아요. 처음부터 다시 시도해 주세요.", "auth.social", 400)
    if error or not code:
        raise ServiceError("SOCIAL_CANCELLED", f"{social.NAMES[provider]} 로그인이 취소됐어요.", "auth.social", 400)
    try:
        ident = social.fetch_identity(provider, code, st["redirect_uri"], state or "", apple_user)
    except social.SocialError as e:
        raise ServiceError(e.code, e.message, "auth.social", 502) from e
    return _social_finish(ident, st.get("link"))


@_locked
def _social_finish(ident: dict[str, Any], link_email: str | None) -> str:
    key = f"{ident['provider']}:{ident['sub']}"
    owner = (store.kv_get("social_ids", key) or {}).get("email")
    if owner and not store.user_by_email(owner):
        store.kv_put("social_ids", key, None)
        owner = None
    pname = social.NAMES[ident["provider"]]
    if link_email:                                   # 로그인한 상태에서 '계정 연결'
        if owner and owner != link_email:
            raise ServiceError("SOCIAL_TAKEN", f"이 {pname} 계정은 이미 다른 Share Pie 계정에 연결돼 있어요.", "auth.social", 409)
        _link(link_email, ident)
        return _new_ticket({"kind": "linked", "email": link_email, "provider": ident["provider"]})
    if owner:
        return _new_ticket({"kind": "login", "email": owner, "provider": ident["provider"]})
    if ident.get("email") and ident.get("email_verified") and store.user_by_email(ident["email"]):
        _link(ident["email"], ident)                 # 같은 (확인된) 이메일로 가입한 계정이 있으면 자동 연결
        return _new_ticket({"kind": "login", "email": ident["email"], "provider": ident["provider"], "linked": True})
    return _new_ticket({"kind": "signup", **ident})  # 처음 온 사람 → 이름·Pie ID 입력 단계


def _link(email: str, ident: dict[str, Any]) -> None:
    u = store.user_by_email(email)
    soc = dict(u.get("social") or {})
    soc[ident["provider"]] = ident["sub"]
    store.update_user(email, {"social": soc})
    store.kv_put("social_ids", f"{ident['provider']}:{ident['sub']}", {"email": email})


def _ticket(ticket: str, consume: bool) -> dict[str, Any]:
    k = hashlib.sha256((ticket or "").encode()).hexdigest()
    t = store.kv_get("social_tickets", k)
    if not t or t["exp"] < time.time():
        if t:
            store.kv_put("social_tickets", k, None)
        raise ServiceError("SOCIAL_TICKET", "소셜 로그인 시간이 지났어요. 다시 시도해 주세요.", "auth.social", 400)
    if consume:
        store.kv_put("social_tickets", k, None)
    return t


@_locked
def social_exchange(ticket: str) -> dict[str, Any]:
    t = _ticket(ticket, consume=False)
    pname = social.NAMES[t["provider"]]
    if t["kind"] in ("login", "linked"):
        _ticket(ticket, consume=True)
        u = store.user_by_email(t["email"])
        if not u:
            raise ServiceError("SOCIAL_TICKET", "계정을 찾을 수 없어요. 다시 시도해 주세요.", "auth.social", 400)
        if t["kind"] == "linked":
            return {"status": "linked", "provider": t["provider"], "providerName": pname, "social": sorted(u.get("social") or {})}
        return {"status": "ok", "provider": t["provider"], "providerName": pname, "linked": bool(t.get("linked")),
                **_public_user(u), "token": _new_session(u["email"])}
    return {"status": "need_profile", "provider": t["provider"], "providerName": pname, "email": t.get("email") or "",
            "emailVerified": bool(t.get("email_verified") and t.get("email")),
            "name": re.sub(r"[^가-힣A-Za-z0-9 ]", "", t.get("name") or "")[:12],
            "pieId": _auto_pie_id(t.get("email") or f"{t['provider']}{t['sub'][-6:]}@x")}


@_locked
def social_complete(ticket: str, name: str, pie_id: str | None, email: str | None = None, code: str | None = None) -> dict[str, Any]:
    """처음 소셜로 온 사람의 가입 마무리 (이름·Pie ID, 이메일을 못 받았으면 메일 인증)."""
    t = _ticket(ticket, consume=False)
    if t["kind"] != "signup":
        raise ServiceError("SOCIAL_TICKET", "이미 처리된 로그인이에요. 다시 시도해 주세요.", "auth.social", 400)
    name = (name or "").strip()
    if not name or len(name) > 12 or not re.fullmatch(r"[가-힣A-Za-z0-9 ]+", name):
        raise ServiceError("BAD_REQUEST", "이름은 12자 이하 한글·영문·숫자로 입력해 주세요.", "auth")
    short = unique_short(name)            # 같은 이름도 가입 가능 (친구는 Pie ID로 구분)
    if t.get("email") and t.get("email_verified"):
        mail = t["email"]
    else:                                              # 이메일을 못 받았거나 확인 안 된 주소 → 메일 인증
        mail = _norm_email(email or "")
        _use_code(mail, "signup", code or "")
    if store.user_by_email(mail):
        raise ServiceError("EMAIL_TAKEN", "이미 가입된 이메일이에요. 그 계정으로 로그인한 뒤 ‘내 정보 > 소셜 계정 연결’에서 연결해 주세요.", "auth", 409)
    if pie_id:
        c = check_pie_id(pie_id)
        if not c["available"]:
            raise ServiceError("PIE_ID_TAKEN" if "사용 중" in c["error"] else "BAD_REQUEST", c["error"], "auth", 409 if "사용 중" in c["error"] else 400)
    key = f"{t['provider']}:{t['sub']}"
    if (store.kv_get("social_ids", key) or {}).get("email"):
        raise ServiceError("SOCIAL_TAKEN", "이 소셜 계정은 이미 가입돼 있어요. 다시 로그인해 주세요.", "auth.social", 409)
    u = store.add_user({"name": name, "short": short, "email": mail, "salt": None, "pw": None, "created_at": time.time(),
                        "verified": True, "pie_id": _norm_pie(pie_id) if pie_id else _auto_pie_id(mail), "friends": [], "address": "",
                        "social": {t["provider"]: t["sub"]}})
    store.kv_put("social_ids", key, {"email": mail})
    _ticket(ticket, consume=True)
    return {**_public_user(u), "token": _new_session(mail), "provider": t["provider"]}


def social_link_start(user: dict[str, Any], provider: str, redirect_uri: str) -> dict[str, Any]:
    if provider in (user.get("social") or {}):
        raise ServiceError("SOCIAL_TAKEN", f"이미 {social.NAMES.get(provider, provider)} 계정이 연결돼 있어요.", "auth.social", 409)
    return {"url": social_start(provider, redirect_uri, link_email=user["email"])}


@_locked
def social_unlink(user: dict[str, Any], provider: str) -> dict[str, Any]:
    soc = dict(user.get("social") or {})
    if provider not in soc:
        raise ServiceError("NOT_FOUND", "연결되지 않은 소셜 계정이에요.", "auth.social", 404)
    if not user.get("pw") and len(soc) == 1:
        raise ServiceError("LAST_LOGIN_METHOD", "로그인할 방법이 없어져요. 먼저 ‘비밀번호 변경’에서 비밀번호를 만들어 주세요.", "auth.social", 409)
    store.kv_put("social_ids", f"{provider}:{soc.pop(provider)}", None)
    store.update_user(user["email"], {"social": soc})
    return {"social": sorted(soc)}


def users(q: str = "") -> list[dict[str, Any]]:
    q = (q or "").strip()
    # 친구 검색: 다른 사람의 이메일은 노출하지 않음
    return [{k: v for k, v in _public_user(u).items() if k not in ("email", "address")} for u in store.users()
            if not q or q in u["name"] or q in u["short"] or q.lstrip("@").lower() in (u.get("pie_id") or "")]


# ───────────── 지갑 등록 / 충전 ─────────────
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")


@_locked
def register_member(name: str, wallet: str | None) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ServiceError("BAD_REQUEST", "이름이 필요해요", "members")
    ch = _chain()
    if not wallet:
        if ch.mode != "mock":
            raise ServiceError("BAD_REQUEST", "MetaMask 지갑 주소가 필요해요", "members")
        wallet = "0x" + hashlib.sha3_256(("mock:" + name).encode()).hexdigest()[:40]
    if not _ADDR.match(wallet):
        raise ServiceError("BAD_REQUEST", "지갑 주소 형식이 올바르지 않아요", "members")
    other = store.name_of(wallet)
    if other and other != name:
        raise ServiceError("WALLET_TAKEN", f"이 지갑은 이미 {other}님이 등록했어요. MetaMask에서 다른 계정을 선택해 주세요.", "members", 409)
    out = dict(store.set_member(name, wallet))
    out["gas"] = (_gas_drip_async if config.GAS_DRIP_ASYNC else _gas_drip)(name, wallet, ch)   # [blockchain 담당] 가스 자동 지급 (실패해도 등록은 성공) · [베타 서버] 뒤에서
    retry_pending([name])          # 이 사람 지갑을 기다리던 정산이 있으면 자동 시작
    return out


_DRIP_INFLIGHT: set[str] = set()
_DRIP_LOCK = threading.Lock()


def _gas_drip_async(name: str, wallet: str, ch) -> dict[str, Any] | None:
    """[베타 서버] 가스 지급을 뒤에서 — 지갑 등록 응답이 체인 확정(Sepolia 12초~)을 기다리지 않고,
    그동안 전역 잠금을 쥐지 않아 다른 사람 요청도 막히지 않는다. 결과는 예전과 같이 gas_drip 기록·서버 로그에 남는다."""
    if ch.mode == "mock" or config.GAS_DRIP_ETH <= 0:
        return None
    key = wallet.lower()
    with _DRIP_LOCK:
        if key in _DRIP_INFLIGHT:
            return {"pending": True}
        _DRIP_INFLIGHT.add(key)

    def run() -> None:
        try:
            _gas_drip(name, wallet, ch)
        except Exception as e:  # noqa: BLE001 — 뒤에서 도는 일이 서버를 죽이면 안 됨
            print(f"[가스 지급 실패] {name} {wallet}: {e}", flush=True)
        finally:
            with _DRIP_LOCK:
                _DRIP_INFLIGHT.discard(key)
    threading.Thread(target=run, name="gas-drip", daemon=True).start()
    return {"pending": True}


def _gas_drip(name: str, wallet: str, ch) -> dict[str, Any] | None:
    """[blockchain 담당] 실제 체인에서 사용자가 예치(MetaMask 서명)하려면 가스가 필요하다.
    faucet 을 직접 찾지 않아도 되게, 지갑 등록 시 잔액이 GAS_DRIP_MIN_ETH 미만이면 에이전트가 GAS_DRIP_ETH 를 보낸다.
    같은 지갑은 GAS_DRIP_COOLDOWN_SEC 에 한 번만. 테스트넷 전용 · 실패해도 등록은 막지 않는다."""
    if ch.mode == "mock" or config.GAS_DRIP_ETH <= 0:
        return None
    key = wallet.lower()
    last = store.kv_get("gas_drip", key) or {}
    if last.get("at") and time.time() - float(last["at"]) < config.GAS_DRIP_COOLDOWN_SEC:
        return {"skipped": "cooldown", "last_tx_hash": last.get("tx_hash")}
    try:
        bal = ch.native_balance(wallet)
        if bal >= config.GAS_DRIP_MIN_ETH:
            return {"skipped": "enough", "balance_eth": bal}
        tx = ch.send_gas(wallet, config.GAS_DRIP_ETH)
    except chainmod.ChainError as e:
        print(f"[가스 지급 실패] {name} {wallet}: {e.code} {e.message}")
        return {"skipped": "failed", "error": e.code}
    if not tx:
        return None
    store.kv_put("gas_drip", key, {"at": time.time(), "tx_hash": tx["tx_hash"], "amount_eth": config.GAS_DRIP_ETH, "name": name})
    print(f"[가스 지급] {name} {wallet} ← {config.GAS_DRIP_ETH} ETH ({tx['tx_hash']})")
    return {"amount_eth": config.GAS_DRIP_ETH, "tx_hash": tx["tx_hash"], "url": ch.explorer_tx(tx["tx_hash"])}


def charge(name: str) -> dict[str, Any]:
    """charge_token — 에이전트가 PieCoin 발급 (사용자는 가스비 없이 충전).
    [베타 서버] 전역 잠금은 확인·예약에만 쓰고, 체인 확정(Sepolia 12초~)은 잠금 밖에서 기다린다 — 그동안 다른 사람 요청이 막히지 않게.
    쿨다운을 먼저 예약해서 두 번 눌러도 한 번만 나가고, 체인이 실패하면 예약을 되돌린다."""
    with STATE_LOCK:
        m = store.get_member(name)
        if not m:
            raise ServiceError("MEMBER_WALLET_MISSING", "먼저 MY 탭에서 지갑을 연결해 주세요.", "charge", 409)
        prev = store.last_charge(name)
        wait = config.CHARGE_COOLDOWN_SEC - (time.time() - prev)
        if wait > 0:
            raise ServiceError("CHARGE_COOLDOWN", f"충전은 {int(wait) + 1}초 뒤에 다시 할 수 있어요.", "charge", 429)
        store.set_charge(name)
        ch = _chain()
    try:
        tx = _wrap_chain(lambda: ch.charge(m["wallet"], config.CHARGE_AMOUNT), "chain.charge")
    except Exception:
        with STATE_LOCK:
            store.set_charge(name, prev)
        raise
    with STATE_LOCK:
        retry_pending([name])          # 잔액이 모자라 기다리던 정산 자동 시작
        return {"amount": config.CHARGE_AMOUNT, "tx_hash": tx["tx_hash"], "url": ch.explorer_tx(tx["tx_hash"]),
            "wallet": wallet(m["wallet"])}


# ───────────── Pie 채팅 (라우터) ─────────────
_DISPUTE = re.compile(r"이의|이상해|이상한|잘못|오송금|틀렸|분쟁|조사|안\s*맞|환불|취소됐|안\s*왔|못\s*받")
_SETTLE = re.compile(r"나눠|나누|분담|더치|정산|적게|엔빵|n빵|반반|각자|균등|감면|내자|낼게")
_SHOP = re.compile(r"사고|살래|사려|구매|찾아|추천|공동구매|싸게|있어\?|비교|메뉴|배달|시켜|먹을|고기|과일|야식")

ROUTE_TOOL = {"name": "route", "description": "사용자 요청 분류", "parameters": {"type": "object", "properties": {
    "intent": {"type": "string", "enum": ["shop", "settle", "dispute", "ask"]}}, "required": ["intent"]}}
_QUESTION = re.compile(r"어디야|어디에|뭐야|무엇|왜|어떤\s*(게|거|가게|브랜드)|브랜드|가게|후기|맛있|칼로리|차이|설명|알려줘|궁금|\?$")


_FOLLOW = re.compile(r"^(알아서|아무거나|상관없|몰라|그냥|대충|응|ㅇㅇ|네|좋아|그걸로)|^\s*\d+\s*명|^\s*[\d,.]+\s*(만|천)?\s*원|^(예산|인원|1인|인당)")


def _is_followup(text: str) -> bool:
    """직전 검색에 대한 짧은 보충 답변인지 (예: '알아서', '4명이고 20만원')."""
    return len(text) <= 20 and bool(_FOLLOW.search(text.strip()))


def _route(text: str, history: list[dict[str, Any]], flow: str, use_llm: bool = True) -> tuple[str, list[dict[str, Any]]]:
    last_bot = next((h for h in reversed(history or []) if h.get("role") == "bot"), None)
    if last_bot and last_bot.get("needs_info") and last_bot.get("intent") in ("shop", "settle", "dispute"):
        return last_bot["intent"], [llm.code_step("chat.route", flow, "이전 질문 이어서")]
    if last_bot and last_bot.get("intent") == "shop" and _is_followup(text):
        return "shop", [llm.code_step("chat.route", flow, "이전 검색 이어서")]
    has_money0 = bool(re.search(r"\d[\d,.]*\s*(만|천)?\s*원|\d+\s*명|예산", text))
    if _QUESTION.search(text) and not has_money0 and not re.search(r"추천|찾아|사고\s*싶|시켜\s*줘|나눠", text):
        return "ask", [llm.code_step("chat.route", flow, "rule: 질문")]
    if _DISPUTE.search(text) and re.search(r"정산|송금|금액|결제|돈|공동구매|주문", text):
        return "dispute", [llm.code_step("chat.route", flow, "rule")]
    names = [u["short"] for u in store.users()] + ["진주", "진우", "민재", "지현"]
    split_signal = (any(n and n in text for n in names) or re.search(r"총\s*[\d,.]+\s*(만|천)?\s*원?\s*(을|를)|적게|더\s*내|감면|엔빵|n빵|더치|반반|각자\s*내", text))
    if _SETTLE.search(text) and split_signal and not re.search(r"찾아|추천|사고\s*싶|메뉴", text):
        return "settle", [llm.code_step("chat.route", flow, "rule")]
    has_money = bool(re.search(r"\d[\d,.]*\s*(만|천)?\s*원|\d+\s*만\b|(^|\s)(만|천)\s*원|예산|\d+\s*명", text))
    if _SHOP.search(text) or (has_money and not split_signal):
        return "shop", [llm.code_step("chat.route", flow, "rule")]
    if _SETTLE.search(text):
        return "settle", [llm.code_step("chat.route", flow, "rule")]
    if not use_llm:
        return "ask", [llm.code_step("chat.route", flow, "rule: 기타")]
    out, meta = llm.client.call_tool("chat.route", "Share Pie 요청을 shop(공동구매·배달 메뉴 찾기) settle(비용 나누기) "
                                     "dispute(정산 문제 이의제기) ask(그 외 질문·대화) 중 하나로 분류하라.", text, ROUTE_TOOL,
                                     mock=lambda: {"intent": "ask"}, flow=flow, max_tokens=300)
    return out.get("intent", "ask"), [meta]


def chat(message: str, history: list[dict[str, Any]] | None = None, context: dict[str, Any] | None = None,
         chat_id: str | None = None, user: str | None = None, scenario: str | None = None, edited: bool | None = None) -> dict[str, Any]:
    """1:1 Pie 한 턴. 베타: 턴 id·기능 예시(시나리오) id가 이 턴의 모든 Kiln 기록에 붙고, 동의한 사람의 턴은 비식별 저장."""
    sc = (beta.scenario(scenario) or {}).get("id")
    turn = beta.new_turn()
    with usage.tagged(turn=turn, scenario=sc, edited=bool(edited) if sc else None) as tg:
        out = _chat_turn(message, history, context, chat_id, user)
    for m in out.get("messages") or []:
        m["turn"] = turn                                 # 답마다 👍/👎를 받을 id
    out["beta"] = {"turn": turn, "scenario": sc, "tokens": tg["tokens"], "calls": tg["calls"]}
    try:
        beta.log_turn(quota.current_email(), channel="chat", flow=chat_id, turn=turn, sid=sc, edited=edited if sc else None,
                      text=message, history=[h.get("text") or "" for h in (history or [])[-4:]], replies=out.get("messages") or [],
                      tags=tg, names=[user or ""])
    except Exception as e:   # noqa: BLE001 — 기록 실패가 대화를 깨면 안 됨
        print(f"[beta] 기록 실패: {e}", flush=True)
    return out


def _chat_turn(message: str, history: list[dict[str, Any]] | None = None, context: dict[str, Any] | None = None,
               chat_id: str | None = None, user: str | None = None) -> dict[str, Any]:
    title = ""
    if user and chat_id:
        title = ((store.kv_get("chats", user) or {}).get(chat_id) or {}).get("title") or ""
    outer = usage.SCOPE.get() or {}
    with usage.scope("chat", title or outer.get("ctx") or (message or "").strip()[:24] or "Pie 대화"), quota.turn() as q:
        return _chat(message, history, context, chat_id, user, limited=q if q and q["blocked"] else None)


def _chat(message: str, history: list[dict[str, Any]] | None = None, context: dict[str, Any] | None = None,
          chat_id: str | None = None, user: str | None = None, limited: dict[str, Any] | None = None) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise ServiceError("BAD_REQUEST", "메시지가 비어 있어요", "chat")
    msgs = None
    history = history or []
    context = context or {}
    flow = chat_id or "chat-" + uuid.uuid4().hex[:6]
    user_hist = [h.get("text", "") for h in history if h.get("role") == "user"]

    if settlement.prohibited_reason(text):   # 지출 통제: 불법 목적 요청은 AI 호출 없이 코드에서 거절 (토큰 0)
        metas = [llm.code_step("chat.guard", flow, "PROHIBITED_PURPOSE")]
        intent, msgs = "ask", [{"from": "bot", "intent": "ask", "text": settlement.REFUSE_MSG, "refused": True}]
    elif context.get("settlement_id"):
        intent, metas = "dispute", [llm.code_step("chat.route", flow, "인증서에서 이의제기")]
    else:
        intent, metas = _route(text, history, flow, use_llm=not limited and not (llm.client.mode == "live" and config.PIE_CHAT == "agent"))
        if limited:   # 구독 한도: Kiln 없이 규칙 기반으로 (계산·결제는 코드라 그대로)
            metas.append(llm.code_step("chat.guard", flow, "0 tokens (code-only): AI 사용 한도 → 규칙 기반 응답"))
        elif llm.client.mode == "live" and config.PIE_CHAT == "agent" and intent not in ("settle", "dispute"):
            intent = "agent"   # 키가 있으면 고정 질문 없이 대화형 에이전트가 판단 (정산·이의제기 확정 신호만 전용 흐름)

    if intent == "agent":
        try:
            msgs = _chat_agent(text, history, user, flow, metas)
            intent = "shop" if any(m.get("compare") for m in msgs) else "ask"
        except llm.LLMError as e:
            metas.append(llm.code_step("assistant.fallback", flow, f"{e.code}: {e.message}"[:200]))
            intent = _route(text, history, flow, use_llm=False)[0]
    if msgs is not None:
        pass
    elif intent == "shop":
        last_bot = next((h for h in reversed(history) if h.get("role") == "bot"), None)
        follow = bool(last_bot and last_bot.get("intent") == "shop" and (last_bot.get("needs_info") or _is_followup(text)))
        ctx_hist = []
        if follow:  # 직전 '새 요청'까지만 거슬러 올라가 모은다 (이전의 다른 요청과 섞지 않음)
            for t in reversed(user_hist):
                ctx_hist.insert(0, t)
                if not _is_followup(t):
                    break
        msgs = _chat_shop(text, ctx_hist, flow, metas)
    elif intent == "settle":
        msgs = _chat_settle(text, user_hist, context, user, flow, metas)
    elif intent == "dispute":
        msgs = _chat_dispute(text, history, context, user, flow, metas)
    else:
        msgs = _chat_answer(text, history, flow, metas)

    if limited:
        msgs = [{"from": "bot", "intent": "ask", "text": quota.limit_text(limited), "limit": _limit_card(limited)}] + msgs
    line = llm.meta_line(metas)
    if limited and not any(m["mode"] in quota.AI_MODES for m in metas):
        line = "AI 사용 한도 도달 → 규칙 기반 응답 · AI 호출 0회 · 0 토큰"
    for mm in msgs:
        mm["meta"] = line
    return {"intent": intent, "messages": msgs, "usage": _usage_of(metas),
            "degraded": any(m["mode"] == "fallback" for m in metas), "limit": _limit_card(limited) if limited else None}


def _limit_card(st: dict[str, Any]) -> dict[str, Any]:
    """한도 안내에 붙는 값 (화면이 'AI 요금제' 버튼을 붙일 수 있게)."""
    return {"plan": st["plan"], "label": st["label"], "which": st["which"], "resetsAt": st["resetsAt"],
            "resetText": quota.when_text(st["resetsAt"])}


ANSWER_SYSTEM = """너는 공동구매·배달 공동주문·정산 앱 Share Pie의 도우미 Pie다. 이전 대화 맥락을 이어서 사용자의 질문에 한국어로 답한다.
- 앞에서 추천한 메뉴·상품의 가격 출처(판매처)를 물으면 대화에 나온 출처만 말한다. 모르면 모른다고 한다.
- 실제 브랜드·가게·가격·후기·최신 정보가 필요하면 need_search=true와 짧은 검색어(search_query)를 준다. 모르는 사실은 지어내지 않는다.
- answer는 검색 없이 답할 수 있을 때의 답(2~4문장). 과장·이모지 금지."""
ANSWER_TOOL = {"name": "answer_plan", "description": "답변 또는 검색 계획", "parameters": {"type": "object", "properties": {
    "need_search": {"type": "boolean"}, "search_query": {"type": ["string", "null"]}, "answer": {"type": "string"}},
    "required": ["need_search", "answer"]}}
ANSWER_WITH_WEB = """너는 Share Pie의 도우미 Pie다. 주어진 검색 결과(제목·요약·링크)만 근거로 질문에 한국어 3~5문장으로 답한다.
검색 결과에 없는 사실·가격은 지어내지 말고, 근거가 약하면 그렇다고 말한다. 이모지 금지."""


def _mock_answer(text: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    last = next((h.get("text", "") for h in reversed(history) if h.get("role") == "bot"), "")
    if re.search(r"브랜드|가게|어디", text) and re.search(r"세트|조합|메뉴|추천", last):
        src = re.findall(r"가격 출처: ([^)\n]+)", last)
        return {"need_search": False, "answer": (f"앞의 가격은 {', '.join(dict.fromkeys(src))} 기준이에요. " if src else
                "그 가게·브랜드 정보는 제가 확인한 게 없어요. ")
                + "실제 주문은 결제자가 배달앱에서 하고, 정산방에서 실제 결제 금액으로 나눠 드릴게요."}
    return {"need_search": False, "answer": "찾고 싶은 상품이나 나눌 비용을 편하게 말해 주세요.\n예: “총 12만원을 3명이 똑같이 나눠줘”"}


def _chat_answer(text, history, flow, metas):
    ctx = "\n".join(f"{'사용자' if h.get('role') == 'user' else 'Pie'}: {(h.get('text') or '')[:300]}" for h in (history or [])[-6:])
    user = (f"이전 대화:\n{ctx}\n\n" if ctx else "") + f"질문: {text}"
    plan, m = llm.client.call_tool("chat.answer", ANSWER_SYSTEM, user, ANSWER_TOOL,
                                   mock=lambda: _mock_answer(text, history), flow=flow, max_tokens=700)
    metas.append(m)
    answer = (plan.get("answer") or "").strip() or _mock_answer(text, history)["answer"]
    q = (plan.get("search_query") or "").strip()
    if plan.get("need_search") and q and websearch.any_enabled():
        try:
            res = (websearch.serper_web(q) if websearch.enabled_sources().get("serper") else []) or websearch.tavily(q)
        except Exception as e:  # noqa: BLE001
            res = []
            metas.append(llm.code_step("chat.search", flow, f"검색 실패 {type(e).__name__}"))
        res = [r for r in res if r.get("title")][:5]
        metas.append(llm.code_step("chat.search", flow, f"0 tokens (code-only): ‘{q}’ 웹 검색 {len(res)}건"))
        if res:
            facts = f"질문: {text}\n검색어: {q}\n" + "\n".join(
                f"- {r['title']} | {(r.get('text') or r.get('content') or r.get('snippet') or '')[:200]} | {r.get('url') or r.get('link')}" for r in res)
            out, m2 = llm.client.call_text("chat.answer", ANSWER_WITH_WEB, facts,
                                           mock=lambda: f"‘{q}’로 찾아본 결과예요: " + " / ".join(r["title"][:40] for r in res[:3]),
                                           flow=flow, max_tokens=700)
            metas.append(m2)
            links = "\n".join(f"· {r['title'][:40]} {r.get('url') or r.get('link') or ''}" for r in res[:3])
            return [{"from": "bot", "intent": "ask", "text": f"{out}\n\n출처\n{links}"}]
    return [{"from": "bot", "intent": "ask", "text": answer}]


def _chat_agent(text, history, user, flow, metas):
    u = store.user_by_short(user) if user else None
    out = assistant.run(text, history, user=user, flow=flow, metas=metas, address=(u or {}).get("address") or None)
    msgs = []
    if out["card"]:
        kind, r = out["card"]
        r = {**r, "explain": ""}
        if kind == "web":
            msgs.append(_chat_shop_web(r)[0])
        elif kind == "combo":
            msgs.append(_chat_shop_combo(r)[0])
        else:
            msgs.append(_catalog_card(r["query"], r["candidates"]))
        msgs[0]["text"] = _card_caption(kind, r)
    msgs.append({"from": "bot", "intent": "shop" if out["card"] else "ask", "text": out["text"]})
    return msgs


def _card_caption(kind, r) -> str:
    n = len(r["candidates"])
    if kind == "combo":
        lines = [f"{i + 1}) {c['label']}: {c['title']} · {won(c['total'])} (1인 {won(c['per'])}, 가격 출처: {c.get('source') or '검색 가격'})"
                 for i, c in enumerate(r["candidates"])]
        return (f"금액·인분·예산을 코드로 검증한 조합 {n}개예요." + (f" (탈락: {', '.join(x for x in r['rejected'] if x)})" if r.get("rejected") else "")
                + "\n" + "\n".join(lines))
    if kind == "web":
        st = r["web"]["stats"]
        src = ", ".join(f"{_SRC_KO.get(k, k)} {v}건" for k, v in st.items() if v and k != "context")
        return f"여러 사이트에서 찾은 후보 {n}개예요 ({src or '결과 적음'})."
    return f"Share Pie 공동구매 후보 {n}개예요 (배송비 포함 1인 비용 기준)."


def _catalog_card(q, cands) -> dict[str, Any]:
    n = q.get("people") or 0
    return {
        "from": "bot", "intent": "shop", "text": _shop_header(q, len(cands)),
        "compare": [c["id"] for c in cands], "n": n or 1, "best": cands[0]["id"],
        "products": {c["id"]: shopping.product_public(c) for c in cands},
        "compareData": [{"id": c["id"], "per": ("약 " + won(c["eval"]["per"])) if n else won(c["eval"]["total"]),
                         "perLabel": "1인 예상" if n else "총액", "packs": c["eval"]["packs"], "total": c["eval"]["total"],
                         "within": c["eval"]["within"]} for c in cands],
        "shopQuery": {"people": n, "title": _shop_title(q)},
    }


def _chat_shop(text, user_hist, flow, metas):
    r = shopping.run(text, history=user_hist, flow=flow)
    metas += r["metas"]
    if r["status"] == "ok_combo":
        return _chat_shop_combo(r)
    if r["status"] == "need_info":
        return [{"from": "bot", "text": r["question"], "intent": "shop", "needs_info": True}]
    if r["status"] == "no_match":
        return [{"from": "bot", "intent": "shop", "text": r["advice"]}]
    if r["status"] == "ok_web":
        return _chat_shop_web(r)
    q, cands = r["query"], r["candidates"]
    n = q.get("people") or 0
    return [{
        "from": "bot", "intent": "shop", "text": _shop_header(q, len(cands)),
        "compare": [c["id"] for c in cands], "n": n or 1, "best": cands[0]["id"],
        "products": {c["id"]: shopping.product_public(c) for c in cands},
        "compareData": [{"id": c["id"], "per": ("약 " + won(c["eval"]["per"])) if n else won(c["eval"]["total"]),
                         "perLabel": "1인 예상" if n else "총액", "packs": c["eval"]["packs"], "total": c["eval"]["total"],
                         "within": c["eval"]["within"]} for c in cands],
        "shopQuery": {"people": n, "title": _shop_title(q)},
    }, {"from": "bot", "intent": "shop", "text": r["explain"]}]


_SRC_KO = {"naver": "네이버쇼핑", "serper": "구글 쇼핑", "coupang": "쿠팡", "page": "상품 페이지", "web_text": "웹", "tavily": "웹 검색"}


def _chat_shop_web(r) -> list[dict[str, Any]]:
    q, cands, got = r["query"], r["candidates"], r["web"]
    n = q.get("people") or 0
    st = got["stats"]
    src = [f"{_SRC_KO.get(k, k)} {v}건" for k, v in st.items() if v and k != "context"]
    off = [k for k, on in got["sources"].items() if not on]
    head = (f"‘{q.get('product_query')}’을(를) {len(got['queries'])}가지 검색어로 여러 사이트에서 찾았어요 ({', '.join(src) or '결과 적음'}). "
            + (f"총 {won(q['budget_total'])} " if q.get("budget_total") else "")
            + (f"· {n}명 " if n else "") + f"기준으로 성격이 다른 {len(cands)}개를 골랐어요."
            + (f"\n(꺼진 소스: {', '.join(off)} — 키를 넣으면 더 넓게 찾아요)" if off else ""))
    data = []
    for c in cands:
        per = (f"약 {won(c['per'])}" if c.get("per") else (f"{c['units']}개 · {won(c['total'])}" if c.get("budget") else won(c["price"])))
        data.append({"id": c["id"], "per": per, "perLabel": "1인 예상" if c.get("per") else ("예산 내 구매" if c.get("budget") else "가격"),
                     "col2Label": "판매처", "col2": c["mall"][:12],
                     "col3Label": "개당" if c.get("qty") else "가격 근거",
                     "col3": won(round(c["ppp"])) if c.get("qty") else ("구조화" if c["verified"] else "확인 필요"),
                     "packs": c.get("units") or 1, "total": c.get("total") or c["price"], "within": c.get("within", True),
                     "version": shopping.VERSION_KO[c["version"]], "url": c.get("url"), "trusted": c["trusted"]})
    warn = [c for c in cands if not c["trusted"]]
    tail = ("\n⚠️ 허용 판매처가 아닌 후보가 있어요: " + ", ".join(c["mall"] for c in warn) + " → 이 상품으로 정산하면 지출 통제로 중단돼요.") if warn else ""
    if not n and not q.get("budget_total") and not q.get("budget_per_person"):
        head += "\n인원과 예산을 알려주시면 예산 안에서 몇 개 살 수 있는지, 1인당 얼마인지도 계산해 드릴게요."
    return [{"from": "bot", "intent": "shop", "text": head, "compare": [c["id"] for c in cands], "n": n or 1,
             "best": cands[0]["id"], "products": {c["id"]: shopping.web_product_public(c, q.get("allowed_malls")) for c in cands},
             "compareData": data, "shopQuery": {"people": n, "title": _shop_title(q)}},
            {"from": "bot", "intent": "shop", "text": r["explain"] + tail}]


def _chat_shop_combo(r) -> list[dict[str, Any]]:
    q, cands, budget = r["query"], r["candidates"], r.get("budget")
    n = q.get("people") or 4
    head = (f"배달 {n}명" + (f" · 총 {won(budget)} 이내" if budget else "")
            + (f" · 1인 {won(budget // n)} 이하" if budget else "")
            + f" 조건으로 AI가 메뉴 조합을 짜고, 코드가 인분·배달비·예산을 검증해 {len(cands)}개를 골랐어요."
            + (f" (예산·인원 조건에 안 맞아 뺀 AI 조합: {', '.join(r['rejected'])})" if r.get("rejected") else ""))
    data = [{"id": c["id"], "per": f"약 {won(c['per'])}", "perLabel": "1인 예상", "col2Label": "구성", "col2": f"{c['serves']}인분",
             "col3Label": "남는 예산" if budget else "배달비", "col3": won(budget - c["total"]) if budget else won(c["fee"]),
             "packs": 1, "total": c["total"], "within": c["within"], "version": c["label"], "url": None, "trusted": True}
            for c in cands]
    return [{"from": "bot", "intent": "shop", "text": head, "compare": [c["id"] for c in cands], "n": n,
             "best": cands[0]["id"], "products": {c["id"]: shopping.combo_product_public(c) for c in cands},
             "compareData": data, "shopQuery": {"people": n, "title": f"배달 조합 · {n}명"}},
            {"from": "bot", "intent": "shop", "text": r["explain"] + "\n(가격은 검색한 판매가 기준 — 배달앱 실제 가격·배달비는 가게마다 달라요)"}]


def _shop_title(q) -> str:
    kw = [k for k in (q.get("keywords") or []) if k != "모임"]
    base = q.get("product_query") or (kw[0] if kw else shopping.CAT_KO.get(q.get("category"), "상품"))
    return f"{base} · {q['people']}명" if q.get("people") else base


def _shop_header(q, k) -> str:
    cond = [f"{shopping.CAT_KO.get(q.get('category'), '상품')}"]
    if q.get("people"):
        cond.append(f"{q['people']}명")
    bpp = shopping.budget_per_person(q)
    if q.get("budget_total"):
        cond.append(f"총 {won(q['budget_total'])} 이내")
    if bpp:
        cond.append(f"1인 {won(bpp)} 이하")
    if q.get("near_only"):
        cond.append("근처 픽업")
    return " · ".join(cond) + f" 조건으로 {k}개를 1인당 비용(배송·배달비 포함) 기준으로 비교했어요."


def _chat_settle(text, user_hist, context, user, flow, metas):
    r = settlement.calculate(text=text, members=context.get("members") or [], total=context.get("total"),
                             payer=context.get("payer") or user, subject=context.get("subject"),
                             history=user_hist, flow=flow)
    metas += r["metas"]
    if r["status"] != "ok":
        return [{"from": "bot", "text": r["question"], "intent": "settle", "needs_info": True}]
    ex, m = settlement.explain(r, r.get("subject"), flow)
    metas.append(m)
    return [{"from": "bot", "intent": "settle", "text": ex, "split": r["shares"],
             "groupName": r.get("subject") or "공동 정산", "settle": _settle_payload(r)}]


def _chat_dispute(text, history, context, user, flow, metas):
    sid = context.get("settlement_id")
    last_bot = next((h for h in reversed(history) if h.get("role") == "bot"), None)
    asked = bool(last_bot and last_bot.get("needs_info") and last_bot.get("intent") == "dispute")
    pending = PENDING_DISPUTE.get(flow) if asked else None
    rec = store.get(sid) if sid else (store.get(pending) if pending else _find_settlement(text, user))
    if not rec:
        return [{"from": "bot", "intent": "dispute",
                 "text": "이의를 제기할 정산을 찾지 못했어요. 정산 탭 → 인증서 → ‘AI 분쟁 조사 요청’으로 시작해 주세요."}]
    rec = _refresh(rec)
    if not sid and not pending:
        # 채팅 문장만으로 되돌릴 수 없는 이의제기(체인 기록·환불)를 바로 실행하지 않고, 어떤 정산인지 먼저 확인
        PENDING_DISPUTE[flow] = rec["id"]
        return [{"from": "bot", "intent": "dispute", "needs_info": True,
                 "text": f"‘{rec['name']}’ 정산({won(rec['total'])}, 결제자 {rec['payer']})에 이의제기를 할까요? "
                         "맞으면 무엇이 문제였는지 한 번 더 구체적으로 적어 주세요. 아니면 ‘취소’라고 해 주세요."}]
    if pending:
        PENDING_DISPUTE.pop(flow, None)
        if re.fullmatch(r"\s*(아니|아니요|아뇨|취소|됐어|괜찮아|ㄴㄴ)[.!]?\s*", text):
            return [{"from": "bot", "intent": "dispute", "text": "알겠어요. 이의제기는 하지 않았어요."}]
    if context.get("dispute") == "start" and not asked:
        state = {"locked": f"지금은 이의제기 가능 시간이에요 (결제자 지급 전 · {_left(rec)} 남음).",
                 "disputed": "이미 이의제기가 접수돼 조사 중이에요.", "paid": "이미 결제자에게 지급이 끝난 정산이에요. 기록 조사만 할 수 있어요.",
                 "open": "아직 전원 예치 전이라 정산이 진행 중이에요.", "blocked": "지출 통제로 중단된 정산이에요.",
                 "refunded": "이미 환불로 종료된 정산이에요."}.get(rec["status"], "")
        return [{"from": "bot", "intent": "dispute", "needs_info": True,
                 "text": f"‘{rec['name']}’ 정산({won(rec['total'])})을 조사할게요. {state}\n어떤 문제가 있었나요? 구체적으로 적어 주세요. (예: 공동구매가 품절로 취소됐어요 / 제 몫이 합의한 금액과 달라요)"}]
    out = dispute_full(rec["id"], user or "", text, flow=flow)
    metas += out.pop("_metas", [])
    return [{"from": "bot", "intent": "dispute", "text": out["message"], "verdict": out.get("verdict"),
             "verdictReason": out.get("verdictReason") or "", "settlementId": rec["id"]}]


def _left(rec) -> str:
    s = max(0, int((rec.get("release_at") or 0) - time.time()))
    return f"{s // 60}분 {s % 60}초" if s >= 60 else f"{s}초"


def _settle_payload(r) -> dict[str, Any]:
    return {"total": r["total"], "payer": r["payer"], "members": r["members"], "shares": r["shares"],
            "ruleText": r["rule_text"], "purpose": r["purpose"], "perPersonCap": r["rule"].get("per_person_cap"),
            "totalCap": r["rule"].get("total_cap"), "warnings": r["warnings"], "subject": r.get("subject")}


def _usage_of(metas) -> dict[str, Any]:
    return {"llm_calls": sum(1 for m in metas if m["mode"] in ("tools", "json", "text")),
            "total_tokens": sum(m["total_tokens"] for m in metas),
            "latency_ms": sum(m["latency_ms"] for m in metas), "steps": metas}


# ───────────── 정산 코어 Stage 1 / 2 / 3 ─────────────
def analyze(text: str, members: list[str], total: int | None = None, payer: str | None = None,
            subject: str | None = None, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    """Stage 1 + 2 (분석 → 코드 계산). 조건이 바뀌면 매번 새 JSON으로 다시 호출하면 된다 (다턴)."""
    if not text:
        raise ServiceError("BAD_REQUEST", "분담 조건 문장이 필요해요", "settlement.analyze")
    r = settlement.calculate(text=text, members=members or [], total=total, payer=payer, subject=subject,
                             history=history, flow=flow)
    out = {"status": r["status"], "rule": r.get("rule"), "usage": _usage_of(r["metas"]), "meta": llm.meta_line(r["metas"])}
    if r["status"] == "ok":
        out.update(_settle_payload(r))
    else:
        out["question"] = r["question"]
    return out


def calculate_only(total: int, members: list[str], adjustments: list[dict[str, Any]], payer: str | None = None,
                   per_person_cap: int | None = None, total_cap: int | None = None, flow: str | None = None) -> dict[str, Any]:
    """Stage 2 단독 — 규칙 JSON을 받아 코드로만 계산 (0 tokens)."""
    try:
        adjustments = settlement.normalize_rule({"adjustments": adjustments or []}, members)["adjustments"]
        shares = money.compute_shares(int(total), members, adjustments)
    except money.CalcError as e:
        raise ServiceError(e.code, e.message, "settlement.calculate") from e
    llm.code_step("settlement.calculate", flow, "0 tokens (code-only)")
    pre = money.policy_check(total=int(total), shares=shares, payer=payer, per_person_cap=per_person_cap, total_cap=total_cap)
    return {"total": int(total), "shares": [[n, a] for n, a in shares], "warnings": [v.to_dict() for v in pre],
            "tokens": 0}


def explain_result(result: dict[str, Any], subject: str | None = None, flow: str | None = None) -> dict[str, Any]:
    r = {"total": result["total"], "payer": result.get("payer") or result["shares"][0][0], "shares": result["shares"],
         "rule_text": result.get("ruleText") or result.get("rule_text") or "",
         "rule": {"adjustments": (result.get("rule") or {}).get("adjustments") or [],
                  "per_person_cap": result.get("perPersonCap"), "total_cap": result.get("totalCap")},
         "warnings": result.get("warnings") or [], "subject": subject}
    text, m = settlement.explain(r, subject, flow)
    return {"message": text, "meta": llm.meta_line([m]), "usage": _usage_of([m])}


def calculate(text: str, members: list[str], total: int | None = None, payer: str | None = None,
              subject: str | None = None, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    """그룹 채팅용 한 번에: Stage1 → Stage2 → Stage3."""
    out = analyze(text, members, total, payer, subject, history, flow)
    if out["status"] == "ok":
        ex = explain_result(out, subject or out.get("subject"), flow)
        out["message"] = ex["message"]
        out["meta"] = llm.meta_line(out["usage"]["steps"] + ex["usage"]["steps"])
        out["usage"] = _usage_of(out["usage"]["steps"] + ex["usage"]["steps"])
    return out


# ───────────── 정산 요청 대기 (지갑·잔액이 준비되면 자동 시작) ─────────────
# 확인 카드까지 끝났는데 누가 지갑을 안 연결했거나 PIE가 모자라면, 요청을 방에 보관했다가
# 그 사람이 지갑을 연결·충전하는 순간 서버가 자동으로 온체인 정산을 시작한다 (다시 누를 버튼을 찾을 필요 없음).
def _rule_violations(kw: dict[str, Any]) -> list[Any]:
    """잔액과 무관한 지출 통제 규칙(합계·총예산·1인 한도·허용 판매처)만 미리 검사 — propose()와 같은 기준."""
    try:
        shares = [(n, int(a)) for n, a in kw.get("shares") or []]
        return money.policy_check(total=int(kw.get("total") or 0), shares=shares, payer=None,
                                  per_person_cap=kw.get("per_person_cap"), total_cap=kw.get("total_cap"),
                                  merchant=kw.get("merchant") or "Share Pie 공동구매",
                                  allowed_merchants=kw.get("allowed_merchants") or config.ALLOWED_MERCHANTS, available=None)
    except (TypeError, ValueError):
        return []


def _not_ready(kw: dict[str, Any]) -> tuple[list[str], list[str]]:
    no_wallet = [n for n in kw["members"] if not store.get_member(n)]
    short: list[str] = []
    if not no_wallet:
        ch = _chain()
        for n, a in kw["shares"]:
            if int(a) <= 0 or (n == kw["payer"] and not kw.get("purchase")):
                continue
            try:
                acc = ch.account(store.get_member(n)["wallet"])
                if acc["balance"] - (acc["committed"] - acc["escrow"]) < int(a):
                    short.append(n)
            except Exception:   # noqa: BLE001 — 체인을 못 읽으면 기다리지 않고 요청 (지출 통제가 판단)
                pass
    return no_wallet, short


def _pending_text(no_wallet: list[str], short: list[str]) -> str:
    parts = []
    if no_wallet:
        parts.append(f"지갑 연결 필요: {', '.join(no_wallet)} (MY 탭 → ‘지갑 연결’)")
    if short:
        parts.append(f"PIE 충전 필요: {', '.join(short)} (MY 탭 → ‘PIE 충전’)")
    return " · ".join(parts)


def propose_request(requester: str | None = None, **kw) -> dict[str, Any]:
    """앱의 ‘정산 요청’. 준비가 안 된 멤버가 있으면 방에 보관하고(자동 시작 대기) 안내만 돌려준다."""
    gid = kw.get("group_id")
    if gid and store.kv_get("groups", gid):
        no_wallet, short = _not_ready(kw)
        rule_bad = _rule_violations(kw)   # 한도·허용 판매처 위반은 충전해도 안 풀리니 기다리지 않고 바로 중단
        if rule_bad and no_wallet:
            raise ServiceError("POLICY_BLOCKED", f"지출 통제로 정산할 수 없어요: {rule_bad[0].message}", "settlement.request", 409)
        if (no_wallet or short) and not rule_bad:
            return _hold(gid, kw, no_wallet, short, requester)
    rec = propose(**kw)
    if gid:
        _room_started(gid, rec)
    return rec


@_locked
def _hold(gid: str, kw: dict[str, Any], no_wallet: list[str], short: list[str], requester: str | None) -> dict[str, Any]:
    g = store.kv_get("groups", gid)
    first = not g.get("pendingPropose")
    g["pendingPropose"] = {"kw": kw, "noWallet": no_wallet, "short": short, "by": requester, "at": time.time()}
    g["v"] += 1
    _sys(g, f"⏳ 정산 준비 중 — {_pending_text(no_wallet, short)}. 준비되면 Pie가 자동으로 온체인 정산을 시작해요 (다시 누를 필요 없어요).")
    store.kv_put("groups", gid, g)
    if first:
        for n in no_wallet + short:
            notify_short(n, "정산", f"{g['name']} · 정산을 시작하려면 {'지갑 연결' if n in no_wallet else 'PIE 충전'}이 필요해요. MY 탭에서 해 주세요.",
                         go=["tab", "my"], action=True, key=f"ready:{gid}")
    return {"status": "waiting", "groupId": gid, "noWallet": no_wallet, "short": short, "message": _pending_text(no_wallet, short)}


def _room_started(gid: str, rec: dict[str, Any]) -> None:
    with STATE_LOCK:
        g = store.kv_get("groups", gid)
        if not g:
            return
        had = bool(g.pop("pendingPropose", None))
        g["sid"], g["v"] = rec["id"], g["v"] + 1
        if rec["status"] == "blocked":
            g["status"] = "중단됨"
            if had:
                _sys(g, f"⛔ 지출 통제로 중단됐어요: {(rec.get('blocked') or {}).get('message', '')}")
        else:
            g["status"] = "승인 대기"
            if had:
                _sys(g, "✅ 모두 준비돼서 Pie가 온체인 정산을 시작했어요. 각자 ‘내 몫 결제하기’를 눌러 주세요.")
        store.kv_put("groups", gid, g)


def retry_pending(names: list[str] | None = None) -> list[str]:
    """지갑 연결·충전 뒤 호출: 이 사람들이 기다리던 정산 요청 중 준비된 것을 시작한다."""
    started = []
    for gid, g in list(store.kv_all("groups").items()):
        pp = (g or {}).get("pendingPropose")
        if not pp or (names and not set(names) & set(pp["kw"]["members"])):
            continue
        no_wallet, short = _not_ready(pp["kw"])
        if no_wallet or short:
            if (no_wallet, short) != (pp.get("noWallet"), pp.get("short")):
                with STATE_LOCK:
                    g2 = store.kv_get("groups", gid)
                    g2["pendingPropose"].update(noWallet=no_wallet, short=short)
                    _sys(g2, f"⏳ 아직 준비 중 — {_pending_text(no_wallet, short)}")
                    g2["v"] += 1
                    store.kv_put("groups", gid, g2)
            continue
        try:
            rec = propose(**pp["kw"])
            _room_started(gid, rec)
            started.append(gid)
        except ServiceError as e:
            with STATE_LOCK:
                g2 = store.kv_get("groups", gid)
                g2.pop("pendingPropose", None)
                _sys(g2, f"⚠️ 자동 정산 시작 실패: {e.message} · 조건을 다시 말해 주세요.")
                g2["v"] += 1
                store.kv_put("groups", gid, g2)
    return started


# ───────────── 온체인 정산 요청 (에이전트 지갑이 서명) ─────────────
_KO_MAN = re.compile(r"(?:^|[\s\d일이삼사오육칠팔구십백천])만(?=[\s\d원이삼사오육칠팔구천백십]|$)")   # 숫자로서의 '만' (만나·만들 제외)
_KO_EOK = re.compile(r"(?:^|[\s\d일이삼사오육칠팔구십백천])억(?=[\s\d원이삼사오육칠팔구천백십만]|$)")


def _amount_sanity(rule_text: str, total: int) -> None:
    """[blockchain 담당] 가드 A — 한글 금액 오파싱 방어. 문장에 숫자 '만'이 있는데 총액이 1만 미만이거나(예: '만2천원'→2,000),
    '억'이 있는데 1억 미만이면 잘못 읽힌 것이 거의 확실하다. 온체인에 올리면 되돌리는 데 이의제기·환불(가스)이 필요하므로 등록 전에 거부한다."""
    t = rule_text or ""
    bad = None
    if _KO_EOK.search(t) and total < 100_000_000:
        bad = "억"
    elif _KO_MAN.search(t) and total < 10_000:
        bad = "만"
    if bad:
        raise ServiceError("AMOUNT_SUSPECT",
                           f"총액이 {total:,}원으로 읽혔는데 문장에 '{bad}' 단위가 있어요. 금액을 숫자로 다시 말해 주세요 (예: 12000원).",
                           "settlement.request", 409, {"total": total, "unit": bad})


@_locked
def propose(*, group_name: str, members: list[str], shares: list[list[Any]], total: int, payer: str,
            rule_text: str = "", purpose: str = "", per_person_cap: int | None = None, total_cap: int | None = None,
            merchant: str | None = None, group_id: str | None = None, mode: str | None = None,
            allowed_merchants: list[str] | None = None, purchase: bool = False,
            product: dict[str, Any] | None = None) -> dict[str, Any]:
    bad = settlement.prohibited_reason(" ".join(str(x or "") for x in (group_name, rule_text, purpose, merchant, (product or {}).get("name"))))
    if bad:   # 지출 통제: 불법 목적(자금세탁 등) 정산·구매는 온체인에 올리지 않는다
        raise ServiceError("PROHIBITED_PURPOSE", settlement.REFUSE_MSG, "settlement.request", 403)
    ch = _chain()
    share_map = {n: int(a) for n, a in shares}
    if set(share_map) != set(members):
        raise ServiceError("BAD_REQUEST", "members와 shares의 이름이 달라요", "settlement.request")
    _amount_sanity(rule_text, int(total))   # [blockchain 담당] 가드 A — 오파싱된 총액을 온체인에 올리지 않는다
    if payer not in members:
        raise ServiceError("BAD_REQUEST", "결제자(payer)는 참여자 중 한 명이어야 해요", "settlement.request")
    if share_map.get(payer, 0) < 0:
        raise ServiceError("BAD_REQUEST", "결제자 부담액이 음수예요", "settlement.request")
    # 결제자는 0원 가능 ('진주 빼고 둘이 나눠') — 단 AI 구매 대행은 결제자도 각자 몫을 인출당하므로 0원이면 뺌
    zero = [n for n, a in share_map.items() if a <= 0 and (purchase or n != payer)]
    if zero:
        raise ServiceError("BAD_REQUEST", f"부담액이 0원인 멤버는 빼고 요청해 주세요: {', '.join(zero)}", "settlement.request")
    missing = [n for n in members if not store.get_member(n)]
    if missing:
        raise ServiceError("MEMBER_WALLET_MISSING", f"지갑을 연결하지 않은 멤버가 있어요: {', '.join(missing)}. "
                           "각자 MY 탭 → ‘지갑 연결’을 먼저 눌러 주세요.", "settlement.request", 409, {"names": missing})
    wallets = {n: store.get_member(n)["wallet"] for n in members}

    sid = "sp-" + uuid.uuid4().hex[:10]
    cid = ch.settlement_id(sid)
    ordered = [(n, share_map[n]) for n in members]
    onchain = [(n, a) for n, a in ordered if a > 0]   # 0원 결제자는 체인 멤버에서 제외 (받는 사람으로만)
    merchant = merchant or "Share Pie 공동구매"
    shop = merchant_account(merchant) if purchase else None   # AI 구매 대행: 가맹점 지갑(데모)으로 결제

    available = {}
    for n in members:
        acc = _wrap_chain(lambda n=n: ch.account(wallets[n]), "chain.read")
        available[n] = acc["balance"] - (acc["committed"] - acc["escrow"])
    violations = money.policy_check(total=int(total), shares=ordered, payer=None if purchase else payer, per_person_cap=per_person_cap,
                                    total_cap=total_cap, merchant=merchant, allowed_merchants=allowed_merchants or config.ALLOWED_MERCHANTS,
                                    available=available)
    llm.code_step("settlement.policy", sid, f"0 tokens (code-only): {len(violations)} violations")
    clean_purpose = settlement.sanitize_purpose(purpose, members, f"{group_name} 분담금")

    rec = {"id": sid, "group_id": group_id, "chain_id": cid, "name": group_name, "total": int(total), "payer": payer,
           "payer_wallet": wallets[payer], "rule_text": rule_text or f"{mode or '균등'} 분배", "purpose": clean_purpose,
           "per_person_cap": per_person_cap, "total_cap": total_cap, "merchant": merchant, "mode": mode,
           "allowed_merchants": allowed_merchants or None,
           "members": [{"name": n, "wallet": wallets[n], "share": a, "state": "payee" if (n == payer and not purchase) else "wait"}
                       for n, a in ordered],
           "purchase": ({"merchant": shop["name"], "merchantWallet": shop["wallet"], "va": _virtual_account(cid),
                         "status": "approving", "product": product or {}, "orderNo": None} if purchase else None),
           "ai_shares": [[n, a] for n, a in ordered], "available_at_check": available,
           "violations": [v.to_dict() for v in violations], "status": "open", "blocked": None, "dispute": None,
           "release_at": 0, "txs": [], "events": [], "created_at": time.time(), "network": ch.info()["network"]}

    if purchase:
        rec["mode"] = "purchase"
    if violations:
        v = violations[0]
        tx = _wrap_chain(lambda: ch.block_settlement(cid, wallets.get(v.member) if v.member else wallets[payer],
                                                      v.reason_code, v.chain_note()), "chain.block")
        rec["status"] = "blocked"
        rec["blocked"] = {**v.to_dict(), "tx_hash": tx["tx_hash"], "block": tx["block"], "url": ch.explorer_tx(tx["tx_hash"])}
        _log_tx(rec, "block", tx, ch)
    else:
        if purchase:
            tx = _wrap_chain(lambda: ch.create_purchase(cid, shop["wallet"], [wallets[n] for n, _ in onchain],
                                                        [a for _, a in onchain], ch.condition_hash(rec["rule_text"]),
                                                        clean_purpose), "chain.create")
        else:
            tx = _wrap_chain(lambda: ch.create_settlement(cid, wallets[payer], [wallets[n] for n, _ in onchain],
                                                      [a for _, a in onchain], ch.condition_hash(rec["rule_text"]),
                                                      clean_purpose), "chain.create")
        _log_tx(rec, "create", tx, ch)
        _apply_events(rec, tx["events"], ch)
    store.put(rec)
    if group_id and rec["status"] != "blocked":
        _listing_set(group_id, "closed", "정산 시작")      # 정산이 시작되면 동네 모집도 마감
    return public(_refresh(rec))


# ───────────── AI 구매 대행 (가상 결제 계좌 → 가맹점 자동 결제) ─────────────
def _merchant_key(name: str) -> str:
    """'쿠팡 로켓배송'·'Coupang' 등 → 허용 가맹점 목록의 대표 이름 (같은 가맹점은 같은 지갑)."""
    for a in config.ALLOWED_MERCHANTS:
        if money.merchant_allowed(name, [a]):
            return a
    return (name or "Share Pie 공동구매").strip()[:30]


def merchant_account(name: str) -> dict[str, Any]:
    """가맹점별 데모 지갑 (테스트넷 전용). 처음 결제받을 때 서버가 자동으로 만든다."""
    key = _merchant_key(name)
    acc = store.kv_get("merchants", key)
    if not acc:
        try:
            from eth_account import Account
            a = Account.create()
            acc = {"name": key, "wallet": a.address, "private_key": a.key.hex(), "note": "테스트넷 데모 가맹점 지갑"}
        except Exception:  # noqa: BLE001
            acc = {"name": key, "wallet": "0x" + secrets.token_hex(20), "note": "모의 체인 데모 가맹점 지갑"}
        acc["created_at"] = time.time()
        store.kv_put("merchants", key, acc)
    return {"name": acc["name"], "wallet": acc["wallet"]}


def _virtual_account(cid: str) -> str:
    """정산 건마다 생기는 가상 결제 계좌 번호 (컨트랙트의 정산 id에서 만든 표시용 번호)."""
    n = int(hashlib.sha256(cid.encode()).hexdigest()[:15], 16)
    d = f"{n % 10**12:012d}"
    return f"SP-{d[:4]}-{d[4:8]}-{d[8:]}"


def _auto_purchase(rec: dict[str, Any], on: dict[str, Any]) -> None:
    """전원이 '내 몫 인출'을 승인하면 AI가 지출 통제를 다시 확인한 뒤 자동으로 인출·결제한다."""
    pur = rec.get("purchase") or {}
    if pur.get("status") != "approving" or on.get("status") != "open":
        return
    states = [m.get("state") for m in on.get("members", [])]
    if not states or any(x != "approved" for x in states):
        return
    ch = _chain()
    shares = [(m["name"], m["share"]) for m in rec["members"] if m["share"] > 0]
    available = {}
    for m in rec["members"]:
        if m["share"] > 0:
            acc = _wrap_chain(lambda m=m: ch.account(m["wallet"]), "chain.read")
            available[m["name"]] = acc["balance"]   # 인출 직전 실제 잔액
    violations = money.policy_check(total=rec["total"], shares=shares, payer=None, per_person_cap=rec.get("per_person_cap"),
                                    total_cap=rec.get("total_cap"), merchant=pur.get("merchant"),
                                    allowed_merchants=rec.get("allowed_merchants") or config.ALLOWED_MERCHANTS, available=available)
    llm.code_step("purchase.policy", rec["id"], f"0 tokens (code-only): 결제 직전 재검사 {len(violations)} violations")
    if violations:
        v = violations[0]
        wal = next((m["wallet"] for m in rec["members"] if m["name"] == v.member), rec["payer_wallet"])
        tx = _wrap_chain(lambda: ch.block_settlement(rec["chain_id"], wal, v.reason_code, v.chain_note()), "chain.block")
        rec["status"] = "blocked"
        rec["blocked"] = {**v.to_dict(), "message": "결제 직전 검사에서 중단: " + v.message, "tx_hash": tx["tx_hash"],
                          "block": tx["block"], "url": ch.explorer_tx(tx["tx_hash"])}
        pur["status"] = "blocked"
        _log_tx(rec, "block", tx, ch)
        _apply_events(rec, tx["events"], ch)
        return
    order_no = time.strftime("SP%Y%m%d-") + secrets.token_hex(3).upper()
    order_ref = "0x" + hashlib.sha256(order_no.encode()).hexdigest()
    tx = _wrap_chain(lambda: ch.execute_purchase(rec["chain_id"], order_ref), "chain.purchase")
    _log_tx(rec, "purchase", tx, ch)
    _apply_events(rec, tx["events"], ch)
    pur.update({"status": "paid", "orderNo": order_no, "orderRef": order_ref, "paidAt": time.time(),
                "txHash": tx["tx_hash"], "url": ch.explorer_tx(tx["tx_hash"])})
    rec["purchase"] = pur
    llm.code_step("purchase.execute", rec["id"], f"0 tokens (code-only): {len(shares)}명 지갑에서 인출 → {pur.get('merchant')} {rec['total']}원 결제")


@_locked
def cancel_settlement(sid: str, name: str) -> dict[str, Any]:
    """전원 예치 전(open)에 멈춘 정산을 결제자가 취소 → 이미 예치한 사람은 컨트랙트가 즉시 환불 (자금 묶임 방지)."""
    rec = _refresh(_get(sid))
    if name != rec["payer"]:
        raise ServiceError("FORBIDDEN", "정산 취소는 결제자만 할 수 있어요.", "settlement.cancel", 403)
    if rec["status"] != "open":
        raise ServiceError("NOT_CANCELLABLE", "전원 예치 전(진행 중)인 정산만 취소할 수 있어요. 예치가 끝났다면 이의제기를 이용해 주세요.",
                           "settlement.cancel", 409, {"status": rec["status"]})
    ch = _chain()
    tx = _wrap_chain(lambda: ch.block_settlement(rec["chain_id"], rec["payer_wallet"], 9, "cancelled by payer"), "chain.block")
    _log_tx(rec, "block", tx, ch)
    _apply_events(rec, tx["events"], ch)
    rec["status"] = "blocked"
    rec["blocked"] = {"code": "CANCELLED", "reason_code": 9, "member": name, "message": "결제자가 정산을 취소했어요 (예치금은 환불)",
                      "tx_hash": tx["tx_hash"], "block": tx["block"], "url": ch.explorer_tx(tx["tx_hash"])}
    store.put(rec)
    return public(_refresh(rec))


def _log_tx(rec, kind, tx, ch, member=None):
    if any(t["tx_hash"] == tx["tx_hash"] and t["kind"] == kind and t.get("member") == member for t in rec["txs"]):
        return
    rec["txs"].append({"kind": kind, "tx_hash": tx["tx_hash"], "block": tx["block"], "url": ch.explorer_tx(tx["tx_hash"]),
                       "member": member, "at": time.time()})


_KIND = {"Locked": "lock", "OfflinePaid": "offline", "FullyLocked": "escrow", "Paid": "paid", "Refunded": "refund",
         "DisputeRaised": "dispute", "DisputeResolved": "resolve", "Blocked": "block",
         "PurchaseApproved": "approve", "Withdrawn": "withdraw", "PurchaseExecuted": "purchase"}


def _apply_events(rec, events, ch):
    known = {(e["tx_hash"], e["event"], str(e["args"].get("member") or e["args"].get("from"))) for e in rec["events"]}
    for e in events:
        key = (e["tx_hash"], e["event"], str(e["args"].get("member") or e["args"].get("from")))
        if key in known or e["args"].get("id") != rec["chain_id"]:
            continue
        rec["events"].append(e)
        kind = _KIND.get(e["event"])
        if not kind:
            continue
        who = store.name_of(e["args"].get("member") or e["args"].get("by") or "")
        if kind == "paid":
            if not any(t["kind"] == "paid" for t in rec["txs"]):
                _log_tx(rec, "paid", e, ch)
        else:
            _log_tx(rec, kind, e, ch, who if kind in ("lock", "offline", "refund", "dispute", "approve", "withdraw") else None)


def _refresh(rec: dict[str, Any], tx_hash: str | None = None, on: dict[str, Any] | None = None,
             release_tx: dict[str, Any] | None = None) -> dict[str, Any]:
    """체인을 다시 읽어 상태를 확정. 이의제기 기간이 끝났으면 에이전트가 지급(release)까지 실행.
    [베타 서버] on(미리 읽은 체인 상태)·release_tx(미리 보낸 지급)를 주면 체인을 다시 부르지 않고 기록만 갱신한다 (체인 감시용)."""
    if rec["status"] in ("blocked", "refunded") and not tx_hash:
        if rec.get("notified") != rec["status"]:
            _settle_notify(rec)
            store.put(rec)
        return rec
    ch = _chain()
    if tx_hash:
        _apply_events(rec, _wrap_chain(lambda: ch.events_from_tx(tx_hash), "chain.read"), ch)
    prefetched = on is not None
    if not prefetched:
        on = _wrap_chain(lambda: ch.get_settlement(rec["chain_id"]), "chain.read")
    if rec.get("purchase") and on["status"] == "open":
        try:
            _auto_purchase(rec, on)
        except ServiceError as e:   # 체인 오류면 다음 조회 때 다시 시도
            rec.setdefault("purchase", {})["lastError"] = e.message
        on = _wrap_chain(lambda: ch.get_settlement(rec["chain_id"]), "chain.read")
    if release_tx is not None:          # [베타 서버] 체인 감시가 잠금 밖에서 보낸 지급
        _log_tx(rec, "release", release_tx, ch)
        _apply_events(rec, release_tx["events"], ch)
    elif not prefetched and on["status"] == "locked" and on.get("release_at") and time.time() >= on["release_at"]:
        try:
            tx = ch.release(rec["chain_id"])
            _log_tx(rec, "release", tx, ch)
            _apply_events(rec, tx["events"], ch)
            on = ch.get_settlement(rec["chain_id"])
        except chainmod.ChainError:
            pass  # 블록 시간이 아직 안 지났으면 다음 조회 때 재시도
    states = {m["address"].lower(): m["state"] for m in on.get("members", [])}
    for m in rec["members"]:
        m["state"] = states.get(m["wallet"].lower(), m.get("state", "wait"))
    rec["release_at"] = on.get("release_at") or rec.get("release_at") or 0
    if on["status"] != "none":
        if on["status"] != rec["status"] and on["status"] in ("paid", "refunded") and not any(t["kind"] == "paid" for t in rec["txs"]):
            try:
                first = min([t["block"] for t in rec["txs"]] or [0])
                _apply_events(rec, ch.scan_events(rec["chain_id"], first), ch)
            except Exception:
                pass
        rec["status"] = on["status"]
    _settle_notify(rec)
    store.put(rec)
    return rec


# ───────────── [베타 서버] 체인 감시 — 정산 목록 새로고침(4초 × 사용자 수)이 체인을 읽지 않게 ─────────────
# 예전엔 새로고침마다 열린 정산의 체인 상태를 전역 잠금 안에서 읽어(공용 RPC 0.1~0.3초씩) 사용자가 늘면 앱 전체가 멈췄다.
# 이제 스레드 하나가 CHAIN_WATCH_SEC마다 열린 정산을 잠금 밖에서 읽고(지급 트랜잭션도 잠금 밖), 기록 갱신만 잠금 안에서 한다.
_WATCH: dict[str, Any] = {"thread": None}
_WATCH_LOCK = threading.Lock()
_OPEN = ("open", "locked", "disputed")


def chain_watch_start() -> bool:
    """실제 체인 + CHAIN_WATCH=1 이면 감시 스레드를 (한 번만) 켜고 True. 모의 체인·끔·체인 설정 오류면 False (예전 방식)."""
    if not config.CHAIN_WATCH:
        return False
    try:
        if chainmod.get().mode == "mock":
            return False
    except chainmod.ChainError:
        return False
    with _WATCH_LOCK:
        if _WATCH["thread"] is None:
            _WATCH["thread"] = threading.Thread(target=_watch_loop, name="chain-watch", daemon=True)
            _WATCH["thread"].start()
            print(f"[체인 감시] 켜짐 — 열린 정산을 {config.CHAIN_WATCH_SEC:g}초마다 뒤에서 읽어요", flush=True)
    return True


def _watch_loop() -> None:
    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=max(1, config.CHAIN_WATCH_WORKERS), thread_name_prefix="chain-read")
    while True:
        t0 = time.time()
        try:
            ids = [r["id"] for r in store.all_settlements() if r.get("status") in _OPEN and r.get("chain_id")]
            list(pool.map(_watch_one, ids))
        except Exception as e:  # noqa: BLE001 — 감시가 멈추면 지급이 안 되므로 계속 돈다
            print(f"[체인 감시] {e}", flush=True)
        time.sleep(max(0.5, config.CHAIN_WATCH_SEC - (time.time() - t0)))


def _watch_one(sid: str) -> None:
    try:
        ch = chainmod.get()
        rec = store.get(sid)
        if not rec or rec.get("status") not in _OPEN:
            return
        on = ch.get_settlement(rec["chain_id"])                                   # 잠금 밖: 체인 읽기
        tx = None
        if on["status"] == "locked" and on.get("release_at") and time.time() >= on["release_at"]:
            try:
                tx = ch.release(rec["chain_id"])                                  # 잠금 밖: 지급 확정 대기
                on = ch.get_settlement(rec["chain_id"])
            except chainmod.ChainError:
                tx = None                                                         # 블록 시간이 아직이면 다음 바퀴에
        with STATE_LOCK:                                                          # 잠금 안: 기록만 갱신
            rec = store.get(sid)
            if rec and rec.get("status") in _OPEN:
                _refresh(rec, on=on, release_tx=tx)
    except Exception as e:  # noqa: BLE001
        print(f"[체인 감시] {sid}: {e}", flush=True)


def _settle_notify(rec: dict[str, Any]) -> None:
    """정산 상태가 바뀔 때 멤버들 알림함에 알림 (+ 등록 시 그룹방에 ‘승인 요청’ 카드). 같은 상태는 한 번만."""
    st = rec["status"]
    if rec.get("notified") == st:
        return
    rec["notified"] = st
    gid, name, payer = rec.get("group_id"), rec.get("name") or "정산", rec.get("payer")
    go = ["gchat", gid] if gid else ["tab", "settle"]
    people = list(dict.fromkeys([m["name"] for m in rec["members"]] + ([payer] if payer else [])))
    if st == "open":
        verb = "AI 구매 대행 인출 승인" if rec.get("purchase") else "정산 결제"
        for m in rec["members"]:
            if m["name"] != payer or rec.get("purchase"):
                if m.get("share", 0) > 0:
                    notify_short(m["name"], "결제 요청", f"{name} · {payer}님이 {verb}{'을' if verb.endswith('승인') else '를'} 요청했어요 · 내 몫 {won(m['share'])}",
                                 go=go, action=True, key=f"approve:{gid or rec['id']}")
        g = store.kv_get("groups", gid) if gid else None
        if g:
            for x in g["msgs"]:
                if x.get("kind") == "approveReq" and not x.get("resolved"):
                    x.update(resolved=True, superseded=True)       # 예전 요청 카드는 닫는다
            g["msgs"].append({"id": "ar" + rec["id"][-10:], "from": payer, "by": payer, "kind": "approveReq", "total": rec["total"],
                              "sid": rec["id"], "purchase": bool(rec.get("purchase")), "resolved": False, "ts": time.time()})
            g["updated_at"] = time.time()
            store.kv_put("groups", gid, g)
        return
    text = {"locked": f"{name} · 모두 결제했어요. 이의제기 기간이 지나면 {payer}님에게 지급돼요.",
            "paid": f"{name} · 정산이 완료됐어요. 정산 인증서가 발급됐어요." if not rec.get("purchase") else f"{name} · AI가 결제를 마쳤어요 (구매 완료).",
            "refunded": f"{name} · 환불이 완료됐어요. 예치한 금액이 지갑으로 돌아왔어요.",
            "blocked": f"{name} · 정산이 중단됐어요: {(rec.get('blocked') or {}).get('message') or '지출 통제 위반'}",
            "disputed": f"{name} · 이의제기가 접수돼 AI가 조사 중이에요."}.get(st)
    if text:
        for n in people:
            notify_short(n, {"paid": "정산 완료", "refunded": "환불", "blocked": "정산 중단", "disputed": "이의제기"}.get(st, "정산"),
                         text, go=go, key=f"settle:{rec['id']}")


@_locked
def sync(sid: str, tx_hash: str | None = None) -> dict[str, Any]:
    return public(_refresh(_get(sid), tx_hash))


def _get(sid: str) -> dict[str, Any]:
    rec = store.get(sid)
    if not rec:
        raise ServiceError("NOT_FOUND", "정산을 찾을 수 없어요", "settlement", 404)
    return rec


@_locked
def get_settlement(sid: str) -> dict[str, Any]:
    return sync(sid)


@_locked
def approve(sid: str, name: str, tx_hash: str | None = None) -> dict[str, Any]:
    """승인 = 예치. 실제 체인: MetaMask lockForSettlement 후 tx_hash로 확정 / mock: 서버가 대신 예치."""
    ch = _chain()
    rec = _get(sid)
    if ch.mode == "mock" and not tx_hash:
        m = store.get_member(name)
        if not m:
            raise ServiceError("MEMBER_WALLET_MISSING", "지갑을 먼저 연결해 주세요.", "settlement.approve", 409)
        tx = _wrap_chain(lambda: ch.mock_lock(rec["chain_id"], m["wallet"]), "chain.lock")
        tx_hash = tx["tx_hash"]
    return sync(sid, tx_hash)


@_locked
def offline_payment(sid: str, participant: str, confirmer: str) -> dict[str, Any]:
    """mark_offline_payment — 결제자가 현금 수령을 확인한 경우만."""
    rec = _get(sid)
    if confirmer != rec["payer"]:
        raise ServiceError("FORBIDDEN", "현금 수령 확인은 결제자만 할 수 있어요.", "settlement.offline", 403)
    m = next((x for x in rec["members"] if x["name"] == participant), None)
    if not m:
        raise ServiceError("NOT_FOUND", "참여자를 찾을 수 없어요", "settlement.offline", 404)
    ch = _chain()
    tx = _wrap_chain(lambda: ch.mark_offline(rec["chain_id"], m["wallet"]), "chain.offline")
    _log_tx(rec, "offline", tx, ch, participant)
    _apply_events(rec, tx["events"], ch)
    return public(_refresh(rec))


@_locked
def list_for(member: str | None) -> list[dict[str, Any]]:
    watched = chain_watch_start()      # [베타 서버] 실제 체인이면 체인 읽기는 감시 스레드가 — 여기선 저장된 상태만
    out = []
    for rec in store.all_settlements():
        if member and not any(m["name"] == member for m in rec["members"]):
            continue
        if not watched and rec["status"] in ("open", "locked", "disputed"):
            try:
                rec = _refresh(rec)
            except ServiceError:
                pass
        out.append(public(rec))
    return out


PENDING_DISPUTE: dict[str, str] = {}   # 채팅별 '이 정산에 이의제기할까요?' 확인 대기


def _find_settlement(text, user) -> dict[str, Any] | None:
    recs = [r for r in store.all_settlements() if not user or any(m["name"] == user for m in r["members"])]
    for r in recs:
        if r["name"] and r["name"] in text:
            return r
    return next((r for r in recs if user and any(m["name"] == user for m in r["members"])), None)


# ───────────── 정산 캘린더 (서버 시계 = 실제 날짜) ─────────────
_KST = _dt.timezone(_dt.timedelta(hours=9), "KST")   # 한국 표준시 (서머타임 없음)


def _kst_date(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _KST).strftime("%Y-%m-%d")


def calendar_for(user: str) -> dict[str, Any]:
    """내가 참여한 정산을 날짜별로 (캘린더 표시용). 날짜는 서버 시계 기준 한국(KST) 실제 날짜 —
    기기 시계가 틀려도 캘린더는 실제 연·월·일에 맞는다. 조회 전용 · AI 미사용 (0 tokens)."""
    events = []
    for rec in list_for(user):
        me = next((m for m in rec["members"] if m["name"] == user), None)
        if not me:
            continue
        paid = next((t for t in rec["txs"] if t.get("kind") == "paid"), None)
        events.append({"date": _kst_date(rec["createdAt"]), "ts": rec["createdAt"], "sid": rec["id"],
                       "groupId": rec.get("groupId"), "name": rec["name"], "total": rec["total"],
                       "myShare": me["share"], "payer": rec["payer"], "status": rec["status"],
                       "purchase": bool(rec.get("purchase")),
                       "paidDate": _kst_date(paid["at"]) if paid and paid.get("at") else None})
    events.sort(key=lambda e: e["ts"])
    return {"today": _kst_date(time.time()), "tz": "Asia/Seoul (KST)", "events": events[-500:]}


def public(rec: dict[str, Any]) -> dict[str, Any]:
    paid = next((t for t in rec["txs"] if t["kind"] == "paid"), None)
    escrow = next((t for t in reversed(rec["txs"]) if t["kind"] in ("escrow", "lock", "offline")), None)
    return {
        "id": rec["id"], "groupId": rec.get("group_id"), "chainId": rec["chain_id"], "name": rec["name"],
        "total": rec["total"], "payer": rec["payer"], "purpose": rec["purpose"], "ruleText": rec["rule_text"],
        "mode": rec.get("mode"), "perPersonCap": rec.get("per_person_cap"), "totalCap": rec.get("total_cap"),
        "merchant": rec.get("merchant"),
        "members": [{"name": m["name"], "wallet": m["wallet"], "share": m["share"], "state": m.get("state", "wait"),
                     "locked": m.get("state") in ("locked", "offline", "payee", "refunded", "approved")} for m in rec["members"]],
        "status": rec["status"], "releaseAt": rec.get("release_at") or 0, "now": time.time(),
        "blocked": rec.get("blocked"), "violations": rec.get("violations", []), "dispute": rec.get("dispute"),
        "txs": rec["txs"], "network": rec.get("network"),
        "cert": ({"txHash": paid["tx_hash"], "block": paid["block"], "url": paid["url"]} if paid else
                 ({"txHash": escrow["tx_hash"], "block": escrow["block"], "url": escrow["url"], "pending": True}
                  if escrow and rec["status"] in ("locked", "disputed") else None)),
        "createdAt": rec["created_at"],
        "purchase": ({**rec["purchase"], "approved": sum(1 for m in rec["members"] if m.get("state") in ("approved", "locked")),
                      "needed": sum(1 for m in rec["members"] if m["share"] > 0)} if rec.get("purchase") else None),
    }


# ───────────── Dispute 모듈 ─────────────
@_locked
def dispute_raise(sid: str, by: str, reason: str) -> dict[str, Any]:
    rec = _refresh(_get(sid))
    if not any(m["name"] == by for m in rec["members"]):
        raise ServiceError("FORBIDDEN", "이 정산의 참여자만 이의제기를 할 수 있어요.", "dispute.raise", 403)
    if not (reason or "").strip():
        raise ServiceError("BAD_REQUEST", "이의 사유를 적어 주세요.", "dispute.raise")
    if rec["status"] != "locked":
        msg = {"paid": "이의제기 가능 시간이 지나 이미 결제자에게 지급됐어요. 조사 기록만 확인할 수 있어요.",
               "open": "아직 전원 예치 전이에요. 예치가 끝난 뒤 지급 전까지 이의제기할 수 있어요.",
               "disputed": "이미 이의제기가 접수돼 조사 중이에요."}.get(rec["status"], "지금은 이의제기를 할 수 없는 상태예요.")
        raise ServiceError("NOT_DISPUTABLE", msg, "dispute.raise", 409, {"status": rec["status"]})
    ch = _chain()
    by_wallet = next(m["wallet"] for m in rec["members"] if m["name"] == by)
    public_reason = settlement.pii_clean(reason, [m["name"] for m in rec["members"]])[:200] or "이의제기"   # 체인엔 개인정보 뺀 사유만
    tx = _wrap_chain(lambda: ch.raise_dispute(rec["chain_id"], by_wallet, public_reason), "chain.dispute")
    rec["dispute"] = {"by": by, "reason": reason.strip(), "raised_tx": tx["tx_hash"], "raised_url": ch.explorer_tx(tx["tx_hash"]),
                      "at": time.time(), "verdict": None}
    _log_tx(rec, "dispute", tx, ch, by)
    _apply_events(rec, tx["events"], ch)
    store.put(rec)
    u = store.user_by_short(by)
    beta.mark_done((u or {}).get("email"), "S07")          # 베타 미션: 이의제기로 기록 검토받기
    return public(_refresh(rec))


@_locked
def dispute_investigate(sid: str, flow: str | None = None) -> dict[str, Any]:
    rec = _refresh(_get(sid))
    d = rec.get("dispute") or {}
    if d.get("resolved_tx"):   # 이미 판정·실행된 이의제기는 다시 판정하지 않음 (기록 덮어쓰기 방지)
        return {**{k: d.get(k) for k in ("verdict", "verdict_ko", "refund", "explanation", "guard", "reason_category")},
                "findings": d.get("findings", []), "metas": [], "already": True}
    ev = dispute.investigate_records(rec, _chain())
    llm.code_step("dispute.records", flow or sid, "0 tokens (code-only): 단계별 기록 대조")
    if not d.get("reason"):
        return {"findings": ev["findings"], "verdict": None, "metas": []}
    j, metas = dispute.judge(rec, ev, d["by"], d["reason"], flow or sid)
    d.update({"verdict": j["verdict"], "verdict_ko": j["verdict_ko"], "refund": j["refund"], "explanation": j["explanation"],
              "guard": j["guard"], "findings": ev["findings"], "reason_category": j["reason_category"]})
    rec["dispute"] = d
    store.put(rec)
    return {**j, "findings": ev["findings"], "metas": metas}


@_locked
def dispute_resolve(sid: str) -> dict[str, Any]:
    rec = _refresh(_get(sid))
    d = rec.get("dispute") or {}
    if rec["status"] != "disputed" or not d.get("verdict"):
        raise ServiceError("NOT_READY", "조사(판정)가 끝난 이의제기만 처리할 수 있어요.", "dispute.resolve", 409)
    ch = _chain()
    refunded = []
    if d["verdict"] == "GENUINE_ERROR" and d.get("refund") not in ("all", "disputer"):   # [blockchain 담당] REFUND_GUARD
        # 착오 판정인데 환불 대상이 없으면 컨트랙트는 남은 예치금을 결제자에게 지급해 버린다 → 최소한 제기자에게 환불
        d["refund"] = "disputer"
        d["guard"] = ((d.get("guard") or "") + " · GENUINE_ERROR인데 refund=none → disputer 로 보정").strip(" ·")
    if d["verdict"] == "GENUINE_ERROR":
        targets = [m for m in rec["members"] if m.get("state") == "locked" and (d["refund"] == "all" or m["name"] == d["by"])]
        for m in targets:
            tx = _wrap_chain(lambda m=m: ch.refund(rec["chain_id"], m["wallet"]), "chain.refund")
            _log_tx(rec, "refund", tx, ch, m["name"])
            _apply_events(rec, tx["events"], ch)
            amt = next((int(e["args"]["amount"]) for e in tx.get("events", []) if e.get("event") == "Refunded"), m["share"])
            refunded.append({"name": m["name"], "amount": amt, "tx_hash": tx["tx_hash"], "url": ch.explorer_tx(tx["tx_hash"])})
    code = chainmod.VERDICT[d["verdict"]]
    note = f"{d['verdict']} · {d.get('reason_category') or ''}"[:120]
    tx = _wrap_chain(lambda: ch.resolve(rec["chain_id"], code, note), "chain.resolve")
    _log_tx(rec, "resolve", tx, ch)
    _apply_events(rec, tx["events"], ch)
    d.update({"refunded": refunded, "resolved_tx": tx["tx_hash"], "resolved_url": ch.explorer_tx(tx["tx_hash"]),
              "resolved_at": time.time()})
    rec["dispute"] = d
    store.put(rec)
    return public(_refresh(rec))


@_locked
def dispute_full(sid: str, by: str, reason: str, flow: str | None = None) -> dict[str, Any]:
    """Pie 채팅용: 접수 → 조사 → 판정 실행을 한 번에. 지급이 끝난 정산이면 조사만."""
    rec = _refresh(_get(sid))
    metas: list[dict[str, Any]] = []
    d0 = rec.get("dispute") or {}
    retry = rec["status"] == "disputed" and not d0.get("resolved_tx")   # 이전에 판정 실행이 실패해 멈춘 이의제기 → 이어서 처리
    if rec["status"] == "locked" or retry:
        if not retry:
            dispute_raise(sid, by, reason)
        j = dispute_investigate(sid, flow)
        metas += j.pop("metas", [])
        after = dispute_resolve(sid)
        d = after["dispute"]
        lines = [f"판정: {d['verdict']} — {d['verdict_ko']}", d.get("explanation") or ""]
        if d.get("guard"):
            lines.append(f"(코드 가드: {d['guard']})")
        if d.get("refunded"):
            lines.append("환불: " + ", ".join(f"{r['name']} {won(r['amount'])}" for r in d["refunded"]) + " → 각자 지갑으로 돌려받았어요")
        lines.append({"paid": "처리 결과: 결제자에게 지급 완료", "refunded": "처리 결과: 전액 환불로 정산 종료"}.get(after["status"], ""))
        lines.append("근거 기록:\n" + "\n".join(("✓ " if x["level"] == "ok" else "⚠️ ") + f"[{x['stage']}] {x['message']}"
                                          for x in j["findings"]))
        return {"message": "\n".join(l for l in lines if l), "verdict": d["verdict"], "verdictReason": d.get("explanation") or "",
                "settlement": after, "_metas": metas}
    ev = dispute.investigate_records(rec, _chain())
    metas.append(llm.code_step("dispute.records", flow or sid, "0 tokens (code-only)"))
    why = {"paid": "이의제기 가능 시간이 지나 이미 지급된 정산이라 판정·환불은 할 수 없고, 기록 조사 결과만 알려드려요.",
           "open": "아직 전원 예치 전이라 이의제기 대상이 아니에요. 현재 기록은 이래요.",
           "disputed": "이미 조사 중인 이의제기가 있어요.", "blocked": "지출 통제로 결제 전에 중단된 정산이에요.",
           "refunded": "이미 환불로 종료된 정산이에요."}.get(rec["status"], "")
    body = "\n".join(("✓ " if x["level"] == "ok" else "⚠️ ") + f"[{x['stage']}] {x['message']}" for x in ev["findings"])
    return {"message": f"{why}\n{body}", "verdict": None, "settlement": public(rec), "_metas": metas}


# ───────────── 지갑 (실시간 자금 추적) ─────────────
def wallet(address: str) -> dict[str, Any]:
    if not _ADDR.match(address or ""):
        raise ServiceError("BAD_REQUEST", "지갑 주소 형식이 올바르지 않아요", "wallet")
    ch = _chain()
    acc = _wrap_chain(lambda: ch.account(address), "chain.read")
    pending = acc["committed"] - acc["escrow"]
    hist = []
    for rec in store.all_settlements():
        me = next((m for m in rec["members"] if m["wallet"].lower() == address.lower()), None)
        if not me:
            continue
        is_payee = rec["payer_wallet"].lower() == address.lower()
        when = time.strftime("%m.%d", time.localtime(rec["created_at"]))
        st, mst = rec["status"], me.get("state")
        base = {"id": f"{rec['id']}:{mst}", "sid": rec["id"], "groupId": rec.get("group_id"), "room": rec.get("name")}
        n0 = len(hist)
        if mst == "refunded":
            hist.append({**base, "d": when, "t": "환불", "s": rec["purpose"], "a": 0, "note": f"+{won(me['share'])} 돌려받음",
                         "kind": "refund", "refunded": True})
        elif st == "paid":
            if is_payee:
                payout = sum(m["share"] for m in rec["members"] if m.get("state") == "locked")
                hist.append({"d": when, "t": "정산 입금", "s": rec["purpose"], "a": payout})
            elif mst == "offline":
                hist.append({"d": when, "t": "현금 정산", "s": rec["purpose"], "a": 0, "note": f"현금 {won(me['share'])}"})
            else:
                hist.append({"d": when, "t": "정산 송금", "s": rec["purpose"], "a": -me["share"]})
        elif st in ("locked", "disputed") and not is_payee and mst == "locked":
            # 지급 전(에스크로)이라 환불 요청 가능 → AI Dispute Agent가 조사·판정 (착오면 자동 환불)
            hist.append({**base, "d": when, "t": "예치 중 (지급 전)", "s": rec["purpose"], "a": -me["share"], "kind": "pay",
                         "refundable": st == "locked" and time.time() < (rec.get("release_at") or 0),
                         "note": "환불 요청 조사 중" if st == "disputed" else None})
        elif st == "open" and not is_payee and mst == "wait":
            hist.append({"d": when, "t": "결제 예정", "s": rec["purpose"], "a": 0, "pending": me["share"]})
        elif st == "blocked":
            hist.append({"d": when, "t": "정산 중단", "s": (rec.get("blocked") or {}).get("message", ""), "a": 0})
        for h in hist[n0:]:
            h["ts"] = rec["created_at"]
    who = store.user_by_short(store.name_of(address) or "")
    for x in (_ai_paid(who["email"])["items"] if who else []):
        hist.append({"id": x["id"], "d": time.strftime("%m.%d", time.localtime(x["at"])), "t": "누적 AI 사용량으로 송금",
                     "s": "Pie Pay → 누적 AI 사용량", "a": -x["amount"], "kind": "ai", "ts": x["at"]})
    hist.sort(key=lambda h: -h.get("ts", 0))        # 최신순 (정산·AI 사용료 송금 섞어서)
    return {"address": address, "name": store.name_of(address), "balance": acc["balance"],
            "scheduled": pending, "escrow": acc["escrow"], "spent": acc["spent"],
            "available": acc["balance"] - pending, "history": hist, "symbol": ch.info().get("token_symbol", "PIE")}


REFUND_REASONS = ("단순 변심", "금액 착오", "인원·참여자 착오", "중복 결제", "기타")


def refund_request(me: dict[str, Any], sid: str, reason: str, note: str = "") -> dict[str, Any]:
    """MY 결제 내역의 ‘환불 요청’ = 이의제기. 지급 전(에스크로)일 때만 가능하고, 결과는 AI 3분류 판정이 정한다
    (GENUINE_ERROR면 자동 환불, 아니면 기각). 사람이 임의로 돈을 돌려받는 경로는 없다."""
    rec = _refresh(_get(sid))
    mine = next((m for m in rec["members"] if m["name"] == me["short"]), None)
    if not mine or mine.get("state") != "locked":
        raise ServiceError("NOT_REFUNDABLE", "내가 예치한 금액이 있는 정산만 환불을 요청할 수 있어요.", "refund", 409)
    if rec["status"] != "locked" or time.time() >= (rec.get("release_at") or 0):
        raise ServiceError("NOT_REFUNDABLE", {"paid": "이미 지급이 끝나 환불할 수 없어요.", "disputed": "이미 환불 요청을 조사 중이에요."}.get(
            rec["status"], "지금은 환불을 요청할 수 없는 상태예요."), "refund", 409)
    if reason not in REFUND_REASONS:
        raise ServiceError("BAD_REQUEST", "환불 사유를 골라 주세요.", "refund")
    note = re.sub(r"\s+", " ", note or "").strip()[:100]
    if reason == "기타" and len(note) < 2:
        raise ServiceError("BAD_REQUEST", "기타 사유를 2자 이상 적어 주세요.", "refund")
    why = f"환불 요청 · {reason}" + (f"({note})" if note else "")
    r = dispute_full(sid, me["short"], why)
    r.pop("_metas", None)
    g = store.kv_get("groups", rec.get("group_id")) if rec.get("group_id") else None
    if g:
        with STATE_LOCK:
            g = store.kv_get("groups", rec["group_id"])
            _sys(g, f"{me['short']}님이 ‘{why}’로 환불을 요청했어요 → AI 판정: {r.get('verdict') or '조사만'}", me["short"])
            store.kv_put("groups", g["id"], g)
    refunded = any(x["name"] == me["short"] for x in ((r.get("settlement") or {}).get("dispute") or {}).get("refunded") or [])
    return {**r, "refunded": refunded}


# ───────────── AI 사용량 · 구독 요금제 (Claude 벤치마킹) ─────────────
# 사용량 = 이 사람 요청에서 일어난 Kiln 호출의 실제 토큰 수(usage.jsonl). 금액 계산·지출 통제·결제는 코드라 0 토큰.
# 쓴 만큼 정산(후불)하지 않는다. 월 구독 요금제(Free·Pro·Max 5x·Max 20x)가 5시간 세션 한도와 주간 한도를 정하고,
# 한도를 넘으면 Kiln을 부르지 않는다 (agent/quota.py). 구독료 결제는 PieToken.transfer(사용자 → 구독료 지갑) 온체인 기록.
_AI_TITLES = {
    "settlement.analyze": "정산 조건 해석", "settlement.explain": "정산 결과 설명", "settlement.calculate": "분담금 계산",
    "settlement.policy": "지출 통제 검사", "dispute.investigate": "분쟁 조사", "dispute.records": "분쟁 기록 정리",
    "shopping.search": "공동구매 비교", "shopping.plan": "구매 조건 파악", "shopping.explain": "비교 결과 설명",
    "shopping.web": "상품 검색", "shopping.calculate": "1인 비용 계산", "chat.route": "요청 의도 파악",
    "chat.answer": "Pie 답변", "chat.search": "검색어 만들기", "group.pie": "Pie mate 답장",
    "assistant.step": "Pie 판단", "assistant.tool": "Pie 도구 사용", "assistant.fallback": "예비 답변",
}
_CODE_STAGES = ("settlement.calculate", "settlement.policy", "shopping.calculate")
SUB_CYCLE_SEC = 30 * 24 * 3600     # 30일마다 결제 (Claude처럼 월 구독)


def _ai_bucket(stage: str) -> str:
    """화면의 단계별 막대(정산 코어 먼저)에 맞춘 묶음. 원래 태그는 tag로 따로 보낸다."""
    if stage in _CODE_STAGES:
        return "settlement.calculate"
    if stage in ("settlement.analyze", "settlement.explain"):
        return stage
    if stage.startswith("dispute."):
        return "dispute.investigate"
    if stage.startswith("shopping."):
        return "shopping.search"
    return "pie.chat"


def _ai_won(tokens: int) -> int:
    return int(round(tokens * config.AI_WON_PER_TOKEN))


def _fee_wallet() -> str:
    return config.AI_FEE_WALLET or _chain().info()["agent"]


def _ai_paid(email: str) -> dict[str, Any]:
    """예전 후불 방식으로 낸 기록 (명세서에 과거 내역으로만 보여 준다)."""
    return store.kv_get("ai_pay", email) or {"paid": 0, "items": []}


def _sub_item(kind: str, plan: str, amount: int, tx_hash: str, ch) -> dict[str, Any]:
    return {"id": "sub-" + uuid.uuid4().hex[:8], "at": time.time(), "kind": kind, "plan": plan, "amount": amount,
            "tx_hash": tx_hash, "url": ch.explorer_tx(tx_hash)}


def _sub_refresh(me: dict[str, Any], rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """주기(30일)가 지났으면 정리: 예약한 해지·낮은 요금제 변경을 반영하고, mock 체인이면 자동 갱신을 시도한다."""
    with STATE_LOCK:
        rec = dict(store.kv_get("ai_sub", me["email"]) or {})
        if not rec.get("plan"):
            return rec
        changed = False
        while time.time() >= rec["renewsAt"]:
            changed = True
            if rec.get("cancelAt") or rec.get("nextPlan") == "free":      # 해지 예약: 기간이 끝나는 순간 Free로
                rec.update(plan=None, cancelAt=None, nextPlan=None)
                notify(me["email"], "AI 구독", "AI 구독이 해지 예약대로 끝났어요. 이제 Free 한도로 쓸 수 있어요.", go=["tab", "my"])
                break
            target = rec.get("nextPlan") or rec["plan"]
            price = int(rec.get("price") or 0) if target == rec["plan"] else quota.PLANS[target]["price"]
            ch, m = _chain(), store.get_member(me.get("short") or rec.get("short") or "")
            renewed = False
            if ch.mode == "mock" and m:                 # mock 체인: 서버가 자동 갱신 (실제 체인은 지갑 서명이 필요해 직접 갱신)
                try:
                    acc = ch.account(m["wallet"])
                    if acc["balance"] - (acc["committed"] - acc["escrow"]) >= price:
                        tx = ch.mock_transfer(m["wallet"], _fee_wallet(), price)
                        rec["items"] = [_sub_item("renew", target, price, tx["tx_hash"], ch)] + rec.get("items", [])[:49]
                        rec.update(plan=target, price=price, nextPlan=None)
                        rec["cycleStart"], rec["renewsAt"] = rec["renewsAt"], rec["renewsAt"] + SUB_CYCLE_SEC
                        llm.code_step("ai.subscribe", None, f"0 tokens (code-only): {quota.PLANS[target]['label']} 자동 갱신 {price:,} PIE")
                        renewed = True
                except Exception:   # noqa: BLE001
                    pass
            if not renewed:
                rec.update(plan=None, cancelAt=None, nextPlan=None)
                notify(me["email"], "AI 구독", "AI 구독을 갱신하지 못해 Free 요금제로 바뀌었어요 (잔액 부족 또는 직접 갱신 필요). "
                       "MY 탭 'AI 요금제'에서 다시 구독할 수 있어요.", go=["tab", "my"], action=True)
                break
        if changed:
            store.kv_put("ai_sub", me["email"], rec)
        return rec


def _sub_refresh_email(email: str) -> dict[str, Any]:
    rec = store.kv_get("ai_sub", email) or {}
    u = store.user_by_email(email) or {}
    return _sub_refresh({"email": email, "short": rec.get("short") or u.get("short") or ""})


quota.set_refresher(_sub_refresh_email)    # 한도 계산 때 주기가 끝난 구독을 먼저 정리 (자동 갱신·만료)


def _sub_view(me: dict[str, Any], rec: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rec = rec if rec is not None else _sub_refresh(me)
    if not rec.get("plan"):
        return None
    p, nxt = quota.PLANS[rec["plan"]], rec.get("nextPlan")
    return {"plan": rec["plan"], "label": p["label"], "price": int(rec.get("price") or p["price"]),
            "cycleStart": rec["cycleStart"], "renewsAt": rec["renewsAt"], "cancelAt": rec.get("cancelAt"),
            "startedAt": rec.get("startedAt"), "nextPlan": nxt, "nextLabel": quota.PLANS[nxt]["label"] if nxt in quota.PLANS else None}


def _quota_view(email: str) -> dict[str, Any]:
    st = quota.state(email)
    return {**st, "sessionHours": config.AI_SESSION_HOURS, "weekDays": config.AI_WEEK_DAYS,
            "resetText": quota.when_text(st["resetsAt"]) if st["blocked"] else None}


def ai_sub(me: dict[str, Any]) -> dict[str, Any]:
    rec = _sub_refresh(me)
    return {"plans": quota.plans_public(), "cycleDays": SUB_CYCLE_SEC // 86400, "sub": _sub_view(me, rec),
            "quota": _quota_view(me["email"]), "items": rec.get("items", [])[:10]}


def _sub_result(me: dict[str, Any], m: dict[str, Any] | None) -> dict[str, Any]:
    return {"sub": ai_sub(me), "usage": ai_usage(me), "wallet": wallet(m["wallet"]) if m else None}


@_locked
def ai_subscribe(me: dict[str, Any], plan: str, tx_hash: str | None = None) -> dict[str, Any]:
    """요금제 시작·변경. 높은 요금제는 지금 결제하고 새 30일 주기를 시작, 낮은 요금제·Free는 이번 주기가 끝날 때 바뀐다(Claude와 같음).
    mock 체인은 서버가 대신 transfer, 실제 체인은 MetaMask 송금 영수증(tx_hash)을 검증한다."""
    pid = str(plan or "").strip().lower()
    if pid not in quota.PLANS:
        raise ServiceError("BAD_REQUEST", "요금제를 골라 주세요 (free · pro · max · max20).", "ai.subscribe")
    if pid == "free":
        return ai_sub_cancel(me)
    p = quota.PLANS[pid]
    m = store.get_member(me["short"])
    if not m:
        raise ServiceError("MEMBER_WALLET_MISSING", "먼저 MY 탭에서 지갑을 연결해 주세요.", "ai.subscribe", 409)
    rec = _sub_refresh(me)
    cur = rec.get("plan")
    if cur == pid:
        if rec.get("cancelAt") or rec.get("nextPlan"):   # 해지·변경 예약 취소 (결제 없음)
            rec.update(cancelAt=None, nextPlan=None)
            store.kv_put("ai_sub", me["email"], rec)
            return _sub_result(me, m)
        raise ServiceError("ALREADY_SUBSCRIBED", f"이미 {p['label']} 요금제예요.", "ai.subscribe", 409)
    if cur and p["price"] < quota.PLANS[cur]["price"]:   # 낮은 요금제: 결제 없이 예약, 다음 결제일부터 적용
        rec.update(nextPlan=pid, cancelAt=None)
        store.kv_put("ai_sub", me["email"], rec)
        llm.code_step("ai.subscribe", None, f"0 tokens (code-only): {quota.PLANS[cur]['label']} → {p['label']} 변경 예약")
        return _sub_result(me, m)
    ch, to = _chain(), _fee_wallet()
    if tx_hash:                                          # 실제 체인: 이미 보낸 송금을 확인만
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
            raise ServiceError("BAD_REQUEST", "트랜잭션 해시 형식이 올바르지 않아요.", "ai.subscribe")
        if store.kv_get("ai_sub_tx", tx_hash.lower()):
            raise ServiceError("ALREADY_RECORDED", "이미 반영된 송금이에요.", "ai.subscribe", 409)
        got = _wrap_chain(lambda: ch.verify_transfer(tx_hash, m["wallet"], to), "chain.read")
        if got < p["price"]:
            raise ServiceError("TX_NOT_VERIFIED", f"구독료({p['price']:,} PIE) 송금을 영수증에서 찾지 못했어요.", "ai.subscribe", 409)
        tx = {"tx_hash": tx_hash}
    else:
        if ch.mode != "mock":
            raise ServiceError("TX_REQUIRED", "MetaMask로 구독료를 송금한 뒤 트랜잭션 해시를 보내 주세요.", "ai.subscribe", 400)
        acc = _wrap_chain(lambda: ch.account(m["wallet"]), "chain.read")
        free = acc["balance"] - (acc["committed"] - acc["escrow"])
        if free < p["price"]:
            raise ServiceError("INSUFFICIENT_BALANCE", f"Pie Pay 가용 잔액({free:,} PIE)이 부족해요. {p['label']}은 월 {p['price']:,} PIE예요.",
                               "ai.subscribe", 409, {"available": free})
        tx = _wrap_chain(lambda: ch.mock_transfer(m["wallet"], to, p["price"]), "chain.transfer")
    now = time.time()
    rec.update(plan=pid, price=p["price"], cycleStart=now, renewsAt=now + SUB_CYCLE_SEC, cancelAt=None, nextPlan=None,
               startedAt=rec.get("startedAt") or now, short=me["short"])
    rec["items"] = [_sub_item("upgrade" if cur else "subscribe", pid, p["price"], tx["tx_hash"], ch)] + rec.get("items", [])[:49]
    store.kv_put("ai_sub", me["email"], rec)
    store.kv_put("ai_sub_tx", tx["tx_hash"].lower(), {"email": me["email"], "plan": pid, "amount": p["price"]})
    llm.code_step("ai.subscribe", None, f"0 tokens (code-only): {p['label']} {'변경' if cur else '구독'} {p['price']:,} PIE {tx['tx_hash'][:12]}")
    return _sub_result(me, m)


@_locked
def ai_sub_cancel(me: dict[str, Any]) -> dict[str, Any]:
    rec = _sub_refresh(me)
    if not rec.get("plan"):
        raise ServiceError("NOT_FOUND", "지금은 Free 요금제예요.", "ai.subscribe", 404)
    rec.update(cancelAt=rec["renewsAt"], nextPlan=None)       # Claude처럼 남은 기간까지는 그대로 이용
    store.kv_put("ai_sub", me["email"], rec)
    return _sub_result(me, store.get_member(me["short"]))


def ai_usage(me: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    """AI 토큰 세부내용 — 이 사람 요청에서 일어난 Kiln 호출(실측 토큰·지연·에너지 추정·응답이 바꾼 행동)
    + 코드로 처리한 단계 + 한도로 규칙 답을 한 기록 + 구독 결제."""
    items: list[dict[str, Any]] = []
    tin = tout = calls = 0
    energy = 0.0
    last_ai: dict[tuple[Any, str], int] = {}
    rows = usage.for_user(me["email"])
    for i, r in enumerate(rows):
        stage, mode, note = r.get("stage", ""), r.get("mode"), r.get("note") or ""
        if mode == "decision":                                # 바로 앞 Kiln 호출에 '응답 → 행동'으로 붙인다
            j = last_ai.get((r.get("flow"), stage))
            if j is not None:
                items[j]["decision"] = (items[j].get("decision", "") + " / " if items[j].get("decision") else "") + note
            continue
        is_ai = mode in quota.AI_MODES
        limited = mode == "fallback" and note.startswith("AI_LIMIT")
        if not is_ai and not limited and not (mode == "code" and stage in _CODE_STAGES):
            continue                                          # 규칙 기반(오프라인)·라우팅 같은 0토큰 기록은 명세서에서 뺌
        p, c = int(r.get("prompt_tokens") or 0), int(r.get("completion_tokens") or 0)
        if is_ai:
            tin, tout, calls = tin + p, tout + c, calls + 1
            energy += float(r.get("energy_wh") or 0)
            last_ai[(r.get("flow"), stage)] = len(items)
        items.append({"id": f"u{int(r['ts'] * 1000)}{i}", "at": int(r["ts"] * 1000), "ai": is_ai, "stage": _ai_bucket(stage),
                      "tag": stage, "inTok": p, "outTok": c, "where": r.get("where") or "chat",
                      "title": ("AI 한도 도달 → 규칙 답" if limited else _AI_TITLES.get(stage, stage)), "ctx": r.get("ctx") or "",
                      "note": (note if is_ai else ("AI 사용 한도라 Kiln을 부르지 않음 (0 tokens)" if limited
                                                   else (note or "코드로 계산 · Kiln 호출 없음 (0 tokens)"))),
                      "model": r.get("model"), "latencyMs": r.get("latency_ms", 0), "flow": r.get("flow"),
                      "counted": bool(r.get("counted", is_ai)), "plan": r.get("plan"), "energyWh": r.get("energy_wh", 0),
                      "limited": limited})
    srec = _sub_refresh(me)
    sub = _sub_view(me, srec)
    for x in srec.get("items", [])[:20]:
        pl = quota.PLANS.get(x.get("plan") or "", {})
        kind = {"renew": "구독 갱신", "upgrade": "요금제 변경"}.get(x.get("kind"), "구독 시작")
        items.append({"id": x["id"], "at": int(x["at"] * 1000), "ai": False, "stage": "money", "tag": "ai.subscribe", "inTok": 0, "outTok": 0,
                      "where": "money", "title": f"{kind} ({pl.get('label', x.get('plan'))})", "ctx": "Pie Pay → AI 구독", "amount": -x["amount"],
                      "note": f"월 {x['amount']:,} PIE" + (f" · tx {x['tx_hash'][:10]}…" if x.get("tx_hash") else ""),
                      "txHash": x.get("tx_hash"), "url": x.get("url")})
    paid = _ai_paid(me["email"])
    for x in paid["items"]:                                   # 예전 후불 방식으로 낸 기록 (읽기 전용)
        items.append({"id": x["id"], "at": int(x["at"] * 1000), "ai": False, "stage": "money", "tag": "ai.pay", "inTok": 0, "outTok": 0,
                      "where": "money", "title": "이전 방식 사용료 송금", "ctx": "Pie Pay → 누적 AI 사용량", "amount": -x["amount"],
                      "note": f"{x['amount']:,} AI원 (구독 전환 전)" + (f" · tx {x['tx_hash'][:10]}…" if x.get("tx_hash") else "")})
    items.sort(key=lambda u: -u["at"])
    return {"items": items[:limit], "total": tin + tout, "tokens": tin + tout, "inTok": tin, "outTok": tout,
            "inWon": _ai_won(tin), "outWon": _ai_won(tout), "calls": calls, "energyWh": round(energy, 5),
            "quota": _quota_view(me["email"]), "sub": sub, "plans": quota.plans_public(), "cycleDays": SUB_CYCLE_SEC // 86400,
            "paid": paid["paid"], "unpaid": 0, "wonPerToken": config.AI_WON_PER_TOKEN, "feeWallet": _fee_wallet(),
            "measured": llm.client.mode == "live", "model": config.KILN_MODEL, "energy": usage.assumptions()}


def ai_pay(me: dict[str, Any], amount: Any = None, tx_hash: str | None = None) -> dict[str, Any]:
    """예전 후불(누적 AI 사용량 송금) — 구독 방식으로 바뀌어 더 받지 않는다."""
    raise ServiceError("BILLING_CHANGED", "AI 사용료를 쓴 만큼 내는 방식은 없어졌어요. 이제 요금제(Free·Pro·Max)가 사용 한도를 정해요.",
                       "ai.pay", 410)


def shopping_search(query: str, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    with quota.turn() as q:
        out = _shopping_search(query, history, flow)
    if q and q["blocked"]:
        out["limit"] = {**_limit_card(q), "text": quota.limit_text(q)}
    return out


def _shopping_search(query: str, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    r = shopping.run(query, history=history, flow=flow)
    out = {"status": r["status"], "query": r.get("query"), "usage": _usage_of(r["metas"]), "meta": llm.meta_line(r["metas"])}
    if r["status"] == "ok":
        out["candidates"] = [{"id": c["id"], **shopping.product_public(c), **c["eval"]} for c in r["candidates"]]
        out["explain"] = r["explain"]
    elif r["status"] == "no_match":
        out["advice"] = r["advice"]
        out["budget_per_person"] = r.get("budget_per_person")
    else:
        out["question"] = r.get("question")
    return out


# ───────────── mock 전용 (MetaMask 없이 팀 개발·테스트) ─────────────
def _mock_only():
    ch = _chain()
    if ch.mode != "mock":
        raise ServiceError("MOCK_ONLY", "CHAIN_MODE=mock 에서만 쓸 수 있어요 (실제 체인은 MetaMask로 서명)", "dev", 403)
    return ch


@_locked
def mock_lock(sid: str, name: str) -> dict[str, Any]:
    _mock_only()
    return approve(sid, name)


@_locked
def mock_tamper(sid: str, name: str, amount: int) -> dict[str, Any]:
    """분쟁 조사 시연용: DB의 합의액을 몰래 바꿔 '불일치'를 만든다 (mock 전용)."""
    _mock_only()
    rec = _get(sid)
    for m in rec["members"]:
        if m["name"] == name:
            m["share"] = int(amount)
    store.put(rec)
    return public(rec)


@_locked
def mock_fast_forward(sid: str) -> dict[str, Any]:
    """시연용: 이의제기 기간을 즉시 끝낸다 (mock 전용)."""
    ch = _mock_only()
    rec = _get(sid)
    s = ch.st["settlements"].get(rec["chain_id"])
    if s and s.get("locked_at"):
        s["locked_at"] = int(time.time()) - ch.dispute_window() - 1
        s["release_after"] = int(time.time()) - 1
        ch._save()
    return sync(sid)


def beta_status(me: dict[str, Any]) -> dict[str, Any]:
    return beta.status(me)


def beta_consent(me: dict[str, Any], agree: bool) -> dict[str, Any]:
    return beta.set_consent(me, agree)


def beta_feedback(me: dict[str, Any], turn: str, rating: str, reason: str | None = None, note: str | None = None) -> dict[str, Any]:
    try:
        return beta.feedback(me, turn, rating, reason, note)
    except ValueError as e:
        raise ServiceError("BAD_REQUEST", str(e), "beta.feedback") from e


def beta_report() -> dict[str, Any]:
    rep = beta.report()
    return {**rep, "markdown": beta.report_markdown(rep)}


def usage_summary(flow: str | None = None) -> dict[str, Any]:
    """심사 제출용 보고서 (agent/report.py): 단계별·구간별·실행별 토큰, 응답 반영, 절감, 에너지 근거, 요금제."""
    rep = report.build(flow)
    return {**rep, "markdown": report.markdown(rep)}


def usage_calls_csv(flow: str | None = None) -> str:
    return report.calls_csv(flow)


# ───────────── 그룹 채팅방 (멤버 모두 같은 방을 봄) ─────────────
_GID = re.compile(r"^[A-Za-z0-9_-]{3,40}$")
_GROUP_KEYS = ("name", "members", "shares", "total", "payer", "ruleText", "purpose", "perPersonCap", "totalCap",
               "merchant", "allowedMalls", "status", "sid", "retired", "approvals", "warnings", "mode")
_MSG_KEYS = ("id", "from", "text", "kind", "confirmData", "analysis", "meta", "guide", "resolved", "accepted", "pie", "ask", "replyTo", "turn")


def _room_view(g: dict[str, Any], me: str | None = None) -> dict[str, Any]:
    typing = g.get("pieTyping") or 0
    L = store.kv_get("listings", g["id"])
    listing = {"cap": L["cap"], "status": _listing_refresh(dict(L), g)["status"], "dong": L.get("dong") or "",
               "deadlineLabel": _deadline_label(L["deadline"])} if L else None
    return {**{k: g.get(k) for k in _GROUP_KEYS}, "id": g["id"], "creator": g["creator"], "v": g["v"],
            "msgs": g["msgs"][-200:], "updatedAt": g["updated_at"], "pieTyping": bool(typing and time.time() - typing < 60),
            "listing": listing, "pendingPropose": ({k: g["pendingPropose"][k] for k in ("noWallet", "short")}
                                                   if g.get("pendingPropose") else None),
            "splitApproval": _split_view(g.get("splitApproval")),
            **(_room_personal(g, me) if me else {})}


def _room_personal(g: dict[str, Any], me: str) -> dict[str, Any]:
    """보는 사람마다 다른 값: 안 읽은 수 · 알림 끔 · 마지막 메시지 시각 · 초대 수락 전 여부."""
    last_read = (g.get("reads") or {}).get(me, 0)
    # 사람·Pie가 보낸 말과 승인 요청만 센다 (‘들어왔어요’ 같은 시스템 안내는 안 읽은 수에 넣지 않음)
    unread = sum(1 for m in g["msgs"] if m.get("ts", 0) > last_read and m.get("by") != me
                 and ((m.get("text") and (m.get("from") != "sys" or m.get("pie"))) or m.get("kind") in ("approveReq", "splitReq")))
    last = next((m.get("ts") for m in reversed(g["msgs"]) if m.get("ts")), g.get("created_at"))
    return {"unread": unread, "muted": me in (g.get("muted") or []), "lastAt": last, "pending": me in (g.get("pending") or [])}


def _room(gid: str, user: str) -> dict[str, Any]:
    g = store.kv_get("groups", gid)
    if not g:
        raise ServiceError("NOT_FOUND", "없는 그룹이에요.", "group", 404)
    if user not in g["viewers"]:
        raise ServiceError("FORBIDDEN", "이 그룹의 멤버만 볼 수 있어요.", "group", 403)
    return g


def _clean_msg(m: dict[str, Any], user: str) -> dict[str, Any]:
    out = {k: m.get(k) for k in _MSG_KEYS if m.get(k) is not None}
    out["id"] = str(out.get("id") or "m" + uuid.uuid4().hex[:10])[:40]
    out["from"] = "sys" if m.get("from") == "sys" else user   # 남의 이름으로 말할 수 없음
    out["by"] = user
    if isinstance(out.get("text"), str):
        out["text"] = out["text"][:2000]
    out["ts"] = time.time()
    return out


@_locked
def group_create(user: str, data: dict[str, Any]) -> dict[str, Any]:
    gid = str(data.get("id") or "g" + uuid.uuid4().hex[:10])
    if not _GID.match(gid):
        raise ServiceError("BAD_REQUEST", "그룹 id 형식이 올바르지 않아요.", "group")
    if store.kv_get("groups", gid):
        return group_update(user, gid, data)
    members = [str(m) for m in (data.get("members") or []) if str(m).strip()][:20]
    if not members:
        raise ServiceError("BAD_REQUEST", "멤버가 없어요.", "group")
    g = {k: data.get(k) for k in _GROUP_KEYS}
    g.update({"id": gid, "members": members, "creator": user, "viewers": sorted(set(members) | {user}),
              "msgs": [_clean_msg(m, user) for m in (data.get("msgs") or [])[:20] if isinstance(m, dict)],
              "v": 1, "created_at": time.time(), "updated_at": time.time()})
    g["name"] = str(g.get("name") or "그룹")[:40]
    g["pending"] = [m for m in members if m != user]          # 초대받은 사람: 알림함에서 참여/거절
    g["reads"] = {user: time.time()}
    store.kv_put("groups", gid, g)
    for m in g["pending"]:
        _invite_notify(g, user, m)
    return _room_view(g, user)


def _invite_notify(g: dict[str, Any], by: str, who: str) -> None:
    notify_short(who, "그룹 초대", f"{by}님이 ‘{g['name']}’ 그룹에 초대했어요. ({len(g['members'])}명)", go=["gchat", g["id"]],
                 req={"type": "invite", "key": g["id"], "status": "pending"})


def _active_settlement(g: dict[str, Any]) -> dict[str, Any] | None:
    """방에 진행 중인 정산(예치·승인·이의제기 단계)이 있으면 그 기록."""
    if not g.get("sid"):
        return None
    try:
        rec = get_settlement(g["sid"])
    except ServiceError:
        return None
    return rec if rec.get("status") in ("open", "locked", "disputed") else None


def _sys(g: dict[str, Any], text: str, by: str = "sys") -> None:
    g["msgs"].append({"id": "s" + uuid.uuid4().hex[:10], "from": "sys", "by": by, "text": text, "ts": time.time()})
    g["updated_at"] = time.time()


@_locked
def group_read(user: str, gid: str) -> dict[str, Any]:
    g = _room(gid, user)
    g.setdefault("reads", {})[user] = time.time()
    store.kv_put("groups", gid, g)
    return {"unread": 0}


@_locked
def group_mute(user: str, gid: str, muted: bool) -> dict[str, Any]:
    g = _room(gid, user)
    ms = [x for x in (g.get("muted") or []) if x != user] + ([user] if muted else [])
    g["muted"] = ms
    store.kv_put("groups", gid, g)
    return {"muted": muted}


@_locked
def group_rename(user: str, gid: str, name: str) -> dict[str, Any]:
    g = _room(gid, user)
    v = re.sub(r"\s+", " ", name or "").strip()
    if not v or len(v) > 20:
        raise ServiceError("BAD_REQUEST", "방 이름은 1~20자로 적어 주세요.", "group")
    if settlement.prohibited_reason(v):
        raise ServiceError("PROHIBITED_PURPOSE", settlement.REFUSE_MSG, "group", 403)
    if v != g.get("name"):
        g["name"] = v                      # 이미 발급된 정산 인증서 제목은 온체인 기록이라 바뀌지 않는다
        g["v"] += 1
        _sys(g, f"{user}님이 방 이름을 ‘{v}’(으)로 바꿨어요", user)
        store.kv_put("groups", gid, g)
    return _room_view(g, user)


@_locked
def group_invite(me: dict[str, Any], gid: str, pie_ids: list[str]) -> dict[str, Any]:
    """방에 친구 초대 (서로 친구인 사람만). 진행 중인 정산에는 포함되지 않고 0원으로 들어온다."""
    me = _fresh(me)
    user = me["short"]
    g = _room(gid, user)
    add = []
    for pid in dict.fromkeys(_norm_pie(p) for p in pie_ids or []):
        u = store.user_by_pie(pid)
        if not u or pid not in _lst(me, "friends"):
            raise ServiceError("NOT_FRIEND", f"@{pid}님은 친구가 아니에요. 친구 요청을 먼저 보내 주세요.", "group", 400)
        if u["short"] not in g["members"]:
            add.append(u["short"])
    if not add:
        raise ServiceError("BAD_REQUEST", "초대할 친구를 골라 주세요.", "group")
    if len(g["members"]) + len(add) > 30:
        raise ServiceError("BAD_REQUEST", "한 방에는 최대 30명까지 있을 수 있어요.", "group")
    active = _active_settlement(g)
    n0 = len(g["members"])
    g["members"] = g["members"] + add
    for k in ("shares", "approvals"):
        cur = list(g.get(k) or [])[:n0] + [0 if k == "shares" else False] * (n0 - len(g.get(k) or []))
        g[k] = cur + [0 if k == "shares" else False] * len(add)
    g["viewers"] = sorted(set(g["viewers"]) | set(add))
    g["pending"] = list(dict.fromkeys((g.get("pending") or []) + add))
    g["v"] += 1
    _sys(g, f"{user}님이 {', '.join(add)}님을 초대했어요" + (" · 진행 중인 정산에는 포함되지 않고, 다음 정산부터 함께해요" if active else ""), user)
    store.kv_put("groups", gid, g)
    for m in add:
        _invite_notify(g, user, m)
    return _room_view(g, user)


@_locked
def group_join(user: str, gid: str) -> dict[str, Any]:
    """알림함의 초대 ‘참여’."""
    g = _room(gid, user)
    if user in (g.get("pending") or []):
        g["pending"] = [x for x in g["pending"] if x != user]
        _sys(g, f"{user}님이 들어왔어요", user)
        store.kv_put("groups", gid, g)
    u = store.user_by_short(user)
    if u:
        _req_done(u["email"], "invite", gid, "accepted")
    return _room_view(g, user)


@_locked
def group_leave(user: str, gid: str, declined: bool = False) -> dict[str, Any]:
    """방 나가기 (초대 거절 포함). 진행 중인 정산이 있으면 분담금이 꼬이므로 막는다."""
    g = _room(gid, user)
    rec = _active_settlement(g)
    if rec and any(m["name"] == user for m in rec.get("members") or []) or (rec and rec.get("payer") == user):
        raise ServiceError("ALREADY_SETTLING", f"‘{g['name']}’은 정산이 진행 중이에요. 정산이 끝나거나 취소된 뒤에 나갈 수 있어요.", "group", 409)
    L = store.kv_get("listings", gid)
    if L and L.get("host") == user and L.get("status") in ("open", "full"):
        L.update(status="closed", closed_reason="모집자가 나감")
        store.kv_put("listings", gid, L)
    sa = g.get("splitApproval")
    if sa and user in sa["targets"]:
        _split_close(g, "cancelled", user)
        g["status"] = "비용 입력 대기"
        _sys(g, f"분담표 승인 요청이 취소됐어요 ({user}님이 나감) · 조건을 다시 말해 주세요.")
    if user in g["members"]:
        i = g["members"].index(user)
        for k in ("members", "shares", "approvals"):
            if isinstance(g.get(k), list) and len(g[k]) > i:
                g[k] = g[k][:i] + g[k][i + 1:]
    g["viewers"] = [v for v in g["viewers"] if v != user]
    g["pending"] = [x for x in (g.get("pending") or []) if x != user]
    g["muted"] = [x for x in (g.get("muted") or []) if x != user]
    if g.get("creator") == user and g["members"]:
        g["creator"] = g["members"][0]
    if g.get("payer") == user and g["members"] and not g.get("sid"):
        g["payer"] = g["members"][0]
    g["v"] += 1
    _sys(g, f"{user}님이 " + ("초대를 거절했어요" if declined else "방에서 나갔어요"), user)
    if g["viewers"]:
        store.kv_put("groups", gid, g)
    else:
        store.kv_put("groups", gid, None)                  # 아무도 없으면 방 삭제
    u = store.user_by_short(user)
    if u:
        _req_done(u["email"], "invite", gid, "declined" if declined else "left")
    return {"left": True}


@_locked
def group_update(user: str, gid: str, patch: dict[str, Any]) -> dict[str, Any]:
    g = _room(gid, user)
    for k in _GROUP_KEYS:
        if k in patch:
            g[k] = patch[k]
    g["viewers"] = sorted(set(g["viewers"]) | set(g.get("members") or []))
    g["v"] += 1
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)
    return _room_view(g, user)


@_locked
def group_message(user: str, gid: str, msg: dict[str, Any]) -> dict[str, Any]:
    g = _room(gid, user)
    m = _clean_msg(msg or {}, user)
    if not any(x["id"] == m["id"] for x in g["msgs"]):
        g["msgs"].append(m)
        g["msgs"] = g["msgs"][-500:]
        g["updated_at"] = time.time()
        store.kv_put("groups", gid, g)
    return m


@_locked
def group_resolve(user: str, gid: str, mid: str, accepted: bool) -> dict[str, Any]:
    g = _room(gid, user)
    m = next((x for x in g["msgs"] if x["id"] == mid), None)
    if not m:
        raise ServiceError("NOT_FOUND", "없는 메시지예요.", "group", 404)
    if m.get("resolved"):
        return m   # 다른 멤버가 먼저 처리
    m.update({"resolved": True, "accepted": bool(accepted), "resolvedBy": user})
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)
    return m


# ───────────── 분담표 승인 (정산 대상 전원 동의 → 온체인 정산 시작) ─────────────
# 확인 카드를 누른 한 사람이 바로 온체인에 올리지 않고, 정산 대상(내 몫이 있는 사람 + 받는 사람) 전원이
# 각자 '승인'해야 서버가 propose_request 를 실행한다. 승인 기록은 방에 남고(누가·언제), 금액 계산은 하지 않는다 (0 tokens).
def _split_targets(kw: dict[str, Any]) -> list[str]:
    share = {str(n): int(a) for n, a in kw.get("shares") or []}
    payer = kw.get("payer")
    return [n for n in kw.get("members") or [] if share.get(n, 0) > 0 or n == payer]


def _split_view(sa: dict[str, Any] | None) -> dict[str, Any] | None:
    if not sa:
        return None
    return {k: sa.get(k) for k in ("id", "by", "at", "targets", "approved", "total", "shares", "payer", "mid")}


def _split_msg(g: dict[str, Any], sa: dict[str, Any]) -> dict[str, Any] | None:
    return next((m for m in g["msgs"] if m.get("id") == sa.get("mid")), None)


def _split_close(g: dict[str, Any], outcome: str, by: str | None = None) -> None:
    """진행 중인 승인 요청을 닫는다 (outcome: started·rejected·superseded·failed·cancelled)."""
    sa = g.pop("splitApproval", None)
    if not sa:
        return
    m = _split_msg(g, sa)
    if m:
        m.update(resolved=True, outcome=outcome, outcomeBy=by, approved=list(sa["approved"]))
    for n in sa["targets"]:
        if n not in sa["approved"]:
            u = store.user_by_short(n)
            if u:
                _req_done(u["email"], "split", g["id"], outcome)


def _split_launch(user: str, gid: str) -> dict[str, Any] | None:
    """전원 승인 → 온체인 정산 요청 (지갑·잔액 준비가 안 됐으면 기존처럼 보관 후 자동 시작)."""
    g = store.kv_get("groups", gid)
    sa = g.get("splitApproval") if g else None
    if not sa or set(sa["targets"]) - set(sa["approved"]):
        return None
    kw = dict(sa["kw"])
    _split_close(g, "started", user)
    _sys(g, f"✅ 정산 대상 {len(sa['targets'])}명이 모두 분담표를 승인했어요 → Pie가 온체인 정산을 요청해요.")
    g["v"] += 1
    store.kv_put("groups", gid, g)
    llm.code_step("settlement.approve_split", gid, f"0 tokens (code-only): {len(sa['targets'])}/{len(sa['targets'])} approved")
    try:
        return propose_request(user, **kw)
    except ServiceError as e:
        g = store.kv_get("groups", gid)
        if g:
            _sys(g, f"⚠️ 정산을 시작하지 못했어요: {e.message} · 조건을 다시 말해 주면 새 분담표로 다시 승인을 받아요.")
            g["status"] = "비용 입력 대기"
            g["v"] += 1
            store.kv_put("groups", gid, g)
        raise


@_locked
def split_start(user: str, gid: str, kw: dict[str, Any]) -> dict[str, Any]:
    """확인 카드 '확인' = 분담표 승인 요청. 요청한 사람이 정산 대상이면 그 사람은 승인한 것으로 센다."""
    g = _room(gid, user)
    if user not in g["members"]:
        raise ServiceError("FORBIDDEN", "이 방의 멤버만 정산을 요청할 수 있어요.", "settlement.approve_split", 403)
    kw = {**kw, "group_id": gid}
    members = [str(n) for n in kw.get("members") or []]
    share_names = [str(n) for n, _ in kw.get("shares") or []]
    if not members or set(share_names) != set(members) or not set(members) <= set(g["members"]):
        raise ServiceError("BAD_REQUEST", "분담표의 멤버가 방 멤버와 달라요. 조건을 다시 말해 주세요.", "settlement.approve_split")
    if kw.get("payer") not in members:
        raise ServiceError("BAD_REQUEST", "받는 사람(결제자)은 참여자 중 한 명이어야 해요.", "settlement.approve_split")
    if settlement.prohibited_reason(" ".join(str(kw.get(k) or "") for k in ("group_name", "rule_text", "purpose", "merchant"))):
        raise ServiceError("PROHIBITED_PURPOSE", settlement.REFUSE_MSG, "settlement.approve_split", 403)
    targets = _split_targets(kw)
    if not targets:
        raise ServiceError("BAD_REQUEST", "나눠 낼 사람이 없어요.", "settlement.approve_split")
    if g.get("splitApproval"):
        _split_close(g, "superseded", user)
    g.pop("pendingPropose", None)                 # 예전 분담표로 기다리던 자동 시작은 취소 (새 분담표로 다시 승인)
    sid = "sa" + uuid.uuid4().hex[:10]
    shares = [[str(n), int(a)] for n, a in kw["shares"]]
    approved = [user] if user in targets else []
    msg = {"id": "sq" + sid[2:], "from": user, "by": user, "kind": "splitReq", "total": int(kw.get("total") or 0),
           "shares": shares, "payer": kw["payer"], "targets": targets, "approved": list(approved), "splitId": sid,
           "resolved": False, "ts": time.time()}
    g["splitApproval"] = {"id": sid, "kw": kw, "by": user, "at": time.time(), "targets": targets, "approved": approved,
                          "total": msg["total"], "shares": shares, "payer": kw["payer"], "mid": msg["id"]}
    g["msgs"].append(msg)
    g["msgs"] = g["msgs"][-500:]
    g["status"] = "승인 대기"
    g["v"] += 1
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)
    mine = dict((n, a) for n, a in shares)
    for n in targets:
        if n not in approved:
            notify_short(n, "승인 요청", f"{g['name']} · {user}님이 분담표 승인을 요청했어요 · 내 몫 {won(mine.get(n, 0))}",
                         go=["gchat", gid], action=True, key=f"split:{gid}",
                         req={"type": "split", "key": gid, "status": "pending"})
    rec = _split_launch(user, gid)              # 정산 대상이 요청한 사람 한 명뿐이면 바로 시작
    return {"room": _room_view(store.kv_get("groups", gid), user), "rec": rec}


@_locked
def split_approve(user: str, gid: str, split_id: str | None = None) -> dict[str, Any]:
    g = _room(gid, user)
    sa = g.get("splitApproval")
    if not sa or (split_id and split_id != sa["id"]):
        raise ServiceError("NOT_FOUND", "승인할 분담표가 없어요. 이미 시작됐거나 바뀌었을 수 있어요.", "settlement.approve_split", 404)
    if user not in sa["targets"]:
        raise ServiceError("FORBIDDEN", "이 분담표의 정산 대상이 아니에요 (내 몫 없음).", "settlement.approve_split", 403)
    if user not in sa["approved"]:
        sa["approved"].append(user)
        m = _split_msg(g, sa)
        if m:
            m["approved"] = list(sa["approved"])
        left = [n for n in sa["targets"] if n not in sa["approved"]]
        _sys(g, f"👍 {user}님이 분담표를 승인했어요 ({len(sa['approved'])}/{len(sa['targets'])})"
             + (f" · 남은 사람: {', '.join(left)}" if left else ""), user)
        g["v"] += 1
        store.kv_put("groups", gid, g)
        u = store.user_by_short(user)
        if u:
            _req_done(u["email"], "split", gid, "approved")
    rec = _split_launch(user, gid)
    return {"room": _room_view(store.kv_get("groups", gid), user), "rec": rec}


@_locked
def split_reject(user: str, gid: str, reason: str = "") -> dict[str, Any]:
    g = _room(gid, user)
    sa = g.get("splitApproval")
    if not sa:
        raise ServiceError("NOT_FOUND", "진행 중인 승인 요청이 없어요.", "settlement.approve_split", 404)
    if user not in sa["targets"] and user != sa["by"]:
        raise ServiceError("FORBIDDEN", "정산 대상만 분담표를 거절할 수 있어요.", "settlement.approve_split", 403)
    reason = re.sub(r"\s+", " ", reason or "").strip()[:100]
    cancelled = user == sa["by"] and (reason == "요청 취소" or user not in sa["targets"])   # 요청한 사람이 거두어들임
    _split_close(g, "cancelled" if cancelled else "rejected", user)
    g["status"] = "비용 입력 대기"
    _sys(g, (f"↩️ {user}님이 분담표 승인 요청을 취소했어요." if cancelled else
             f"✋ {user}님이 분담표에 동의하지 않았어요" + (f" (“{reason}”)" if reason else "") + ".")
         + " 조건을 다시 말해 주면 Pie가 새 확인 카드를 만들어요.", user)
    g["v"] += 1
    store.kv_put("groups", gid, g)
    if not cancelled and sa["by"] != user:
        notify_short(sa["by"], "정산", f"{g['name']} · {user}님이 분담표에 동의하지 않았어요" + (f": {reason}" if reason else ""),
                     go=["gchat", gid])
    return {"room": _room_view(g, user), "rec": None}


# ───────────── 그룹 채팅방의 Pie mate (방의 한 멤버처럼 대화) ─────────────
# 모든 메시지를 서버가 받자마자 읽고: 잡담은 무시(코드 판단, 토큰 0) · 정산/구매 관련이면 답 · 이름을 부르면 무조건 답.
PIE_NAME = re.compile(
    r"(?i)(?<![a-z])(?:pie\s*mate|piemate|share\s*pie|sharepie|pie(?:bot)?|pai)(?![a-z])"
    r"|쉐어\s*파이|셰어\s*파이|세어\s*파이|파이\s*메이트|파이\s*매이트|파이\s*봇|파메|퐈이|@\s*파이"
    r"|(?<![가-힣])파이(?=$|[\s,.!?~^ㅋㅎㅠㅜ;:)]|야|아|님|씨|가\b|가\s|는\s|도\s|랑|한테|에게|좀|쨩|짱|이야|이\s)")
_SPLIT = re.compile(r"나눠|나누|나눔|분담|n\s*빵|엔\s*빵|더치|똑같이|균등|반반|빼고|제외|적게|덜\s*내|더\s*내|많이\s*내|비율|%|퍼센트|씩\s*(내|부담)|몰아|내가\s*(쏠|낼)|쏜다|쏠게")
_SETTLE_TALK = re.compile(r"정산|얼마|총액|금액|송금|입금|환불|이의|결제|냈|내야|내면|갚|돈|예치|승인|인출|잔액|충전|영수증|계산|PIE|코인|지갑|\d\s*(원|만|천|억)|[일이삼사오육칠팔구십백천만억]\s*원|%")
_BUY_TALK = re.compile(r"사자|살까|살래|사줘|사야|사는|구매|주문|시키|시켜|시킬|배달|메뉴|추천|쿠팡|가격|최저가|공구|공동\s*구매|장바구니|상품|배송|먹을까|뭐\s*먹|먹자|골라|고를|어디서\s*사|가성비|할인|쿠폰")
_QUESTION = re.compile(r"\?|뭐|어떻게|얼마|누구|누가|언제|왜|어디|어때|할까|될까|맞아|나는|난\b|그럼|근데")

GROUP_PIE_SYSTEM = """[그룹 채팅방 모드]
지금 너는 여러 친구가 있는 그룹 채팅방의 한 멤버 'Pie mate(파이)'다. 사람처럼 대화에 끼어 자연스럽게 말한다.
- 대화 기록은 '이름: 내용' 형식이다. 방금 말한 사람의 말을 끝까지 읽고 의도를 정확히 이해한 뒤, 그 사람 이름을 불러 그 말에 맞게 답한다.
  앞에서 오간 말(누가 뭘 사자고 했는지, 누가 얼마를 냈는지)을 기억해서 이어 간다. 엉뚱하게 처음부터 다시 묻지 않는다.
- 1~3문장, 친근한 해요체, 단톡방 말투. 필요할 때만 짧은 목록.
- 정산 조건(총액·나누는 방식)을 말하면 앱이 따로 계산 카드를 띄운다. 금액은 절대 머리로 계산하지 말고 split_cost 결과만 말한다.
- 이름만 부르면(예: '파이야') 반갑게 대답하고, 방 상황을 보고 지금 도울 수 있는 걸 한 가지 제안한다.
- 방 정보에 없는 사실(누가 냈는지 등)을 지어내지 않는다. 앱에 없는 버튼·메뉴·기능을 지어내지 않는다.
- 정산이 ‘시작 대기’면 무엇이 남았는지(지갑 연결·PIE 충전, 누구) 그대로 알려 주고, 준비되면 자동으로 시작된다고 말한다.
- 분담표 ‘승인 대기’면 아직 승인 안 한 사람에게 방의 ‘분담표 승인 요청’ 카드나 그룹 탭 카드의 ‘분담표 승인하기’를 누르라고 안내한다. 정산 대상 전원이 승인해야 온체인 정산이 시작된다.
- 온체인 정산이 시작됐으면 각자 방의 ‘결제 요청’ 카드나 그룹 탭 카드의 ‘내 몫 결제하기’를 누르면 된다고 안내한다."""


def _pie_room_context(g: dict[str, Any]) -> str:
    lines = [f"방 이름: {g.get('name')}", f"멤버: {', '.join(g.get('members') or [])}"]
    if g.get("total"):
        lines.append(f"정산 총액: {won(int(g['total']))} · 결제자(받는 사람): {g.get('payer') or '미정'}")
    shares = g.get("shares") or []
    if g.get("members") and any(shares):
        lines.append("분담표: " + ", ".join(f"{n} {won(int(a or 0))}" for n, a in zip(g["members"], shares)))
    if g.get("ruleText"):
        lines.append(f"확정된 조건: {g['ruleText']}")
    pp = g.get("pendingPropose")
    sa = g.get("splitApproval")
    if sa:
        left = [n for n in sa["targets"] if n not in sa["approved"]]
        lines.append(f"정산 상태: 분담표 승인 대기 {len(sa['approved'])}/{len(sa['targets'])} — 승인: {', '.join(sa['approved']) or '없음'}"
                     f" · 아직: {', '.join(left)}. 정산 대상 전원이 승인하면 서버가 자동으로 온체인 정산을 시작함")
    elif pp and not g.get("sid"):
        lines.append(f"정산 상태: 확인 완료 · 온체인 시작 대기 — {_pending_text(pp.get('noWallet') or [], pp.get('short') or [])}. "
                     "준비되면 서버가 자동으로 시작함 (따로 누를 버튼 없음)")
    elif g.get("sid"):
        try:
            rec = get_settlement(g["sid"])
            st = {"wait": "대기", "locked": "예치(결제) 완료", "offline": "현금 확인", "refunded": "환불", "payee": "받는 사람", "approved": "인출 승인"}
            lines.append(f"온체인 정산 상태: {rec.get('status')} · " + ", ".join(
                f"{m['name']} {st.get(m.get('state'), m.get('state'))}" for m in rec.get("members") or []))
        except Exception:   # noqa: BLE001
            lines.append(f"온체인 정산 상태: {g.get('status')}")
    else:
        lines.append(f"정산 상태: {g.get('status') or '조건 입력 대기'} (아직 온체인 등록 전)")
    return "\n".join(lines)


def _pie_speaker(m: dict[str, Any]) -> str:
    return "Pie" if m.get("pie") or m.get("from") == "sys" else str(m.get("from"))


def pie_should_reply(text: str, recent: list[dict[str, Any]], speaker: str | None = None) -> tuple[bool, str]:
    """(답할지, 이유). 코드만으로 판단 → 잡담은 토큰 0으로 넘긴다."""
    if settlement.prohibited_reason(text):
        return True, "prohibited"
    if PIE_NAME.search(text):
        return True, "called"
    last_pie = next((i for i, m in enumerate(reversed(recent)) if m.get("pie")), None)
    if last_pie is not None and last_pie <= 2:
        pm = list(reversed(recent))[last_pie]
        same = not pm.get("to") or pm.get("to") == speaker
        if (pm.get("ask") == "settle") or (last_pie == 0 and same and (pm.get("ask") or _QUESTION.search(text))):
            return True, "followup"          # Pie가 방금 물은 것에 대한 대답 / Pie가 말 건 사람의 바로 다음 말
    if _SPLIT.search(text) or _SETTLE_TALK.search(text):
        return True, "settle"
    if _BUY_TALK.search(text):
        return True, "buy"
    return False, "chitchat"


def _pie_is_condition(text: str, reason: str, recent: list[dict[str, Any]]) -> bool:
    """정산 조건(→ 계산 카드)인지, 대화(→ 에이전트 답)인지."""
    last = next((m for m in reversed(recent) if m.get("pie")), None)
    if reason == "followup" and last and last.get("ask") == "settle":
        return True
    if _SPLIT.search(text) and not re.search(r"(뭐|어떻게|어떡|할까|좋을까|나을까)\s*\??\s*$", text):
        return True
    has_amt = bool(textutil.parse_amounts(text)) or "%" in text
    return has_amt and not _BUY_TALK.search(text) and not re.search(r"\?\s*$", text)


def _pie_confirm_card(d: dict[str, Any], g: dict[str, Any]) -> dict[str, Any]:
    adj = (d.get("rule") or {}).get("adjustments") or []
    kinds = {a.get("kind") for a in adj}
    mode = ("균등 분배" if not adj else "비율 분배" if kinds & {"ratio", "percent"} else "고정 금액 + 나머지 분배" if "fixed" in kinds
            else "차등 분배" if kinds & {"less", "more"} else "일부 제외 후 분배" if "exclude" in kinds else "맞춤 분배")
    lines = [f"{n} {won(a)}" + (" (결제자)" if n == d.get("payer") else "") for n, a in d["shares"]]
    lines += [f"⚠️ {w['message']} → 요청하면 지출 통제로 중단돼요" for w in d.get("warnings") or []]
    if (d.get("rule") or {}).get("total_note"):
        lines.insert(0, f"총액 근거: {d['rule']['total_note']}")
    return {"id": "p" + uuid.uuid4().hex[:10], "from": "sys", "kind": "confirm", "resolved": False, "meta": d.get("meta"),
            "confirmData": {"itemName": d.get("subject") or g.get("name"), "total": d["total"], "participants": d["members"],
                            "modeLabel": mode, "lines": lines}, "analysis": d}


@_locked
def _pie_post(gid: str, msgs: list[dict[str, Any]], typing: bool | None = None) -> None:
    g = store.kv_get("groups", gid)
    if not g:
        return
    for m in msgs:
        m.setdefault("ts", time.time())
        m.setdefault("by", "pie")
        g["msgs"].append(m)
    g["msgs"] = g["msgs"][-500:]
    if typing is not None:
        g["pieTyping"] = time.time() if typing else 0
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)


def _pie_say(text: str, reply_to: str, meta: str = "", ask: str | None = None) -> dict[str, Any]:
    m = {"id": "p" + uuid.uuid4().hex[:10], "from": "sys", "pie": True, "text": text[:1500], "replyTo": reply_to, "meta": meta}
    if ask:
        m["ask"] = ask
    return m


def group_pie(user: str, gid: str, mid: str, scenario: str | None = None, edited: bool | None = None) -> list[dict[str, Any]]:
    """방금 올라온 메시지를 읽고 Pie mate가 답할 메시지들(방에도 저장)을 돌려준다. 답할 필요 없으면 [].
    베타: 턴 id·시나리오 id가 이 턴의 Kiln 기록과 Pie 답에 붙고, 동의한 사람의 턴은 비식별 저장."""
    g = _room(gid, user)
    sc = (beta.scenario(scenario) or {}).get("id")
    if sc:
        beta.mark_done(quota.current_email(), sc)       # 그룹 예시는 보내기만 해도 완료 (잡담 판정이어도)
    turn = beta.new_turn()
    with usage.scope("group", g.get("name") or "그룹방"), quota.turn() as q, \
            usage.tagged(turn=turn, scenario=sc, edited=bool(edited) if sc else None) as tg:
        out = _group_pie(user, gid, mid, limited=q if q and q["blocked"] else None, turn=turn)
    if out:
        try:
            m = next((x for x in g["msgs"] if x.get("id") == mid), {}) or {}
            idx = next((i for i, x in enumerate(g["msgs"]) if x.get("id") == mid), len(g["msgs"]))
            hist = [f"{x.get('from')}: {x.get('text')}" for x in g["msgs"][max(0, idx - 4):idx] if x.get("text")]
            beta.log_turn(quota.current_email(), channel="group", flow=gid, turn=turn, sid=sc, edited=edited if sc else None,
                          text=f"{m.get('from', user)}: {m.get('text', '')}", history=hist, replies=out, tags=tg,
                          names=list(g.get("members") or []) + [user])
        except Exception as e:   # noqa: BLE001
            print(f"[beta] 그룹 기록 실패: {e}", flush=True)
    return out


def _with_turn(out: list[dict[str, Any]], turn: str | None) -> list[dict[str, Any]]:
    for x in out:
        if turn and x.get("pie"):
            x["turn"] = turn
    return out


def _group_pie(user: str, gid: str, mid: str, limited: dict[str, Any] | None = None, turn: str | None = None) -> list[dict[str, Any]]:
    g = _room(gid, user)
    idx = next((i for i, m in enumerate(g["msgs"]) if m.get("id") == mid), None)
    if idx is None:
        return []
    m = g["msgs"][idx]
    if m.get("from") == "sys" or not (m.get("text") or "").strip():
        return []
    if any(x.get("replyTo") == mid for x in g["msgs"]):
        return []                                    # 이미 답함 (중복 호출)
    text, speaker = m["text"].strip(), m["from"]
    recent = [x for x in g["msgs"][max(0, idx - 14):idx] if x.get("text") or x.get("kind") == "confirm"]
    flow = gid
    reply, why = pie_should_reply(text, recent, speaker)
    if not reply:
        llm.code_step("group.pie", flow, "0 tokens (code-only): 잡담 → Pie 응답 안 함")
        return []
    if why == "prohibited":
        out = [_pie_say(f"{speaker}님, " + settlement.REFUSE_MSG, mid, llm.meta_line([llm.code_step("group.pie", flow, "PROHIBITED_PURPOSE")]))]
        _pie_post(gid, _with_turn(out, turn))
        return out
    if g.get("pendingPropose") and re.search(r"지갑|충전|연결|확인|버튼|시작|안\s*돼|안\s*보|왜", text):
        if retry_pending(list(g["pendingPropose"]["kw"]["members"])):
            g = store.kv_get("groups", gid)          # 방금 자동 시작됨 → 최신 상태로 답
    _pie_post(gid, [], typing=True)
    try:
        out = _pie_answer(g, text, speaker, why, recent, mid, flow, limited=limited)
        if limited and out and _limit_notice_once(limited):      # 한도 안내는 초기화 전까지 한 번만 (방 도배 방지)
            out[0]["text"] = (f"(AI 사용 한도: {quota.when_text(limited['resetsAt'])}에 초기화 · 지금은 규칙으로 답해요) "
                              + (out[0].get("text") or ""))
            out[0]["limit"] = _limit_card(limited)
        for x in out:
            if x.get("pie"):
                x["to"] = speaker
                if speaker not in (x.get("text") or "")[:40]:
                    x["text"] = f"{speaker}님, " + x["text"]      # 누구에게 하는 말인지 항상 분명하게
    except Exception as e:   # noqa: BLE001 — Pie가 실패해도 채팅은 계속
        out = [_pie_say(f"{speaker}님, 잠깐 생각이 꼬였어요. 한 번만 다시 말해 줄래요? ({type(e).__name__})", mid)]
    _pie_post(gid, _with_turn(out, turn), typing=False)
    return out


def _limit_notice_once(st: dict[str, Any]) -> bool:
    email = quota.current_email()
    if not email:
        return False
    q = store.kv_get("ai_quota", email) or {}
    if q.get("noticeFor") == st.get("resetsAt"):
        return False
    store.kv_put("ai_quota", email, {**q, "noticeFor": st.get("resetsAt")})
    return True


def _pie_answer(g, text, speaker, why, recent, mid, flow, limited=None) -> list[dict[str, Any]]:
    stopped = g.get("status") == "중단됨"
    condition = _pie_is_condition(text, why, recent)
    if condition and g.get("sid") and not stopped:
        condition = False                           # 등록된 정산은 바꿀 수 없음 → 대화로 상태 안내
    if condition and g.get("sid") and stopped and (g.get("payer") or speaker) != speaker:
        return [_pie_say(f"{speaker}님, 중단된 정산의 조건은 결제자 {g.get('payer')}님이 다시 정해 주셔야 해요.", mid)]
    if condition:
        last_reject = max([i for i, x in enumerate(recent) if x.get("kind") == "confirm" and x.get("resolved") and not x.get("accepted")] or [-1])
        hist = [x["text"] for x in recent[last_reject + 1:] if x.get("text") and not x.get("pie") and x.get("from") != "sys"][-4:]
        clean_text = PIE_NAME.sub(" ", text).strip(" ,.!?~") or text
        total = g.get("total") or sum(int(a or 0) for a in (g.get("shares") or [])) or None
        d = analyze(clean_text, g.get("members") or [], total, g.get("payer") or speaker, g.get("name"), hist, flow)
        if d["status"] == "ok":
            head = _pie_say(f"{speaker}님 말 이해했어요! 이렇게 나누면 돼요 👇 맞으면 확인을 눌러 주세요.", mid, d.get("meta", ""))
            return [head, _pie_confirm_card(d, g)]
        if d["status"] == "refused":
            return [_pie_say(f"{speaker}님, {d['question']}", mid, d.get("meta", ""))]
        return [_pie_say(f"{speaker}님, {d['question']}", mid, d.get("meta", ""), ask="settle")]
    # 대화: 방 상황 + 최근 대화를 읽고 에이전트가 답 (필요하면 상품·메뉴 검색, split_cost)
    metas: list[dict[str, Any]] = []
    hist = [{"role": "assistant" if x.get("pie") else "user", "text": f"{_pie_speaker(x)}: {x.get('text')}"}
            for x in recent if x.get("text") and (x.get("pie") or x.get("from") != "sys")]
    extra = GROUP_PIE_SYSTEM + "\n[방 정보]\n" + _pie_room_context(g)
    if llm.client.mode == "live" and not limited:
        try:
            u = store.user_by_short(speaker)
            res = assistant.run(f"{speaker}: {text}", hist, user=speaker, flow=flow, metas=metas,
                                address=(u or {}).get("address") or None, system_extra=extra,
                                channel="group", room=_pie_room_context(g))     # 두뇌: persona + modes의 group + 방 정보
            body = res["text"]
            if res.get("card"):
                body += "\n\n" + _pie_card_text(res["card"])
            ask = "chat" if re.search(r"\?\s*$", body) else None
            return [_pie_say(body, mid, llm.meta_line(metas), ask=ask)]
        except llm.LLMError as e:
            metas.append(llm.code_step("assistant.fallback", flow, f"{e.code}: {e.message}"[:200]))
    return [_pie_say(_pie_rule_reply(g, text, speaker, why), mid, llm.meta_line(metas or [llm.code_step("group.pie", flow, "규칙 기반 답")]))]


def _pie_card_text(card) -> str:
    kind, r = card
    cands = r.get("candidates") or []
    if kind == "combo":
        return _card_caption(kind, r)
    rows = []
    for i, c in enumerate(cands[:4]):
        p = c.get("product") or c
        name = p.get("title") or p.get("name") or c.get("title") or "상품"
        price = (c.get("eval") or {}).get("per") or p.get("price") or c.get("price")
        rows.append(f"{i + 1}) {name}" + (f" · {won(int(price))}" + ("/1인" if (c.get("eval") or {}).get("per") else "") if price else ""))
    return ("찾은 후보예요:\n" + "\n".join(rows) + "\n마음에 드는 게 있으면 Pie 탭에서 카드를 눌러 정산방으로 가져올 수 있어요.") if rows else ""


def _pie_rule_reply(g, text, speaker, why) -> str:
    """Kiln 없이(오프라인·장애) 쓰는 규칙 답 — 방 상황을 코드로 읽어 말한다."""
    ctx = _pie_room_context(g).split("\n")
    state = next((l for l in ctx if "상태" in l), "")
    if why == "called" and not (_SPLIT.search(text) or _SETTLE_TALK.search(text) or _BUY_TALK.search(text)):
        return f"네 {speaker}님, 저 여기 있어요! 😊 " + ("총액이랑 나누는 방식을 말해 주면 바로 계산해 드릴게요." if not g.get("sid") else state)
    if why == "buy":
        return f"{speaker}님, 살 거 정해지면 가격이랑 나누는 방식을 말해 주세요. 상품 비교는 Pie 탭에서 찾아 드릴 수 있어요."
    if re.search(r"누가|안\s*냈|결제\s*했|상태|어디까지", text):
        return f"{speaker}님, 지금 {state.replace('온체인 ', '')}"
    return f"{speaker}님, " + ("정산 조건은 ‘총 12만원 똑같이 나눠줘’처럼 말해 주면 바로 계산해 드릴게요." if not g.get("sid") else state)


# ───────────── 동네 공동구매 모집 (GPS로 근처 이웃에게 공개) ─────────────
# 모집한 사람이 동의한 '모집 위치'만 약 100m 단위로 저장. 보는 사람의 위치는 거리 계산에만 쓰고 저장하지 않는다.
# 다른 사람에게는 좌표 대신 동 이름과 대략 거리(100m 단위)만 보여 준다.
LISTING_RADII = (1, 3, 5, 10)
_JOIN_MAX_KM = 10


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _ll(lat: Any, lng: Any) -> tuple[float, float] | None:
    try:
        la, lo = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    return (la, lo) if -90 <= la <= 90 and -180 <= lo <= 180 and (la, lo) != (0.0, 0.0) else None


def _dist_label(d: float | None) -> str:
    if d is None:
        return "같은 동네"
    if d < 150:
        return "바로 근처"
    return f"약 {int(round(d / 100) * 100)}m" if d < 1000 else f"약 {d / 1000:.1f}km"


def _deadline_label(ts: float) -> str:
    left = ts - time.time()
    if left <= 0:
        return "마감"
    if left < 3600:
        return f"{max(1, int(left // 60))}분 남음"
    if left < 86400:
        return f"{int(left // 3600)}시간 남음"
    return f"D-{int(left // 86400)}"


def _listing_refresh(L: dict[str, Any], g: dict[str, Any] | None) -> dict[str, Any]:
    if not g:
        L["status"] = "closed"
        return L
    if L["status"] in ("open", "full"):
        if time.time() > L["deadline"]:
            L.update(status="closed", closed_reason="기간 마감")
        elif g.get("sid") and g.get("status") != "중단됨":
            L.update(status="closed", closed_reason="정산 시작")
        else:
            L["status"] = "full" if len(g.get("members") or []) >= L["cap"] else "open"
    return L


def _listing_view(L: dict[str, Any], g: dict[str, Any], me: str, dist: float | None) -> dict[str, Any]:
    members = g.get("members") or []
    total = int(g.get("total") or 0)
    return {"id": L["gid"], "name": g.get("name") or L["name"], "host": L["host"], "dong": L.get("dong") or "",
            "distanceM": int(round(dist / 100) * 100) if dist is not None else None, "distanceLabel": _dist_label(dist),
            "joined": len(members), "cap": L["cap"], "total": total,
            "perPerson": math.ceil(total / L["cap"]) if total else None,       # 모집 인원이 다 모였을 때 1인 (코드 계산)
            "status": L["status"], "closedReason": L.get("closed_reason"),
            "deadline": L["deadline"], "deadlineLabel": _deadline_label(L["deadline"]), "note": L.get("note") or "",
            "product": g.get("product") or None, "merchant": g.get("merchant"),
            "isMine": L["host"] == me, "isMember": me in members, "createdAt": L["created_at"]}


def listing_create(user: dict[str, Any], gid: str, cap: int, lat: Any = None, lng: Any = None,
                   deadline_hours: int = 48, note: str = "") -> dict[str, Any]:
    me = user["short"]
    ll = _ll(lat, lng)
    dong = ""
    if ll:
        try:
            dong = geo.reverse(*ll)["address"]
        except geo.GeoError:
            dong = ""
    dong = dong or user.get("address") or ""
    if not ll and not dong:
        raise ServiceError("NEED_LOCATION", "근처 이웃에게 보이려면 위치가 필요해요. 위치를 켜거나 ‘우리 동네’를 먼저 설정해 주세요.", "groupbuy", 400)
    return _listing_create(me, gid, cap, (round(ll[0], 3), round(ll[1], 3)) if ll else None, dong, deadline_hours, note)


@_locked
def _listing_create(me, gid, cap, ll, dong, deadline_hours, note) -> dict[str, Any]:
    g = _room(gid, me)
    if g.get("creator") != me:
        raise ServiceError("FORBIDDEN", "그룹을 만든 사람만 모집글을 올릴 수 있어요.", "groupbuy", 403)
    if g.get("sid") and g.get("status") != "중단됨":
        raise ServiceError("ALREADY_SETTLING", "이미 정산이 시작된 방은 모집할 수 없어요.", "groupbuy", 409)
    if settlement.prohibited_reason(" ".join([g.get("name") or "", note or ""])):
        raise ServiceError("PROHIBITED_PURPOSE", settlement.REFUSE_MSG, "groupbuy", 403)
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        cap = 0
    members = g.get("members") or []
    if not 2 <= cap <= 30 or cap < len(members):
        raise ServiceError("BAD_REQUEST", f"모집 인원은 지금 인원({len(members)}명) 이상, 2~30명으로 정해 주세요.", "groupbuy")
    hours = max(1, min(int(deadline_hours or 48), 168))
    L = {"gid": gid, "host": me, "name": g.get("name"), "cap": cap, "lat": ll[0] if ll else None, "lng": ll[1] if ll else None,
         "dong": dong, "created_at": time.time(), "deadline": time.time() + hours * 3600, "status": "open",
         "note": re.sub(r"\s+", " ", note or "")[:120]}
    store.kv_put("listings", gid, L)
    g["msgs"].append({"id": "l" + uuid.uuid4().hex[:10], "from": "sys", "by": me, "ts": time.time(),
                      "text": f"📍 {dong or '우리 동네'} 근처 이웃에게 공동구매 모집을 시작했어요 · {cap}명까지 · {_deadline_label(L['deadline'])}. "
                              "참여한 이웃은 이 채팅방에 들어와요."})
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)
    return _listing_view(_listing_refresh(L, g), g, me, None)


def listings_nearby(user: dict[str, Any], lat: Any = None, lng: Any = None, radius_km: Any = 3) -> dict[str, Any]:
    me, here = user["short"], _ll(lat, lng)
    try:
        radius = float(radius_km)
    except (TypeError, ValueError):
        radius = 3.0
    radius = min(LISTING_RADII, key=lambda r: abs(r - radius))
    my_dong = user.get("address") or ""
    items = []
    for gid, L in list(store.kv_all("listings").items()):
        if not L:
            continue
        g = store.kv_get("groups", gid)
        L = _listing_refresh(L, g)
        if not g:
            continue
        mine_or_in = L["host"] == me or me in (g.get("members") or [])
        if L["status"] != "open" and not (mine_or_in and L["status"] == "full"):
            continue
        dist = _dist_m(here, (L["lat"], L["lng"])) if here and L.get("lat") is not None else None
        if here and dist is not None:
            if dist > radius * 1000 and not mine_or_in:
                continue
        elif not (my_dong and L.get("dong") == my_dong) and not mine_or_in:
            continue                                       # 위치를 모르면 같은 동네 것만
        items.append(_listing_view(L, g, me, dist))
    items.sort(key=lambda x: (x["distanceM"] is None, x["distanceM"] or 0, -x["createdAt"]))
    mode = "gps" if here else ("dong" if my_dong else "none")
    return {"items": items, "mode": mode, "radiusKm": radius, "radii": list(LISTING_RADII), "dong": my_dong}


@_locked
def listing_join(user: dict[str, Any], gid: str, lat: Any = None, lng: Any = None) -> dict[str, Any]:
    me = user["short"]
    L = store.kv_get("listings", gid)
    g = store.kv_get("groups", gid)
    if not L or not g:
        raise ServiceError("NOT_FOUND", "없는 모집글이에요.", "groupbuy", 404)
    L = _listing_refresh(L, g)
    members = list(g.get("members") or [])
    if me in members:
        return {**_listing_view(L, g, me, None), "already": True}
    if L["status"] != "open":
        raise ServiceError("LISTING_CLOSED", {"full": "모집 인원이 다 찼어요."}.get(L["status"], f"모집이 끝났어요 ({L.get('closed_reason') or '마감'})."),
                           "groupbuy", 409)
    here = _ll(lat, lng)
    if here and L.get("lat") is not None:
        d = _dist_m(here, (L["lat"], L["lng"]))
        if d > _JOIN_MAX_KM * 1000:
            raise ServiceError("TOO_FAR", f"모집 위치에서 {d / 1000:.0f}km 떨어져 있어 참여할 수 없어요 (동네 공동구매는 {_JOIN_MAX_KM}km 이내).", "groupbuy", 403)
    elif not (user.get("address") and user.get("address") == L.get("dong")):
        raise ServiceError("NEED_LOCATION", "근처인지 확인하려면 위치를 켜 주세요.", "groupbuy", 400)
    members.append(me)
    shares = list(g.get("shares") or [0] * (len(members) - 1)) + [0]
    approvals = list(g.get("approvals") or [False] * (len(members) - 1)) + [False]
    g.update(members=members, shares=shares, approvals=approvals, viewers=sorted(set(g["viewers"]) | {me}), v=g["v"] + 1,
             updated_at=time.time())
    g["msgs"].append({"id": "l" + uuid.uuid4().hex[:10], "from": "sys", "by": me, "ts": time.time(),
                      "text": f"🙋 {me}님이 동네 공동구매에 참여했어요 ({len(members)}/{L['cap']}명)."
                              + (" 모집 인원이 다 찼어요! 이제 나누는 방식을 정해 주세요." if len(members) >= L["cap"] else "")})
    L = _listing_refresh(L, g)
    store.kv_put("groups", gid, g)
    store.kv_put("listings", gid, L)
    return _listing_view(L, g, me, None)


@_locked
def listing_leave(user: dict[str, Any], gid: str) -> dict[str, Any]:
    me = user["short"]
    L, g = store.kv_get("listings", gid), store.kv_get("groups", gid)
    if not L or not g or me not in (g.get("members") or []):
        raise ServiceError("NOT_FOUND", "참여하지 않은 모집이에요.", "groupbuy", 404)
    if L["host"] == me:
        raise ServiceError("FORBIDDEN", "모집한 사람은 나갈 수 없어요. 모집을 마감해 주세요.", "groupbuy", 403)
    if g.get("sid") and g.get("status") != "중단됨":
        raise ServiceError("ALREADY_SETTLING", "정산이 시작돼서 나갈 수 없어요.", "groupbuy", 409)
    i = g["members"].index(me)
    for k in ("members", "shares", "approvals"):
        if isinstance(g.get(k), list) and len(g[k]) > i:
            g[k] = g[k][:i] + g[k][i + 1:]
    g["viewers"] = [v for v in g["viewers"] if v != me]
    g["v"] += 1
    g["msgs"].append({"id": "l" + uuid.uuid4().hex[:10], "from": "sys", "by": me, "ts": time.time(),
                      "text": f"{me}님이 공동구매에서 나갔어요 ({len(g['members'])}/{L['cap']}명)."})
    g["updated_at"] = time.time()
    store.kv_put("groups", gid, g)
    store.kv_put("listings", gid, _listing_refresh(L, g))
    return {"left": True}


def listing_close(user: dict[str, Any], gid: str) -> dict[str, Any]:
    L = store.kv_get("listings", gid)
    if not L or L["host"] != user["short"]:
        raise ServiceError("NOT_FOUND", "내 모집글이 아니에요.", "groupbuy", 404)
    _listing_set(gid, "closed", "모집자가 마감")
    return {"closed": True}


@_locked
def _listing_set(gid: str, status: str, reason: str) -> None:
    L = store.kv_get("listings", gid)
    if L and L["status"] in ("open", "full"):
        L.update(status=status, closed_reason=reason)
        store.kv_put("listings", gid, L)


def listing_of(user: dict[str, Any], gid: str) -> dict[str, Any] | None:
    L, g = store.kv_get("listings", gid), store.kv_get("groups", gid)
    if not L or not g:
        return None
    return _listing_view(_listing_refresh(L, g), g, user["short"], None)


def groups_for(user: str) -> list[dict[str, Any]]:
    gs = [g for g in store.kv_all("groups").values() if user in g["viewers"]]
    return [_room_view(g, user) for g in sorted(gs, key=lambda g: -g["updated_at"])[:50]]


# ───────────── Pie 대화 기록 (다른 기기·새로고침 후에도 유지) ─────────────
def chats_for(user: str) -> list[dict[str, Any]]:
    rec = store.kv_get("chats", user) or {}
    return sorted(rec.values(), key=lambda c: -c.get("savedAt", 0))[:50]


@_locked
def chat_save(user: str, chat: dict[str, Any]) -> dict[str, Any]:
    cid = str(chat.get("id") or "")
    if not _GID.match(cid):
        raise ServiceError("BAD_REQUEST", "대화 id 형식이 올바르지 않아요.", "chat")
    import json as _json
    if len(_json.dumps(chat, ensure_ascii=False)) > 300_000:
        chat = {**chat, "msgs": (chat.get("msgs") or [])[-60:]}
    rec = dict(store.kv_get("chats", user) or {})
    rec[cid] = {**chat, "savedAt": time.time()}
    if len(rec) > 50:
        for k in sorted(rec, key=lambda k: rec[k]["savedAt"])[:len(rec) - 50]:
            rec.pop(k)
    store.kv_put("chats", user, rec)
    return {"saved": cid}


@_locked
def chat_delete(user: str, cid: str) -> dict[str, Any]:
    rec = dict(store.kv_get("chats", user) or {})
    rec.pop(cid, None)
    store.kv_put("chats", user, rec)
    return {"deleted": cid}
