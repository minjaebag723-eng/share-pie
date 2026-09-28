"""AI Shopping Agent (선택 모듈) — 자연어 구매 조건 → (코드) 필터·예산 계산 → 후보 비교 설명.

LLM 호출: 조건 해석 1회(shopping.search) + 비교 설명 1회(shopping.explain).
1인당 비용·예산 초과 여부·팩 수는 전부 코드가 계산 (CLAUDE.md 0-2, 0-6 원칙).
카탈로그에 맞는 상품이 없으면 억지로 다른 상품을 보여주지 않고, 예산 계산 + 조언만 준다.
"""
from __future__ import annotations

import json
import math
import re
import threading
from pathlib import Path
from typing import Any

from . import config, llm, money, websearch
from .textutil import josa, parse_amounts, parse_people, to_int, won

# 예시 데이터 없음: 가짜 공동구매 상품·샘플 배달 메뉴표(catalog.json)를 모두 지웠다.
# - 상품 가격: 인터넷 검색(공식 API)으로 찾은 실제 판매가만 쓴다 (web_run)
# - 배달 메뉴: AI 비서가 실제 브랜드 메뉴 가격을 검색해 조합한다 (assistant.menu_price_search)
# - 공동구매 탭: 실제 사용자가 GPS 근처에 올린 모집글만 (service.listings_nearby)
_lock = threading.Lock()


CATALOG: list[dict[str, Any]] = []   # 예시 상품 없음 (하위 호환용 빈 목록)
BY_ID = {p["id"]: p for p in CATALOG}
CATS = ["MEAT", "FRUIT", "FRESH", "DAIRY", "LIVING", "SNACK", "DELIVERY", "ANY"]
CAT_KO = {"MEAT": "고기", "FRUIT": "과일", "FRESH": "신선식품", "DAIRY": "유제품", "LIVING": "생활용품",
          "SNACK": "간식", "DELIVERY": "배달 메뉴", "ANY": "상품"}
NEED_G_PER_PERSON = {"MEAT": 300, "FRUIT": 500}  # 1인 적정량 가정 (README에 명시)

SYSTEM = """너는 공동구매·배달 공동주문 앱 Share Pie의 '구매 조건 해석기'다. 사용자의 말에서 조건만 구조화한다. 상품을 지어내지 마라.
- category: MEAT(정육) FRUIT(과일) FRESH(계란·채소·쌀) DAIRY(유제품) LIVING(생활용품) SNACK(간식·라면·커피)
  DELIVERY(배달 음식·야식·치킨·피자·족발·중식·분식·초밥 등 메뉴) ANY(분류 불가)
- people: 함께 사는/먹는 인원. budget_total(총예산) / budget_per_person(1인 예산)은 정수 원. '예산 15만원'→budget_total 150000.
- include_shipping: 기본 true (배송비·배달비 포함 비교).
- near_only: '우리 동네/학교 근처/직접 받을' 등 근거리 요청이면 true.
- keywords: 사용자가 말한 품목 단어(예: 치킨, 삼겹살). 친구 모임·파티·뒤풀이·자취방 식사면 '모임'도 넣는다.
- prefer / avoid: 'A보다 B'면 B를 prefer, A를 avoid.
- 이전 대화가 있으면 이어서 해석한다.
- product_query: 인터넷에서 검색할 핵심 상품명 (예: '한정선 찹쌀떡'). must_include: 제목에 꼭 들어가야 할 고유명사·브랜드 (예: ['한정선']).
- search_queries: 여러 버전을 찾기 위한 검색어 2~3개 (예: '한정선 찹쌀떡', '한정선 선물세트', '한정선 요거트 찹쌀떡 대용량'). 모르는 신상이면 이름 그대로 쓴다.
- allowed_malls: '쿠팡에서만', '편의점 말고'처럼 판매처 조건이 있으면 허용할 판매처 이름들.
- 인원(people)도 예산도 모르면 missing에 people, budget을 넣고 question에 짧은 한국어 질문. 예산만 있으면 검색을 진행한다."""

TOOL = {
    "name": "set_shopping_query",
    "description": "공동구매 검색 조건을 구조화한다",
    "parameters": {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": CATS},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "people": {"type": ["integer", "null"]},
            "budget_total": {"type": ["integer", "null"]},
            "budget_per_person": {"type": ["integer", "null"]},
            "include_shipping": {"type": "boolean"},
            "near_only": {"type": "boolean"},
            "prefer": {"type": "array", "items": {"type": "string"}},
            "avoid": {"type": "array", "items": {"type": "string"}},
            "product_query": {"type": ["string", "null"]},
            "must_include": {"type": "array", "items": {"type": "string"}},
            "search_queries": {"type": "array", "items": {"type": "string"}},
            "allowed_malls": {"type": "array", "items": {"type": "string"}},
            "missing": {"type": "array", "items": {"type": "string", "enum": ["people", "budget"]}},
            "question": {"type": ["string", "null"]},
        },
        "required": ["category", "missing"],
    },
}

