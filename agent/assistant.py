"""Pie 대화형 에이전트 — 고정 질문 없이 모델이 스스로 도구를 골라 쓰고 답한다.

- 모델(Kiln)이 판단: 무엇을 찾을지, 어떤 조합을 짤지, 되물을지 가정할지
- 코드가 보장: 가격·합계·예산·인분 검증 (도구 안에서 계산, 모델은 숫자를 만들지 않음)
- 모든 LLM 호출은 assistant.step, 도구 실행은 assistant.tool (0 tokens) 로 기록
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from . import brain, usage, llm, money, shopping, websearch
from .textutil import to_int, won

MAX_STEPS = 6
DELIVERY_FEE = 3000  # 검색 메뉴의 배달비 가정 (판매처별 1회)
MENU_CACHE: dict[str, dict[str, dict[str, Any]]] = {}   # 채팅별로 찾은 메뉴 (id 유지)
NOT_MENU = re.compile(r"소스|시즈닝|키링|굿즈|쿠폰북|스티커|인형|밀키트|냉동|스틱|분말|캡슐|원두|믹스|티셔츠|케이스")
POPULAR = {
    "치킨": ["교촌 허니콤보", "BBQ 황금올리브", "BHC 뿌링클", "굽네 고추바사삭"],
    "피자": ["도미노 포테이토 L", "피자헛 슈퍼슈프림 L", "파파존스 수퍼파파스 L"],
    "햄버거": ["맘스터치 싸이버거 세트", "버거킹 와퍼 세트", "맥도날드 빅맥 세트"],
    "떡볶이": ["엽기떡볶이 오리지널", "신전떡볶이 세트"],
    "족발": ["가장맛있는족발 앞다리", "족발야시장 앞다리"],
    "보쌈": ["원할머니 보쌈"],
    "찜닭": ["봉추찜닭"],
    "커피": ["스타벅스 아메리카노", "메가커피 아메리카노"],
    "디저트": ["배스킨라빈스 패밀리", "설빙 인절미설빙"],
}

SYSTEM = """너는 Share Pie 앱의 AI 비서 'Pie'다. 친구들과 공동구매·배달 공동주문을 고르고 비용을 나누는 일을 돕는다.
ChatGPT처럼 자연스럽게 대화하되, 아래 원칙을 지킨다.
- 자금세탁·검은돈·마약·불법도박·보이스피싱·대포통장·뇌물·탈세 등 불법 목적의 정산·구매·분배는 도와주지 않는다. 한두 문장으로 정중히 거절하고 도구를 호출하지 않는다.
- 가격·상품·메뉴·가게·브랜드 같은 사실은 반드시 도구 결과만 근거로 말한다. 모르면 도구로 찾고, 그래도 없으면 모른다고 한다.
- 조건이 일부 빠졌거나 사용자가 '알아서'라고 하면 되묻지 말고 합리적으로 가정해 먼저 제안하고, 가정은 한 줄로 밝힌다.
  정말 진행할 수 없을 때만 한 가지를 짧게 묻는다. 같은 질문을 반복하지 않는다.
- 배달 음식: 먼저 menu_price_search(food=음식 종류, 필요하면 brands)로 실제 브랜드 메뉴 가격을 찾는다.
  음식 종류마다 따로 부른다(치킨 한 번, 피자 한 번). 음식과 관계없는 상품(커피 스틱 등)은 절대 조합에 넣지 않는다. 검색이 안 되면 가격을 지어내지 말고 찾지 못했다고 말한 뒤, 가게에서 본 금액을 알려 주면 나눠 주겠다고 한다.
  찾은 메뉴 id로 인원·예산·취향에 맞는 서로 다른 조합 2~3개를 설계하고(검색 메뉴는 serves에 몇 인분인지 판단해 넣는다),
  반드시 check_delivery_combos로 검증한다(탈락하면 고쳐서 다시 검증). 통과한 조합만 도구가 준 금액 그대로 추천한다(검증해야 앱에 선택 카드가 뜬다).
  금액을 직접 더하지 마라.
