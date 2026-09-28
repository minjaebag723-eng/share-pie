"""심사 제출용 AI 사용 보고서 — 챌린지 A 'Kiln API 통합 및 효율성' · '조건 확인 및 증거' 항목에 맞춘 데이터.

- 단계별(단순 합계 아님): 호출 수 · 입력/출력 토큰 · 호출당 평균 · 지연 · 에너지 상한 · 비중
- 워크플로 구간별: 정산 코어(Stage 1 AI → Stage 2 코드 → 지출 통제 코드 → Stage 3 AI) · 분쟁 · 공동구매 · Pie 대화 · 구독 결제
- 실행별: 정산 1건 = 실행 1회. 조건(총액·인원·1인/총 한도·허용 판매처) · 결과(통과/중단/지급/환불) · 온체인 tx 해시 ·
  단계 순서(AI 호출 → 응답이 바꾼 행동 → 코드 처리)
- 절감: AI 없이 코드로 처리한 단계, 잡담 무시, 불법 목적 차단, 한도 차단 → 최소 절감 토큰 추정(계산 근거 포함)
- 에너지: 호출마다 실측 지연시간 × NPU 전력 가정 → Wh 상한 (가정 문구 그대로)
공개 보고서라 이메일 · 대화 제목 · 사람 이름 · 분담 조건 원문은 넣지 않는다.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import time
from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from . import config, quota, store, usage

AI = quota.AI_MODES
_KST = _dt.timezone(_dt.timedelta(hours=9), "KST")

# (구간 id, 이름, 정확히 맞는 단계, 접두어)
PHASES = [
    ("settle", "정산 코어", ("settlement.analyze", "settlement.calculate", "settlement.policy", "settlement.explain"), ()),
    ("dispute", "분쟁·증거", (), ("dispute.",)),
    ("shop", "공동구매·추천", (), ("shopping.",)),
    ("chat", "Pie 대화 (1:1·그룹)", ("group.pie",), ("chat.", "assistant.")),
    ("billing", "구독 결제", ("ai.subscribe", "ai.pay"), ()),
]
STAGE_ORDER = ["settlement.analyze", "settlement.calculate", "settlement.policy", "settlement.explain",
               "dispute.records", "dispute.investigate", "shopping.plan", "shopping.web", "shopping.search",
               "shopping.calculate", "shopping.explain", "chat.guard", "chat.route", "assistant.step", "assistant.fallback",
               "chat.answer", "chat.search", "group.pie", "ai.subscribe", "ai.pay"]
STAGE_KO = {
    "settlement.analyze": "Stage 1 조건 해석", "settlement.calculate": "Stage 2 금액 계산", "settlement.policy": "지출 통제 검사",
    "settlement.explain": "Stage 3 결과 설명", "dispute.records": "분쟁 기록 대조", "dispute.investigate": "분쟁 판정",
    "shopping.plan": "구매 조건 파악", "shopping.web": "상품 검색", "shopping.search": "공동구매 비교",
    "shopping.calculate": "1인 비용 계산", "shopping.explain": "비교 결과 설명", "chat.guard": "요청 차단·한도",
    "chat.route": "요청 의도 파악", "assistant.step": "Pie 에이전트 판단", "assistant.fallback": "예비 답변",
    "chat.answer": "Pie 답변", "chat.search": "검색어 만들기", "group.pie": "Pie mate 응답 판단",
    "ai.subscribe": "구독 결제", "ai.pay": "이전 방식 사용료",
}
_KIND_KO = {"create": "정산 등록", "block": "지출 통제 중단", "lock": "예치", "escrow": "전원 예치", "paid": "지급",
            "refund": "환불", "dispute": "이의제기", "resolve": "판정 기록", "offline": "현금 확인", "approve": "인출 승인",
            "withdraw": "인출", "purchase": "가맹점 결제", "cancel": "취소"}


def phase_of(stage: str) -> str:
    for pid, _label, exact, prefixes in PHASES:
        if stage in exact or (prefixes and stage.startswith(prefixes)):
            return pid
    return "other"


def _kst(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts, _KST).strftime("%Y-%m-%d %H:%M:%S")


def _wh(r: dict[str, Any]) -> float:
    return float(r.get("energy_wh") or usage.energy_wh(r.get("latency_ms", 0)))


def _stage_stats(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "code_steps": 0, "fallbacks": 0, "prompt_tokens": 0,
                                                         "completion_tokens": 0, "total_tokens": 0, "latency_ms": 0, "energy_wh": 0.0})
    for r in rows:
        b, mode = by[r.get("stage", "?")], r.get("mode")
        if mode in AI:
            b["calls"] += 1
            for k in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"):
                b[k] += int(r.get(k) or 0)
            b["energy_wh"] += _wh(r)
        elif mode == "code":
            b["code_steps"] += 1
        elif mode in ("fallback", "mock"):
            b["fallbacks"] += 1
    grand = sum(b["total_tokens"] for b in by.values()) or 1
    out = []
    for st, b in by.items():
        if not (b["calls"] or b["code_steps"] or b["fallbacks"]):
            continue                                              # '응답 반영' 기록만 있는 단계는 표에서 뺀다
        out.append({"stage": st, "label": STAGE_KO.get(st, st), "phase": phase_of(st),
                    "kind": "AI" if b["calls"] else ("코드" if b["code_steps"] else "규칙(오프라인)"), **b,
                    "energy_wh": round(b["energy_wh"], 6),
                    "avg_tokens": round(b["total_tokens"] / b["calls"], 1) if b["calls"] else 0,
                    "avg_latency_ms": round(b["latency_ms"] / b["calls"]) if b["calls"] else 0,
                    "share_pct": round(b["total_tokens"] / grand * 100, 1)})
    po = {p[0]: i for i, p in enumerate(PHASES)}
    out.sort(key=lambda x: (po.get(x["phase"], 99), STAGE_ORDER.index(x["stage"]) if x["stage"] in STAGE_ORDER else 99, x["stage"]))
    return out


def _phases(stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for pid, label, *_ in PHASES + [("other", "기타", (), ())]:
        xs = [s for s in stages if s["phase"] == pid]
        if xs:
            out.append({"phase": pid, "label": label, "stages": [s["stage"] for s in xs],
                        **{k: sum(s[k] for s in xs) for k in ("calls", "code_steps", "total_tokens", "latency_ms")},
                        "energy_wh": round(sum(s["energy_wh"] for s in xs), 6)})
    return out


def _savings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ai_rows = [r for r in rows if r.get("mode") in AI]
    avg = round(sum(r["total_tokens"] for r in ai_rows) / len(ai_rows)) if ai_rows else 0
    grp = [r for r in ai_rows if r.get("where") == "group"]
    avg_g = round(sum(r["total_tokens"] for r in grp) / len(grp)) if grp else avg
    note = lambda r: r.get("note") or ""   # noqa: E731
    cnt = {
        "group_skip": sum(1 for r in rows if r.get("stage") == "group.pie" and r.get("mode") == "code" and "잡담" in note(r)),
        "prohibited": sum(1 for r in rows if r.get("mode") == "code" and ("PROHIBITED_PURPOSE" in note(r) or "불법 목적" in note(r))),
        "limit": sum(1 for r in rows if r.get("mode") == "fallback" and note(r).startswith("AI_LIMIT")),
        "code_fix": sum(1 for r in rows if r.get("stage") == "settlement.analyze" and r.get("mode") == "code"),
        "code_calc": sum(1 for r in rows if r.get("mode") == "code" and r.get("stage") in ("settlement.calculate", "settlement.policy", "shopping.calculate")),
    }
    items = [
        {"id": "group_skip", "label": "그룹방 잡담에는 Pie가 끼지 않음 (답할지 코드가 먼저 판단)", "count": cnt["group_skip"],
         "est_tokens": cnt["group_skip"] * avg_g, "basis": f"잡담 1건 = Kiln 최소 1회(그룹방 호출 평균 {avg_g:,}토큰)를 안 부른 것으로 계산"},
        {"id": "prohibited", "label": "불법 목적 요청은 AI 호출 전에 코드가 거절", "count": cnt["prohibited"],
         "est_tokens": cnt["prohibited"] * avg, "basis": f"1건 = Kiln 최소 1회(호출 평균 {avg:,}토큰)"},
        {"id": "code_fix", "label": "AI가 놓친 금액을 코드가 읽어 되묻기·재호출을 막음", "count": cnt["code_fix"],
         "est_tokens": cnt["code_fix"] * avg, "basis": f"1건 = 재호출 1회(호출 평균 {avg:,}토큰)"},
        {"id": "limit", "label": "구독 한도를 넘어 Kiln 없이 규칙으로 답함", "count": cnt["limit"],
         "est_tokens": cnt["limit"] * avg, "basis": f"1건 = Kiln 최소 1회(호출 평균 {avg:,}토큰)"},
        {"id": "code_calc", "label": "금액 계산·합계 검증·지출 통제는 코드로만 (Stage 2)", "count": cnt["code_calc"],
         "est_tokens": None, "basis": "설계상 이 단계는 처음부터 AI를 부르지 않아 추정치에 넣지 않음 (0 토큰)"},
    ]
    return {"items": items, "est_tokens_avoided": sum(i["est_tokens"] or 0 for i in items), "avg_call_tokens": avg,
            "design": [
                "금액 계산·합계 검증·지출 통제는 코드(0 토큰). AI는 조건 해석(Stage 1)과 설명(Stage 3)만 한다.",
                "그룹방은 답할지를 코드가 먼저 정한다(이름 부름·정산·구매 이야기만). 잡담은 AI 호출 0회.",
                f"{config.KILN_MODEL}: 평소엔 긴 사고를 끄고(/no_think), 판단이 어려운 단계({', '.join(_think_stages())})만 사고 모드.",
                "답이 max_tokens에 걸리면 한도를 늘려 한 번만 다시 부르고, 잘린 시도의 토큰도 빠짐없이 기록한다.",
                f"구독 한도: 5시간 세션·주간 한도를 넘으면 Kiln을 부르지 않는다(정산·결제는 코드로 계속). 분쟁 조사는 한도 밖.",
            ]}


def _think_stages() -> tuple[str, ...]:
    from . import llm
    return tuple(getattr(llm, "THINK_STAGES", ()))


def _energy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ai_rows = [r for r in rows if r.get("mode") in AI]
    wh, tok = sum(_wh(r) for r in ai_rows), sum(int(r.get("total_tokens") or 0) for r in ai_rows)
    lat = sum(int(r.get("latency_ms") or 0) for r in ai_rows)
    return {"total_wh_upper": round(wh, 5), "calls": len(ai_rows), "tokens": tok, "latency_ms": lat,
            "wh_per_call": round(wh / len(ai_rows), 6) if ai_rows else 0,
            "wh_per_1k_tokens": round(wh / tok * 1000, 6) if tok else 0, **usage.assumptions()}


def _outcome(rec: dict[str, Any]) -> str:
    if rec.get("blocked"):
        return "지출 통제로 중단 (온체인 Blocked 기록)"
    d = rec.get("dispute") or {}
    if d.get("verdict"):
        return f"이의제기 → {d.get('verdict')}" + (" · 환불" if d.get("refund") not in (None, "none") else "")
    return {"open": "예치 진행 중", "locked": "전원 예치 · 에스크로 보관", "paid": "결제자에게 지급 완료",
            "disputed": "분쟁 조사 중", "refunded": "환불", "cancelled": "취소"}.get(rec.get("status"), rec.get("status") or "-")


def runs(rows: list[dict[str, Any]] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """정산 1건 = 실행 1회. 그 정산의 흐름(sid)과, 등록 직전까지 방(group_id)에서 일어난 해석·대화를 묶는다."""
    rows = rows if rows is not None else usage.read_all()
    by_flow: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_flow[r.get("flow")].append(r)
    prev: dict[Any, float] = {}
    out = []
    for n, rec in enumerate(sorted(store.all_settlements(), key=lambda x: x.get("created_at", 0)), 1):
        sid, gid, t1 = rec["id"], rec.get("group_id"), float(rec.get("created_at", 0))
        t0 = prev.get(gid, t1 - 6 * 3600) if gid else t1 - 6 * 3600
        if gid:
            prev[gid] = t1
        steps = list(by_flow.get(sid, [])) + ([r for r in by_flow.get(gid, []) if t0 < r["ts"] <= t1 + 120] if gid else [])
        steps = sorted((r for r in steps if r.get("mode") in AI + ("code", "decision", "fallback")), key=lambda r: r["ts"])
        ai = [r for r in steps if r.get("mode") in AI]
        out.append({
            "run": n, "sid": sid, "createdAt": t1, "status": rec.get("status"), "outcome": _outcome(rec),
            "conditions": {"total": rec.get("total"), "members": len(rec.get("members") or []),
                           "perPersonCap": rec.get("per_person_cap"), "totalCap": rec.get("total_cap"),
                           "allowedMerchants": rec.get("allowed_merchants"), "merchant": rec.get("merchant"),
                           "purchase": bool(rec.get("purchase"))},
            "violations": [v.get("code") for v in rec.get("violations") or [] if isinstance(v, dict)],
            "txs": [{"kind": t.get("kind"), "label": _KIND_KO.get(t.get("kind"), t.get("kind")), "tx_hash": t.get("tx_hash"),
                     "block": t.get("block"), "url": t.get("url"), "at": t.get("at")} for t in rec.get("txs") or []],
            "ai_calls": len(ai), "tokens": sum(int(r.get("total_tokens") or 0) for r in ai),
            "latency_ms": sum(int(r.get("latency_ms") or 0) for r in ai), "energy_wh": round(sum(_wh(r) for r in ai), 6),
            "code_steps": sum(1 for r in steps if r.get("mode") == "code"),
            "steps": [{"ts": r["ts"], "stage": r.get("stage"), "mode": r.get("mode"), "tokens": int(r.get("total_tokens") or 0),
                       "latency_ms": int(r.get("latency_ms") or 0), "note": (r.get("note") or "")[:160]} for r in steps],
        })
    return out[-limit:]


def build(flow: str | None = None) -> dict[str, Any]:
    rows = [r for r in usage.read_all() if flow is None or r.get("flow") == flow]
    stages = _stage_stats(rows)
    ai_rows = [r for r in rows if r.get("mode") in AI]
    total_lat = sum(int(r.get("latency_ms") or 0) for r in ai_rows)
    en = _energy(rows)
    return {
        "generatedAt": time.time(), "flow": flow,
        "model": config.KILN_MODEL, "endpoint": urlparse(config.KILN_BASE_URL).netloc or config.KILN_BASE_URL,
        "llmMode": config.LLM_MODE, "live": config.LLM_MODE == "live",
        "stages": stages, "phases": _phases(stages), "savings": _savings(rows), "energy": en,
        "decisions": sum(1 for r in rows if r.get("mode") == "decision"),
        "runs": runs(rows) if flow is None else [x for x in runs() if x["sid"] == flow],
        "plans": quota.plans_public(),
        # 예전 /api/usage 필드 (호환)
        "llm_calls": len(ai_rows), "code_steps": sum(1 for r in rows if r.get("mode") == "code"),
        "offline_steps": sum(1 for r in rows if r.get("mode") in ("mock", "fallback")),
        "total_tokens": sum(int(r.get("total_tokens") or 0) for r in ai_rows), "total_latency_ms": total_lat,
        "energy_wh_upper_bound": en["total_wh_upper"], "assumptions": usage.assumptions(),
    }


CSV_HEAD = ["시각(KST)", "실행·흐름", "구간", "단계", "단계 이름", "처리", "입력 토큰", "출력 토큰", "합계 토큰",
            "지연(ms)", "에너지 상한(Wh)", "모델", "한도 포함", "요금제", "채널", "비고·응답 반영"]
_MODE_KO = {"tools": "Kiln(tools)", "json": "Kiln(json)", "text": "Kiln(text)", "code": "코드", "decision": "응답 반영",
            "fallback": "규칙(대체)", "mock": "규칙(오프라인)"}


def calls_csv(flow: str | None = None) -> str:
    """호출 한 줄 = 한 행. 개인정보(이메일·대화 제목)는 빼고 흐름 id로만 묶는다. 엑셀용 BOM 포함."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEAD)
    for r in usage.read_all():
        if flow and r.get("flow") != flow:
            continue
        mode = r.get("mode")
        ai = mode in AI
        w.writerow([_kst(r["ts"]), r.get("flow") or "", phase_of(r.get("stage", "")), r.get("stage", ""),
                    STAGE_KO.get(r.get("stage", ""), ""), _MODE_KO.get(mode, mode), r.get("prompt_tokens", 0),
                    r.get("completion_tokens", 0), r.get("total_tokens", 0), r.get("latency_ms", 0),
                    round(_wh(r), 6) if ai else 0, r.get("model") or "", "예" if r.get("counted") else "아니오",
                    r.get("plan") or "", r.get("where") or "", (r.get("note") or "")[:200]])
    return "\ufeff" + buf.getvalue()


