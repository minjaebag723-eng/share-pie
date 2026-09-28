"""AI Dispute Agent (선택 모듈) — CLAUDE.md 7번: 판정은 3가지뿐.

  NORMAL_APPROVAL   정상 승인이었음 → 정산 유지, 이의 기각
  GENUINE_ERROR     진짜 착오·오류 → refund_participant 자동 호출
  BAD_FAITH_DISPUTE 악의적 이의제기 → 이의 기각, 근거 기록 공개

1) investigate_records(): 요청 → Stage1/2 결과 → 온체인 등록 → 승인(예치) → 결제 기록을 코드로 대조 (토큰 0)
2) judge(): 대조 결과 + 이의 사유를 LLM에 넘겨 3분류 판정 (dispute.investigate)
3) 코드 가드: LLM 판정이 기록과 모순되면 코드가 보정 (예: 기록 불일치가 있는데 기각 → GENUINE_ERROR)
"""
from __future__ import annotations

import re
from typing import Any

from . import llm
from .textutil import won

VERDICTS = ("NORMAL_APPROVAL", "GENUINE_ERROR", "BAD_FAITH_DISPUTE")
VERDICT_KO = {"NORMAL_APPROVAL": "정상 승인 (정산 유지)", "GENUINE_ERROR": "진짜 착오 (환불)",
              "BAD_FAITH_DISPUTE": "악의적 이의제기 (기각)"}
TXN_ISSUES = ("cancelled", "not_delivered", "duplicate", "amount_error")

SYSTEM = """너는 공동정산 앱 Share Pie의 분쟁 조사관(AI Dispute Agent)이다. 판정은 반드시 셋 중 하나다.
- NORMAL_APPROVAL: 기록이 모두 일치하고 이의가 오해·단순 불만이다 → 정산 유지
- GENUINE_ERROR: 기록 불일치가 있거나, 공동구매 취소·미배송·중복 결제·금액 착오처럼 기록으로 반박할 수 없는 거래 문제가 구체적으로 제기됐다 → 환불
- BAD_FAITH_DISPUTE: 이의 내용이 기록으로 명백히 반박된다 (예: 본인이 직접 서명해 예치했는데 승인한 적 없다고 주장) → 기각
refund: 취소·미배송처럼 모두에게 해당하면 all, 이의 제기자만 해당하면 disputer, 환불 없으면 none.
explanation: 근거가 된 기록을 인용해 한국어 3~4문장. 기록에 없는 사실을 지어내지 마라."""

TOOL = {
    "name": "set_dispute_verdict",
    "description": "이의제기 판정",
    "parameters": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "reason_category": {"type": "string", "enum": ["cancelled", "not_delivered", "duplicate", "amount_error",
                                                           "not_approved_claim", "misunderstanding", "other"]},
            "refund": {"type": "string", "enum": ["none", "disputer", "all"]},
            "explanation": {"type": "string"},
        },
        "required": ["verdict", "reason_category", "refund", "explanation"],
    },
}