EXPLAIN_SYSTEM = """너는 Share Pie의 공동구매 비교 도우미다. 주어진 표의 숫자만 사용해 한국어 3~4문장으로 설명한다.
AI 추천 상품을 먼저 이유와 함께 말하고, 나머지 상품은 어떤 사람에게 맞는지 한 문장씩. 숫자를 새로 계산하거나 지어내지 마라. 과장·이모지 금지."""

ADVICE_SYSTEM = """너는 Share Pie의 구매 도우미다. 사용자가 찾는 품목이 Share Pie 공동구매 목록에 없다.
주어진 예산 계산 결과(코드가 계산한 숫자)만 사용해, 어떤 종류를 고르면 좋을지 한국어 2~3문장으로 조언하라.
구체적인 가게 이름이나 가격을 지어내지 마라. 마지막에 '메뉴와 금액이 정해지면 정산방을 만들어 드릴게요'라고 안내하라."""

_CAT_WORDS = [
    ("DELIVERY", r"배달|쿠팡\s*이츠|배민|배달의\s*민족|요기요|땡겨요|메뉴|야식|치킨|피자|족발|보쌈|중식|짜장|짬뽕|탕수육|분식|떡볶이|초밥|마라|찜닭|햄버거|버거|곱창|시켜"),
    ("MEAT", r"고기|삼겹|목살|한우|소고기|돼지|닭가슴|오리|대패|항정|정육"),
    ("FRUIT", r"과일|딸기|귤|사과|포도|샤인|바나나|수박"),
    ("FRESH", r"계란|달걀|토마토|채소|쌀"),
    ("DAIRY", r"우유|요거트|치즈|유제품"),
    ("LIVING", r"휴지|화장지|세제|생수|생활"),
    ("SNACK", r"라면|과자|간식|커피"),
]
_KW = sorted({t for p in CATALOG for t in p["tags"] if t not in ("모임", "배달")}, key=len, reverse=True)


def pat_all() -> str:
    return "|".join(p for _, p in _CAT_WORDS)


def _merge_rules(q: dict[str, Any], text: str) -> dict[str, Any]:
    """AI가 놓친 값은 코드 규칙으로 보충 (분류·인원·예산). AI가 채운 값은 그대로 둔다."""
    q = dict(q or {})
    r = _mock_query(text)
    if q.get("category") in (None, "", "ANY") and r["category"] != "ANY":
        q["category"] = r["category"]
    if r["category"] == "DELIVERY" and re.search(r"배달|이츠|배민|요기요|땡겨요|시켜", text):
        q["category"] = "DELIVERY"  # 배달 앱 이름(쿠팡이츠)을 쇼핑몰(쿠팡)로 오해하지 않도록
        q["product_query"], q["search_queries"], q["allowed_malls"], q["must_include"] = None, [], [], []
    for k in ("people", "budget_total", "budget_per_person"):
        if not q.get(k) and r.get(k):
            q[k] = r[k]
    for k in ("keywords", "prefer", "avoid"):
        q[k] = list(dict.fromkeys((q.get(k) or []) + (r.get(k) or [])))
    if q.get("category") in (None, "", "ANY") and re.search(r"뭐\s*먹|뭘\s*먹|먹을까|먹지|먹자|식사|저녁|점심|회식", text):
        q["category"] = "DELIVERY"
    if q.get("category") != "DELIVERY":
        for k in ("product_query", "must_include", "search_queries", "allowed_malls"):
            if not q.get(k) and r.get(k):
                q[k] = r[k]
    q.setdefault("include_shipping", True)
    for k in ("people", "budget_total", "budget_per_person"):   # LLM이 "4명"·"15만원" 같은 문자열을 줘도 정수로
        v = to_int(q.get(k))
        q[k] = v if v and v > 0 else None
    for k in ("keywords", "prefer", "avoid", "must_include", "search_queries", "allowed_malls"):
        v = q.get(k)
        q[k] = [str(x) for x in (v if isinstance(v, list) else ([v] if v else []))]
    if q.get("product_query") is not None and not isinstance(q.get("product_query"), str):
        q["product_query"] = str(q["product_query"])
    return q


