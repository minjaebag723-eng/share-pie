"""코드 점검에서 찾은 문제들의 회귀 테스트 (가짜 LLM 출력으로 경계값 검사).
실행: DATA_DIR=/tmp/sp-robust LLM_MODE=mock KILN_API_KEY= SERPER_API_KEY= DISPUTE_WINDOW_SEC=2 python tests/robustness_check.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import assistant, llm, money, service, settlement, shopping  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


def fake_tool(out):
    """다음 call_tool 호출이 LLM이 이상한 값을 준 것처럼 돌려주게."""
    orig = llm.client.call_tool

    def f(stage, system, user, tool, mock=None, flow=None, max_tokens=0):
        llm.client.call_tool = orig
        return out, {"stage": stage, "mode": "tools", "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "latency_ms": 1}
    llm.client.call_tool = f


print("[LLM 출력 형식 오류]")
fake_tool({"total_amount": "38,900원", "members": "진주, 진우, 민재", "payer": "김진주",
           "adjustments": [{"name": "김진주", "kind": "less", "value": "5000원"}, {"name": "진우"}, "x"],
           "per_person_cap": "50000", "missing": []})
r = settlement.calculate(text="진주가 결제했어. 진주는 5천원 적게", members=["진주", "진우", "민재"])
ok(r["status"] == "ok" and r["total"] == 38900 and sum(a for _, a in r["shares"]) == 38900, f"문자열 금액·이름 정리 후 계산: {r.get('shares')}")
ok(r["payer"] == "진주", "문장에서 말한 결제자 반영: " + str(r.get("payer")))
ok(money.compute_shares(10000, ["a", "b"], [{"name": "b", "kind": "ratio", "value": 1.5}]) == [("a", 4000), ("b", 6000)], "1.5배 비율 유지")

sess = assistant.Session("t-robust", [])
sess.menu["m1"] = {"name": "치킨 한 마리", "price": 20000, "mall": "테스트몰", "url": None, "query": "치킨", "found": 1}   # 검색으로 찾은 메뉴 흉내
res = sess.run_tool("check_delivery_combos", {"people": "4명", "budget_total": "15만원",
                                              "combos": ["bad", {"label": "x", "items": [{"id": "m1", "qty": "2개", "serves": 2}]}]})
ok("passed" in res and res["passed"] and res["passed"][0]["total"] == 20000 * 2 + 3000, f"도구 인자 문자열(4명·15만원·2개) 처리: {res.get('passed')}")
res = sess.run_tool("check_delivery_combos", {"people": 4, "combos": [{"label": "가짜", "items": [{"id": "d1", "qty": 2}]}]})
ok(not res.get("passed"), "검색하지 않은 메뉴(예전 예시 id)는 조합에 못 씀")
ok(not hasattr(sess, "delivery_menu") and all(t["name"] != "delivery_menu" for t in assistant.TOOLS), "예시 메뉴표 도구 없음")
ok(shopping.CATALOG == [] and not (Path(shopping.__file__).parent / "catalog.json").exists(), "예시 상품 카탈로그 파일 없음")
res = sess.run_tool("split_cost", {"total": "12만원", "members": "진주,민재"})
ok([x["name"] for x in res.get("shares", [])] == ["진주", "민재"], f"members 문자열 분리: {res}")
res = sess.run_tool("check_delivery_combos", {"people": None, "combos": None})
ok(isinstance(res, dict), "None 인자도 500 없이 처리")

print("[예산 경계 · 이름 · 개인정보]")
q = shopping._merge_rules({"people": "3명", "budget_total": "10만원", "category": "ANY"}, "")
ok(shopping.evaluate({"cat": "SNACK", "price": 100000, "shipping": 0, "qty_g": None}, q)["within"], "총예산에 딱 맞는 상품은 예산 내")
ok(service.short_name("김진주") == "진주" and service.short_name("Alice") == "Alice" and service.short_name("남궁민수") == "남궁민수", "짧은 이름 규칙")
p = settlement.pii_clean("진주님 삼겹살 김진주 010-1234-5678 a@b.com 분담금", ["진주"])
ok("010" not in p and "@" not in p and "진주" not in p and "김" not in p, f"체인 문구 개인정보 제거: '{p}'")
ok(not money.merchant_allowed("Cucina Market", ["CU"]) and money.merchant_allowed("CU 성수점", ["CU"]), "짧은 가맹점 이름은 단어 단위 일치")

print("[억 단위 · 퍼센트 총액 · 불법 목적]")
from agent import textutil  # noqa: E402
ok(textutil.parse_amounts("100억") == [10_000_000_000] and textutil.parse_amounts("1억 5천만원") == [150_000_000], "억 단위 금액 인식")
ok(textutil.parse_amounts("4명이 2kg") == [], "단위 없는 숫자는 금액 아님")
r = settlement.calculate(text="100억의 15%를 둘이 나눠", members=["진주", "민재"])
ok(r["status"] == "ok" and r["total"] == 1_500_000_000 and sum(a for _, a in r["shares"]) == r["total"], f"'100억의 15%' 총액은 코드가 계산: {r.get('total')}")
r = settlement.calculate(text="우리가 검은돈으로 100억을 벌었어 근데 세탁 수수료가 15%야 둘이서 나눠서 정산할 예정이야", members=["진주", "민재"])
ok(r["status"] == "refused" and r["code"] == "PROHIBITED_PURPOSE", "자금세탁 정산 요청 거절")
ok(settlement.calculate(text="세탁소 비용 3만원 나눠", members=["진주", "민재"])["status"] == "ok", "'세탁소'는 정상 정산")
out = service.chat("검은돈 세탁 수수료 나눠줘", [], {}, "rb-guard", None)
ok(out["messages"][0].get("refused"), "1:1 채팅도 코드에서 거절 (AI 호출 없음)")
try:
    service.propose(group_name="세탁 수수료", members=["a", "b"], shares=[["a", 1], ["b", 1]], total=2, payer="a")
    ok(False, "정산 요청 API도 불법 목적 거부")
except service.ServiceError as e:
    ok(e.code == "PROHIBITED_PURPOSE", "정산 요청 API도 불법 목적 거부")

print("[AI가 금액을 놓쳐도 코드가 읽음 · 부가세 더하기]")
M4 = ["진주", "진우", "민재", "지현"]
r = settlement.calculate(text="오늘 레스토랑 비용 100만원 나왔는데 부가세 10%붙여서 10%더한 금액이야", members=M4, payer="진주")
ok(r["status"] == "ok" and r["total"] == 1_100_000 and r["shares"][0][1] == 275_000, f"100만원 + 부가세 10% = 110만원 → 1인 27.5만원: {r.get('total')}")
fake_tool({"total_amount": None, "members": [], "adjustments": [], "missing": ["total_amount"], "question": "나눌 총금액은 얼마인가요?"})
r = settlement.calculate(text="총액이 100만원이야", members=M4, payer="진주")
ok(r["status"] == "ok" and r["total"] == 1_000_000, "AI가 총액을 놓쳐도 코드가 ‘100만원’을 읽어 계산 (같은 질문 반복 안 함)")
fake_tool({"total_amount": 1000000, "members": [], "adjustments": [], "missing": []})
r = settlement.calculate(text="100만원에 부가세 10% 더해서 나눠줘", members=M4, payer="진주")
ok(r["total"] == 1_100_000, "AI가 부가세를 빼먹고 100만원이라 해도 코드가 110만원으로 바로잡음")

print("[그룹방 Pie mate 판단]")
for t, want in [("파이야", True), ("파메 이거 어떻게 해", True), ("pie?", True), ("쉐어파이 최고", True), ("파이 메이트 도와줘", True),
                ("하이", False), ("ㅋㅋㅋ", False), ("애플파이 먹고싶다", False), ("파이팅!", False), ("와이파이 안 돼", False),
                ("총 12만원 똑같이 나눠줘", True), ("치킨 시킬까?", True), ("나는 얼마 내면 돼?", True)]:
    ok(service.pie_should_reply(t, [])[0] == want, f"'{t}' → {'답함' if want else '무시'}")
ok(service.pie_should_reply("응 그거", [{"pie": True, "ask": "settle", "text": "총금액은?"}])[0], "Pie가 물은 직후 짧은 대답은 이어서 이해")

print("[같은 이름 가입 · 인증번호 재요청 규칙]")
from agent import config  # noqa: E402
def _su(name, mail):
    return service.signup(name, mail, "pw123456", service.send_code(mail, "signup")["dev_code"])


a, b, c, d = _su("박하늘", "sky1@robust.test"), _su("최하늘", "sky2@robust.test"), _su("박하늘", "sky3@robust.test"), _su("박하늘", "sky4@robust.test")
ok([a["short"], b["short"], c["short"], d["short"]] == ["하늘", "최하늘", "박하늘", "하늘2"], f"같은 이름 허용 · 정산 이름 자동 구분: {[a['short'], b['short'], c['short'], d['short']]}")
config.CODE_RESEND_SEC, config.CODE_FREE_RESENDS = 60, 2
rs = [service.send_code("resend@robust.test", "signup") for _ in range(3)]
ok([r["resend_after"] for r in rs] == [0, 0, 60] and rs[0]["expires_in"] == 300, f"처음+재요청 2번은 바로, 그 뒤 60초: {[r['resend_after'] for r in rs]} · 유효 {rs[0]['expires_in']}초")
try:
    service.send_code("resend@robust.test", "signup")
    ok(False, "4번째 요청은 1분 대기")
except service.ServiceError as e:
    ok(e.code == "CODE_COOLDOWN" and e.details["wait"] > 50, "4번째 요청은 1분 대기: " + e.message)
config.CODE_RESEND_SEC = 0

print("[정산 상태]")
for n in ("진주", "진우", "민재"):
    try:
        service.signup(("김" + n) if n != "진주" else "김진주", f"{n}@robust.test", "pw123456")
    except service.ServiceError:
        pass
    service.register_member(n, None)
    service.charge(n) if True else None
rec = service.propose(group_name="결제자 빠짐", members=["진주", "진우", "민재"], shares=[["진주", 0], ["진우", 6000], ["민재", 6000]],
                      total=12000, payer="진주")
ok(rec["status"] == "open", "결제자 0원(‘진주 빼고 둘이’) 정산 등록")
service.mock_lock(rec["id"], "진우")
c = service.cancel_settlement(rec["id"], "진주")
ok(c["status"] == "blocked", "전원 예치 전 결제자 취소 → 중단 + 환불")
try:
    service.cancel_settlement(rec["id"], "진우")
    ok(False, "결제자 아닌 사람 취소 거부")
except service.ServiceError:
    ok(True, "결제자 아닌 사람 취소 거부")

rec = service.propose(group_name="이의제기 테스트", members=["진주", "진우", "민재"], shares=[["진주", 4000], ["진우", 4000], ["민재", 4000]],
                      total=12000, payer="진주")
service.mock_lock(rec["id"], "진우")
service.mock_lock(rec["id"], "민재")
out = service.chat("정산 금액이 잘못됐어", [], {}, "rb-chat", "민재")
ok(out["messages"][0].get("needs_info") and "할까요" in out["messages"][0]["text"], "채팅 문장만으로는 확인 먼저: " + out["messages"][0]["text"][:40])
h = [{"role": "user", "text": "정산 금액이 잘못됐어"}, {"role": "bot", "text": out["messages"][0]["text"], "intent": "dispute", "needs_info": True}]
out = service.chat("공동구매가 품절로 취소됐어요 010-9999-8888", h, {}, "rb-chat", "민재")
st = service.get_settlement(rec["id"])
ok(st["dispute"] and st["dispute"]["verdict"] == "GENUINE_ERROR" and st["status"] == "refunded", "확인 후 판정·환불")
ok(all(r["amount"] == 4000 for r in st["dispute"]["refunded"]), "환불 금액은 체인 이벤트 기준")
again = service.dispute_investigate(rec["id"])
ok(again.get("already"), "이미 처리된 이의제기는 다시 판정하지 않음")

rec = service.propose(group_name="기간", members=["진주", "진우"], shares=[["진주", 5000], ["진우", 5000]], total=10000, payer="진주")
service.mock_lock(rec["id"], "진우")
time.sleep(2.2)
try:
    service.dispute_raise(rec["id"], "진우", "늦은 이의")
    st = service.get_settlement(rec["id"])
    ok(st["status"] == "paid", "기간이 끝나면 지급 (이의제기 불가)")
except service.ServiceError as e:
    ok(e.code == "NOT_DISPUTABLE", "기간이 끝나면 이의제기 불가: " + e.code)

print("[AI 구매 대행]")
for n in ("진주", "진우"):
    service.charge(n)
bal = lambda n: service._chain().account(service.store.get_member(n)["wallet"])["balance"]   # noqa: E731
p1 = service.propose(group_name="구매 잔액변동", members=["진주", "진우"], shares=[["진주", 30000], ["진우", 30000]], total=60000,
                     payer="진주", merchant="쿠팡", purchase=True)
service.mock_lock(p1["id"], "진주")
b0 = bal("진우")
other = service.propose(group_name="다른 정산", members=["진우", "민재"], shares=[["진우", b0 - 10000], ["민재", 1000]], total=b0 - 9000, payer="민재")
if other["status"] == "open":
    service.mock_lock(other["id"], "진우")   # 승인 후 다른 곳에 돈을 써 버림
st = service.get_settlement(p1["id"])
if st["status"] == "open" and bal("진우") < 30000:
    try:
        service.mock_lock(p1["id"], "진우")
    except service.ServiceError:
        pass
    st = service.get_settlement(p1["id"])
ok(st["status"] in ("blocked", "open") and not (st.get("purchase") or {}).get("orderNo"), f"잔액이 모자라면 AI가 결제하지 않음: {st['status']}")
ok(bal("진주") >= 0 and all(m["state"] != "locked" for m in st["members"]), "일부만 인출되는 일 없음")

print("✓ 전체 통과" if not fails else f"✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