- 가격이 어디서 왔는지 물으면 도구 이름을 말하지 말고 출처를 그대로 설명한다 (예: '카카오톡 선물하기에 올라온 교촌 허니콤보 판매가 23,000원').. 필요하면 바로 menu_price_search로 실제 가격을 찾아 준다.
- 답변에서 '도구'라는 말을 쓰지 마라. 사람처럼 자연스럽게 말한다.
- 상품·공동구매·가격 비교: search_products. 브랜드·후기·뜻·최신 소식 같은 일반 정보: web_search.
- 비용 나누기 계산: split_cost. 금액 계산을 머릿속으로 하지 말고 도구 숫자를 쓴다.
- 도구를 부를 때는 인자를 채워서 바로 부른다. 불필요한 도구 호출은 하지 않는다(토큰 절약).
- 답변은 한국어, 핵심 위주 3~6문장 또는 짧은 목록. 이모지·마크다운 기호(**, #, 표) 금지 — 앱은 일반 텍스트로 보여 준다. 추천 후보는 앱이 카드로 함께 보여 주니 숫자를 길게 반복하지 말고
  왜 그걸 추천하는지, 무엇을 가정했는지, 다음에 할 일(카드를 눌러 정산방 만들기 등)을 말한다."""

# 두뇌 파일(agent/pie_brain)을 쓰면 성격·원칙은 persona.md·modes.md에서 오고, 도구 절차만 코드에 남는다 (가이드라인 ①: 도구 이름·사용법은 persona에 쓰지 않음)
TOOL_RULES = """[도구 쓰는 법 — 앱 코드 규칙]
- 배달 음식: 먼저 menu_price_search(food=음식 종류, 필요하면 brands)로 실제 브랜드 메뉴 가격을 찾는다. 음식 종류마다 따로 부른다(치킨 한 번, 피자 한 번). 음식과 관계없는 상품(커피 스틱 등)은 조합에 넣지 않는다.
  검색이 안 되면 가격을 지어내지 말고 찾지 못했다고 말한 뒤, 가게에서 본 금액을 알려 주면 나눠 주겠다고 한다.
- 찾은 메뉴 id로 인원·예산·취향에 맞는 서로 다른 조합 2~3개를 설계하고(검색 메뉴는 serves에 몇 인분인지 넣는다), 반드시 check_delivery_combos로 검증한다(탈락하면 고쳐서 다시 검증). 통과한 조합만 도구가 준 금액 그대로 추천한다(검증해야 앱에 선택 카드가 뜬다).
- 가격 출처를 물으면 판매처와 판매가를 그대로 설명하고(예: '카카오톡 선물하기에 올라온 교촌 허니콤보 판매가 23,000원'), 필요하면 바로 menu_price_search로 실제 가격을 찾아 준다.
- 상품·공동구매·가격 비교: search_products. 브랜드·후기·뜻·최신 소식 같은 일반 정보: web_search. 비용 나누기 계산: split_cost (도구 숫자만 쓴다).
- 도구를 부를 때는 인자를 채워서 바로 부른다. 불필요한 도구 호출은 하지 않는다(토큰 절약)."""


def build_system(text: str, history: list[dict[str, Any]] | None, *, user: str | None, address: str | None,
                 channel: str = "chat", room: str | None = None, system_extra: str | None = None) -> tuple[str, dict[str, Any]]:
    """가이드라인 순서로 조립한 시스템 프롬프트와 기록용 요약. 두뇌 파일이 없으면 예전 SYSTEM(+system_extra)."""
    situation = [f"오늘: {dt.date.today().isoformat()}"] + ([f"지금 대화 상대: {user}"] if user else []) + \
        ([f"사용자 동네: {address} (‘우리 동네’, ‘근처’, 배달은 이 지역 기준으로 생각한다)"] if address else []) + \
        ([f"[방 정보]\n{room}"] if room else [])
    prompt, meta = brain.compose(channel, tool_rules=TOOL_RULES, situation=situation, text=text, has_history=bool(history))
    if prompt is None:
        legacy = SYSTEM + "\n" + "\n".join(situation[:3] if not room else situation[:-1]) + (("\n" + system_extra) if system_extra else "")
        return legacy, {"legacy": True, "chars": len(legacy)}
    if system_extra and channel != "group":        # 그룹 규칙·방 정보는 두뇌(modes.md의 group + 상황 정보)가 이미 넣음
        prompt += "\n\n" + system_extra
    return prompt, meta

TOOLS = [
    {"name": "search_products",
     "description": "여러 쇼핑 사이트(키가 있으면 구글쇼핑·네이버 등)와 Share Pie 공동구매에서 상품 가격을 찾아 최저가/가성비/대량/프리미엄 등 버전별 후보를 돌려준다. 예산·인원을 주면 예산 내 수량과 1인 비용도 계산한다.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "검색할 상품명 (예: 한정선 찹쌀떡)"},
         "must_include": {"type": "array", "items": {"type": "string"}, "description": "상품명에 꼭 들어가야 할 브랜드·고유명사"},
         "budget_total": {"type": "integer"}, "people": {"type": "integer"},
         "allowed_malls": {"type": "array", "items": {"type": "string"}, "description": "사용자가 판매처를 제한했을 때만 (예: 쿠팡)"}},
         "required": ["query"]}},
    {"name": "web_search",
     "description": "일반 웹 검색 (브랜드·가게·뜻·후기·최신 정보). 제목·요약·링크를 돌려준다.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "menu_price_search",
     "description": "실제 브랜드 배달 메뉴 가격(기프티콘·온라인 판매가)을 찾는다. food만 주면 인기 브랜드 대표 메뉴를 알아서 찾고, "
                    "brands로 원하는 브랜드를, queries로 '브랜드 메뉴명'을 직접 줄 수도 있다. 결과 id를 check_delivery_combos에 그대로 쓴다.",
     "parameters": {"type": "object", "properties": {
         "food": {"type": "string", "description": "음식 종류: 치킨, 피자, 햄버거, 떡볶이, 족발, 보쌈, 찜닭, 커피, 디저트 등"},
         "brands": {"type": "array", "items": {"type": "string"}, "description": "원하는 브랜드 (예: 교촌, BBQ). 사용자가 '다른 브랜드'라고 하면 앞과 다른 브랜드"},
         "queries": {"type": "array", "items": {"type": "string"}, "description": "직접 검색어 '브랜드 메뉴명' (선택)"}},
         "required": ["food"]}},
    {"name": "check_delivery_combos",
     "description": "설계한 배달 메뉴 조합을 코드가 검증한다: 없는 메뉴·예산 초과·인분 부족은 탈락. 통과한 조합의 합계·1인 비용·남는 예산을 돌려주고 앱에 카드로 표시한다.",
     "parameters": {"type": "object", "properties": {
         "people": {"type": "integer"}, "budget_total": {"type": ["integer", "null"]},
         "combos": {"type": "array", "items": {"type": "object", "properties": {
             "label": {"type": "string", "description": "조합 성격 (예: 균형, 가성비, 푸짐하게)"},
             "reason": {"type": "string"},
             "items": {"type": "array", "items": {"type": "object", "properties": {
                 "id": {"type": "string"}, "qty": {"type": "integer"},
                 "serves": {"type": "integer", "description": "검색 메뉴(m로 시작)일 때 1개가 몇 인분인지"}}, "required": ["id", "qty"]}}},
             "required": ["label", "items"]}}},
         "required": ["people", "combos"]}},
    {"name": "split_cost",
     "description": "총액을 사람별로 나눈다 (1원 단위, 합계=총액 보장). adjustments 예: {name, kind: less|more|fixed|exclude, value}",
     "parameters": {"type": "object", "properties": {
         "total": {"type": "integer"}, "members": {"type": "array", "items": {"type": "string"}},
         "adjustments": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string"}, "kind": {"type": "string", "enum": ["less", "more", "fixed", "exclude"]},
             "value": {"type": ["integer", "null"]}}, "required": ["name", "kind"]}}},
         "required": ["total", "members"]}},
]


class Session:
    """한 번의 사용자 메시지 처리 동안 도구 결과(카드)를 모은다."""

    def __init__(self, flow: str, metas: list[dict[str, Any]]):
        self.flow, self.metas = flow, metas
        self.card: tuple[str, dict[str, Any]] | None = None
        self.used: set[str] = set()
        self.menu: dict[str, dict[str, Any]] = dict(MENU_CACHE.get(flow, {}))   # 이 채팅에서 찾은 메뉴 (다음 턴에도 유지)

    def _log(self, name: str, note: str) -> None:
        self.metas.append(llm.code_step("assistant.tool", self.flow, f"0 tokens (code-only): {name} · {note}"))

    # ── 도구 ──
    def search_products(self, query: str, must_include=None, budget_total=None, people=None, allowed_malls=None, **_):
        q = {"product_query": query, "search_queries": [query], "must_include": must_include or [],
             "budget_total": budget_total, "people": people, "allowed_malls": allowed_malls or [], "category": "ANY",
             "keywords": [], "include_shipping": True}
        if websearch.any_enabled():
            got = websearch.gather([query], context_query=query)
            offers = shopping._relevant(got["offers"], q) + shopping._share_pie_offers(q)
            cands = shopping.pick_versions(offers, q, q["allowed_malls"]) if offers else []
            self._log("search_products", f"‘{query}’ 후보 {len(got['offers'])}개 → {len(cands)}개 · {got['stats']}")
            if cands:
                self.card = ("web", {"query": q, "candidates": cands, "web": got})
            return {"source": "web", "candidates": [
                {"version": shopping.VERSION_KO[c["version"]], "title": c["title"][:60], "mall": c["mall"], "price": c["price"],
                 "units_in_budget": c.get("units"), "total": c.get("total"), "per_person": c.get("per"),
                 "allowed_mall": c["trusted"], "price_verified": c["verified"]} for c in cands],
                "context": [x.get("title", "")[:60] for x in (got.get("context") or [])[:3]]}
        mq = shopping._merge_rules({"category": "ANY"}, query)
        q.update({k: mq.get(k) for k in ("category", "keywords")})
        cands = [c for c in shopping.search(q) if c["cat"] != "DELIVERY"]
        self._log("search_products", f"인터넷 검색 키 없음 → 후보 {len(cands)}개")
        if cands:
            self.card = ("catalog", {"query": q, "candidates": cands})
        return {"source": "none", "note": "인터넷 검색 키가 없어 상품 가격을 찾을 수 없다. 모른다고 말하고, 동네 이웃 공동구매는 공동구매 탭에서 볼 수 있다고 안내한다.",
                "candidates": [{"name": c["name"], "price": c["price"], "shipping": c["shipping"],
                                "total": c["eval"]["total"], "per_person": c["eval"]["per"] if people else None,
                                "within_budget": c["eval"]["within"]} for c in cands[:5]]}

    def web_search(self, query: str, **_):
        res = []
        try:
            if websearch.enabled_sources().get("serper"):
                res = websearch.serper_web(query)
            if not res and websearch.enabled_sources().get("tavily"):
                res = websearch.tavily(query)
        except Exception as e:  # noqa: BLE001
            self._log("web_search", f"실패 {type(e).__name__}")
            return {"error": "검색 실패"}
        self._log("web_search", f"‘{query}’ {len(res)}건")
        if not websearch.any_enabled():
            return {"error": "웹 검색 키가 없어 검색할 수 없다"}
        return {"results": [{"title": r.get("title", "")[:80], "snippet": (r.get("text") or r.get("content") or r.get("snippet") or "")[:220],
                             "url": r.get("url") or r.get("link")} for r in res[:5]]}

    def menu_price_search(self, food: str = "", brands=None, queries=None, **_):
        if not websearch.enabled_sources().get("serper") and not websearch.enabled_sources().get("naver"):
            return {"error": "웹 가격 검색 키가 없어 실제 메뉴 가격을 찾을 수 없다. 가격을 지어내지 말고, 가게에서 본 금액을 알려 주면 나눠 주겠다고 안내하라."}
        food = (food or "").strip()
        qs = [str(x).strip() for x in (queries or []) if str(x).strip()]
        for br in brands or []:                      # 브랜드만 주면 대표 메뉴로 보강
            hit = next((m for m in POPULAR.get(food, []) if m.split()[0].lower() == str(br).lower()), None)
            qs.append(hit or f"{br} {food}".strip())
        if not qs:
            qs = POPULAR.get(food, [])[:3] or ([f"{food} 기프티콘"] if food else [])
        qs = [q for q in dict.fromkeys(qs)][:4]
        out = []
        for q in qs:
            toks = [t for t in q.split() if len(t) >= 2][:2]
            try:
                rows = (websearch.serper_shop(q + " 기프티콘") if websearch.enabled_sources().get("serper")
                        else websearch.naver_shop(q))
            except Exception as e:  # noqa: BLE001
                self._log("menu_price_search", f"‘{q}’ 실패 {type(e).__name__}")
                continue
            norm = lambda t: t.lower().replace(" ", "")  # noqa: E731
            rows = [r for r in rows if r.get("price") and 3000 <= int(r["price"]) <= 150000
                    and all(norm(t) in norm(r["title"]) for t in toks) and not NOT_MENU.search(r["title"])]
            rows.sort(key=lambda r: r["price"])
            picked = rows[:1] + ([rows[len(rows) // 2]] if len(rows) > 2 else rows[1:2])   # 최저가 + 중간 가격
            for r in picked:
                mid = f"m{len(self.menu) + 1}"
                self.menu[mid] = {"name": r["title"][:40], "price": int(r["price"]), "mall": r.get("mall") or "", "url": r.get("url"),
                                  "query": q, "found": len(rows)}
                out.append({"id": mid, "name": r["title"][:50], "price": int(r["price"]), "seller": r.get("mall"),
                            "note": f"‘{q}’ 검색 {len(rows)}건 중 " + ("최저가" if r is picked[0] else "중간 가격")})
            self._log("menu_price_search", f"‘{q}’ {len(rows)}건")
        MENU_CACHE[self.flow] = self.menu
        if not out:
            return {"error": f"‘{', '.join(qs)}’ 가격을 찾지 못했다. 다른 브랜드로 다시 찾거나, 못 찾았다고 솔직하게 말하라 (가격을 지어내지 마라)."}
        return {"items": out, "delivery_fee_assumed": DELIVERY_FEE,
                "note": "기프티콘·온라인 판매가 기준. 배달앱 실제 가격·배달비는 가게마다 다를 수 있다. 조합에는 이 id를 그대로 써라."}

    def _resolve(self, iid: str) -> str | None:
        """id가 틀려도 이름으로 찾아 준다 (작은 모델이 id 대신 메뉴 이름을 쓰는 경우). 검색으로 찾은 메뉴만."""
        if iid in self.menu:
            return iid
        key = iid.replace(" ", "").lower()
        if len(key) >= 2:
            for mid, m in self.menu.items():
                n = m["name"].replace(" ", "").lower()
                if key in n or n in key:
                    return mid
        return None

    def _eval_mixed(self, items: list, people: int, budget: int | None) -> dict[str, Any] | None:
        merged: dict[str, dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            iid, qty = str(it.get("id") or it.get("name") or ""), to_int(it.get("qty"), 1) or 1
            if not 1 <= qty <= 10:
                continue
            iid = self._resolve(iid)
            if not iid:
                return None
            m = self.menu[iid]
            base = {"name": m["name"], "price": m["price"], "fee": DELIVERY_FEE, "serves": max(1, min(6, to_int(it.get("serves"), 2) or 2)),
                    "seller": m["mall"], "key": m["mall"] or iid, "url": m.get("url")}
            if iid in merged:
                merged[iid]["qty"] += qty
            else:
                merged[iid] = {**base, "qty": qty}
        if not merged:
            return None
        food = sum(v["price"] * v["qty"] for v in merged.values())
        fee = sum({v["key"]: v["fee"] for v in merged.values()}.values())   # 가게(판매처)별 배달비 1회
        serves = sum(v["serves"] * v["qty"] for v in merged.values())
        total = food + fee
        return {"items": merged, "food": food, "fee": fee, "total": total, "serves": serves,
                "per": -(-total // max(1, people)), "within": budget is None or total <= budget, "enough": serves >= people}

    def check_delivery_combos(self, people: int, combos: list, budget_total=None, **_):
        people = max(1, to_int(people, 1) or 1)
        budget_total = to_int(budget_total)
        budget_total = budget_total if budget_total and budget_total > 0 else None
        ok, bad, seen = [], [], set()
        for c in (combos if isinstance(combos, list) else [])[:5]:
            if not isinstance(c, dict):
                continue
            ev = self._eval_mixed(c.get("items") if isinstance(c.get("items"), list) else [], people, budget_total)
            if not ev:
                bad.append({"label": c.get("label"), "why": "찾은 적 없는 메뉴 id"})
                continue
            if not ev["within"]:
                bad.append({"label": c.get("label"), "why": f"예산 초과 (합계 {ev['total']}원)"})
                continue
            if not ev["enough"]:
                bad.append({"label": c.get("label"), "why": f"인분 부족 ({ev['serves']}인분 < {people}명)"})
                continue
            if ev["serves"] > max(people * 3, people + 6):
                bad.append({"label": c.get("label"), "why": f"양이 너무 많음 ({ev['serves']}인분)"})
                continue
            key = tuple(sorted((k, v["qty"]) for k, v in ev["items"].items()))
            if key in seen:
                continue
            seen.add(key)
            ok.append({**ev, "label": (c.get("label") or "추천")[:10], "reason": c.get("reason") or ""})
        self._log("check_delivery_combos", f"통과 {len(ok)} · 탈락 {len(bad)}")
        cands = [_mixed_public(c, i, budget_total) for i, c in enumerate(ok[:3])]
        if cands:
            self.card = ("combo", {"query": {"people": people, "budget_total": budget_total}, "candidates": cands,
                                   "budget": budget_total, "rejected": [b["label"] for b in bad]})
        return {"passed": [{"label": c["label"], "menu": c["title"], "servings": c["serves"], "food": c["food"],
                            "delivery_fee": c["fee"], "total": c["total"], "per_person": c["per"], "price_source": c["source"],
                            "left_budget": (budget_total - c["total"]) if budget_total else None} for c in cands],
                "rejected": bad}

    def split_cost(self, total: int, members: list, adjustments=None, **_):
        if isinstance(members, str):
            members = [m for m in re.split(r"[,\s·/]+", members) if m]
        members = [str(m).strip() for m in (members or []) if str(m).strip()]
        adjustments = [a for a in (adjustments or []) if isinstance(a, dict)]
        try:
            shares = money.compute_shares(to_int(total), [str(m) for m in members], adjustments or [])
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)[:200]}
        self._log("split_cost", f"{len(shares)}명 · 합계 {sum(a for _, a in shares)}")
        return {"shares": [{"name": n, "amount": a} for n, a in shares], "sum": sum(a for _, a in shares)}

    def run_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, name, None) if name in {t["name"] for t in TOOLS} else None
        if not fn:
            return {"error": f"없는 도구: {name}"}
        self.used.add(name)
        try:
            return fn(**(args if isinstance(args, dict) else {}))
        except Exception as e:  # noqa: BLE001 — 도구 오류는 모델에게 돌려줘 스스로 고치게 (서버 500 방지)
            self._log(name, f"오류 {type(e).__name__}: {e}"[:120])
            return {"error": f"인자 또는 처리 오류: {type(e).__name__}: {e}"[:200]}


def _mixed_public(c: dict[str, Any], idx: int, budget: int | None) -> dict[str, Any]:
    items = c["items"]
    parts = [v["name"] + (f" ×{v['qty']}" if v["qty"] > 1 else "") for v in items.values()]
    sellers = sorted({v["seller"] for v in items.values() if v.get("seller")})
    return {"id": f"combo{idx}-" + "-".join(f"{k}x{v['qty']}" for k, v in items.items()), "title": " + ".join(parts),
            "label": c["label"], "reason": c.get("reason", ""), "source": ", ".join(sellers) or "검색 가격",
            **{k: c[k] for k in ("food", "fee", "total", "serves", "per", "within")}, "by": "ai",
            "urls": [v.get("url") for v in items.values() if v.get("url")]}


def _history_messages(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for h in (history or [])[-8:]:
        t = (h.get("text") or "").strip()
        if not t:
            continue
        out.append({"role": "user" if h.get("role") == "user" else "assistant", "content": t[:400]})
    return out


def run(text: str, history: list[dict[str, Any]], *, user: str | None, flow: str,
        metas: list[dict[str, Any]], address: str | None = None, system_extra: str | None = None,
        channel: str = "chat", room: str | None = None) -> dict[str, Any]:
    """반환 {text, card(kind, data)|None}. LLM을 못 쓰면 LLMError."""
    sess = Session(flow, metas)
    sys, bmeta = build_system(text, history, user=user, address=address, channel=channel, room=room, system_extra=system_extra)
    tg = usage.TAGS.get()
    if tg is not None:
        tg["brain"] = bmeta                          # 베타 기록: 어떤 지식·예시가 들어갔는지
    llm.code_step("assistant.brain", flow, "0 tokens (code-only): " + (
        "예전 프롬프트 (pie_brain 없음)" if bmeta.get("legacy") else
        f"{bmeta['channel']} · 태그 {','.join(bmeta['tags'])} · 지식 {len(bmeta['knowledge'])}조각({bmeta['knowledge_chars']}자) · "
        f"예시 {','.join(bmeta['examples']) or '없음'}({bmeta['example_chars']}자) · 프롬프트 {bmeta['chars']:,}자"))
    messages: list[dict[str, Any]] = [{"role": "system", "content": sys}] + _history_messages(history) + \
        [{"role": "user", "content": text}]
    guards = 0
    for step in range(MAX_STEPS):
        tools = TOOLS if step < MAX_STEPS - 1 else []
        if tools:
            force = "check_delivery_combos" if (messages[-1]["role"] == "user" and messages[-1]["content"].startswith("[앱]")) else None
            try:
                msg, meta = llm.client.agent_step("assistant.step", messages, tools, flow=flow, max_tokens=2000, force=force)
            except llm.LLMError as e:
                if not force or e.code not in ("LLM_BAD_REQUEST", "FORCE_REJECTED", "TOOLS_UNSUPPORTED"):
                    raise
                msg, meta = llm.client.agent_step("assistant.step", messages, tools, flow=flow, max_tokens=2000)
        else:
            content, meta = llm.client.call_text("assistant.step", messages[0]["content"],
                                                 _flatten(messages[1:]), mock=lambda: "", flow=flow, max_tokens=900)
            msg = {"content": content, "tool_calls": []}
        metas.append(meta)
        if meta.get("mode") == "fallback":
            raise llm.LLMError("LLM_UNAVAILABLE", "agent step fallback")
        # 심사 기준 '응답이 행동에 반영되는 방식' — Kiln 응답이 고른 다음 행동을 0토큰 기록으로 남긴다
        llm.decision("assistant.step", flow, ("Kiln 응답 → 도구 호출: " + ", ".join(c["name"] for c in msg["tool_calls"]))
                     if msg["tool_calls"] else f"Kiln 응답 → 최종 답변 ({len(msg.get('content') or '')}자)")
        if not msg["tool_calls"]:
            wants_combo = bool(re.search(r"\d+\s*명|예산|만\s*원|\d[\d,]*\s*원|조합|구성|알아서|시킬|주문|배달|나눠", text)) or \
                bool(re.search(r"조합|×\s*\d|x\s*\d|총\s*금액|1인", msg["content"] or ""))
            if wants_combo and ("menu_price_search" in sess.used) and sess.card is None and guards < 2 \
                    and step < MAX_STEPS - 2:
                # 가드: 메뉴를 보고 조합을 말했는데 검증을 안 했거나 전부 탈락이면 → 검증 도구를 강제 호출 (카드·숫자 보장)
                guards += 1
                llm.decision("assistant.step", flow, "코드 가드: 검증 안 된 조합 답변 → check_delivery_combos 강제 (숫자는 도구 결과만)")
                messages.append({"role": "assistant", "content": msg["content"]})
                messages.append({"role": "user", "content": "[앱] " + (
                    "방금 말한 조합들을 check_delivery_combos로 검증해 줘. 검증을 통과해야 선택 카드가 표시되고, 금액은 도구 결과로 다시 말해야 해."
                    if "check_delivery_combos" not in sess.used else
                    "검증을 통과한 조합이 없어. 탈락 이유(인분 부족·예산 초과)를 보고 수량을 고쳐 check_delivery_combos로 다시 검증해 줘.")})
                continue
            return {"text": clean(msg["content"]) or "조금 더 자세히 말해 주시면 찾아볼게요.", "card": sess.card}
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"], ensure_ascii=False)}}
            for c in msg["tool_calls"]]})
        for c in msg["tool_calls"]:
            result = sess.run_tool(c["name"], c["args"])
            messages.append({"role": "tool", "tool_call_id": c["id"], "name": c["name"],
                             "content": json.dumps(result, ensure_ascii=False)[:2500]})
    return {"text": clean(messages[-1].get("content") or "") if messages[-1]["role"] == "assistant" and messages[-1].get("content") and not messages[-1].get("tool_calls") else "여기까지 찾아봤어요. 조건을 조금 더 알려주시면 이어서 볼게요.", "card": sess.card}


def clean(text: str) -> str:
    """앱은 마크다운을 렌더링하지 않으므로 기호 제거."""
    import re
    t = llm.strip_think(text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?m)^#{1,6}\s*", "", t)
    t = re.sub(r"(?m)^\s*[-*]\s+", "· ", t)
    t = t.replace("`", "")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _flatten(msgs: list[dict[str, Any]]) -> str:
    lines = []
    for m in msgs:
        if m["role"] == "tool":
            lines.append(f"[도구 결과 {m.get('name')}] {m['content']}")
        elif m.get("tool_calls"):
            lines.append("[Pie가 도구 호출] " + ", ".join(c["function"]["name"] for c in m["tool_calls"]))
        else:
            lines.append(f"{'사용자' if m['role'] == 'user' else 'Pie'}: {m.get('content') or ''}")
    return "\n".join(lines) + "\n\n위 도구 결과를 바탕으로 사용자에게 최종 답변만 써라."