def _mock_query(text: str) -> dict[str, Any]:
    cat = next((c for c, pat in _CAT_WORDS if re.search(pat, text)), "ANY")
    people = parse_people(text)
    q: dict[str, Any] = {"category": cat, "keywords": [], "people": people, "budget_total": None,
                         "budget_per_person": None, "include_shipping": True,
                         "near_only": bool(re.search(r"동네|근처|직접\s*받|픽업|가까", text)),
                         "prefer": [], "avoid": [], "missing": [], "question": None}
    m = re.search(r"(1인|인당|한\s*명당|한\s*사람당)\s*([^,.]*?원|만\s*원)", text)
    if m:
        a = parse_amounts(m.group(0))
        q["budget_per_person"] = a[0] if a else None
    amts = [a for a in parse_amounts(text) if a != q["budget_per_person"]]
    if amts:
        q["budget_total"] = max(amts)
    pm = re.search(r"(\S+?)보다는?\s*(\S+?)(이|가)?\s*(많|좋|낫)", text)
    if pm:
        q["avoid"].append(pm.group(1)); q["prefer"].append(pm.group(2))
    if re.search(r"친구|자취|뒤풀이|파티|모임|MT|축제", text):
        q["keywords"].append("모임")
    for kw in _KW:
        if kw in text and kw not in q["prefer"] and kw not in q["avoid"] and kw not in q["keywords"]:
            q["keywords"].append(kw)
    stop = re.compile(r"^(예산|공동구매|공구|추천|추천해줘|추천해|찾아줘|찾아|정도|이내|이하|쯤|해줘|알려줘|비교|비교해줘|좀|싸게|저렴하게|"
                      r"인당|1인|한|명당|친구|친구들|친구들이랑|친구랑|우리|같이|함께|나눠|나눠먹을|먹을|거|것|사고|싶어|싶은데|살래|사려고|"
                      r"뭐|뭘|먹지|먹을까|먹자|시킬까|시킬건데|시키려고|만원|천원|원|만|천|에서|말고|배송비|포함|총|명이서|명이|명|알아서|아무거나|상관없어|상관없음|몰라|모름|그냥|대충|네|응|ㅇㅇ|괜찮아)$")
    malls = re.compile(r"^(쿠팡|네이버|11번가|G마켓|SSG|컬리|GS25|CU|이마트)(에서)?(만|말고)?$")
    toks = []
    for t in re.split(r"\s+", re.sub(r"[?!.,~/]", " ", text)):
        t = re.sub(r"(이야|야|요|임|입니다|이요)$", "", t) if len(t) > 2 else t
        if not t or re.search(r"\d", t) or stop.match(t) or malls.match(t):
            continue
        toks.append(re.sub(r"(이랑|랑|으로|로|을|를|이|가|은|는|도)$", "", t) if len(t) > 3 else t)
    core = " ".join(toks[:4]).strip()
    q["product_query"] = core or None
    first = core.split(" ")[0] if core else ""
    q["must_include"] = [first] if first and not re.search(pat_all(), first) else []
    q["search_queries"] = [core, f"{core} 세트", f"{core} 대용량"] if core else []
    mall = re.findall(r"(쿠팡|네이버|11번가|G마켓|SSG|컬리|GS25|CU|이마트)(?:에서)?\s*만", text)
    q["allowed_malls"] = mall
    if not people and not q["near_only"] and not (q["budget_total"] or q["budget_per_person"]):
        q["missing"].append("people")
        if not (q["budget_total"] or q["budget_per_person"]):
            q["missing"].append("budget")
        q["question"] = "몇 명이 함께하시나요?" + (" 그리고 전체 예산은 어느 정도인가요?" if "budget" in q["missing"] else "")
    return q


# ───────── 코드 계산 (Stage 2 성격: 토큰 0) ─────────
def budget_per_person(q: dict[str, Any]) -> int | None:
    people = q.get("people") or 0
    if q.get("budget_per_person"):
        return int(q["budget_per_person"])
    if q.get("budget_total") and people:
        return q["budget_total"] // people
    return None


def evaluate(p: dict[str, Any], q: dict[str, Any]) -> dict[str, Any]:
    people = max(1, q.get("people") or 1)
    need = NEED_G_PER_PERSON.get(p["cat"])
    if p.get("serves"):
        packs = max(1, math.ceil(people / p["serves"]))
    elif need and p.get("qty_g"):
        packs = max(1, math.ceil(people * need / p["qty_g"]))
    else:
        packs = 1
    ship = p["shipping"] if q.get("include_shipping", True) else 0
    total = p["price"] * packs + ship
    per = math.ceil(total / people)
    bpp = budget_per_person(q)
    if q.get("budget_total"):   # 총예산이 있으면 총액으로 비교 (1인 나눗셈 반올림 때문에 딱 맞는 상품이 탈락하지 않게)
        within = total <= q["budget_total"]
    else:
        within = bpp is None or per <= bpp
    grams_pp = round(p["qty_g"] * packs / people) if p.get("qty_g") else None
    return {"packs": packs, "total": total, "per": per, "within": within, "grams_pp": grams_pp,
            "shipping": ship, "budget_per": bpp}


