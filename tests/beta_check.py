"""베타 데이터 수집 검사 — 기능 예시(미션) · 동의 · 비식별 · 턴/버전 표시 · 피드백 · 내보내기 · 버전 비교 보고서.
실행: DATA_DIR=/tmp/sp-beta LLM_MODE=mock CHAIN_MODE=mock KILN_API_KEY= APP_VERSION=beta-1 BETA_EXPORT_KEY=k123 python tests/beta_check.py
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import beta, config, quota, service, store, usage  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


run = uuid.uuid4().hex[:4]
code = service.send_code(f"beta.{run}@t.test", "signup")["dev_code"]
service.signup("오진주", f"beta.{run}@t.test", "pass1234", code=code)
me = store.user_by_email(f"beta.{run}@t.test")
usage.set_actor(me)

print("[기능 예시(미션) — 필요한 데이터별로]")
st = service.beta_status(me)
S = {s["id"]: s for s in st["scenarios"]}
ok(st["enabled"] and st["version"] == "beta-1" and st["consent"] is None and st["total"] == 13 and st["done"] == 0, "베타 켜짐 · 미션 13개 · 동의 전")
tags = {t for s in beta.SCENARIOS for t in s["tags"]}
ok({"settle", "settle_ask", "settle_change", "shop", "dispute", "name_call", "status", "howto"} <= tags, f"학습 태그 {len(tags)}종을 고루")
ok(sum(s["bench"] for s in beta.SCENARIOS) >= 5 and all(s["where"] in ("chat", "group", "action") for s in beta.SCENARIOS),
   f"버전 비교용 기준 과제 {sum(s['bench'] for s in beta.SCENARIOS)}개")
crit = {g for s in beta.SCENARIOS for g in s["goal"]}
ok(crit == {"train", "token", "criteria"} and S["S06"]["follow"] and S["S07"]["where"] == "action",
   "목표 3가지 모두 · 지출 통제는 조건 바꿔 재실행(follow) · 이의제기는 버튼 미션")

print("[동의 전: 턴 표시·미션 완료만, 대화 글은 저장 안 함]")
r = service.chat(S["S01"]["text"], [], {}, "c-beta-1", me["short"], scenario="S01", edited=False)
t1 = r["beta"]["turn"]
ok(t1.startswith("t_") and all(m.get("turn") == t1 for m in r["messages"]), "답마다 turn id (👍/👎용)")
rows = [x for x in usage.read_all() if x.get("turn") == t1]
ok(rows and all(x.get("scenario") == "S01" and x.get("version") == "beta-1" and x.get("edited") is False for x in rows),
   f"이 턴의 기록 {len(rows)}줄 모두 시나리오·버전·‘그대로 보냄’ 표시")
ok(service.beta_status(me)["done"] == 1 and not beta.DIALOGS.exists() or not any(json.loads(x).get("turn") == t1 for x in beta.DIALOGS.read_text(encoding="utf-8").splitlines()),
   "미션 완료 1 · 동의 전이라 대화 글 저장 없음")

print("[동의 후: 비식별 저장]")
st = service.beta_consent(me, True)
ok(st["consent"] is True, "동의")
txt = "오진주랑 민재 연락처 010-1234-5678 jinju@naver.com 지갑 0x" + "a" * 40 + " 치킨 2만 피자 1.8만 넷이 나눠줘 결제는 진주가"
r = service.chat(txt, [{"role": "user", "text": "민재가 계좌 110-123-456789로 보내래"}], {}, "c-beta-2", me["short"], scenario="S02", edited=True)
t2 = r["beta"]["turn"]
d = next(json.loads(x) for x in beta.DIALOGS.read_text(encoding="utf-8").splitlines() if json.loads(x)["turn"] == t2)
blob = json.dumps(d, ensure_ascii=False)
ok(all(x not in blob for x in ("오진주", "010-1234-5678", "jinju@naver.com", "0xaaaa", "110-123-456789", "beta." + run)),
   "이름·전화·이메일·지갑·계좌번호·계정 모두 지움")
a0 = d["user"].split("랑")[0]
ok(a0 in beta.PSEUDO and d["user"].count(a0) == 2 and "오" + a0 not in d["user"], f"실명 '오진주'·짧은 이름 '진주' → 같은 가명 '{a0}' (성만 남지 않음)")
ok("[전화번호]" in d["user"] and "[이메일]" in d["user"] and "[지갑]" in d["user"] and "[번호]" in d["history"][0] and d["uid"] == beta.uid(me["email"]),
   f"자리표시·가명으로 문장 구조는 유지: {d['user'][:40]}…")
ok(d["scenario"] == "S02" and d["edited"] is True and d["version"] == "beta-1" and d["channel"] == "chat" and d["reply"],
   "시나리오 · 고쳐 보냄 · 버전 · 채널 · Pie 답")

print("[피드백 → 학습·평가 후보]")
service.beta_feedback(me, t2, "down", "금액이 틀렸어요", "합계가 이상해요 010-9999-8888")
service.beta_feedback(me, t1, "up")
try:
    service.beta_feedback(me, "x", "meh")
    ok(False, "잘못된 피드백 거부")
except service.ServiceError as e:
    ok(e.code == "BAD_REQUEST", "잘못된 피드백 거부")
ev = [json.loads(x) for x in beta.export("eval").splitlines()]
tr = [json.loads(x) for x in beta.export("train").splitlines()]
ok(any(x["id"] == f"beta-{t2}" and x["reason"] == "금액이 틀렸어요" and "[전화번호]" in (x["note"] or "") for x in ev),
   "👎 → 평가 문제 후보 (이유·의견, 의견 속 번호도 지움)")
ok(not any(x["id"] == f"beta-{t2}" for x in tr) and all("ideal" in x for x in tr), "👎는 예시 후보에서 빠짐")

print("[버전 비교 — 같은 예시를 정식 버전으로]")
config.APP_VERSION = "1.0"
service.chat(S["S01"]["text"], [], {}, "c-beta-3", me["short"], scenario="S01", edited=False)
config.APP_VERSION = "beta-1"
rep = service.beta_report()
s01 = {x["version"]: x for x in rep["scenarios"] if x["scenario"] == "S01"}
ok(set(s01) >= {"beta-1", "1.0"} and s01["beta-1"]["asIs"] >= 1 and s01["beta-1"]["up"] == 1, "S01: 베타·정식 두 줄 · 그대로 보낸 턴 · 👍")
ok({"beta-1", "1.0"} <= set(rep["versions"]) and "## 2. 기능 예시(시나리오)별" in rep["markdown"] and "0x" not in rep["markdown"],
   "버전별 합계 · 마크다운 보고서 (대화 글 없음)")
ok(rep["participation"]["consented"] >= 1 and rep["participation"]["missionsDone"]["S02"] >= 1 and "criteria" in rep, "참여·미션·심사 기준 실행 수")

print("[내보내기는 관리자만]")
from starlette.testclient import TestClient  # noqa: E402
from backend.app import app  # noqa: E402
c = TestClient(app)
ok(c.get("/api/beta/export.jsonl?kind=eval").status_code in (401, 403), "로그인·키 없으면 거부")
ok(c.get("/api/beta/export.jsonl?kind=eval&key=wrong").status_code in (401, 403), "틀린 키 거부")
resp = c.get("/api/beta/export.jsonl?kind=eval&key=k123")
ok(resp.status_code == 200 and f"beta-{t2}" in resp.text, "키가 맞으면 내려받기")
ok(c.get("/api/beta/report").status_code == 200 and "## 1. 버전별 비교" in c.get("/api/beta/report.md").text, "공개 요약 보고서")

print("[철회하면 지움]")
st = service.beta_consent(me, False)
left = [x for x in beta.DIALOGS.read_text(encoding="utf-8").splitlines() + beta.FEEDBACK.read_text(encoding="utf-8").splitlines()
        if json.loads(x).get("uid") == beta.uid(me["email"])]
ok(st["consent"] is False and not left, "동의 철회 → 저장된 대화·의견 삭제")
r = service.chat("둘이 만원 반반", [], {}, "c-beta-4", me["short"])
ok(r["beta"]["turn"] and not any(json.loads(x).get("turn") == r["beta"]["turn"] for x in beta.DIALOGS.read_text(encoding="utf-8").splitlines()),
   "철회 후엔 저장 안 함 (토큰 통계만)")

print("[베타 한도 — 구독 없어도 Pro 한도 (BETA_PLAN=pro)]")
config.BETA_PLAN = "pro"
q = quota.state(me["email"])
ok(q["plan"] == "pro" and q["beta"] and q["paidPlan"] == "free" and "(베타 무료)" in q["label"], f"{q['label']} · 세션 {q['session']['limit']:,} 토큰")
config.BETA_PLAN = ""
ok(quota.state(me["email"])["plan"] == "free", "끄면 Free 한도")

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
