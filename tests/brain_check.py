"""Pie 두뇌(agent/pie_brain → agent/brain.py) 검사 — 가이드라인 순서·한도대로 프롬프트가 조립돼 실제 Kiln 요청에 들어가는지.
실행: DATA_DIR=/tmp/sp-brain CHAIN_MODE=mock LLM_MODE=live KILN_API_KEY=x python tests/brain_check.py
(Kiln 호출은 가로채서 보낸 본문만 확인 — 네트워크 없음)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import assistant, brain, llm, service, usage  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


print("[두뇌 파일]")
st = brain.stats()
ok(brain.ready() and st["persona_chars"] <= 1200 and st["modes"] == ["chat", "group"] and st["chunks"] >= 30 and st["examples"] >= 62,
   f"persona {st['persona_chars']}자 · 모드 {st['modes']} · 지식 {st['chunks']}조각 · 예시 {st['examples']}개")

print("[이번 메시지 유형(태그) — 예시를 고르는 기준]")
CASES = [("삼겹살 38,900원 넷이 똑같이 나눠줘", "chat", False, "settle"), ("총 5만원인데 진주는 조금 더 내게 해줘", "chat", False, "settle_ask"),
         ("아 총액 32만원이었어", "chat", True, "settle_change"), ("누가 아직 안 냈어?", "group", False, "status"),
         ("확인했는데 정산이 안 시작돼", "group", False, "pending"), ("월말이라 거지다 넷이 치킨 시키자 6만원 안에서", "chat", False, "shop"),
         ("이의제기 언제까지 할 수 있어?", "chat", False, "dispute"), ("충전 어디서 해?", "chat", False, "howto"),
         ("파이야", "group", False, "name_call"), ("마약 판 돈 셋이 나눠줘", "chat", False, "refuse"),
         ("심심한데 끝말잇기 하자", "chat", False, "offtopic"), ("진우: 8만원 넷이 똑같이 나누는데 1인 1만5천원 넘으면 안 돼", "group", False, "settle")]
bad = [(t, want, brain.tags_for(t, ch, h)) for t, ch, h, want in CASES if brain.tags_for(t, ch, h)[0] != want]
ok(not bad, f"태그 {len(CASES) - len(bad)}/{len(CASES)}" + (f" — 틀림: {bad}" if bad else ""))

print("[④ 관련 지식 — 사실 질문만, 최대 2조각 · 800자]")
k = brain.knowledge_for("AI 요금제는 어떻게 돼?", tags=["howto"])
ok(k and k[0]["file"] == "ai_pay", f"요금제 질문 → {[c['file'] + '#' + c['title'] for c in k]}")
k = brain.knowledge_for("충전 어디서 해?", tags=["howto"])
ok(k and k[0]["title"].startswith("PIE 충전"), "충전 질문 → 제목에 '충전'이 있는 조각이 먼저")
ok(not brain.knowledge_for("삼겹살 38,900원 넷이 똑같이 나눠줘", tags=["settle"]), "정산 요청에는 지식 안 넣음 (토큰 절약)")
worst = max((sum(len(c["text"]) for c in brain.knowledge_for(t, tags=["howto"])) for t, *_ in CASES), default=0)
ok(worst <= brain.KNOW_MAX_CHARS, f"지식은 가장 많을 때도 {worst}자 ≤ 800자")

print("[⑤ 예시 대화 — 태그·채널 맞는 것 최대 3개 · 750자]")
ex = brain.examples_for(["status"], "group", seed="누가 아직 안 냈어?")
ok(1 <= len(ex) <= 3 and all("status" in e["tags"] and e["mode"] in ("both", "group") for e in ex), f"그룹 진행 상황 → {[e['id'] for e in ex]}")
ok(all(e["mode"] != "group" for e in brain.examples_for(["settle", "status"], "chat", seed="x")), "1:1에는 그룹 전용 예시가 안 들어감")
ok(max(sum(len(brain.render_example(e)) for e in brain.examples_for(brain.tags_for(t, ch, h), ch, seed=t)) for t, ch, h, _w in CASES) <= brain.EX_MAX_CHARS,
   "예시는 가장 많을 때도 750자 이하")

print("[조립 순서: persona → 모드 → 도구 규칙 → 상황 → 지식 → 예시]")
sysp, meta = assistant.build_system("이의제기 언제까지 할 수 있어?", [], user="진주", address=None, channel="group", room="멤버 진주·민재 · 총액 30,000원")
order = [sysp.find(x) for x in ("# 정체성", "그룹방의 한 멤버다", "[도구 쓰는 법", "[상황 정보]", "[방 정보]", "[관련 지식", "[예시 대화")]
ok(all(i >= 0 for i in order) and order == sorted(order), f"그룹 프롬프트 {meta['chars']:,}자 · 순서 맞음")
ok("[그룹 채팅방 모드]" not in sysp and "1:1 대화다" not in sysp, "그룹 규칙은 modes.md의 group만 (예전 GROUP_PIE_SYSTEM·chat 규칙 없음)")
c_sys, c_meta = assistant.build_system("AI 요금제는 어떻게 돼?", [], user="진주", address=None)
ok("1:1 대화다" in c_sys and "그룹방의 한 멤버다" not in c_sys and c_meta["knowledge"], "1:1 프롬프트: chat 규칙 + 요금제 지식")

print("[실제 Kiln 요청에 그대로 들어가는지 (호출 가로채기)]")
sent = []


def fake_post(self, stage, flow, payload, mode="text"):
    sent.append(payload)
    row = usage.record(stage, flow=flow, prompt_tokens=300, completion_tokens=40, latency_ms=100, mode=mode, model="qwen3-32b")
    return {"choices": [{"message": {"role": "assistant", "content": "MY 탭 'AI 요금제'에서 바꿀 수 있어요."}}]}, llm._meta(row)


llm.KilnClient._post = fake_post
metas = []
with usage.tagged(turn="t_0000000001") as tg:
    r = assistant.run("AI 요금제는 어떻게 돼?", [], user="진주", flow="f-brain", metas=metas)
body = sent[-1]["messages"][0]["content"]
ok("너는 Share Pie의 공동정산 도우미 Pie다" in body and "## AI 요금제는 어떻게 돼 있어요?" in body, "보낸 system 메시지 = persona + 요금제 지식")
ok(tg.get("brain", {}).get("knowledge") and tg["tokens"] == 340 and tg["calls"] == 1, "턴 기록: 어떤 지식이 들어갔는지 · 턴 토큰 합계")
rows = [x for x in usage.read_all() if x.get("flow") == "f-brain"]
ok(any(x["stage"] == "assistant.brain" and "지식 1조각" in x["note"] for x in rows), "0토큰 기록: 태그·지식·예시·프롬프트 글자 수")
ok(all(x.get("turn") == "t_0000000001" and x.get("version") for x in rows), "이 턴의 모든 기록에 turn·version")
brain_dir = brain.DIR
brain.DIR = Path("/nonexistent")
brain._cache["sig"] = None
legacy, lm = assistant.build_system("안녕", [], user=None, address=None)
ok(lm.get("legacy") and legacy.startswith("너는 Share Pie 앱의 AI 비서"), "두뇌 파일이 없으면 예전 프롬프트로 (서비스는 그대로)")
brain.DIR = brain_dir
brain._cache["sig"] = None

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