def _score(p, ev, q) -> float:
    s = 0.0 if ev["within"] else -10.0
    if ev["grams_pp"]:
        need = NEED_G_PER_PERSON.get(p["cat"], 400)
        s += min(ev["grams_pp"] / need, 1.25)          # 적정량까지는 넉넉할수록 가산
    if p.get("serves"):
        waste = ev["packs"] * p["serves"] - max(1, q.get("people") or 1)
        s += 0.9 if waste <= 1 else 0.4                 # 인원에 딱 맞는 구성일수록 (남는 인분이 적을수록)
    bpp = ev["budget_per"]
    if bpp:
        s += 0.25 * min(ev["per"] / bpp, 1.0)            # 예산 안에서는 약간만 가산 (싼 게 무조건 1등이 되지 않도록)
        s += 0.35 * (1.0 - min(ev["per"] / bpp, 1.0))    # 예산 대비 여유가 있을수록
    else:
        s += 1.0 - min(ev["per"] / 30000, 1.0)           # 예산이 없으면 저렴할수록
    s += 0.3 * (p["joined"] / p["cap"]) if p["cap"] else 0
    tags = set(p["tags"]) | {p["name"]}
    for w in q.get("prefer") or []:
        if any(w in t for t in tags):
            s += 0.6
    for w in q.get("avoid") or []:
        if any(w in t for t in tags):
            s -= 0.4
    for w in q.get("keywords") or []:
        if any(w in t for t in tags):
            s += 0.5
    return s


def search(q: dict[str, Any]) -> list[dict[str, Any]]:
    cat = q.get("category") or "ANY"
    items = [p for p in CATALOG if cat == "ANY" or p["cat"] == cat]
    kws = [k for k in (q.get("keywords") or []) + (q.get("prefer") or []) if k and k != "모임"]
    if kws:
        hit = [p for p in items if any(k in t or t in k for k in kws for t in p["tags"] + [p["name"]])]
        if hit and cat != "ANY" and len(hit) < 3:
            items = hit + [p for p in items if p not in hit]  # 같은 분류에서 대안을 채워 최소 3개
        elif hit:
            items = hit
        elif cat == "ANY":
            items = []  # 목록에 없는 품목 → 엉뚱한 상품을 보여주지 않는다
    elif cat == "ANY":
        items = []
    if q.get("near_only"):
        items = [p for p in items if p["distance_m"] is not None] or items
    ranked = []
    for p in items:
        ev = evaluate(p, q)
        ranked.append({**p, "eval": ev, "score": round(_score(p, ev, q), 3)})
    hit_ids = {p["id"] for p in items if kws and any(k in t or t in k for k in kws for t in p["tags"] + [p["name"]])}
    ranked.sort(key=lambda x: (x["id"] not in hit_ids, -x["score"]))
    return ranked[:3]


def _table(q, cands) -> str:
    cond = [f"{q.get('people') or '?'}명"]
    if q.get("budget_per_person"):
        cond.append(f"1인 {won(q['budget_per_person'])} 이하")
    if q.get("budget_total"):
        cond.append(f"총 {won(q['budget_total'])} 이하")
    if q.get("prefer"):
        cond.append("선호 " + ",".join(q["prefer"]))
    lines = ["조건: " + ", ".join(cond) + ", 배송비·배달비 포함"]
    for letter, c in zip("ABC", cands):
        e = c["eval"]
        lines.append(f"{letter} {c['name']} | {won(c['price'])}×{e['packs']} + 배송 {won(e['shipping'])} = {won(e['total'])} | "
                     f"1인 {won(e['per'])}" + (f" · 1인 {e['grams_pp']}g" if e["grams_pp"] else "") +
                     (f" · {c['serves']}인분 기준" if c.get("serves") else "") +
                     f" | {c['deadline']} | {'예산 이내' if e['within'] else '예산 초과'}")
    lines.append(f"AI 추천: {cands[0]['name']}")
    return "\n".join(lines)


