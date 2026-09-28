"""AI 구독 한도 실측 검사 — 가짜 Kiln(호출마다 516 토큰) + 모의 체인. 한도를 넘으면 Kiln 호출 자체가 멈추는지 호출 수로 확인한다.
python -m uvicorn tests.fake_kiln:app --port 8011 &
DATA_DIR=/tmp/sp-limit LLM_MODE=live KILN_API_KEY=x KILN_MODEL=qwen3-32b KILN_BASE_URL=http://127.0.0.1:8011/v1 \
  SERPER_API_KEY= CHARGE_COOLDOWN_SEC=0 AI_PRO_SESSION_TOKENS=2500 AI_PRO_WEEK_TOKENS=20000 python tests/ai_limit_check.py
(Free 세션 500 토큰 → Kiln 한 번이면 닿는다)
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, dispute, llm, quota, service, store, usage  # noqa: E402

fails = []
KILN = config.KILN_BASE_URL.rsplit("/v1", 1)[0]


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


def kiln_calls() -> int:
    return len(httpx.get(KILN + "/calls").json())


def user(name, email):
    code = service.send_code(email, "signup")["dev_code"]
    service.signup(name, email, "pass1234", code=code)
    u = store.user_by_email(email)
    service.register_member(u["short"], None)
    return u


assert config.AI_PRO_SESSION_TOKENS == 2500, "AI_PRO_SESSION_TOKENS=2500 으로 실행"
print("[사용자별 AI 사용량 — 실측 토큰]")
a = user("김에이", "limit.a@test.com")
b = user("박비", "limit.b@test.com")
with usage.scope("chat", "야식 정산", actor=a):
    service.chat("셋이 30000원 똑같이 나눠줘", [], {}, "c-lim-1", a["short"])
    service.calculate_only(30000, ["에이", "비", "씨"], [])        # 확인 카드의 Stage 2 (코드 전용)
va, vb = service.ai_usage(a), service.ai_usage(b)
ai_rows = [i for i in va["items"] if i["ai"]]
ok(va["calls"] >= 1 and va["tokens"] == va["inTok"] + va["outTok"] > 0, f"A의 Kiln 호출 {va['calls']}회 · {va['tokens']:,} 토큰 (응답의 usage 그대로)")
ok(all(i["where"] == "chat" and i["ctx"] == "야식 정산" and i["counted"] and i["energyWh"] > 0 for i in ai_rows),
   "어디서 쓴 AI인지 · 한도 포함 · 에너지 추정")
ok(any(i.get("decision") for i in ai_rows), f"응답이 바꾼 행동 기록 ({next((i['decision'] for i in ai_rows if i.get('decision')), '-')})")
ok(any(i["stage"] == "settlement.calculate" and not i["ai"] and i["inTok"] == 0 for i in va["items"]), "금액 계산은 코드 → 0 토큰")
ok(vb["tokens"] == 0 and vb["calls"] == 0, "B에게는 A의 사용량이 안 붙음")
ok(va["measured"] and va["model"] == "qwen3-32b" and va["unpaid"] == 0, "Kiln 실측 · qwen3-32b · 후불 없음")

print("[Free 세션 한도 → Kiln 호출이 실제로 멈춤]")
qa = quota.state(a["email"])
ok(qa["plan"] == "free" and qa["blocked"] and qa["session"]["used"] >= 500, f"A: Free 세션 {qa['session']['used']:,}/{qa['session']['limit']:,} → 막힘")
n0 = kiln_calls()
with usage.scope("chat", "야식 정산", actor=a):
    r = service.chat("넷이 48000원 나눠줘 민재는 5천원 덜", [], {}, "c-lim-2", a["short"])
ok(kiln_calls() == n0, "한도 넘은 다음 턴: Kiln 호출 0회")
ok(r["limit"] and "한도" in r["messages"][0]["text"] and r["messages"][0]["meta"].endswith("0 토큰"), "한도 안내 + '0 토큰' 표시")
ok(any("48,000" in (m.get("text") or "") or m.get("confirm") or m.get("card") for m in r["messages"][1:]) or len(r["messages"]) > 1,
   "정산 계산은 규칙·코드로 계속")
lim = [i for i in service.ai_usage(a)["items"] if i.get("limited")]
ok(lim and lim[0]["title"] == "AI 한도 도달 → 규칙 답", "명세서에 '한도 도달 → 규칙 답' 기록")
with usage.scope("chat", "분쟁", actor=a):
    n1 = kiln_calls()
    out, meta = llm.client.call_tool("dispute.investigate", dispute.SYSTEM, "이의 사유: 금액이 틀렸어요", dispute.TOOL,
                                     mock=lambda: {"verdict": "NORMAL_APPROVAL", "refund": "none"})
ok(kiln_calls() == n1 + 1 and meta["mode"] in quota.AI_MODES, "분쟁 조사는 한도와 상관없이 Kiln 호출 (증거 도구는 항상 동작)")
with usage.scope("chat", "야식 정산", actor=b):
    n2 = kiln_calls()
    service.chat("둘이 10000원 반반", [], {}, "c-lim-3", b["short"])
ok(kiln_calls() > n2, "B는 자기 한도 안이라 Kiln 호출 (한도는 사람마다 따로)")

print("[요금제를 올리면 바로 다시 AI]")
service.charge(a["short"])
r = service.ai_subscribe(a, "pro")
ok(r["sub"]["sub"]["plan"] == "pro" and not quota.state(a["email"])["blocked"], "Pie Pro 결제 → 세션 한도 2,500으로 바로 풀림")
n3 = kiln_calls()
with usage.scope("chat", "야식 정산", actor=a):
    service.chat("넷이 48000원 나눠줘 민재는 5천원 덜", [], {}, "c-lim-4", a["short"])
ok(kiln_calls() > n3, "다시 Kiln 호출")

print("[보고서]")
rep = service.usage_summary()
ok(rep["live"] and rep["llm_calls"] >= 3 and any(s["stage"] == "settlement.analyze" and s["calls"] for s in rep["stages"]),
   f"실측 보고서: Kiln {rep['llm_calls']}회 · {rep['total_tokens']:,} 토큰 · 에너지 상한 {rep['energy_wh_upper_bound']} Wh")
ok(next(i for i in rep["savings"]["items"] if i["id"] == "limit")["count"] >= 1, "절감 표에 '한도로 규칙 답' 건수")

print("✓ 전체 통과" if not fails else f"✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
