"""분담표 승인(정산 대상 전원 동의 → 온체인 정산 시작) 백엔드 검사.
실행: DATA_DIR=/tmp/sp-split LLM_MODE=mock CHAIN_MODE=mock KILN_API_KEY= python tests/split_approval_check.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import service, store  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


def err(fn, code):
    try:
        fn()
    except service.ServiceError as e:
        return e.code == code, e.code
    return False, "no error"


run = uuid.uuid4().hex[:4]
people = {"진주": "김진주", "진우": "박진우", "민재": "이민재", "지현": "최지현"}
for short, full in people.items():
    try:
        service.signup(full, f"{short}.{run}@split.test", "pw123456")
    except service.ServiceError:
        pass
    service.register_member(short, None)
    service.charge(short)
S = {s: (store.user_by_short(s) or {}).get("short", s) for s in people}   # 같은 이름이 이미 있으면 서버가 바꾼 이름
jin, woo, min_, hyun = S["진주"], S["진우"], S["민재"], S["지현"]


def room(members, name="분담표 테스트"):
    gid = "gs" + uuid.uuid4().hex[:8]
    service.group_create(jin, {"id": gid, "name": name, "members": members})
    for m in members:
        if m != jin:
            service.group_join(m, gid)
    return gid


def kw(members, shares, payer, name="분담표 테스트"):
    return {"group_name": name, "members": members, "shares": [[n, a] for n, a in zip(members, shares)], "total": sum(shares),
            "payer": payer, "rule_text": "균등 분배", "purpose": f"{name} 분담금"}


print("[전원 승인 → 온체인 정산]")
gid = room([jin, woo, min_])
r = service.split_start(jin, gid, kw([jin, woo, min_], [5000, 5000, 5000], jin))
sa = r["room"]["splitApproval"]
ok(r["rec"] is None and sa["approved"] == [jin] and sa["targets"] == [jin, woo, min_], "요청 = 요청자만 승인 1/3, 아직 온체인 아님")
ok(not r["room"].get("sid") and any(m.get("kind") == "splitReq" for m in r["room"]["msgs"]), "방에 분담표 승인 카드 메시지")
ok(err(lambda: service.split_approve(hyun, gid), "FORBIDDEN")[0], "방 멤버가 아니면 승인 불가")
r = service.split_approve(woo, gid)
ok(r["rec"] is None and r["room"]["splitApproval"]["approved"] == [jin, woo], "진우 승인 → 2/3")
r2 = service.split_approve(woo, gid)
ok(r2["room"]["splitApproval"]["approved"] == [jin, woo], "같은 사람이 두 번 눌러도 한 번만 셈")
r = service.split_approve(min_, gid)
ok(r["rec"] and r["rec"]["status"] == "open" and r["room"]["sid"] == r["rec"]["id"] and not r["room"]["splitApproval"],
   "마지막 승인 → 서버가 온체인 정산 요청 (status=open)")
card = next(m for m in r["room"]["msgs"] if m.get("kind") == "splitReq")
ok(card["outcome"] == "started" and card["approved"] == [jin, woo, min_], "승인 카드: 전원 승인 기록 · 결과 started")
ok(err(lambda: service.split_approve(woo, gid), "NOT_FOUND")[0], "이미 시작된 뒤 승인 → NOT_FOUND")

print("[정산 대상만 승인]")
gid = room([jin, woo, min_, hyun])
r = service.split_start(woo, gid, kw([jin, woo, min_, hyun], [0, 6000, 6000, 0], jin))
ok(r["room"]["splitApproval"]["targets"] == [jin, woo, min_], "내 몫 0원인 지현은 대상 아님 · 받는 사람(진주)은 0원이어도 대상")
ok(err(lambda: service.split_approve(hyun, gid), "FORBIDDEN")[0], "정산 대상이 아니면 승인 불가 (내 몫 없음)")

print("[동의 안 함 · 요청 취소 · 나가기]")
r = service.split_reject(min_, gid, "금액이 이상해요")
card = next(m for m in r["room"]["msgs"] if m.get("kind") == "splitReq")
ok(not r["room"]["splitApproval"] and card["outcome"] == "rejected" and card["outcomeBy"] == min_ and r["room"]["status"] == "비용 입력 대기",
   "민재 거절 → 요청 취소 · 상태 조건 입력 대기")
ok(any("동의하지 않았어요" in (m.get("text") or "") for m in r["room"]["msgs"]), "거절 기록이 방에 남음")
service.split_start(jin, gid, kw([jin, woo, min_, hyun], [3000, 3000, 3000, 3000], jin))
r = service.split_start(jin, gid, kw([jin, woo, min_, hyun], [6000, 2000, 2000, 2000], jin))
cards = [m for m in r["room"]["msgs"] if m.get("kind") == "splitReq"]
ok(cards[-2]["outcome"] == "superseded" and not cards[-1].get("resolved"), "새 분담표로 다시 요청하면 예전 카드는 ‘새 요청으로 바뀜’")
r = service.split_reject(jin, gid, "요청 취소")
ok(not r["room"]["splitApproval"] and next(m for m in reversed(r["room"]["msgs"]) if m.get("kind") == "splitReq")["outcome"] == "cancelled",
   "요청한 사람이 취소")
service.split_start(jin, gid, kw([jin, woo, min_, hyun], [3000, 3000, 3000, 3000], jin))
service.group_leave(hyun, gid)
g = store.kv_get("groups", gid)
ok(not g.get("splitApproval") and hyun not in g["members"], "승인 대기 중 정산 대상이 나가면 요청 취소")

print("[입력 검사]")
gid = room([jin, woo])
ok(err(lambda: service.split_start(jin, gid, kw([jin, hyun], [1000, 1000], jin)), "BAD_REQUEST")[0], "방에 없는 사람이 들어간 분담표 거부")
ok(err(lambda: service.split_start(jin, gid, kw([jin, woo], [1000, 1000], hyun)), "BAD_REQUEST")[0], "받는 사람이 참여자가 아니면 거부")
ok(err(lambda: service.split_start(jin, gid, {**kw([jin, woo], [1000, 1000], jin), "purpose": "자금세탁 수수료"}), "PROHIBITED_PURPOSE")[0],
   "불법 목적은 승인 요청 단계에서 거부")

print("[혼자 내는 정산은 바로 시작]")
gid = room([jin, woo])
r = service.split_start(jin, gid, kw([woo], [4000], woo))
ok(r["room"]["splitApproval"]["targets"] == [woo] and r["rec"] is None, "진우 혼자 내고 받는 정산 · 진주가 요청 → 대상 진우 1명, 진주는 승인할 필요 없음")
r = service.split_start(woo, gid, kw([woo], [4000], woo))
ok(r["rec"] is not None and r["rec"]["status"] in ("open", "locked") and not r["room"]["splitApproval"], "대상 본인이 요청하면 승인 1/1 → 바로 온체인 정산 요청")

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