def _mock_explain(q, cands) -> str:
    best = cands[0]; e = best["eval"]
    if not q.get("people"):
        s = [f"{josa(best['name'])} {best['where']}에서 받을 수 있고 {won(e['total'])}이라 가장 추천해요."]
    else:
        s = [f"{josa(best['name'])} {q['people']}명 기준 {e['packs']}개 · 총 {won(e['total'])}, 1인 약 {won(e['per'])}"
             + (f"(1인 {e['grams_pp']:,}g)" if e["grams_pp"] else "")
             + ("으로 예산 안에 들어와 추천해요." if e["within"] else "이에요.")]
    for c in cands[1:]:
        ce = c["eval"]
        if not ce["within"]:
            s.append(f"{josa(c['name'])} 1인 {won(ce['per'])}으로 예산을 넘어요.")
        elif c["deadline_days"] == 0 and c["cat"] != "DELIVERY":
            s.append(f"{josa(c['name'])} 마감이 오늘이라 빠르게 사려는 경우 볼 만해요.")
        else:
            s.append(f"{josa(c['name'])} " + (f"1인 {won(ce['per'])}으로 " if q.get("people") else "") + "대안이 될 수 있어요.")
    return " ".join(s)


def _advice_facts(q) -> str:
    bpp = budget_per_person(q)
    parts = [f"찾는 것: {', '.join(q.get('keywords') or []) or CAT_KO.get(q.get('category'), '상품')}"]
    if q.get("people"):
        parts.append(f"인원 {q['people']}명")
    if q.get("budget_total"):
        parts.append(f"총 예산 {won(q['budget_total'])}")
    if bpp:
        parts.append(f"1인 예산 {won(bpp)}")
    return " / ".join(parts)


def _mock_advice(q) -> str:
    bpp = budget_per_person(q)
    head = "찾으시는 상품의 실제 가격을 확인하지 못했어요."
    if not websearch.any_enabled():
        head += " (인터넷 상품 검색이 꺼져 있어요 — 서버 .env에 SERPAPI_API_KEY(또는 SERPER·네이버·Tavily 키)를 넣으면 여러 사이트에서 찾아 비교해 드려요.)"
    if bpp and q.get("people"):
        head += f" {q['people']}명 · 총 {won(q.get('budget_total') or bpp * q['people'])} 기준이면 1인 {won(bpp)}까지 쓸 수 있어요."
    return head + " 상품과 금액이 정해지면 “총 ○○원을 ○명이 나눠줘”라고 말해 주세요. 바로 정산방을 만들어 드릴게요."