def investigate_records(rec: dict[str, Any], ch) -> dict[str, Any]:
    """코드 대조 — 단계별 ok/warn/error."""
    f: list[dict[str, Any]] = []

    def add(stage, level, msg):
        f.append({"stage": stage, "level": level, "message": msg})

    on = ch.get_settlement(rec["chain_id"]) if rec.get("chain_id") else {"status": "none", "members": []}
    by_addr = {m["address"].lower(): m for m in on.get("members", [])}
    now = {m["name"]: m["share"] for m in rec["members"]}

    if on.get("members"):
        if on.get("condition_hash") and on["condition_hash"] != ch.condition_hash(rec.get("rule_text") or ""):
            add("최초 요청", "error", "저장된 분담 조건 원문이 체인에 기록된 해시와 달라요 (등록 후 조건이 바뀜)")
        else:
            add("최초 요청", "ok", f"분담 조건 원문 해시 일치: “{(rec.get('rule_text') or '')[:40]}”")

    ai = {n: a for n, a in (rec.get("ai_shares") or [])}
    diff = [n for n in now if ai and ai.get(n) != now[n]]
    if diff:
        add("정산 코어(Stage1·2)", "error", "AI 계산값과 요청된 분담액이 달라요: " +
            ", ".join(f"{n} 계산 {won(ai.get(n, 0))} → 요청 {won(now[n])}" for n in diff))
    elif sum(now.values()) != rec["total"]:
        add("정산 코어(Stage1·2)", "error", f"분담액 합계 {won(sum(now.values()))} ≠ 총액 {won(rec['total'])}")
    else:
        add("정산 코어(Stage1·2)", "ok", f"코드 계산 합계 {won(rec['total'])} 검증 통과")

    if rec.get("status") == "blocked":
        b = rec.get("blocked") or {}
        add("지출 통제", "warn", f"결제 전 중단됨: {b.get('message', '')}")

    if on.get("members"):
        bad = False
        for m in rec["members"]:
            o = by_addr.get((m.get("wallet") or "").lower())
            if not o:
                add("온체인 등록", "error", f"{m['name']}님 지갑이 체인 분담표에 없어요"); bad = True
            elif o["share"] != m["share"]:
                add("온체인 등록", "error", f"{m['name']}님 체인 등록액 {won(o['share'])} ≠ 합의액 {won(m['share'])}"); bad = True
        if not bad:
            add("온체인 등록", "ok", f"{len(on['members'])}명 분담표가 체인과 일치")

        signed = [m["name"] for m in rec["members"] if by_addr.get(m["wallet"].lower(), {}).get("state") in ("locked", "refunded")]
        cash = [m["name"] for m in rec["members"] if by_addr.get(m["wallet"].lower(), {}).get("state") == "offline"]
        waiting = [m["name"] for m in rec["members"] if by_addr.get(m["wallet"].lower(), {}).get("state") == "wait"]
        if signed:
            add("승인(예치)", "ok", f"본인 지갑 서명으로 예치: {', '.join(signed)}")
        if cash:
            add("승인(예치)", "ok", f"현금 결제 확인 기록: {', '.join(cash)}")
        if waiting:
            add("승인(예치)", "warn", f"아직 예치하지 않은 멤버: {', '.join(waiting)}")

    st = on.get("status")
    if st in ("locked", "disputed"):
        add("결제", "ok", f"전원 확보 · 에스크로 보관 중 {won(on.get('escrowed', 0))} (결제자에게 아직 지급 전)")
    elif st == "paid":
        paid = [e for e in rec.get("events", []) if e["event"] == "Paid"]
        wrong = [e for e in paid if e["args"].get("to", "").lower() != (rec.get("payer_wallet") or "").lower()]
        if wrong:
            add("결제", "error", f"받는 사람 주소가 결제자와 다른 송금 {len(wrong)}건")
        else:
            add("결제", "ok", f"결제자에게 지급 완료 · 목적 “{on.get('purpose', '')}”")
    elif st == "refunded":
        add("결제", "ok", "전액 환불로 종료된 정산")

    errors = [x for x in f if x["level"] == "error"]
    return {"findings": f, "has_error": bool(errors), "chain": on,
            "signed": {m["name"]: by_addr.get(m["wallet"].lower(), {}).get("state") for m in rec["members"]}}


