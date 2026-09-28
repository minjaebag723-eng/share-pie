"""AI 구독 한도 — Claude 요금제를 벤치마킹해 '월 구독이 사용량을 정하는' 방식.

- 쓴 만큼 정산(후불)하지 않는다. 요금제(Free · Pie Pro · Pie Max 5x · Pie Max 20x)가 두 가지 한도를 정한다.
    · 5시간 세션 한도: 첫 AI 사용부터 5시간. 세션이 끝나면 다음 AI 사용 때 새 세션이 시작된다.
    · 주간 한도: 기준 시각(첫 사용)부터 7일마다 초기화.
- 사용량 = 이 사람 요청에서 일어난 Kiln 호출의 실제 토큰 수(usage.jsonl의 prompt + completion). 코드 단계는 0.
- 한도를 넘으면 Kiln을 부르지 않는다(0 토큰). 금액 계산·지출 통제·결제·승인은 원래 코드라 그대로 동작하고,
  대화는 규칙 기반 답으로 대체된다. 이미 시작된 답은 끝까지 한다(한 턴 도중에 끊지 않음 — Claude와 같은 방식).
- 분쟁 조사(dispute.*)는 한도와 상관없이 항상 동작한다. 증거·분쟁 도구가 요금제 때문에 막히면 안 되기 때문.
"""
from __future__ import annotations

import contextvars
import datetime as _dt
import math
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable

from . import config, store

AI_MODES = ("tools", "json", "text")          # 실제 Kiln 호출 기록만 사용량에 들어간다
EXEMPT_PREFIXES = ("dispute.",)                 # 분쟁 조사는 한도 밖 (공정성)
_KEEP_SEC = 8 * 86400                           # 한도 계산에 필요한 만큼만 메모리에 (주간 7일 + 여유)
_KST = _dt.timezone(_dt.timedelta(hours=9), "KST")

PLAN_ORDER = ("free", "pro", "max", "max20")
PLANS: dict[str, dict[str, Any]] = {
    "free": {"id": "free", "label": "Free", "price": 0, "mult": 0.2,
             "desc": "가끔 정산을 부탁하는 개인 · Pie 대화 약 5번 / 5시간"},
    "pro": {"id": "pro", "label": "Pie Pro", "price": config.AI_PRICE_PRO, "mult": 1,
            "desc": "모임 정산을 자주 하는 사람 · Free의 5배"},
    "max": {"id": "max", "label": "Pie Max 5x", "price": config.AI_PRICE_MAX, "mult": 5,
            "desc": "총무·공동구매 방장 · Pro의 5배"},
    "max20": {"id": "max20", "label": "Pie Max 20x", "price": config.AI_PRICE_MAX20, "mult": 20,
              "desc": "여러 방을 매일 돌리는 헤비 유저 · Pro의 20배"},
}

TURN: contextvars.ContextVar[bool] = contextvars.ContextVar("sp_quota_turn", default=False)

_lock = threading.RLock()
_rows: dict[str, list[tuple[float, int]]] | None = None     # email → [(ts, tokens)] 시간순
_refresher: Callable[[str], dict[str, Any]] | None = None     # service가 등록: 구독 주기 정리(자동 갱신·만료)


def set_refresher(fn: Callable[[str], dict[str, Any]]) -> None:
    global _refresher
    _refresher = fn


def limits(plan: str) -> dict[str, int]:
    m = PLANS.get(plan, PLANS["free"])["mult"]
    return {"session": int(config.AI_PRO_SESSION_TOKENS * m), "week": int(config.AI_PRO_WEEK_TOKENS * m)}


def plan_public(plan: str) -> dict[str, Any]:
    p = PLANS[plan]
    return {**{k: p[k] for k in ("id", "label", "price", "desc", "mult")}, **{f"{k}Limit": v for k, v in limits(plan).items()}}


def plans_public() -> list[dict[str, Any]]:
    return [plan_public(k) for k in PLAN_ORDER]


def plan_of(email: str, refresh: bool = True) -> str:
    """지금 요금제. 구독 주기가 끝났으면(refresh) service의 정리 함수로 자동 갱신·만료를 먼저 반영한다."""
    rec = store.kv_get("ai_sub", email) or {}
    if refresh and rec.get("plan") and time.time() >= rec.get("renewsAt", 0) and _refresher:
        try:
            rec = _refresher(email) or {}
        except Exception:   # noqa: BLE001 — 한도 계산은 절대 요청을 깨지 않는다
            pass
    p = rec.get("plan")
    return p if p in PLANS else "free"


def counts(row: dict[str, Any]) -> bool:
    """이 기록이 한도에 들어가나 — 로그인한 사람의 실제 Kiln 호출이고, 분쟁 조사가 아니면."""
    return bool(row.get("user")) and row.get("mode") in AI_MODES and not str(row.get("stage", "")).startswith(EXEMPT_PREFIXES)


def _load() -> None:
    global _rows
    if _rows is not None:
        return
    from . import usage   # 순환 import 방지
    cutoff, rows = time.time() - _KEEP_SEC, {}
    for r in usage.read_all():
        if counts(r) and r.get("ts", 0) >= cutoff:
            rows.setdefault(r["user"], []).append((float(r["ts"]), int(r.get("total_tokens") or 0)))
    for v in rows.values():
        v.sort()
    _rows = rows


