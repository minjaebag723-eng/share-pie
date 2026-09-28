"""대화형 에이전트 경로 점검 (가짜 Kiln + 가짜 웹).
python -m uvicorn tests.fake_kiln:app --port 8011 & python -m uvicorn tests.fake_web:app --port 8012 &
LLM_MODE=live KILN_API_KEY=x KILN_BASE_URL=http://127.0.0.1:8011/v1 SERPER_API_KEY=x SERPER_API_BASE=http://127.0.0.1:8012/serper WEB_ALLOW_PRIVATE=1 python tests/agent_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import service  # noqa: E402

h, fails = [], []


def say(t):
    r = service.chat(t, history=h, chat_id="agent-check", user="민재")
    h.append({"role": "user", "text": t})
    for m in r["messages"]:
        h.append({"role": "bot", "text": m["text"], "intent": m.get("intent")})
    return r


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


r = say("쿠팡이츠에서 4명이고 예산은 20만원 메뉴구성은 알아서 해줘")
ok(r["messages"][0].get("compare") and all(x.startswith("combo") for x in r["messages"][0]["compare"]), "배달: AI 조합 → 코드 검증 카드")
ok("환각" in r["messages"][0]["text"], "없는 메뉴를 쓴 AI 조합은 탈락")
ok(not any("어떤 상품" in m["text"] for m in r["messages"]), "고정 질문 없음")
r = say("음식들 브랜드는 어디야")
ok(r["intent"] == "ask" and r["messages"][-1]["text"], "이어지는 질문에 답함")
r = say("한정선 공동구매 20만원")
ok(r["messages"][0].get("compare"), "상품 검색 카드")
r = say("총 12만원을 진주, 민재, 지현이 나눠줘")
ok(r["intent"] == "settle", "정산은 전용 흐름 유지 (분담표 카드)")
h.clear()
r = say("가족이 대가족이라서 12명이고 배달로 치킨 피자 넉넉하게, 예산 25만원")
ok(r["messages"][0].get("compare"), "AI가 검증을 건너뛰어도 가드가 검증을 강제 → 선택 카드 표시")
ok("**" not in r["messages"][-1]["text"], "마크다운 기호 제거")
h.clear()
r = say("교촌으로 4명 배달 6만원")
card = r["messages"][0]
ok(card.get("compare") and "카카오톡 선물하기" in card["text"], "실제 브랜드 가격 검색 → 출처 표시 카드: " + card.get("text", "")[:120].replace("\n", " "))
pid = card["compare"][0] if card.get("compare") else None
ok(pid and card["products"][pid]["total"] == 23000 * 2 + 3000, "검색 가격 × 수량 + 배달비를 코드가 계산 (49,000원)")
r = say("아까 그 치킨으로 6명 9만원")
card = r["messages"][0]
ok(card.get("compare") and "72,000" in card["text"], "다음 턴에도 찾은 메뉴 유지 + 이름으로 id 찾기 (23,000×3+3,000): " + card.get("text", "")[:90].replace("\n", " "))
print("✓ 전체 통과" if not fails else f"✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