def _mock_judge(reason: str, disputer_state: str | None, has_error: bool) -> dict[str, Any]:
    r = reason or ""
    if has_error:
        return {"verdict": "GENUINE_ERROR", "reason_category": "amount_error", "refund": "disputer",
                "explanation": "코드 대조에서 기록 불일치가 확인돼 착오로 판정했어요. 이의 제기자의 예치금을 환불해요."}
    if re.search(r"취소|품절|주문.*안\s*됐|주문.*실패", r):
        return {"verdict": "GENUINE_ERROR", "reason_category": "cancelled", "refund": "all",
                "explanation": "공동구매가 취소됐다는 사유는 기록으로 반박할 수 없는 거래 문제라 착오로 판정했어요. 예치된 금액을 모두 환불해요."}
    if re.search(r"안\s*왔|못\s*받|배송.*안|미배송|도착.*안", r):
        return {"verdict": "GENUINE_ERROR", "reason_category": "not_delivered", "refund": "all",
                "explanation": "상품을 받지 못했다는 사유는 기록으로 반박할 수 없어 착오로 판정했어요. 예치금을 환불해요."}
    if re.search(r"두\s*번|중복", r):
        return {"verdict": "GENUINE_ERROR", "reason_category": "duplicate", "refund": "disputer",
                "explanation": "중복 결제 사유로 이의 제기자의 예치금을 환불해요."}
    if re.search(r"승인.*(안|않|없)|동의.*(안|않|없)|서명.*(안|않|없)|모르는|참여.*(안|않|없)", r) and disputer_state == "locked":
        return {"verdict": "BAD_FAITH_DISPUTE", "reason_category": "not_approved_claim", "refund": "none",
                "explanation": "승인한 적 없다고 했지만, 체인에는 본인 지갑으로 직접 서명한 예치 기록이 있어요. 기록과 모순되므로 이의를 기각해요."}
    return {"verdict": "NORMAL_APPROVAL", "reason_category": "misunderstanding", "refund": "none",
            "explanation": "요청 원문, 코드 계산, 온체인 분담표, 예치 서명이 모두 일치해 정상 승인으로 판정했어요. 정산은 그대로 유지돼요."}


def judge(rec: dict[str, Any], evidence: dict[str, Any], disputer: str, reason: str,
          flow: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dstate = evidence["signed"].get(disputer)
    lines = [f"정산: {rec['name']} / 총 {won(rec['total'])} / 결제자 {rec['payer']}",
             f"분담 조건 원문: {rec.get('rule_text') or '-'}",
             "분담·상태: " + ", ".join(f"{m['name']} {won(m['share'])}({evidence['signed'].get(m['name']) or '-'})"
                                     for m in rec["members"]),
             f"이의 제기자: {disputer} (체인 상태: {dstate or '-'})",
             f"이의 사유: {reason}",
             "코드 대조 결과:"] + [f"- [{x['level']}] {x['stage']}: {x['message']}" for x in evidence["findings"]]
    out, meta = llm.client.call_tool("dispute.investigate", SYSTEM, "\n".join(lines), TOOL,
                                     mock=lambda: _mock_judge(reason, dstate, evidence["has_error"]),
                                     flow=flow, max_tokens=900)
    v = out.get("verdict") if out.get("verdict") in VERDICTS else "NORMAL_APPROVAL"
    refund = out.get("refund") if out.get("refund") in ("none", "disputer", "all") else "none"
    guard = None
    # ── 코드 가드 ──
    if evidence["has_error"] and v != "GENUINE_ERROR":
        guard = "기록 불일치가 있어 GENUINE_ERROR로 보정"; v = "GENUINE_ERROR"; refund = refund if refund != "none" else "disputer"
    elif v == "GENUINE_ERROR" and not evidence["has_error"] and out.get("reason_category") not in TXN_ISSUES:
        guard = "기록이 모두 일치하고 거래 문제가 아니어서 NORMAL_APPROVAL로 보정"; v = "NORMAL_APPROVAL"; refund = "none"
    elif v == "BAD_FAITH_DISPUTE" and dstate not in ("locked", "offline"):
        guard = "본인 서명 기록이 없어 악의 판정 근거 부족 → NORMAL_APPROVAL로 보정"; v = "NORMAL_APPROVAL"; refund = "none"
    if v != "GENUINE_ERROR":
        refund = "none"
    elif refund == "none":
        refund = "disputer"
    if meta.get("mode") in ("tools", "json", "text"):
        llm.decision("dispute.investigate", flow, f"Kiln 응답 → 판정 {v}" + (f" (코드 가드: {guard})" if guard else "")
                     + {"none": " → 정산 유지, 환불 없음", "disputer": " → 이의 제기자 환불 트랜잭션 실행",
                        "all": " → 전원 환불 트랜잭션 실행"}[refund])
    return ({"verdict": v, "verdict_ko": VERDICT_KO[v], "refund": refund, "reason_category": out.get("reason_category"),
             "explanation": out.get("explanation") or "", "guard": guard}, [meta])
