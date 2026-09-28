"""AI 구독 검사 — Claude 요금제 벤치마킹: 쓴 만큼 정산하지 않고, 월 구독 요금제가 5시간 세션 한도·주간 한도를 정한다.
+ 심사 제출용 보고서(단계별·실행별 토큰, 응답 반영, 절감, 에너지 근거)까지.
실행: DATA_DIR=/tmp/sp-sub LLM_MODE=mock CHAIN_MODE=mock KILN_API_KEY= AI_PRO_SESSION_TOKENS=1000 AI_PRO_WEEK_TOKENS=3000 \
      python tests/ai_sub_check.py
(한도를 작게 잡아 몇 번의 기록만으로 한도에 닿게 한다 → Free 세션 200 · 주간 600 토큰)
"""
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, quota, report, service, store, usage  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


def err(fn, code):
    try:
        fn()
    except service.ServiceError as e:
        return e.code == code
    return False


assert config.AI_PRO_SESSION_TOKENS == 1000 and config.AI_PRO_WEEK_TOKENS == 3000, "AI_PRO_SESSION_TOKENS=1000 AI_PRO_WEEK_TOKENS=3000 으로 실행"
run = uuid.uuid4().hex[:4]
me = {"email": f"sub.{run}@t.test", "short": "진주"}
service.register_member("진주", None)
service.charge("진주")                              # 100,000 PIE
wallet = store.get_member("진주")["wallet"]
usage.set_actor(me)                                  # 이 테스트의 AI 호출은 진주의 사용량


def use_ai(tokens, stage="settlement.analyze", flow="f-sub"):
    usage.record(stage, flow=flow, prompt_tokens=tokens // 2, completion_tokens=tokens - tokens // 2, latency_ms=800, mode="tools",
                 model=config.KILN_MODEL)


def bal():
    return service.wallet(wallet)["balance"]


def st():
    return quota.state(me["email"])


print("[요금제 — Claude 구조: Free → Pro → Max 5x → Max 20x]")
v = service.ai_sub(me)
P = {p["id"]: p for p in v["plans"]}
ok(list(P) == ["free", "pro", "max", "max20"], "요금제 4종 순서")
ok([P[k]["price"] for k in P] == [0, 4900, 24500, 49000], "가격 0 · 4,900 · 24,500 · 49,000 PIE (Max 5x = Pro×5, Max 20x = Max 5x×2)")
ok(P["free"]["sessionLimit"] * 5 == P["pro"]["sessionLimit"] and P["max"]["sessionLimit"] == P["pro"]["sessionLimit"] * 5
   and P["max20"]["weekLimit"] == P["pro"]["weekLimit"] * 20, "한도 배수: Free = Pro/5 · Max 5x = 5배 · Max 20x = 20배")
ok(v["sub"] is None and v["quota"]["plan"] == "free" and v["quota"]["session"]["limit"] == 200, "구독 전 = Free (세션 200 토큰)")

print("[사용량 = 실제 Kiln 토큰만 · 분쟁 조사는 한도 밖]")
use_ai(120)
usage.record("settlement.calculate", flow="f-sub", prompt_tokens=0, completion_tokens=0, latency_ms=0, mode="code")
use_ai(500, stage="dispute.investigate")
s = st()
ok(s["session"]["used"] == 120 and s["week"]["used"] == 120, f"세션·주간 사용 120 (코드 단계 0 · 분쟁 조사 500은 제외)")
ok(s["session"]["resetsAt"] and abs(s["session"]["resetsAt"] - s["session"]["start"] - 5 * 3600) < 1, "세션 = 첫 사용부터 5시간")
rows = usage.for_user(me["email"])
ok(rows[-1]["counted"] is False and rows[-3]["counted"] is True and rows[-3]["plan"] == "free" and rows[-3]["energy_wh"] > 0,
   "기록마다 한도 포함 여부 · 요금제 · 에너지 추정(Wh)")

print("[세션 한도 → Kiln 대신 규칙 · 이미 시작한 답은 끝까지]")
use_ai(100)                                          # 220 ≥ 200 → 막힘
s = st()
ok(s["blocked"] and s["which"] == "session" and s["resetsAt"] == s["session"]["resetsAt"], "세션 한도 도달 → blocked (세션 초기화 시각)")
ok(quota.check("settlement.analyze") is not None, "다음 Kiln 호출은 막힘 (llm._post가 AI_LIMIT으로 규칙 기반 대체)")
ok(quota.check("dispute.investigate") is None, "분쟁 조사는 한도와 상관없이 호출")
r = service.chat("오늘 고기 3만원 셋이 나눠줘", [], {}, None, "진주")
m0 = r["messages"][0]
ok(r["limit"] and "한도" in m0["text"] and m0.get("limit") and "0 토큰" in m0["meta"],
   f"1:1 대화: 한도 안내가 먼저 · 규칙으로 계속 ({m0['meta']})")