def reset_cache() -> None:
    """테스트용: 다음 계산 때 usage.jsonl을 다시 읽는다."""
    global _rows
    with _lock:
        _rows = None


def add(row: dict[str, Any]) -> None:
    """usage.record가 기록을 남길 때마다 부른다."""
    if not counts(row):
        return
    email = row["user"]
    with _lock:
        _load()
        lst = _rows.setdefault(email, [])
        lst.append((float(row["ts"]), int(row.get("total_tokens") or 0)))
        cutoff = time.time() - _KEEP_SEC
        if lst[0][0] < cutoff:
            _rows[email] = [x for x in lst if x[0] >= cutoff]
    q = store.kv_get("ai_quota", email) or {}
    if not q.get("weekAnchor"):                      # 주간 초기화 기준 = 처음 AI를 쓴 시각 (한 번만 저장)
        store.kv_put("ai_quota", email, {**q, "weekAnchor": float(row["ts"])})


def _session(lst: list[tuple[float, int]], now: float) -> dict[str, Any]:
    span = config.AI_SESSION_HOURS * 3600
    start, used = None, 0
    for ts, tok in lst:
        if start is None or ts >= start + span:     # 세션이 끝난 뒤 첫 사용 = 새 세션 시작
            start, used = ts, 0
        used += tok
    if start is None or now >= start + span:
        return {"start": None, "used": 0, "resetsAt": None}
    return {"start": start, "used": used, "resetsAt": start + span}


def _week(email: str, lst: list[tuple[float, int]], now: float) -> dict[str, Any]:
    span = config.AI_WEEK_DAYS * 86400
    anchor = (store.kv_get("ai_quota", email) or {}).get("weekAnchor") or (lst[0][0] if lst else now)
    k = max(0, math.floor((now - anchor) / span)) if now >= anchor else 0
    start = anchor + k * span
    return {"start": start, "used": sum(t for ts, t in lst if ts >= start), "resetsAt": start + span}


def state(email: str, plan: str | None = None) -> dict[str, Any]:
    """지금 사용량과 한도. blocked면 다음 AI 호출은 막힌다.
    베타(BETA_PLAN)면 구독 없는 사용자도 그 요금제 한도로 쓴다 — 한도 때문에 베타 데이터가 끊기지 않게."""
    paid = plan or plan_of(email)
    plan, beta = paid, False
    if paid == "free" and config.BETA_PLAN in PLANS and config.BETA_PLAN != "free":
        plan, beta = config.BETA_PLAN, True
    lim = limits(plan)
    with _lock:
        _load()
        lst = list(_rows.get(email, []))
    now = time.time()
    s, w = _session(lst, now), _week(email, lst, now)
    out: dict[str, Any] = {"plan": plan, "label": PLANS[plan]["label"] + (" (베타 무료)" if beta else ""), "paidPlan": paid, "beta": beta}
    for key, win in (("session", s), ("week", w)):
        limit = lim[key]
        out[key] = {**win, "limit": limit, "left": max(0, limit - win["used"]),
                    "pct": min(100, round(win["used"] / limit * 100)) if limit else 100}
    over = [k for k in ("session", "week") if out[k]["used"] >= out[k]["limit"]]
    out["blocked"] = bool(over)
    out["which"] = ("week" if "week" in over else "session") if over else None       # 둘 다면 더 늦게 풀리는 주간
    out["resetsAt"] = out[out["which"]]["resetsAt"] if over else None
    return out


def when_text(ts: float | None) -> str:
    if not ts:
        return "곧"
    t, now = _dt.datetime.fromtimestamp(ts, _KST), _dt.datetime.fromtimestamp(time.time(), _KST)
    hm = f"{'오전' if t.hour < 12 else '오후'} {(t.hour % 12) or 12}:{t.minute:02d}"
    if t.date() == now.date():
        return hm
    if t.date() == (now + _dt.timedelta(days=1)).date():
        return f"내일 {hm}"
    return f"{t.month}월 {t.day}일 {hm}"


def limit_text(st: dict[str, Any]) -> str:
    what = "이번 5시간 AI 사용 한도" if st.get("which") == "session" else "이번 주 AI 사용 한도"
    return (f"{what}({st['label']})를 다 써서 지금은 AI 없이 규칙으로 답해요. {when_text(st.get('resetsAt'))}에 다시 AI로 답할 수 있어요. "
            "정산 계산·결제·승인은 그대로 돼요. 더 쓰려면 MY 탭 'AI 요금제'에서 요금제를 올릴 수 있어요.")


def current_email() -> str | None:
    from . import usage
    who = usage.ACTOR.get()
    return who["email"] if who else None


@contextmanager
def turn():
    """사용자 요청 한 번(Pie 대화 한 턴)의 시작. 시작할 때 한도 안이면 그 턴의 AI 호출은 끝까지 허용한다.
    반환: 한도 상태(dict) 또는 None(로그인 안 한 요청)."""
    email = current_email()
    if not email:
        yield None
        return
    st = state(email)
    tok = TURN.set(not st["blocked"])
    try:
        yield st
    finally:
        TURN.reset(tok)


def check(stage: str) -> dict[str, Any] | None:
    """Kiln을 부르기 직전(llm._post). 막아야 하면 한도 상태를, 아니면 None."""
    if str(stage).startswith(EXEMPT_PREFIXES) or TURN.get():
        return None
    email = current_email()
    if not email:
        return None
    st = state(email)
    return st if st["blocked"] else None