def run(text: str, *, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    joined = " / ".join(h[:80] for h in (history or [])[-4:])
    user = (f"이전 대화: {joined}\n" if joined else "") + f"요청: {text}"
    q, m1 = llm.client.call_tool("shopping.search", SYSTEM, user, TOOL,
                                 mock=lambda: _mock_query((joined + " " + text).strip()), flow=flow, max_tokens=700)
    metas = [m1]
    q = _merge_rules(q, (joined + " " + text).strip())
    has_budget = q.get("budget_total") or q.get("budget_per_person")
    known = bool(q.get("product_query")) or q.get("category") not in (None, "ANY")
    delegated = bool(re.search(r"알아서|아무거나|상관없|몰라|그냥|대충", joined + " " + text))
    if not known and (delegated or has_budget or q.get("people")):
        q["category"], known = "ANY", True   # 품목을 맡기면 되묻지 않고 예산·인원 기준으로 전체에서 고른다
        q["keywords"] = list(dict.fromkeys((q.get("keywords") or []) + ["모임"]))
    if not known and not q.get("near_only"):
        return {"status": "need_info", "question": "어떤 상품이나 메뉴를 찾으시나요? 예: “한정선 찹쌀떡 20만원”, “4명 먹을 고기”", "query": q, "metas": metas}
    if not q.get("people") and not has_budget and not delegated and q.get("category") in ("MEAT", "FRUIT", "DELIVERY") and not q.get("product_query"):
        return {"status": "need_info", "question": q.get("question") or "몇 명이 함께하시나요? 그리고 전체 예산은 어느 정도인가요? (모르면 ‘알아서’라고 해 주세요)", "query": q, "metas": metas}
    if q.get("category") == "DELIVERY" and (q.get("budget_total") or q.get("budget_per_person")
                                            or re.search(r"구성|조합|알아서|여러|골고루|이것저것", joined + " " + text)):
        return delivery_combos(q, flow, metas)
    if websearch.any_enabled() and q.get("category") != "DELIVERY" and (q.get("product_query") or q.get("search_queries")):
        return web_run(q, flow, metas)

    cands = search(q)
    metas.append(llm.code_step("shopping.calculate", flow, f"code: {len(CATALOG)}개 중 {len(cands)}개 · 1인당 비용 계산"))
    if not cands:
        text_out, m2 = llm.client.call_text("shopping.explain", ADVICE_SYSTEM, _advice_facts(q),
                                            mock=lambda: _mock_advice(q), flow=flow, max_tokens=500)
        metas.append(m2)
        return {"status": "no_match", "query": q, "advice": text_out, "budget_per_person": budget_per_person(q), "metas": metas}
    text_out, m2 = llm.client.call_text("shopping.explain", EXPLAIN_SYSTEM, _table(q, cands),
                                        mock=lambda: _mock_explain(q, cands), flow=flow, max_tokens=700)
    metas.append(m2)
    return {"status": "ok", "query": q, "candidates": cands, "explain": text_out, "metas": metas}


def product_public(p: dict[str, Any]) -> dict[str, Any]:
    """프론트 this.P 형식과 동일한 필드."""
    keys = ("name", "cat", "price", "joined", "cap", "deadline", "where", "tint", "shipping", "merchant")
    out = {k: p.get(k) for k in keys}
    out["serves"] = p.get("serves")
    return out


# ═════════════ 인터넷 여러 사이트 검색 → 버전별 추천 ═════════════
VERSION_KO = {"cheapest": "최저가", "value": "가성비", "bulk": "대량 구매", "premium": "프리미엄",
              "sharepie": "Share Pie 공구", "alt": "대안"}
_SRC_KO = {"naver": "네이버쇼핑", "serper": "구글 쇼핑", "coupang": "쿠팡 API", "page": "상품 페이지", "web_text": "웹 본문", "share_pie": "Share Pie"}
_SRC_RANK = {"naver": 0, "serper": 0, "coupang": 0, "page": 1, "share_pie": 1, "web_text": 3}

WEB_EXPLAIN_SYSTEM = """너는 Share Pie의 구매 비교 도우미다. 여러 사이트에서 코드가 모아 계산한 표만 근거로 한국어 4~5문장으로 설명한다.
각 후보가 어떤 사람에게 맞는지(최저가/가성비/대량/프리미엄 등) 말하고, 가장 추천하는 하나를 이유와 함께 먼저 말한다.
표의 숫자를 그대로 인용하고 새로 계산하거나 지어내지 마라. '웹 본문' 가격은 판매 페이지에서 다시 확인하라고 말한다.
참고 문맥(뉴스·블로그)은 판매처·트렌드 설명에만 쓰고 가격 근거로 쓰지 마라. 이모지 금지."""


def _norm(s: str) -> str:
    return re.sub(r"[\s\[\]()·,_\-/]+", "", (s or "").lower())


def _relevant(offers, q):
    must = [_norm(m) for m in (q.get("must_include") or []) if m and len(_norm(m)) >= 2]
    core = [_norm(t) for t in re.split(r"\s+", q.get("product_query") or "") if len(_norm(t)) >= 2]
    avoid = [_norm(a) for a in (q.get("avoid") or []) if a]
    out = []
    for o in offers:
        t = _norm(o["title"])
        if any(a and a in t for a in avoid):
            continue
        if must and not all(m in t for m in must):
            continue
        if not must and core and not any(c in t for c in core):
            continue
        out.append(o)
    return out


def _share_pie_offers(q) -> list[dict[str, Any]]:
    words = [w for w in re.split(r"\s+", q.get("product_query") or "") if len(w) >= 2]
    out = []
    for p in CATALOG:
        if p["cat"] == "DELIVERY":
            continue
        if any(w in p["name"] or any(w in t for t in p["tags"]) for w in words):
            out.append({"id": p["id"], "title": p["name"], "price": p["price"] + (p.get("shipping") or 0), "mall": p["merchant"],
                        "url": None, "source": "share_pie", "verified": True, "qty": parse_qty_catalog(p)})
    return out


def parse_qty_catalog(p) -> int | None:
    return websearch.parse_qty(p["name"])


def _price_math(o, q) -> dict[str, Any]:
    people = q.get("people") or 0
    bpp = budget_per_person(q)
    B = q.get("budget_total") or (bpp * people if bpp and people else None) or bpp
    units = (B // o["price"]) if B else 1
    within = units >= 1
    units = max(units, 1)
    pieces = (o.get("qty") or 1) * units
    total = o["price"] * units
    per = math.ceil(total / people) if people else None
    ppp = o["price"] / (o.get("qty") or 1)
    if bpp and per and per > bpp and not q.get("budget_total"):
        within = False
    return {"units": units, "pieces": pieces, "total": total, "per": per, "ppp": ppp, "within": within, "budget": B}


def pick_versions(offers, q, allowed_malls: list[str]) -> list[dict[str, Any]]:
    """코드가 '성격이 다른' 후보를 고른다: 최저가 · 가성비(개당) · 대량 · 프리미엄 · Share Pie 공구."""
    rows = []
    for o in offers:
        m = _price_math(o, q)
        trusted = money.merchant_allowed(o["mall"], allowed_malls or config.ALLOWED_MERCHANTS)
        rows.append({**o, **m, "trusted": trusted})
    pool = [r for r in rows if r["within"] and r["trusted"]] or [r for r in rows if r["within"]] or rows
    pool.sort(key=lambda r: (_SRC_RANK.get(r["source"], 2), r["price"]))
    chosen, used = [], set()

    def take(ver, cands):
        for r in cands:
            if r["id"] not in used:
                used.add(r["id"]); chosen.append({**r, "version": ver}); return

    verified = [r for r in pool if r["verified"]] or pool
    take("cheapest", sorted(verified, key=lambda r: r["price"]))
    take("value", sorted([r for r in verified if r.get("qty")], key=lambda r: r["ppp"]))
    take("bulk", sorted(verified, key=lambda r: -r["pieces"]))
    take("premium", sorted(verified, key=lambda r: -r["price"]))
    take("sharepie", [r for r in pool if r["source"] == "share_pie"])
    rest = [r for r in rows if r["within"]] or rows  # 3개가 안 되면 허용 목록 밖(경고 표시)·웹 본문 가격까지 채운다
    for r in sorted(pool, key=lambda r: (_SRC_RANK.get(r["source"], 2), r["price"])) + \
             sorted(rest, key=lambda r: (_SRC_RANK.get(r["source"], 2), r["price"])):
        if len(chosen) >= 3:
            break
        take("alt", [r])
    return chosen[:5]


def _web_table(q, cands, context) -> str:
    cond = [f"찾는 것: {q.get('product_query')}"]
    if q.get("people"):
        cond.append(f"{q['people']}명")
    if q.get("budget_total"):
        cond.append(f"총 예산 {won(q['budget_total'])}")
    if budget_per_person(q):
        cond.append(f"1인 {won(budget_per_person(q))}")
    lines = [" / ".join(cond)]
    for i, c in enumerate(cands):
        lines.append(f"{'ABCDE'[i]} [{VERSION_KO[c['version']]}] {c['title'][:45]} | {c['mall']} | {won(c['price'])}"
                     + (f"({c['qty']}개입, 개당 {won(round(c['ppp']))})" if c.get("qty") else "")
                     + (f" | 예산으로 {c['units']}개 = {won(c['total'])}" if c.get("budget") else "")
                     + (f" | 1인 {won(c['per'])}" if c.get("per") else "")
                     + f" | 출처 {_SRC_KO.get(c['source'], c['source'])}{'' if c['verified'] else '(가격 확인 필요)'}"
                     + ("" if c["trusted"] else " | 허용 판매처 아님"))
    if context:
        lines.append("참고 문맥:")
        lines += [f"- {x['title'][:40]}: {x['text'][:90]}" for x in context[:3]]
    return "\n".join(lines)


def _mock_web_explain(q, cands) -> str:
    best = cands[0]
    s = [f"{VERSION_KO[best['version']]} 기준으로는 {best['mall']}의 {josa(best['title'][:30], '이/가')} {won(best['price'])}"
         + (f"이고, 예산으로 {best['units']}개({won(best['total'])})를 살 수 있어요." if best.get("budget") else "이에요.")]
    for c in cands[1:]:
        tag = VERSION_KO[c["version"]]
        extra = f" 개당 {won(round(c['ppp']))}" if c.get("qty") else ""
        s.append(f"{tag}: {c['mall']} {c['title'][:24]} {won(c['price'])}{extra}"
                 + ("" if c["verified"] else " (웹 본문 가격이라 판매 페이지에서 확인 필요)") + ".")
    if q.get("people") and best.get("per"):
        s.append(f"{q['people']}명이 나누면 1인 약 {won(best['per'])}이에요.")
    elif not q.get("people"):
        s.append("인원을 알려주시면 1인당 금액도 계산해 드릴게요.")
    return " ".join(s)


def web_run(q, flow, metas) -> dict[str, Any]:
    queries = (q.get("search_queries") or []) or [q.get("product_query")]
    got = websearch.gather(queries, context_query=q.get("product_query"))
    offers = _relevant(got["offers"], q) + _share_pie_offers(q)
    note = f"검색 {len(got['queries'])}개 · 후보 {len(got['offers'])}개 → 관련 {len(offers)}개 · 소스 {got['stats']}"
    metas.append(llm.code_step("shopping.web", flow, note + (f" · 오류 {got['errors']}" if got["errors"] else "")))
    if not offers:
        advice, m = llm.client.call_text("shopping.explain", ADVICE_SYSTEM, _advice_facts(q),
                                         mock=lambda: _mock_advice(q), flow=flow, max_tokens=500)
        metas.append(m)
        return {"status": "no_match", "query": q, "advice": "여러 사이트를 검색했지만 조건에 맞는 상품 가격을 찾지 못했어요. " + advice,
                "budget_per_person": budget_per_person(q), "metas": metas, "web": got}
    cands = pick_versions(offers, q, q.get("allowed_malls") or [])
    metas.append(llm.code_step("shopping.calculate", flow, f"0 tokens (code-only): 버전 {len(cands)}개 · 예산 내 수량·1인 비용"))
    text_out, m2 = llm.client.call_text("shopping.explain", WEB_EXPLAIN_SYSTEM, _web_table(q, cands, got["context"]),
                                        mock=lambda: _mock_web_explain(q, cands), flow=flow, max_tokens=900)
    metas.append(m2)
    return {"status": "ok_web", "query": q, "candidates": cands, "explain": text_out, "metas": metas, "web": got}


def web_product_public(c: dict[str, Any], allowed_malls: list[str] | None = None) -> dict[str, Any]:
    tints = {"naver": "#E7EFD9", "serper": "#E3F0F6", "coupang": "#FCE3D3", "page": "#E3E6F3", "web_text": "#F1E6D3", "share_pie": "#FDEBC8"}
    return {"name": c["title"], "cat": VERSION_KO[c["version"]], "price": c["price"], "joined": 0, "cap": 0,
            "deadline": c["mall"], "where": f"{c['mall']} · {_SRC_KO.get(c['source'], c['source'])}", "tint": tints.get(c["source"], "#F1E6D3"),
            "shipping": 0, "merchant": c["mall"], "url": c.get("url"), "isWeb": c["source"] != "share_pie",
            "verified": c["verified"], "qty": c.get("qty"), "trusted": c["trusted"], "source": c["source"],
            "units": c.get("units"), "total": c.get("total"), "allowedMalls": allowed_malls or []}


# ───────────── 배달 메뉴 조합 (AI가 구성 → 코드가 검증) ─────────────
def delivery_combos(q: dict[str, Any], flow, metas) -> dict[str, Any]:
    """규칙 기반(파이프라인) 흐름의 배달 요청: 예시 메뉴표를 쓰지 않으므로 지어내지 않고 솔직하게 안내한다.
    실제 메뉴 가격 조합은 AI 비서(Kiln + 웹 검색)가 menu_price_search → check_delivery_combos로 만든다."""
    people = q.get("people") or 0
    budget = q.get("budget_total") or ((q.get("budget_per_person") or 0) * people) or None
    metas.append(llm.code_step("shopping.calculate", flow, "0 tokens (code-only): 예시 메뉴 없음 → 조합 안 만듦"))
    why = ("실제 가게 메뉴 가격을 검색하려면 AI 연결(Kiln)과 웹 검색 키가 필요해요."
           if not websearch.any_enabled() else "지금은 AI 비서가 연결되지 않아 실제 메뉴를 찾아 조합할 수 없어요.")
    tip = (f" {people}명 · 총 {won(budget)}이면 1인 {won(-(-budget // people))}까지예요." if people and budget else "")
    return {"status": "no_match", "query": q, "metas": metas,
            "advice": f"배달 메뉴 조합은 가짜 예시 가격으로 만들지 않아요. {why}{tip} 가게와 금액이 정해지면 “총 ○○원을 ○명이 나눠줘”라고 말해 주세요."}


def combo_product_public(c: dict[str, Any]) -> dict[str, Any]:
    return {"name": c["title"], "cat": c["label"], "price": c["food"], "shipping": c["fee"], "joined": 0, "cap": 0,
            "deadline": "주문 즉시", "where": f"{c['serves']}인분 · 가격 출처: {c.get('source') or '검색 가격'}", "tint": "#FCE3D3",
            "merchant": "Share Pie 배달 공동주문", "url": None, "isWeb": True, "isCombo": True, "verified": True,
            "trusted": True, "source": "combo", "units": 1, "total": c["total"], "allowedMalls": [], "reason": c.get("reason", "")}