ok(len(r["messages"]) >= 2, "한도여도 정산 계산 결과는 규칙으로 나옴 (계산은 원래 코드)")
tok = quota.TURN.set(True)                           # 턴 시작 때 한도 안이었으면 그 턴은 끝까지
ok(quota.check("assistant.step") is None, "진행 중인 턴은 도중에 끊지 않음")
quota.TURN.reset(tok)

print("[구독 시작 → 한도 즉시 5배]")
b0 = bal()
r = service.ai_subscribe(me, "pro")
ok(bal() == b0 - 4900 and r["sub"]["sub"]["plan"] == "pro", f"Pie Pro 결제 4,900 PIE ({b0:,} → {bal():,})")
ok(not st()["blocked"] and st()["session"]["limit"] == 1000, "올리자마자 세션 한도 1,000 → 다시 AI 사용 가능")
ok(err(lambda: service.ai_subscribe(me, "pro"), "ALREADY_SUBSCRIBED"), "같은 요금제 중복 결제 거부")
ok(err(lambda: service.ai_subscribe({"email": "nw@t.test", "short": "없는사람"}, "pro"), "MEMBER_WALLET_MISSING"), "지갑 없으면 구독 불가")
ok(err(lambda: service.ai_pay(me, 100), "BILLING_CHANGED"), "예전 '누적 사용량 송금'은 410 BILLING_CHANGED")

print("[높은 요금제는 바로 · 낮은 요금제는 주기 끝에 (Claude와 같음)]")
b1 = bal()
r = service.ai_subscribe(me, "max")
ok(bal() == b1 - 24500 and r["sub"]["sub"]["plan"] == "max" and r["sub"]["sub"]["label"] == "Pie Max 5x", "Max 5x로 올림 → 24,500 PIE 바로 결제")
b2 = bal()
r = service.ai_subscribe(me, "pro")
sub = r["sub"]["sub"]
ok(bal() == b2 and sub["plan"] == "max" and sub["nextPlan"] == "pro" and sub["nextLabel"] == "Pie Pro", "Pro로 내림 → 결제 없이 다음 결제일부터 (예약)")
r = service.ai_subscribe(me, "max")
ok(r["sub"]["sub"]["nextPlan"] is None and bal() == b2, "같은 요금제를 다시 고르면 예약 취소 (결제 없음)")
service.ai_subscribe(me, "pro")
rec = store.kv_get("ai_sub", me["email"])
rec["renewsAt"] = time.time()
store.kv_put("ai_sub", me["email"], rec)
b3 = bal()
v = service.ai_sub(me)
ok(v["sub"]["plan"] == "pro" and bal() == b3 - 4900, "주기가 끝나면 예약한 Pro로 바뀌고 Pro 가격으로 자동 갱신 (mock 체인)")

print("[해지 → 남은 기간 이용 후 Free]")
service.ai_sub_cancel(me)
v = service.ai_sub(me)
ok(v["sub"]["cancelAt"] == v["sub"]["renewsAt"] and v["quota"]["plan"] == "pro", "해지 예약 · 남은 기간은 Pro 그대로")
b4 = bal()
service.ai_subscribe(me, "pro")
ok(service.ai_sub(me)["sub"]["cancelAt"] is None and bal() == b4, "해지 취소 (추가 결제 없음)")
service.ai_subscribe(me, "free")                     # Free 고르기 = 해지 예약
rec = store.kv_get("ai_sub", me["email"])
rec["renewsAt"] = time.time()
store.kv_put("ai_sub", me["email"], rec)
v = service.ai_sub(me)
notifs = (store.kv_get("notifs", me["email"]) or {}).get("items", [])
ok(v["sub"] is None and v["quota"]["plan"] == "free" and any("Free 한도" in n["text"] for n in notifs), "기간이 끝나면 Free + 알림")

print("[갱신 실패 → Free + 알림]")
service.ai_subscribe(me, "pro")
rec = store.kv_get("ai_sub", me["email"])
rec.update(renewsAt=time.time(), price=10 ** 9)
store.kv_put("ai_sub", me["email"], rec)
v = service.ai_sub(me)
notifs = (store.kv_get("notifs", me["email"]) or {}).get("items", [])
ok(v["sub"] is None and any("갱신하지 못해" in n["text"] for n in notifs), "잔액 부족 → Free로 바뀌고 알림")

