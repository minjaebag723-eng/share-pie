"""단계별 토큰·지연시간 기록 → 챌린지 A '토큰 사용량 보고 + 에너지 추정 근거' 제출용."""
from __future__ import annotations

import contextvars
import json
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Any

from . import config

USAGE_FILE = config.DATA_DIR / "usage.jsonl"
_lock = threading.Lock()

# 누가(로그인 사용자) · 어디서(1:1 대화 / 그룹방) 부른 AI인지 — 요청마다 따로 (contextvars는 스레드풀로도 전달됨)
ACTOR: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("sp_actor", default=None)
SCOPE: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("sp_scope", default=None)
# 이번 턴 표시 (베타 비교용): turn id · 시나리오 id · 예시를 고쳐 보냈는지. 기록마다 붙고, 턴 합계(토큰·호출)도 여기에 쌓인다
TAGS: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("sp_tags", default=None)


@contextmanager
def tagged(**kw):
    """with usage.tagged(turn=..., scenario=...) as tg: 안에서 일어난 기록에 turn·scenario·edited가 붙고 tg에 턴 합계가 쌓인다."""
    cur = {k: v for k, v in kw.items() if v is not None}
    cur.update(tokens=0, calls=0, limited=False)
    tok = TAGS.set(cur)
    try:
        yield cur
    finally:
        TAGS.reset(tok)


def set_actor(user: dict[str, Any] | None) -> None:
    ACTOR.set({"email": user["email"], "short": user.get("short", "")} if user and user.get("email") else None)


@contextmanager
def scope(where: str, ctx: str = "", actor: dict[str, Any] | None = None):
    """이 안에서 일어난 Kiln 호출은 where(chat|group)·ctx(대화 제목/방 이름)로 기록된다."""
    t1 = SCOPE.set({"where": where, "ctx": (ctx or "")[:40]})
    t2 = ACTOR.set({"email": actor["email"], "short": actor.get("short", "")}) if actor and actor.get("email") else None
    try:
        yield
    finally:
        SCOPE.reset(t1)
        if t2 is not None:
            ACTOR.reset(t2)


def record(stage: str, *, flow: str | None, prompt_tokens: int, completion_tokens: int,
           latency_ms: int, mode: str, ok: bool = True, note: str = "", cost: Any = None,
           model: str | None = None) -> dict[str, Any]:
    row = {
        "ts": round(time.time(), 3),
        "stage": stage,
        "flow": flow,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "total_tokens": int(prompt_tokens or 0) + int(completion_tokens or 0),
        "latency_ms": int(latency_ms),
        "mode": mode,  # tools | json | mock | fallback | code
        "ok": ok,
        "note": note,
        "cost": cost,
        "model": model,
    }
    if mode in ("tools", "json", "text"):             # 실제 Kiln 호출만: 측정한 지연시간으로 에너지 상한 추정
        row["energy_wh"] = round(energy_wh(latency_ms), 6)
    who, sc = ACTOR.get(), SCOPE.get()
    if who:
        row["user"] = who["email"]
    if sc:
        row.update(where=sc["where"], ctx=sc["ctx"])
    from . import quota                                # 순환 import 방지
    if who:
        row["plan"] = quota.plan_of(who["email"], refresh=False)
    row["counted"] = quota.counts(row)                 # 구독 한도(5시간·주간)에 들어가는 호출인가
    row["version"] = config.APP_VERSION                # 베타 ↔ 정식 버전 비교
    tg = TAGS.get()
    if tg is not None:
        row.update({k: tg[k] for k in ("turn", "scenario", "edited") if k in tg})
        if mode in ("tools", "json", "text"):
            tg["tokens"] += row["total_tokens"]
            tg["calls"] += 1
        elif mode == "fallback" and str(note).startswith("AI_LIMIT"):
            tg["limited"] = True
    global _cache_sig
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with _lock:
        with USAGE_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
        if _cache is not None:
            _cache.append(row)
            _cache_sig = _file_sig()
    quota.add(row)
    for hook in HOOKS:                     # 베타: 비식별 사본을 beta-data 폴더에 (agent/beta.py)
        try:
            hook(row)
        except Exception as e:  # noqa: BLE001 — 기록 사본 실패가 AI 호출을 깨면 안 됨
            print(f"[usage] 후크 실패: {e}", flush=True)
    return row


HOOKS: list[Any] = []
_cache: list[dict[str, Any]] | None = None     # 파일을 매번 다시 읽지 않게 메모리에 (100명이 사용량 화면을 폴링해도 가볍게)
_cache_sig: tuple | None = None


