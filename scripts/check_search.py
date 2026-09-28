"""인터넷 상품 검색 키 확인: py scripts/check_search.py [검색어]"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, websearch  # noqa: E402

q = " ".join(sys.argv[1:]) or "한정선 찹쌀떡"
on = websearch.enabled_sources()
print("켜진 소스:", ", ".join(k for k, v in on.items() if v) or "없음 (.env 에 SERPER_API_KEY 확인)")
tests = [("serper 쇼핑", websearch.serper_shop), ("serper 웹", websearch.serper_web),
         ("naver 쇼핑", websearch.naver_shop), ("tavily", websearch.tavily)]
for label, fn in tests:
    if not on.get(label.split()[0]):
        continue
    try:
        rows = fn(q)
        print(f"✓ {label}: {len(rows)}건")
        for r in rows[:3]:
            print("   -", (r.get("title") or "")[:40], "|", r.get("mall") or r.get("source") or "", "|", r.get("price") or "")
    except Exception as e:  # noqa: BLE001
        print(f"✗ {label}: {type(e).__name__} {str(e)[:200]}")