print("[주간 한도 — 세션과 따로]")
week_me = {"email": f"week.{run}@t.test", "short": "민재"}
now = time.time()
with usage.USAGE_FILE.open("a", encoding="utf-8") as f:     # 6~30시간 전 사용 기록 (지난 세션들) → 이번 주 520
    for h, t in ((30, 200), (18, 160), (6, 160)):
        f.write(json.dumps({"ts": now - h * 3600, "stage": "assistant.step", "flow": "f-week", "prompt_tokens": t, "completion_tokens": 0,
                            "total_tokens": t, "latency_ms": 500, "mode": "tools", "user": week_me["email"]}) + "\n")
store.kv_put("ai_quota", week_me["email"], {"weekAnchor": now - 31 * 3600})
quota.reset_cache()
s = quota.state(week_me["email"])
ok(s["session"]["used"] == 0 and s["week"]["used"] == 520 and not s["blocked"], "지난 세션 사용은 주간에만 남음 (주간 520/600)")
usage.set_actor(week_me)
use_ai(90, flow="f-week")
s = quota.state(week_me["email"])
ok(s["blocked"] and s["which"] == "week" and s["session"]["used"] == 90, "세션은 여유(90/200)여도 주간 600을 넘으면 막힘 (주간 초기화 시각)")
usage.set_actor(me)

print("[명세서 — 호출마다 응답 반영·에너지·한도 포함]")
use_ai(40, stage="assistant.step", flow="f-dec")
service.llm.decision("assistant.step", "f-dec", "Kiln 응답 → 도구 호출: split_cost")
v = service.ai_usage(me)
it = next(u for u in v["items"] if u.get("flow") == "f-dec" and u["ai"])
ok(it["decision"].endswith("split_cost") and it["energyWh"] > 0 and it["counted"], "Kiln 호출 한 줄에 '응답 → 행동' · 에너지 · 한도 포함 표시")
ok(v["unpaid"] == 0 and v["quota"]["plan"] in quota.PLANS and v["energy"]["npu_power_watts"] == config.NPU_POWER_WATTS,
   "후불 없음(미납 0) · 한도 상태 · 에너지 가정 포함")
ok(any(u["tag"] == "ai.subscribe" and u["amount"] == -4900 and u.get("txHash") for u in v["items"]), "구독 결제 −4,900 PIE와 tx 해시")

print("[심사용 보고서 — 조건을 바꾼 두 번의 실행]")
service.register_member("민재", None)
service.charge("민재")
ok1 = service.propose(group_name=f"보고서 {run} A", members=["진주", "민재"], shares=[["진주", 15000], ["민재", 15000]],
                      total=30000, payer="진주", rule_text="똑같이", purpose="저녁 식사")
usage.record("settlement.analyze", flow=ok1["id"] if isinstance(ok1, dict) and ok1.get("id") else None, prompt_tokens=300,
             completion_tokens=40, latency_ms=900, mode="tools", model=config.KILN_MODEL)
blocked = None
try:
    blocked = service.propose(group_name=f"보고서 {run} B", members=["진주", "민재"], shares=[["진주", 15000], ["민재", 15000]],
                              total=30000, payer="진주", rule_text="똑같이", purpose="저녁 식사", total_cap=20000)
except service.ServiceError as e:
    print("   (B 등록 결과:", e.code, ")")
rep = service.usage_summary()
runs = [x for x in rep["runs"] if x["sid"] in {(ok1 or {}).get("id"), (blocked or {}).get("id")}]
ok(len(runs) == 2, f"정산 두 건 = 실행 두 번 ({[x['outcome'] for x in runs]})")
ok(any("중단" in x["outcome"] and any(t["kind"] == "block" for t in x["txs"]) for x in runs), "총 한도 2만원을 넘긴 실행은 지출 통제로 중단 + 온체인 Blocked tx")
ok(any(x["conditions"]["totalCap"] == 20000 for x in runs) and all(x["txs"] for x in runs), "실행마다 조건(총 한도)과 tx 해시")
ok([p["phase"] for p in rep["phases"]][0] == "settle" and any(s["stage"] == "settlement.calculate" and s["kind"] == "코드" for s in rep["stages"]),
   "단계별 표: 정산 코어 먼저 · 금액 계산은 코드(0 토큰)")
ok(rep["decisions"] >= 1 and rep["savings"]["items"][0]["id"] == "group_skip" and rep["energy"]["wh_per_1k_tokens"] > 0,
   "응답 반영 건수 · 절감 항목 · 1,000토큰당 에너지")
md = rep["markdown"]
ok(all(h in md for h in ("## 1. 워크플로 단계별 토큰", "## 3. 실행(정산)별 기록", "## 4. 불필요한 추론", "## 5. 에너지 추정 근거", "## 6. 구독 요금제")),
   "README용 마크다운 6개 절")
csv_txt = service.usage_calls_csv()
ok(csv_txt.startswith("\ufeff시각(KST)") and "@t.test" not in csv_txt and "응답 반영" in csv_txt, "호출별 CSV (개인정보 없음 · 응답 반영 행 포함)")

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
