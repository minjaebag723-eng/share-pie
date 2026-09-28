"""정산 캘린더(실제 날짜 · KST) 백엔드 검사.
실행: DATA_DIR=/tmp/sp-cal LLM_MODE=mock CHAIN_MODE=mock KILN_API_KEY= python tests/calendar_check.py
"""
import datetime as dt
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import service  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


run = uuid.uuid4().hex[:4]
for n in ("진주", "진우"):
    service.register_member(n, None)
    service.charge(n)

kst_today = dt.datetime.fromtimestamp(time.time(), dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d")

print("[실제 날짜 (서버 시계 · KST)]")
c = service.calendar_for("진주")
ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["today"]) is not None, "today 형식 YYYY-MM-DD: " + c["today"])
ok(c["today"] == kst_today, f"today = 한국 시간 실제 날짜 ({kst_today})")

print("[정산 → 캘린더 표시]")
before = len(c["events"])
rec = service.propose(group_name=f"캘린더 테스트 {run}", members=["진주", "진우"], shares=[["진주", 3000], ["진우", 3000]],
                      total=6000, payer="진주")
c = service.calendar_for("진주")
ev = next((e for e in c["events"] if e["sid"] == rec["id"]), None)
ok(len(c["events"]) == before + 1 and ev is not None, "정산하면 캘린더에 1건 추가")
ok(ev["date"] == kst_today, "정산 날짜 = 오늘 (KST): " + ev["date"])
ok(ev["myShare"] == 3000 and ev["total"] == 6000 and ev["payer"] == "진주", f"내 몫·총액·받는 사람: {ev['myShare']}/{ev['total']}/{ev['payer']}")
ok(ev["status"] in ("open", "locked"), "상태 포함: " + ev["status"])

c2 = service.calendar_for("진우")
ev2 = next((e for e in c2["events"] if e["sid"] == rec["id"]), None)
ok(ev2 is not None and ev2["myShare"] == 3000, "참여자(진우) 캘린더에도 같은 정산 · 진우 몫 3,000")
c3 = service.calendar_for("김구경꾼")
ok(all(e["sid"] != rec["id"] for e in c3["events"]), "참여하지 않은 사람 캘린더에는 안 보임")

print("[완료된 정산]")
service.mock_lock(rec["id"], "진우")
rec2 = service.get_settlement(rec["id"])
if rec2["status"] == "locked":
    service.mock_fast_forward(rec["id"])
c = service.calendar_for("진주")
ev = next(e for e in c["events"] if e["sid"] == rec["id"])
ok(ev["status"] == "paid" and ev["paidDate"] == kst_today, f"완료 상태·지급 날짜 반영: {ev['status']} / {ev['paidDate']}")

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