def _n(v: Any) -> str:
    return f"{v:,}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def markdown(rep: dict[str, Any] | None = None) -> str:
    """README·발표 자료에 그대로 붙일 수 있는 표."""
    r = rep or build()
    L = [f"# Share Pie · Kiln API 사용 보고서",
         f"생성 {_kst(r['generatedAt'])} KST · 모델 `{r['model']}` ({r['endpoint']}) · "
         f"{'실측 (LLM_MODE=live)' if r['live'] else '오프라인 규칙 모드 — 실측값 아님'} · Kiln 호출 {r['llm_calls']:,}회 · "
         f"응답 반영 기록 {r['decisions']:,}건", "",
         "## 1. 워크플로 단계별 토큰", "",
         "| 구간 | 단계 | 처리 | Kiln 호출 | 코드 처리 | 입력 | 출력 | 합계 | 호출당 평균 | 평균 지연(ms) | 에너지 상한(Wh) | 비중 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    ph = {p[0]: p[1] for p in PHASES}
    for s in r["stages"]:
        L.append(f"| {ph.get(s['phase'], '기타')} | {s['label']} `{s['stage']}` | {s['kind']} | {s['calls']} | {s['code_steps']} | "
                 f"{_n(s['prompt_tokens'])} | {_n(s['completion_tokens'])} | {_n(s['total_tokens'])} | {_n(s['avg_tokens'])} | "
                 f"{_n(s['avg_latency_ms'])} | {s['energy_wh']:.5f} | {s['share_pct']}% |")
    L += ["", "## 2. 구간별 합계", "", "| 구간 | Kiln 호출 | 코드 처리 | 토큰 | 에너지 상한(Wh) |", "|---|---|---|---|---|"]
    for p in r["phases"]:
        L.append(f"| {p['label']} | {p['calls']} | {p['code_steps']} | {_n(p['total_tokens'])} | {p['energy_wh']:.5f} |")
    L += ["", "## 3. 실행(정산)별 기록 — 조건을 바꾼 실행 비교", "",
          "| 실행 | 정산 | 조건 | 결과 | Kiln 호출 | 토큰 | 에너지 상한(Wh) | 온체인 기록 |", "|---|---|---|---|---|---|---|---|"]
    for x in r["runs"]:
        c = x["conditions"]
        cond = [f"총 {_n(c['total'])}원 · {c['members']}명"]
        if c.get("perPersonCap"):
            cond.append(f"1인 한도 {_n(c['perPersonCap'])}원")
        if c.get("totalCap"):
            cond.append(f"총 한도 {_n(c['totalCap'])}원")
        if c.get("allowedMerchants"):
            cond.append("허용 판매처 " + "·".join(c["allowedMerchants"]))
        if x["violations"]:
            cond.append("위반 " + ",".join(x["violations"]))
        txs = " ".join(f"{t['label']} [`{(t['tx_hash'] or '')[:10]}…`]({t['url']})" if t.get("url") else f"{t['label']} `{(t['tx_hash'] or '')[:10]}…`"
                       for t in x["txs"][:6]) or "-"
        L.append(f"| Run {x['run']} | `{x['sid']}` | {' · '.join(cond)} | {x['outcome']} | {x['ai_calls']} | {_n(x['tokens'])} | {x['energy_wh']:.5f} | {txs} |")
    for x in r["runs"][-2:]:                                   # 최근 두 실행은 단계 순서까지
        L += ["", f"**Run {x['run']} 단계 순서** (`{x['sid']}` · {x['outcome']})", ""]
        for i, s in enumerate(x["steps"][:24], 1):
            tag = {"decision": "응답 반영", "code": "코드", "fallback": "규칙"}.get(s["mode"], "Kiln")
            extra = f" · {_n(s['tokens'])}토큰 · {s['latency_ms']}ms" if s["mode"] in AI else ""
            L.append(f"{i}. [{tag}] `{s['stage']}`{extra}" + (f" — {s['note']}" if s["note"] else ""))
        for t in x["txs"]:
            L.append(f"- [체인] {t['label']} `{t['tx_hash']}`" + (f" (블록 {t['block']})" if t.get("block") else ""))
    sv = r["savings"]
    L += ["", "## 4. 불필요한 추론을 줄인 방법과 효과", "", "| 방법 | 건수 | 최소 절감 추정(토큰) | 계산 근거 |", "|---|---|---|---|"]
    for i in sv["items"]:
        L.append(f"| {i['label']} | {i['count']} | {_n(i['est_tokens']) if i['est_tokens'] is not None else '-'} | {i['basis']} |")
    L += ["", f"최소 절감 추정 합계 {_n(sv['est_tokens_avoided'])}토큰 (호출 평균 {_n(sv['avg_call_tokens'])}토큰 기준, 실제로는 한 번에 여러 걸음이라 더 크다)", ""]
    L += [f"- {d}" for d in sv["design"]]
    e = r["energy"]
    L += ["", "## 5. 에너지 추정 근거", "",
          f"- 측정값: {e['measured']}",
          f"- 가정: NPU 전력 {e['npu_power_watts']:g}W × 카드 {e['npu_count']:g}장 ({e['source']})",
          f"- 공식: {e['formula']} — {e['bound']}",
          f"- 결과: 총 {e['total_wh_upper']:.5f} Wh 상한 · Kiln 호출 1회당 {e['wh_per_call']:.6f} Wh · 1,000토큰당 {e['wh_per_1k_tokens']:.6f} Wh",
          "", "## 6. 구독 요금제와 사용 한도", "",
          "| 요금제 | 월 가격 (PIE) | 5시간 세션 한도 (토큰) | 주간 한도 (토큰) |", "|---|---|---|---|"]
    L += [f"| {p['label']} | {_n(p['price'])} | {_n(p['sessionLimit'])} | {_n(p['weekLimit'])} |" for p in r["plans"]]
    L += ["", "PIE는 테스트넷 토큰이라 실제 가치가 없다. 구독료 결제는 PieToken.transfer 온체인 기록으로 남는다."]
    return "\n".join(L)