def _file_sig() -> tuple | None:
    try:
        st = USAGE_FILE.stat()
        return (st.st_ino, st.st_size, st.st_mtime_ns)
    except FileNotFoundError:
        return None


def read_all() -> list[dict[str, Any]]:
    """모든 기록 (복사본 리스트). 파일이 밖에서 바뀌거나 지워지면 다시 읽는다."""
    global _cache, _cache_sig
    with _lock:
        sig = _file_sig()
        if sig is None:
            _cache, _cache_sig = None, None
            return []
        if _cache is None or sig != _cache_sig:
            rows = []
            for line in USAGE_FILE.read_text(encoding="utf-8").splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            _cache, _cache_sig = rows, sig
        return list(_cache)


def for_user(email: str) -> list[dict[str, Any]]:
    """이 사용자가 부른 기록만 (AI 사용 명세서용)."""
    return [r for r in read_all() if r.get("user") == email]


def energy_wh(latency_ms: float) -> float:
    """에너지(Wh) 상한 추정 = NPU 전력(W) × 카드 수 × 처리시간(s) / 3600.
    배치 처리로 여러 요청이 카드를 나눠 쓰므로 실제 값은 이보다 작다(보수적 상한)."""
    return config.NPU_POWER_WATTS * config.NPU_COUNT * (latency_ms / 1000.0) / 3600.0


def assumptions() -> dict[str, Any]:
    """에너지 추정의 측정값·가정·공식 (보고서·README에 그대로)."""
    return {"npu_power_watts": config.NPU_POWER_WATTS, "npu_count": config.NPU_COUNT,
            "formula": "Wh = NPU 전력(W) × 카드 수 × 응답 지연(초) / 3600",
            "bound": "배치 처리로 여러 요청이 카드를 나눠 쓰는 효과를 빼서 실제보다 큰 값(상한)",
            "measured": "Kiln 요청부터 응답까지 걸린 시간(latency_ms)을 호출마다 실측",
            "source": "RNGD TDP 150W — developer.furiosa.ai/latest/en/overview/rngd.html"}


def summarize(flow: str | None = None) -> dict[str, Any]:
    rows = [r for r in read_all() if flow is None or r.get("flow") == flow]
    by: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                                         "total_tokens": 0, "latency_ms": 0})
    for r in rows:
        b = by[r["stage"]]
        b["calls"] += 1
        for k in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"):
            b[k] += r.get(k, 0)
    stages = []
    for stage, b in sorted(by.items()):
        stages.append({**b, "stage": stage,
                       "avg_tokens": round(b["total_tokens"] / b["calls"], 1) if b["calls"] else 0,
                       "energy_wh": round(energy_wh(b["latency_ms"]), 5)})
    total_tokens = sum(s["total_tokens"] for s in stages)
    total_latency = sum(s["latency_ms"] for s in stages)
    return {
        "flow": flow,
        "stages": stages,
        "llm_calls": sum(1 for r in rows if r["mode"] in ("tools", "json", "text")),
        "code_steps": sum(1 for r in rows if r["mode"] == "code"),
        "offline_steps": sum(1 for r in rows if r["mode"] in ("mock", "fallback")),
        "total_tokens": total_tokens,
        "total_latency_ms": total_latency,
        "energy_wh_upper_bound": round(energy_wh(total_latency), 5),
        "assumptions": assumptions(),
    }


def report_markdown() -> str:
    s = summarize()
    lines = ["| 단계 | 호출 | 입력 토큰 | 출력 토큰 | 합계 | 평균 | 지연(ms) | 에너지 상한(Wh) |",
             "|---|---|---|---|---|---|---|---|"]
    for st in s["stages"]:
        lines.append(f"| {st['stage']} | {st['calls']} | {st['prompt_tokens']} | {st['completion_tokens']} | "
                     f"{st['total_tokens']} | {st['avg_tokens']} | {st['latency_ms']} | {st['energy_wh']} |")
    lines.append(f"\n총 {s['total_tokens']} 토큰 · Kiln 호출 {s['llm_calls']}회 · 코드 처리 {s['code_steps']}단계 · 에너지 상한 {s['energy_wh_upper_bound']} Wh")
    lines.append(f"가정: {s['assumptions']['formula']} / NPU {s['assumptions']['npu_power_watts']}W × {s['assumptions']['npu_count']}장")
    return "\n".join(lines)
