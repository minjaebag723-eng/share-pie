"""AI Settlement Agent — 자연어 분담 조건 이해 → (코드) 계산·검증 → 송금 목적 문구.

LLM 호출: 정산 1건당 1회 (조건 해석 + 송금 목적 문구를 한 번의 tool call로 같이 받음).
AI는 문장에 적힌 숫자를 옮기고 표현 유형만 고른다. 더하기·빼기·곱하기·나누기·퍼센트는 전부 코드가 한다
(Pie mate 학습 가이드라인 ⑥ 계산 조건 해석). 코드 안전망(_mock_rule)이 같은 유형을 규칙으로 읽어,
AI가 놓치거나 잘못 가른 금액·%를 바로잡는다 (0 tokens).
"""
from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from . import llm, money
from .textutil import amount_spans, josa, parse_people, to_int, to_num, won

SYSTEM = """너는 공동정산 앱 Share Pie의 '분담 조건 해석기'다. 계산은 절대 하지 않는다.
문장을 조건 조각으로 나누고, 조각마다 아래 유형 하나를 골라 set_split_rule에 옮긴다.
더하기·빼기·곱하기·나누기·퍼센트 계산은 전부 코드가 한다. 문장에 적힌 숫자만 그대로 옮긴다.

[금액]
- 총액 한 개 → total_amount
- 금액 여러 개를 더하거나 뺌("치킨 2만 + 피자 1.8만", "3만원에서 쿠폰 5천원 빼고")
  → amount_parts [20000,18000] / [30000,-5000]. 직접 더하지 마라.
- 한 사람당 금액("한 명당 만원씩") → per_person_amount. 인원수를 곱하지 마라.

[퍼센트 — %의 앞뒤 말로 가른다]
- 부가세·봉사료·팁·수수료 + "더해서/붙여서/별도" → base_amount=원금, total_pct=N, total_pct_type="add"
- "N% 할인/깎아서/쿠폰 N%" → base_amount=원금, total_pct=N, total_pct_type="discount"
- "A원의 N%", "N%만 나눠" → base_amount=A, total_pct=N, total_pct_type="portion"
- "부가세 포함 11만원"처럼 최종 금액이 적혀 있음 → total_amount=그 금액, %는 무시
- 이름 + N%, 더/덜 없음("진주 40%", "진주가 전체의 40%") → percent N
- 이름 + N% + 더/덜/많이/적게("진주는 20% 더") → more_pct N / less_pct N
- 어느 것인지 모르겠으면 되묻는다.

[사람별]
- "N원 덜/적게/감면" → less, "N원 더" → more, "N원만/N원 낼게" → fixed, "빼고/안 먹었어/안 갔어" → exclude
- 배수·비례: "두 배"→ratio 2, "절반"→ratio 0.5, "1.5배"→ratio 1.5,
  "3:2:1"→이름을 말한 순서대로 ratio 3,2,1, "3박 중 진주는 2박"→진주 ratio 2, 나머지 사람 ratio 3
- 본인 것만 따로("진주 음료 4,500원은 본인이") → more 4500
- 일부 사람만 나누는 항목("술값 2만원은 진주·민재만") → items [{"amount":20000,"members":["진주","민재"]}]
  항목 금액도 총액 안에 들어 있다. 총액이 따로 없으면 항목 금액까지 amount_parts에 넣는다.

[기타]
- 주문·결제·계산·카드 긁은 사람 → payer
- "1인 X원 넘으면 안 돼" → per_person_cap, "총 X원 안에서" → total_cap. 한도는 총액이 아니다.
- "천원 단위로" → round_unit 1000
- "n빵·반반·똑같이·나머지는 똑같이" → 조정 없음

[되묻기 — 추측하지 말고 missing=["vague"], question 한 개]
- 양이 모호함: "조금 더", "적당히", "많이 먹은 사람이 더"
- 조정된 사람을 다시 기준으로 삼음: "민재는 5천원 덜, 진주는 민재의 두 배"
- 비율의 주인이 없음: "3:2:1로 나눠"
- 원화가 아님: "50달러"
- 여러 사람이 따로 결제함: "진주가 3만원, 민재가 2만원 냈어" (결제자는 한 명만 가능)
- 총액·참여자를 모름 → missing에 total_amount / members

[숫자] 5천원=5000, 1.8만=18000, 3만5천원=35000, 1억 5천만원=150000000. 문장에 금액이 있으면 비우지 마라.
[그 밖] members=문장에 나온 참여자 이름(없으면 []), subject=정산 대상(모르면 null),
purpose=송금 목적 한 줄 40자 이내·개인정보 금지. 불법 목적의 돈이면 prohibited=true."""

_KIND_ENUM = ["less", "more", "fixed", "exclude", "ratio", "percent", "more_pct", "less_pct"]

TOOL = {
    "name": "set_split_rule",
    "description": "자연어 비용 분담 조건을 구조화한다 (숫자는 문장 그대로, 계산은 코드가 한다)",
    "parameters": {
        "type": "object",
        "properties": {
            "total_amount": {"type": ["integer", "null"], "description": "문장에 적힌 최종 총액 한 개"},
            "amount_parts": {"type": "array", "items": {"type": "integer"},
                             "description": "더하거나 빼는 금액 조각(빼는 금액은 음수). 직접 더하지 마라"},
            "per_person_amount": {"type": ["integer", "null"], "description": "한 사람당 금액. 인원수를 곱하지 마라"},
            "base_amount": {"type": ["integer", "null"], "description": "%가 붙는 원금"},
            "total_pct": {"type": ["number", "null"], "description": "총액에 붙는 % 숫자 그대로 (10% → 10)"},
            "total_pct_type": {"type": "string", "enum": ["add", "discount", "portion"],
                               "description": "add=더해서·붙여서·별도 / discount=할인·깎아서·쿠폰 / portion=A원의 N%·N%만"},
            "members": {"type": "array", "items": {"type": "string"}},
            "payer": {"type": ["string", "null"]},
            "adjustments": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"},
                "kind": {"type": "string", "enum": _KIND_ENUM},
                "value": {"type": "number"}}, "required": ["name", "kind", "value"]}},
            "items": {"type": "array", "description": "일부 사람만 나누는 항목", "items": {"type": "object", "properties": {
                "amount": {"type": "integer"}, "members": {"type": "array", "items": {"type": "string"}},
                "label": {"type": ["string", "null"]}}, "required": ["amount", "members"]}},
            "round_unit": {"type": ["integer", "null"], "description": "'천원 단위로' → 1000"},
            "per_person_cap": {"type": ["integer", "null"]},
            "total_cap": {"type": ["integer", "null"]},
            "purpose": {"type": "string"},
            "subject": {"type": ["string", "null"]},
            "prohibited": {"type": "boolean", "description": "자금세탁·마약·불법도박·사기 등 불법 목적의 돈이면 true"},
            "missing": {"type": "array", "items": {"type": "string", "enum": ["total_amount", "members", "vague"]}},
            "question": {"type": ["string", "null"]},
        },
        "required": ["adjustments", "purpose", "missing"],
    },
}

KNOWN_NAMES = ["진주", "진우", "민재", "지현", "서연", "도윤", "하린", "준호"]
KINDS = set(_KIND_ENUM)
ROUND_UNITS = {10, 50, 100, 500, 1000, 5000, 10000}

# ───────────── 코드 안전망: 규칙 기반 해석 (오프라인 · AI 보정 · 0 tokens) ─────────────
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_TOTAL_PCT_WORD = re.compile(r"부가세|부가가치세|봉사료|서비스\s*(?:차지|요금|비)|팁|수수료|세금|VAT|vat|이자")
_PCT_TOTAL_POST = re.compile(r"\s*(?:을|를|의)?\s*(?:할인|세일|쿠폰|포함|붙|별도|더해|더한|더하|가산|off|OFF|DC|디씨|수수료|부가세|봉사료|팁|이자)")
_LESS_POST = re.compile(r"\s*(?:정도|쯤|가량)?\s*(?:을|를|만큼|씩)?\s*(?:더\s*)?(?:덜|적게|낮게|깎|싸게|작게)")
_MORE_POST = re.compile(r"\s*(?:정도|쯤|가량)?\s*(?:을|를|만큼|씩)?\s*(?:더(?!치)|많이|추가로?|높게|얹)")
_ADD_POST = re.compile(r"\s*(?:을|를|만큼|씩)?\s*(?:더한|더해|더하|붙여|붙어|붙인|붙은|붙이|추가|가산|얹|플러스|포함해서|포함하면|포함시켜|올려|올린)")
_ADD_ANY = re.compile(r"더한|더해|더하|붙여|붙어|붙인|붙은|붙이|추가|가산|얹|플러스|포함해서|포함하면|포함시켜|별도")
_DISC_PRE = re.compile(r"(?:쿠폰|할인|세일|DC|디씨)\s*(?:으로|을|를|이|가)?\s*$")
_DISC_POST = re.compile(r"\s*(?:을|를|만큼)?\s*(?:할인|깎|세일|DC|디씨|dc|off|OFF|싸게|저렴)")
_PORTION = re.compile(r"수수료|세금|이자|떼|몫|팁")
_INC_STATE = re.compile(r"\s*(?:이야|임|이에요|예요|이고|이라|인|된|가격|금액|가|\)|$|[,.]|이니|이래|입니다)")

_PP_BEFORE = re.compile(r"(?:1\s*인당?|인당|한\s*명당|1\s*명당|한\s*사람당|각자|각각|한\s*명에)\s*(?:최대|최고|많아야)?\s*$")
_CAP_TOTAL_BEFORE = re.compile(r"(?:총|전체|총\s*예산|예산)\s*(?:은|는|이|가|:)?\s*(?:최대)?\s*$")
_CAP_AFTER = re.compile(r"\s*(?:원)?\s*(?:씩)?\s*(?:을|를|이|가|은|는)?\s*(?:안\s*)?(?:넘|초과|이하|까지|이내|한도|안에서|안으로|미만|내에서|내로)")
_PP_NOT_AFTER = re.compile(r"\s*(?:원)?\s*(?:씩)?\s*(?:을|를|만큼|정도)?\s*(?:더|덜|적게|많이|추가|넘|초과|이하|까지|이내|한도|미만|빼)")
_TOT_PRE = re.compile(r"(?:총|합계|전부|모두|다\s*합쳐서?|합쳐서|총액|전체|결제\s*금액|영수증)\s*(?:은|는|이|가|:|으로|로|해서)?\s*$")
_TOT_POST_STRONG = re.compile(r"\s*(?:원)?\s*(?:이|가|을|를)?\s*중(?:에|에서)?(?![가-힣])")          # '8만원 중'
_TOT_POST = re.compile(r"\s*(?:원)?\s*(?:이|가|을|를)?\s*(?:나왔|나옴|결제했|결제|계산했|들었|썼|냈|샀|긁었"      # '4만원 나왔어'
                       r"|으로\s*(?:깎|할인|줄|내렸|됐)|로\s*(?:깎|할인|줄|내렸|됐))")
_ADD_PRE = re.compile(r"(?:\+|추가로?|별도로?|따로)\s*(?:[가-힣]{1,6}\s*)?$")
_ADD_AFTER = re.compile(r"\s*(?:원)?\s*(?:은|는|을|를|이|가|도)?\s*(?:추가|더(?!치)|별도|따로|플러스)")
_ROUND = re.compile(r"(오백|오천|십|백|천|만|\d[\d,]*)\s*원?\s*(?:단위|자리)")
_ROUND_MAP = {"십": 10, "백": 100, "오백": 500, "천": 1000, "오천": 5000, "만": 10000}
_CUR = re.compile(r"\d[\d,.]*\s*(?:달러|불(?=$|\s|[이을은으씩짜,.])|엔(?=$|\s|[이을은으씩짜,.])|유로|위안|파운드|USD|JPY|EUR|CNY|usd|jpy|eur|cny)|[$€¥£]\s*\d")
_ITEM_TERM = re.compile(r"\s*(?:만(?!\s*원|\s*\d|큼)|끼리|둘이서|셋이서|넷이서|둘이|셋이|넷이|(?:가|이)\s*(?:나눠|나누|반반|내|부담))")
_NAME_SEP = re.compile(r"\s*(?:,|·|/|&|\+|랑|이랑|하고|와|과|및|그리고)\s*|\s+")
_JOIN_ONLY = re.compile(r"\s*(?:,|·|/|&|\+|:|랑|이랑|하고|와|과|및|그리고)?\s*")
_BOUND = re.compile(r"[;!?\n]|(?<!\d)[.,]|[.,](?!\d)|\s(?:그리고|근데|그런데|대신)\s")   # 1.5·1,000의 점·쉼표는 경계 아님
_EXCL_HEAD = re.compile(r"\s*(?:은|는|이|가|도)?\s*(?:빼고|빼줘|빼자|빼|제외|없이|말고)")
_EXCL_ANY = re.compile(r"안\s*(?:내|먹|갔|왔|낼)|불참|못\s*(?:갔|왔|먹|가|와|내|낼)|빠졌|빠질|빠져|빠진")
_MULT = re.compile(r"(\d+(?:\.\d+)?)\s*배(?![달송터꼽추])|(한|두|세|네|다섯)\s*배(?![달송터꼽추])")
_HALF = re.compile(r"절반|반\s*만(?!\s*원)|반값|반\s*(?:만\s*)?(?:내|부담)")
_AMT_P = r"\s*(?:원)?\s*(?:씩)?\s*(?:을|를|만큼|정도|은|는)?\s*"
_LESS_AMT = re.compile(_AMT_P + r"(?:더\s*)?(?:적게|덜|감면|빼|깎|할인|싸게|낮게|마이너스|안\s*내도)")
_MORE_AMT = re.compile(_AMT_P + r"(?:더(?!치|\s*냈)|많이|추가|얹|플러스)")   # '2만원 더 냈으니까'(이미 더 낸 돈)는 제외
_FIXED_AMT = re.compile(r"\s*(?:원)?\s*(?:씩)?\s*(?:만(?!\s*원|\s*\d|큼)|고정)"
                        r"|\s*(?:원)?\s*(?:씩)?\s*(?:을|를|은|는)?\s*(?:낼게|낼래|낸대|낸다|낼|내(?![었야])|부담)")
_OWN = re.compile(r"본인|자기|자기\s*꺼|지\s*꺼|따로|혼자|개인|직접")
_PAST_AMT = re.compile(_AMT_P + r"(?:더|덜)\s*(?:냈|줬|보냈)")
_PAID_AMT = re.compile(r"\s*(?:원)?\s*(?:을|를)?\s*(?:냈|결제|계산했|샀|긁)")
_PAYER = re.compile(r"주문|결제|계산했|계산할게|카드|긁")
_PAID_WORD = re.compile(r"냈(?!으면)|샀(?!으면)")
_VAGUE_AMT = re.compile(r"(?:조금|좀|약간|많이|살짝|적당히|대충)\s*(?:더|덜|적게|많이)|적당히|많이\s*먹은\s*사람")
_EQUAL = re.compile(r"똑같이|균등|n빵|N빵|엔빵|반반|더치|1/n")
_RATIO_LIST = re.compile(r"(?<![\d.:])(\d+(?:\.\d+)?)((?:\s*:\s*\d+(?:\.\d+)?)+)(?![\d.]|\s*:)")
_RATIO_POST = re.compile(r"\s*(?:로|으로|의\s*비율|비율|씩|$|[,.])")
_RATIO_PRE = re.compile(r"(?:=|비율\s*(?:은|는|이|가|로|을)?)\s*$")
_BARE_RATIO = re.compile(r"\s*(?:은|는|이|가|:)?\s*(\d+(?:\.\d+)?)(?!\s*(?:원|만|천|억|%|배|박|밤|명|개|인|시|분|일|kg|g|번|차|잔|병|마리|판)|[\d.,])")
_SUB_BETWEEN = re.compile(r"\s*(?:원)?\s*(?:에서|인데|이었는데|짜리인데|짜리에서|중에서)\s*,?\s*(?:[가-힣]{0,6}\s*)?"
                          r"(?:쿠폰|할인|포인트|적립금|마일리지|상품권)?\s*(?:으로|을|를)?\s*")
_SUB_POST = re.compile(r"\s*(?:원)?\s*(?:을|를|은|는|이|가)?\s*(?:빼|뺀|할인|깎|차감|제외|쓰|썼|사용|받|적용)")
_STOP_LABEL = {"총", "합계", "전부", "모두", "다", "합쳐서", "합쳐", "총액", "전체", "금액", "가격", "비용", "돈", "예산",
               "한도", "인당", "명당", "당", "각자", "각", "최대", "최소", "원래", "정가", "그냥", "대충", "약", "딱", "그리고",
               "및", "에서", "중", "쿠폰", "할인", "포인트", "적립금", "인데", "는데", "근데", "그럼", "우리", "오늘", "어제",
               "내가", "나", "너", "그", "이거", "저거", "빼고", "제외", "더", "덜", "씩", "나왔는데", "했는데", "이고"}
_NUM_KO = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5}


def _norm(text: str) -> str:
    """전각 기호·'20퍼센트/20프로' → '20%'. 이후 위치 계산은 모두 이 문자열 안에서만 한다."""
    t = (text or "").replace("％", "%").replace("：", ":")
    return re.sub(r"(\d)\s*(?:퍼센트|프로(?![젝그필모세듀]))", r"\1%", t)


def _name_re(pool: list[str]) -> str:
    return "|".join(re.escape(n) for n in sorted({p for p in pool if p}, key=len, reverse=True))


def _names_list_at(t: str, i: int, nre: str) -> tuple[list[str], int]:
    """t[i:]의 '진주·민재' / '진주랑 민재' 같은 이름 나열 → (이름들, 끝 위치)."""
    names: list[str] = []
    j = i
    if not nre:
        return names, j
    one = re.compile(rf"\s*({nre})(?:님|씨)?(?:이(?=[\s,·/&랑하와과만끼가도]))?")
    nxt = re.compile(rf"\s*(?:{nre})")
    while True:
        m = one.match(t, j)
        if not m:
            break
        names.append(m.group(1))
        j = m.end()
        s = _NAME_SEP.match(t, j)
        if s and s.end() > j and nxt.match(t, s.end()):
            j = s.end()
            continue
        break
    return names, j


def _label_before(t: str, s: int, nre: str) -> str | None:
    """금액 바로 앞 이름표 ('술값 2만원' → 술값). 사람 이름·'총'·'인당' 같은 말은 이름표가 아님."""
    m = re.search(r"([가-힣A-Za-z]{1,8})\s*$", t[max(0, s - 12): s])
    if not m:
        return None
    w = re.sub(r"(?:은|는|이|가|을|를|도|만|끼리)$", "", m.group(1)) or m.group(1)
    if w in _STOP_LABEL or (nre and re.fullmatch(rf"(?:{nre})(?:님|씨)?", w)):
        return None
    return w


def _total_marked(t: str, span: tuple[int, int, int], strong: bool = False) -> bool:
    """'총 4만원' · '8만원 중'(강한 표시) / '4만원 나왔어' · '결제했어'(약한 표시) 처럼 총액이라고 적힌 금액인지."""
    s, e, _ = span
    if _TOT_PRE.search(t[max(0, s - 10): s]) or _TOT_POST_STRONG.match(t[e: e + 8]):
        return True
    return not strong and bool(_TOT_POST.match(t[e: e + 14]))


def _added(t: str, span: tuple[int, int, int]) -> bool:
    """'배달비 3천원 추가' · '+ 3천원'처럼 따로 더해지는 금액인지."""
    s, e, _ = span
    return bool(_ADD_PRE.search(t[max(0, s - 10): s]) or _ADD_AFTER.match(t[e: e + 10]))


def _included(t: str, cands: list[tuple[int, int, int]]) -> tuple[int, int, int] | None:
    """'부가세 포함 11만원' · '11만원(부가세 포함)' → 최종 금액 (%는 다시 붙이지 않음)."""
    for m in re.finditer(r"포함", t):
        after = t[m.end(): m.end() + 12]
        nxt = [x for x in cands if m.end() <= x[0] <= m.end() + 10]
        if re.match(r"(?:해서|하면|시켜)", after) and not nxt:
            continue                     # '10만원에 부가세 포함해서 계산' → 원금에 더한다는 뜻
        if nxt:
            return nxt[0]
        if _INC_STATE.match(after):
            prv = [x for x in cands if x[1] <= m.start() and m.start() - x[1] <= 20]
            if prv:
                return prv[-1]
    return None


def _parts(t: str, cands: list[tuple[int, int, int]]) -> list[int]:
    """여러 금액 → 더하거나 빼는 조각 ('3만원에서 쿠폰 5천원 빼고' → [30000, -5000])."""
    out = []
    for i, (s, e, v) in enumerate(cands):
        sign = 1
        if i > 0:
            between = t[cands[i - 1][1]: s]
            if re.search(r"[-−－]", between) or (_SUB_BETWEEN.fullmatch(between) and _SUB_POST.match(t, e)):
                sign = -1
        out.append(sign * v)
    return out


def _classify(t: str, e: int, end: int, spans, used: set[int], pct_used: set[int], days: bool):
    """한 사람 조건 조각(이름 뒤 ~ 절 끝)을 유형 하나로 가른다."""
    seg = t[e:end]
    out: list[tuple[str, float]] = []
    info: dict[str, Any] = {"payer": False, "paid": None, "vague": False, "night": None}
    sp = [x for x in spans if e <= x[0] < end and x[0] not in used]
    pcts = [m for m in _PCT.finditer(t, e, end) if m.start() not in pct_used]
    xm = _EXCL_ANY.search(seg)
    if _EXCL_HEAD.match(seg) or (xm and not any(x[0] < e + xm.start() for x in sp) and not pcts):
        out.append(("exclude", 0))                           # '진주 빼고' · '진주는 여행 안 갔어 30만원'(금액보다 앞에서 빠짐)
    else:
        done = False
        for pm in pcts:
            pre, post = t[max(e, pm.start() - 8): pm.start()], t[pm.end(): pm.end() + 10]
            if _TOTAL_PCT_WORD.search(pre) or _PCT_TOTAL_POST.match(post):
                continue                                     # 총액에 붙는 % (부가세·할인 등)
            v = float(pm.group(1))
            if _LESS_POST.match(post) and v < 100:
                out.append(("less_pct", v))
            elif _MORE_POST.match(post) and v <= 500:
                out.append(("more_pct", v))
            elif v <= 100:
                out.append(("percent", v))
            else:
                continue
            pct_used.add(pm.start())
            done = True
            break
        if not done:
            nights = list(re.finditer(r"(\d+)\s*(?:박|밤)", seg))
            if days and not nights:
                nights = list(re.finditer(r"(\d+)\s*일(?!\s*(?:에|날|부터|까지|째))", seg))
            mm = _MULT.search(seg)
            if nights and int(nights[-1].group(1)) > 0:
                out.append(("ratio", int(nights[-1].group(1))))
                info["night"] = int(nights[-1].group(1))
                if len(nights) >= 2:
                    info["night_total"] = int(nights[0].group(1))
                done = True
            elif mm:
                out.append(("ratio", float(mm.group(1)) if mm.group(1) else _NUM_KO[mm.group(2)]))
                done = True
            elif re.search(r"(?:전체|총액|전부)\s*의?\s*(?:절반|반)", seg):
                out.append(("percent", 50))                  # '진주가 전체의 절반' → 총액의 50%
                done = True
            elif _HALF.search(seg):
                out.append(("ratio", 0.5))                   # '진주는 절반만' → 한 사람 몫의 절반
                done = True
        for s, en, v in (sp if not done else []):
            kind = None
            if _PAST_AMT.match(t, en):                       # '저번에 5천원 더 냈으니까' → 이번 조건이 아니라 지난 일
                info["past"] = v
                used.add(s)
                continue
            if _LESS_AMT.match(t, en):
                kind = "less"
            elif _MORE_AMT.match(t, en):
                kind = "more"
            elif _FIXED_AMT.match(t, en):
                kind = "fixed"
            elif _OWN.search(t[en: en + 16]):
                kind = "more"                                # 본인 것 따로
            elif _PAID_AMT.match(t, en):
                info["paid"] = v
            if kind:
                out.append((kind, v))
                used.add(s)
                done = True
                info.pop("past", None)                       # 이번에 어떻게 할지 말했으면 되묻지 않음
            break
        if not done and _VAGUE_AMT.search(seg):
            info["vague"] = True
    if _PAYER.search(seg) or info["paid"] is not None or (_PAID_WORD.search(seg) and not out):
        info["payer"] = True
    return out, info


def _mock_rule(text: str, members: list[str], total: int | None, subject: str | None) -> dict[str, Any]:
    """규칙 기반 해석 — Kiln이 없을 때의 해석이자, Kiln 결과를 바로잡는 안전망 (가이드라인 ⑥의 분류표를 코드로)."""
    t = _norm(text)
    pool = [p for p in dict.fromkeys(list(members or []) + KNOWN_NAMES) if p]
    nre = _name_re(pool)
    rule: dict[str, Any] = {"total_amount": None, "members": [], "payer": None, "adjustments": [],
                            "per_person_cap": None, "total_cap": None, "missing": [], "question": None}
    spans = amount_spans(t)
    used: set[int] = set()
    pct_used: set[int] = set()
    taken: list[tuple[int, int]] = []
    vague: list[tuple[str, str]] = []

    def free() -> list[tuple[int, int, int]]:
        return [x for x in spans if x[0] not in used]

    # 1) 한도 — 한도는 총액이 아니다
    for s, e, v in spans:
        before, after = t[max(0, s - 12): s], t[e: e + 14]
        if _PP_BEFORE.search(before) and (_CAP_AFTER.match(after) or re.search(r"(?:최대|최고|많아야)\s*$", before)):
            rule["per_person_cap"] = v
            used.add(s)
        elif _CAP_TOTAL_BEFORE.search(before) and _CAP_AFTER.match(after):
            rule["total_cap"] = v
            used.add(s)
    # 2) 단위 맞춤 ('천원 단위로') — 여기 나온 '천원'은 금액이 아님
    for m in _ROUND.finditer(t):
        u = _ROUND_MAP.get(m.group(1)) or to_int(m.group(1))
        if u in ROUND_UNITS:
            rule["round_unit"] = u
        used.update(s for s, e, _ in spans if s < m.end() and e > m.start())
    # 3) 원화가 아님
    if _CUR.search(t):
        vague.append(("currency", "원화 금액으로 알려 주세요. Share Pie는 원화 기준으로만 나눠요 (예: 68,000원)."))
    # 4) 일부 사람만 나누는 항목 ('술값 2만원은 진주·민재만')
    items: list[dict[str, Any]] = []
    restrict: list[str] | None = None
    for s, e, v in list(spans):
        if s in used:
            continue
        pm = re.compile(r"\s*(?:원)?\s*(은|는|만큼은|어치는|짜리는)?\s*").match(t, e)
        names, j = _names_list_at(t, pm.end(), nre)
        if not names or not _ITEM_TERM.match(t, j):
            continue
        label = _label_before(t, s, nre)
        others = [x for x in spans if x[0] != s and x[0] not in used]
        if not others and not (total and total != v) and not (pm.group(1) or label):
            restrict = names                                 # '3만원 진주랑 민재만 나눠' → 참여자를 좁힘 (항목 아님)
            continue
        items.append({"amount": v, "members": list(dict.fromkeys(names)), "label": label})
        used.add(s)
        taken.append((pm.end(), j))
    # 이름이 먼저 오는 꼴: '진주랑 민재만 마셨어 술값 2만원'
    scanned: list[tuple[int, int]] = []
    for m in (re.finditer(rf"(?:{nre})", t) if nre else []):
        if any(x <= m.start() < y for x, y in taken + scanned):
            continue
        names, j = _names_list_at(t, m.start(), nre)
        scanned.append((m.start(), j))
        term = re.compile(r"(?:만(?!원)|\s*끼리)").match(t, j) if names else None     # '민재만'(붙여 씀)·'끼리'
        if not term:
            continue
        bnd = _BOUND.search(t, term.end(), min(len(t), term.end() + 16))
        lim = bnd.start() if bnd else min(len(t), term.end() + 16)
        amt = next((x for x in spans if term.end() <= x[0] < lim and x[0] not in used), None)
        if not amt or re.match(r"\s*(?:원)?\s*씩", t[amt[1]:]) or _LESS_AMT.match(t, amt[1]) or _MORE_AMT.match(t, amt[1]) \
                or _PAID_AMT.match(t, amt[1]) or _PAST_AMT.match(t, amt[1]):
            continue                                         # '진주·민재만 5천원씩 더' → 사람 조건 (항목 아님)
        s, _, v = amt
        label = _label_before(t, s, nre)
        others = [x for x in spans if x[0] != s and x[0] not in used]
        if not others and not (total and total != v) and not label:
            restrict = names                                 # '진주랑 민재만 3만원 나눠' → 참여자를 좁힘
            continue
        items.append({"amount": v, "members": list(dict.fromkeys(names)), "label": label})
        used.add(s)
        taken.append((m.start(), j))
    if items:
        rule["items"] = items
    # 5) 사람별 조건 — 이름마다 자기 절만 읽는다 (다음 사람 이름·쉼표에서 끊음)
    days = bool(re.search(r"\d+\s*일\s*(?:중|동안|간|짜리)", t))
    hits: list[tuple[int, int, str, bool]] = []
    for n in sorted(set(pool), key=len, reverse=True):
        for m in re.finditer(re.escape(n), t):
            a, b = m.start(), m.end()
            if any(x < b and a < y for x, y in taken) or any(h[0] < b and a < h[1] for h in hits):
                continue
            hm = re.match(r"(?:님|씨)?(?:이(?=[는가도랑하와만의께\s,.]|$))?", t[b:])
            e2 = b + hm.end()
            hits.append((a, e2, n, bool(re.match(r"\s*(?:의|보다|만큼)", t[e2:]))))
    hits.sort()
    # '의' 없이 '민재는 진우 두 배'처럼 주어(은·는·이·가) 바로 뒤 이름 + 배수·절반 → 그 이름은 기준(참조)이다.
    # 조사가 없는 나열('진주랑 민재 두 배')은 그대로 두 주어.
    for k in range(1, len(hits)):
        a2, e3, n2, ref2 = hits[k]
        pa, pe, _pn, pref = hits[k - 1]
        if not ref2 and not pref and re.fullmatch(r"\s*(?:은|는|이|가)\s+", t[pe:a2]) \
                and re.match(r"\s*(?:\d+(?:\.\d+)?|두|세|네|다섯)\s*배|\s*(?:절반|반)", t[e3:]):
            hits[k] = (a2, e3, n2, True)
    subj = [h for h in hits if not h[3]]
    adj: dict[str, list[dict[str, Any]]] = {}
    refs: dict[str, set[str]] = {}
    nights: dict[str, int] = {}
    night_totals: list[int] = []
    paid: dict[str, int] = {}
    vague_names: list[str] = []
    joined: list[str] = []
    for i, (a, e, n, _) in enumerate(subj):
        nxt = subj[i + 1][0] if i + 1 < len(subj) else len(t)
        if i + 1 < len(subj) and _JOIN_ONLY.fullmatch(t[e:nxt]):
            joined.append(n)                                 # '진주랑 민재는 5천원씩 더' → 뒤 사람 조건을 같이 받음
            continue
        end = min(nxt, e + 32)
        bm = _BOUND.search(t, e, end)
        end = bm.start() if bm else end
        res, info = _classify(t, e, end, spans, used, pct_used, days)
        for who in joined + [n]:
            for k, v in res:
                adj.setdefault(who, []).append({"name": who, "kind": k, "value": v})
            if info["night"]:
                nights[who] = info["night"]
            if info["vague"]:
                vague_names.append(who)
        joined = []
        if info.get("night_total"):
            night_totals.append(info["night_total"])
        if info["payer"]:
            rule["payer"] = n
        if info["paid"] is not None:
            paid[n] = info["paid"]
        if info.get("past") and not res:
            vague.append(("past", f"{n}님이 이미 더(덜) 낸 {info['past']:,}원을 이번 정산에 어떻게 반영할까요? "
                                  f"예: “{josa(n)} {info['past']:,}원 덜 내”처럼 알려 주세요."))
        refs[n] = {h[2] for h in hits if h[3] and e <= h[0] < end and h[2] != n}
    # 연쇄 관계: '진주는 민재의 두 배'인데 민재도 조정됨 → 코드가 한 번에 못 풂 → 되묻기
    for n, rs in refs.items():
        if adj.get(n) and any(adj.get(r) for r in rs):
            vague.append(("chain", f"{n}님 금액을 원이나 %로 알려 주세요. 예: {josa(n)} 2만원, {josa(n)} 20% 더"))
            break
    # 비율 나열 ('진주:민재:지현 = 3:2:1', '3:2:1로') — 이름을 말한 순서대로
    ratio_src: dict[str, str] = {}
    owners = [o for o in dict.fromkeys(h[2] for h in subj) if not any(x["kind"] == "exclude" for x in adj.get(o, []))]
    listed = False
    for m in _RATIO_LIST.finditer(t):
        if not (_RATIO_POST.match(t, m.end()) or _RATIO_PRE.search(t[max(0, m.start() - 10): m.start()])):
            continue
        vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(0))]
        listed = True
        if len(owners) == len(vals) and all(v > 0 for v in vals):
            for o, v in zip(owners, vals):
                adj[o] = [x for x in adj.get(o, []) if x["kind"] not in ("ratio", "percent")] + [{"name": o, "kind": "ratio", "value": v}]
                ratio_src[o] = "list"
        else:
            r = m.group(0).replace(" ", "")
            eg = ":".join((list(members or [])[:len(vals)] if len(members or []) >= len(vals) else KNOWN_NAMES[:len(vals)]))
            vague.append(("ratio_owner", f"{r}에서 누가 몇인지 알려 주세요. 예: {eg} = {r}"))
        break
    if not listed and "비율" in t:                           # '진주 3 민재 2 지현 1 비율로'
        for a, e, n, _ in subj:
            bm = _BARE_RATIO.match(t, e)
            if bm and float(bm.group(1)) > 0 and not adj.get(n):
                adj[n] = [{"name": n, "kind": "ratio", "value": float(bm.group(1))}]
                ratio_src[n] = "list"
    # 박·일 수 비례 ('3박 중 진주는 2박') — 나머지 사람은 전체 박수 (calculate에서 참여자에게 채움)
    if nights:
        unit = r"(\d+)\s*일(?!\s*(?:에|날|부터|까지|째))" if days else r"(\d+)\s*(?:박|밤)"
        alln = [int(x) for x in re.findall(unit, t)]
        tot = max(night_totals) if night_totals else (max(alln) if len(alln) > len(nights) else None)
        if tot and tot >= max(nights.values()):
            rule["nights_total"] = tot
            for n in nights:
                ratio_src[n] = "nights"
        else:
            vague.append(("nights_total", "전체 일정이 몇 박(며칠)인가요? 예: 3박 중 진주는 2박"))
    rule["adjustments"] = [x for n in adj for x in adj[n]]
    if ratio_src:
        rule["ratio_src"] = ratio_src
    if len(paid) >= 2:
        vague.append(("multi_payer", "여러 명이 따로 결제한 건 한 번에 나눌 수 없어요. 결제한 사람 한 명과 나눌 총액으로 알려 주세요. "
                                     "예: 민재가 5만원 결제했어, 넷이 똑같이"))
    # 6) 한 사람당 금액 ('한 명당 만원씩')
    for s, e, v in free():
        before, after = t[max(0, s - 10): s], t[e: e + 12]
        if not (re.match(r"\s*(?:원)?\s*씩", after) or _PP_BEFORE.search(before)) or _PP_NOT_AFTER.match(after):
            continue
        if nre and re.search(rf"(?:{nre})(?:님|씨)?(?:이)?\s*(?:은|는|이|가|도)?\s*$", before):
            continue                                        # '민재는 5천원씩' → 그 사람 조건 (위에서 처리)
        rule["per_person_amount"] = v
        used.add(s)
        break
    # 7) 총액에 붙는 % — 앞뒤 말로 가른다 (포함 > 할인 > 더함 > 일부 > 모름=되묻기)
    free_pcts = [m for m in _PCT.finditer(t) if m.start() not in pct_used]

    def set_base(cs: list[tuple[int, int, int]]) -> None:
        ex = [x for x in cs if _total_marked(t, x)]
        if ex:
            rule["base_amount"] = ex[-1][2]
            used.add(ex[-1][0])
        elif len(cs) >= 2:
            rule["amount_parts"] = _parts(t, cs)
            used.update(x[0] for x in cs)
        elif cs:
            rule["base_amount"] = cs[-1][2]
            used.add(cs[-1][0])

    if free_pcts:
        pm = free_pcts[0]
        n_pct, ps, pe = float(pm.group(1)), pm.start(), pm.end()
        pre, post = t[max(0, ps - 16): ps], t[pe: pe + 16]
        cands = free()
        before = [x for x in cands if x[1] <= ps]
        after = [x for x in cands if x[0] >= pe]
        separate = "별도" in pre + post
        inc = _included(t, cands)
        if inc:
            rule.update(total_amount=inc[2], pct_type="included", total_explicit=True)
            used.add(inc[0])
        elif _DISC_PRE.search(pre) or _DISC_POST.match(post):
            if after and not before:                         # '10% 할인받아서 27,000원' → 이미 할인된 최종 금액
                rule.update(total_amount=after[0][2], pct_type="included", total_explicit=True)
                used.add(after[0][0])
            else:
                set_base(before)
                rule.update(total_pct=n_pct, total_pct_type="discount")
        elif _ADD_POST.match(post) or separate or re.search(r"\+\s*$", pre) or (
                _TOTAL_PCT_WORD.search(pre) and _ADD_ANY.search(t[pe: pe + 24])):
            if after and not before and not separate:        # '부가세 더해서 11만원' → 최종 금액
                rule.update(total_amount=after[0][2], pct_type="included", total_explicit=True)
                used.add(after[0][0])
            else:
                set_base(before or after)
                rule.update(total_pct=n_pct, total_pct_type="add")
        elif _PORTION.search(pre + t[pe: pe + 10]) or re.search(r"의\s*$", pre) or re.match(
                r"\s*(?:만|를|을)?\s*(?:나눠|나누|떼|정산)", post):
            set_base(cands)
            rule.update(total_pct=n_pct, total_pct_type="portion")
        else:
            vague.append(("pct_unknown", f"{n_pct:g}%가 무엇에 붙는지 알려 주세요. 예: 부가세 {n_pct:g}% 더해서 / "
                                         f"{n_pct:g}% 할인받았어 / 진주는 {n_pct:g}% 더"))
    # 8) 나머지 금액 → 총액 · 금액 조각
    cands = free()
    if not (rule.get("total_amount") or rule.get("total_pct") or rule.get("amount_parts")) and cands:
        strong = [x for x in cands if _total_marked(t, x, strong=True)]
        weak = [x for x in cands if x not in strong and _total_marked(t, x)]
        extra = [x for x in cands if x not in strong + weak and _added(t, x)]
        if (strong or weak) and extra:
            rule["amount_parts"] = _parts(t, cands)                                 # '총 3만원이고 배달비 3천원 추가'
        elif strong:
            rule.update(total_amount=strong[-1][2], total_explicit=True)            # '총 4만원' · '8만원 중'
        elif weak and (len(cands) == 1 or not any(_added(t, x) for x in cands if x not in weak)):
            rule.update(total_amount=weak[-1][2], total_explicit=True)              # '치킨 2만 피자 2만 해서 4만원 나왔어'
        elif weak:
            rule["amount_parts"] = _parts(t, cands)                                 # '3만원 결제했고 배달비 3천원 추가'
        elif rule.get("per_person_amount"):
            rule["amount_parts"] = _parts(t, cands)          # '한 명당 만원씩 + 배달비 3천원'
        elif items and len(cands) == 1 and not _label_before(t, cands[0][0], nre):
            rule["total_amount"] = cands[0][2]               # '8만원인데 술값 2만원은 진주·민재만' (항목은 총액 안)
        elif items:
            rule["amount_parts"] = [it["amount"] for it in items] + _parts(t, cands)
        elif len(cands) >= 2:
            rule["amount_parts"] = _parts(t, cands)
        else:
            rule["total_amount"] = cands[0][2]
    if rule.get("amount_parts") and len(rule["amount_parts"]) == 1 and not rule.get("per_person_amount"):
        rule["total_amount"] = rule.pop("amount_parts")[0]
    # 9) 참여자 — 항목·비교 대상으로만 나온 이름은 참여자 목록이 아님
    named = list(dict.fromkeys(h[2] for h in subj))
    if restrict:
        rule["members"] = list(dict.fromkeys(restrict))
    elif len(named) >= 2 and "나머지" not in t:
        rule["members"] = named
    # 10) 되묻기 · 빠진 정보
    if vague_names:
        n = vague_names[0]
        vague.insert(0, ("amount", f"{n}님이 ‘조금 더/덜’ 낸다는 게 정확히 얼마인가요? 예: “{josa(n)} 5천원 더” 또는 “{josa(n)} 20% 더”처럼 알려 주세요."))
    elif _VAGUE_AMT.search(t) and not rule["adjustments"] and not _EQUAL.search(t):
        vague.append(("amount", "‘조금 더/덜’이 정확히 얼마인가요? 예: “진우는 5천원 더” 또는 “20% 더”처럼 알려 주세요."))
    if vague:
        rule["missing"] = ["vague"]
        rule["vague_reason"], rule["question"] = vague[0]
    if not (rule.get("total_amount") or rule.get("total_pct") or rule.get("amount_parts") or rule.get("per_person_amount") or total):
        rule["missing"].append("total_amount")
    if not (rule["members"] or members):
        rule["missing"].append("members")
    if rule["missing"] and "vague" not in rule["missing"]:
        q = []
        if "members" in rule["missing"]:
            q.append("누구와 나누시나요? 참여자 이름을 알려주세요")
        if "total_amount" in rule["missing"]:
            q.append("나눌 총금액은 얼마인가요")
        rule["question"] = " 그리고 ".join(q) + "?"
    sm = re.search(r"([가-힣A-Za-z0-9]+\s*(여행|공동구매|모임|회비|뒤풀이|MT|회식|파티))", t)
    rule["subject"] = sm.group(1) if sm else None
    rule["purpose"] = ""  # calculate()에서 최종 결제자 기준으로 기본 문구 생성
    return rule


# ───────────── 예시 (agent/pie_brain/calc_examples.jsonl) ─────────────
_EX_PATH = Path(__file__).resolve().parent / "pie_brain" / "calc_examples.jsonl"
_EX_CACHE: dict[str, Any] = {"mtime": None, "rows": []}


def _load_examples() -> list[dict[str, Any]]:
    """팀이 쓰는 계산 예시 파일. 바뀌면 다음 호출에 자동 반영 (재시작 불필요)."""
    try:
        mt = _EX_PATH.stat().st_mtime
    except OSError:
        return []
    if _EX_CACHE["mtime"] != mt:
        rows = []
        for line in _EX_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(j, dict) and j.get("type") and j.get("text") and isinstance(j.get("rule"), dict):
                rows.append(j)
        _EX_CACHE.update(mtime=mt, rows=rows)
    return _EX_CACHE["rows"]


def calc_types(text: str, members: list[str] | None = None) -> list[str]:
    """문장에 들어 있는 계산 표현 유형 (예시 고르기용 · 코드 · 0 tokens). 단순 'n빵'이면 []."""
    t = _norm(text)
    nre = _name_re(list(members or []) + KNOWN_NAMES)
    n_amt = len(amount_spans(t))
    out: list[str] = []
    if "%" in t:
        if "포함" in t:
            out.append("pct_included")
        if re.search(r"할인|깎|쿠폰|세일", t):
            out.append("pct_discount")
        if _ADD_ANY.search(t) and (_TOTAL_PCT_WORD.search(t) or "+" in t):
            out.append("pct_add")
        if re.search(r"%\s*(?:정도|쯤)?\s*(?:을|를|만큼)?\s*(?:더(?![해한하])|덜|많이|적게)", t):
            out.append("pct_more")
        elif re.search(rf"(?:{nre})\S{{0,6}}\s*\d+(?:\.\d+)?\s*%", t):
            out.append("pct_person")
        if re.search(r"의\s*\d+(?:\.\d+)?\s*%|%\s*만|수수료|이자", t):
            out.append("pct_portion")
    if re.search(r"(?:의|보다)\s*(?:(?:\d+(?:\.\d+)?|한|두|세)\s*배|절반)", t):
        out.append("ask")
    if re.search(r"\d\s*:\s*\d", t):
        out.append("ratio_list")
    if re.search(r"\d\s*(?:박|밤)|\d\s*일\s*(?:중|동안)", t):
        out.append("nights")
    if re.search(r"\d\s*배|(?:두|세|네)\s*배|절반|반\s*만", t):
        out.append("ratio")
    if re.search(r"(?:원|만|천)\s*씩", t):
        out.append("per_person")
    if re.search(r"단위", t):
        out.append("round")
    if n_amt >= 2:
        if re.search(rf"(?:{nre})\s*(?:만|끼리)", t):
            out.append("items")
        out.append("parts")
    return out


def pick_examples(text: str, members: list[str] | None = None, k: int = 2) -> list[str]:
    """맞는 유형의 예시를 최대 k개 (서로 다른 유형). 예시 파일이 없거나 해당 유형이 없으면 []."""
    rows = _load_examples()
    out, seen = [], set()
    for typ in calc_types(text, members):
        if len(out) >= k or typ in seen:
            continue
        row = next((r for r in rows if r["type"] == typ), None)
        if row:
            seen.add(typ)
            out.append(f'- "{row["text"]}" → {json.dumps(row["rule"], ensure_ascii=False, separators=(",", ":"))}')
    return out


def _default_purpose(subject: str | None, rule: dict[str, Any]) -> str:
    base = f"{subject or '공동 비용'} 분담금"
    tags: list[str] = []
    for a in rule.get("adjustments") or []:
        kind = a.get("kind") if isinstance(a, dict) else None
        if kind == "less" and to_int(a.get("value")):
            tags.append(f"{'주문자' if a.get('name') == rule.get('payer') else '1인'} {to_int(a.get('value')):,}원 감면")
        elif kind == "exclude":
            tags.append("일부 제외")
        elif kind in ("ratio", "percent", "more_pct", "less_pct"):
            tags.append("비율 분담")
    if rule.get("items"):
        tags.append("항목별 분담")
    tags = list(dict.fromkeys(tags))
    return base + (f"({', '.join(tags)})" if tags else "(균등)")


def pii_clean(text: str, names: list[str] | None = None) -> str:
    """공개 체인에 올리기 전 개인정보 제거: 이름(성+이름·짧은 이름), 전화번호, 이메일."""
    p = (text or "").strip().replace("\n", " ")
    p = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "", p)
    p = re.sub(r"(\+?82[-\s]?)?0?1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}", "", p)
    p = re.sub(r"\d{2,3}-\d{3,4}-\d{4}", "", p)
    pool = set((names or []) + KNOWN_NAMES)
    try:
        from . import store
        for u in store.users_raw():
            pool.update(x for x in (u.get("name"), u.get("short")) if x)
    except Exception:  # noqa: BLE001
        pass
    sur = "김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용"
    for n in sorted(pool, key=len, reverse=True):   # 긴 이름(김진주)부터, 짧은 이름 앞의 성도 함께
        p = re.sub(rf"[{sur}]?{re.escape(n)}(님|씨)?" if len(n) == 2 else rf"{re.escape(n)}(님|씨)?", "", p)
    return re.sub(r"\s{2,}", " ", p).strip(" ,·-")


def sanitize_purpose(purpose: str, names: list[str], fallback: str) -> str:
    """체인에 올라가는 문구에서 실명·연락처 제거 + 길이 제한."""
    p = pii_clean(purpose, names)
    if len(p) < 4:
        p = fallback
    return p[:60]


PROHIBITED = re.compile(r"자금\s*세탁|돈\s*세탁|세탁\s*(수수료|비용|대금)|검은\s*돈|비자금|마약|필로폰|대마|불법\s*도박|도박\s*빚|"
                        r"보이스\s*피싱|대포\s*(통장|폰)|뇌물|탈세|장물|사기\s*(친|쳐서|로)\s*번|해킹\s*(대가|수익)|랜섬")


def prohibited_reason(text: str) -> str | None:
    """불법 목적 정산 차단 (코드 규칙). AI 판단(prohibited)과 함께 쓴다."""
    m = PROHIBITED.search(text or "")
    return m.group(0) if m else None


REFUSE_MSG = ("불법 자금(자금세탁·마약·불법도박 등)과 관련된 돈은 정산을 도와드릴 수 없어요. "
              "Share Pie는 모임·여행·공동구매처럼 합법적인 공동 비용만 나누고 기록해요.")


def _pct_of(r: dict[str, Any]) -> tuple[float | None, str | None]:
    """AI가 고른 %의 종류 → 코드가 총액 배율로 바꿈 (add 10 → 110, discount 10 → 90, portion 20 → 20)."""
    n = to_num(r.get("total_pct"))
    typ = str(r.get("total_pct_type") or "").strip().lower()
    if n is not None and n > 0:
        if typ in ("add", "surcharge", "더함"):
            return (100 + n, "add") if n <= 200 else (None, None)
        if typ in ("discount", "할인"):
            return (100 - n, "discount") if n < 100 else (None, None)
        if typ in ("portion", "일부"):
            return (n, "portion") if n <= 100 else (None, None)
        return None, "unknown"
    legacy = to_num(r.get("total_percent"))                 # 이전 형식 (100+N을 AI가 직접 적던 방식)
    if legacy and 0 < legacy <= 300:
        t0 = str(r.get("pct_type") or "")
        return legacy, (t0 if t0 in ("add", "discount", "portion") else ("add" if legacy > 100 else "portion"))
    return None, ("included" if r.get("pct_type") == "included" else None)


def normalize_rule(rule: Any, members: list[str]) -> dict[str, Any]:
    """LLM 출력 정리: 숫자 문자열("38,900원")→정수, 없는 사람·종류 없는 조정은 버림, 이름은 멤버 이름으로 맞춤."""
    r = dict(rule) if isinstance(rule, dict) else {}
    for k in ("total_amount", "per_person_cap", "total_cap", "base_amount", "per_person_amount"):
        v = to_int(r.get(k))
        r[k] = v if v and v > 0 else None
    pct, typ = _pct_of(r)
    r.pop("pct_unknown", None)
    if typ == "unknown":
        r["pct_unknown"] = to_num(r.get("total_pct"))
        pct, typ = None, None
    r["total_percent"], r["pct_type"] = pct, typ
    r.pop("total_pct", None)
    r.pop("total_pct_type", None)
    parts = r.get("amount_parts")
    if isinstance(parts, (int, float, str)) and not isinstance(parts, bool):
        parts = [parts]
    r["amount_parts"] = [v for v in (to_int(p) for p in (parts if isinstance(parts, list) else []) if not isinstance(p, bool)) if v][:20]
    ru = to_int(r.get("round_unit"))
    r["round_unit"] = ru if ru in ROUND_UNITS else None
    r["prohibited"] = bool(r.get("prohibited"))
    ms = r.get("members")
    if isinstance(ms, str):
        ms = re.split(r"[,\s·/]+", ms)
    ms = [str(m).strip() for m in (ms if isinstance(ms, list) else []) if str(m).strip()]
    if members:
        ms = [money.match_member(m, members) or m for m in ms]
    r["members"] = list(dict.fromkeys(ms))
    pool = list(dict.fromkeys(r["members"] + list(members or [])))
    adj = []
    for a in r.get("adjustments") or []:
        if not isinstance(a, dict) or a.get("kind") not in KINDS:
            continue
        name = money.match_member(a.get("name"), pool)
        if not name:
            continue
        kind, v = a["kind"], a.get("value")
        if kind in ("ratio", "percent", "more_pct", "less_pct"):
            v = to_num(v)
            if v is None or v <= 0 or (kind == "less_pct" and v >= 100) or (kind == "more_pct" and v > 500) \
                    or (kind == "percent" and v > 100):
                continue
        elif kind == "exclude":
            v = 0
        else:
            v = to_int(v)
            if v is None:
                continue
            v = abs(v)
        adj.append({"name": name, "kind": kind, "value": v})
    r["adjustments"] = adj
    items = []
    for it in r.get("items") or []:
        if not isinstance(it, dict):
            continue
        amt = to_int(it.get("amount"))
        ims = it.get("members")
        if isinstance(ims, str):
            ims = re.split(r"[,\s·/]+", ims)
        names: list[str] = []
        for x in ims if isinstance(ims, list) else []:
            nm = money.match_member(x, pool) if pool else (str(x).strip() or None)
            if nm and nm not in names:
                names.append(nm)
        if amt and amt > 0 and names:
            lab = it.get("label")
            items.append({"amount": amt, "members": names, "label": str(lab).strip()[:12] if lab else None})
    r["items"] = items[:10]
    r["payer"] = money.match_member(r.get("payer"), pool) if r.get("payer") else None
    r["missing"] = [m for m in (r.get("missing") or []) if isinstance(m, str)]
    for k in ("purpose", "subject", "question"):
        r[k] = str(r[k]) if r.get(k) is not None else None
    return r


def _eq(a, b) -> bool:
    try:
        return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return False


def _has_total(r: dict[str, Any]) -> bool:
    return bool(r.get("total_amount") or r.get("total_percent") or r.get("amount_parts") or r.get("per_person_amount"))


_PCT_KO = {"add": "더함", "discount": "할인", "portion": "일부"}


def _merge_backstop(rule: dict[str, Any], code: dict[str, Any]) -> list[str]:
    """AI 해석(rule)을 코드 해석(code)으로 보정. 코드가 확실한 신호(할인·더해서·포함·총·씩·N% 더 …)를 읽은 것만 고친다."""
    notes: list[str] = []
    ct = code.get("pct_type")
    if ct in ("included", "add", "discount", "portion"):
        rule.pop("pct_unknown", None)                   # AI가 %의 종류를 못 골라도 코드가 읽은 말(할인·더해서·포함·의)로 정함
    # ① %의 종류 — 최종 금액이 적혀 있으면 %를 다시 붙이지 않음 / 더함·할인은 코드가 읽은 말이 기준
    if ct == "included" and code.get("total_amount"):
        if rule.get("total_percent") or rule.get("total_amount") != code["total_amount"]:
            rule.update(total_amount=code["total_amount"], total_percent=None, pct_type="included", base_amount=None,
                        amount_parts=[], total_explicit=True)
            notes.append(f"최종 금액 {code['total_amount']:,}원(%는 이미 반영됨)")
    elif ct in ("add", "discount") and code.get("total_percent"):
        if not (rule.get("pct_type") == ct and _eq(rule.get("total_percent"), code["total_percent"])):
            base = code.get("base_amount") or rule.get("base_amount") or (None if code.get("amount_parts") else rule.get("total_amount"))
            rule.update(total_percent=code["total_percent"], pct_type=ct, base_amount=base,
                        amount_parts=code.get("amount_parts") or [], total_amount=None)
            n = code["total_percent"] - 100 if ct == "add" else 100 - code["total_percent"]
            notes.append(f"{n:g}% {_PCT_KO[ct]}")
    elif ct == "portion" and code.get("total_percent") and not rule.get("total_percent"):
        rule.update(total_percent=code["total_percent"], pct_type="portion",
                    base_amount=code.get("base_amount") or rule.get("base_amount") or rule.get("total_amount"),
                    amount_parts=code.get("amount_parts") or [], total_amount=None)
        notes.append(f"총액의 {code['total_percent']:g}%")
    # ② 총액을 AI가 통째로 놓침
    if not _has_total(rule) and _has_total(code):
        for k in ("total_amount", "amount_parts", "per_person_amount", "base_amount", "total_percent", "pct_type", "total_explicit"):
            if code.get(k):
                rule[k] = code[k]
        notes.append("총액 " + (f"{code['total_amount']:,}원" if code.get("total_amount") else "(코드가 읽은 금액)"))
    # ③ '총 4만원'·'8만원 중'처럼 총액이라고 적힌 금액
    if code.get("total_explicit") and code.get("total_amount") and ct != "included" and not rule.get("total_percent") \
            and not rule.get("per_person_amount"):
        if rule.get("total_amount") != code["total_amount"] or rule.get("amount_parts"):
            rule.update(total_amount=code["total_amount"], amount_parts=[])
            notes.append(f"총액 {code['total_amount']:,}원")
        rule["total_explicit"] = True
    # ④ 여러 금액의 합·차 (AI가 직접 더했거나 하나만 골랐을 때)
    if code.get("amount_parts") and not code.get("total_percent") and not rule.get("total_percent") and not rule.get("total_explicit"):
        cs = sum(code["amount_parts"])
        ls = sum(rule.get("amount_parts") or []) or rule.get("total_amount")
        if ls != cs:
            rule.update(amount_parts=code["amount_parts"], total_amount=None)
            notes.append("금액 조각 " + _fmt_parts(code["amount_parts"]))
    # ⑤ 한 사람당 금액
    if code.get("per_person_amount") and not rule.get("per_person_amount"):
        if rule.get("total_amount") in (None, code["per_person_amount"]):
            rule.update(per_person_amount=code["per_person_amount"], total_amount=None)
            notes.append(f"1인 {code['per_person_amount']:,}원씩")
    # ⑥ 사람별 조건 — % 종류(N% 더 ↔ 총액의 N%) · 배수 · 박수 · 빠뜨린 조건
    src = code.get("ratio_src") or {}
    for ca in code.get("adjustments") or []:
        n, k, v = ca["name"], ca["kind"], ca["value"]
        las = [x for x in rule["adjustments"] if x["name"] == n]
        if any(x["kind"] == k and _eq(x["value"], v) for x in las):
            continue
        if k in ("more_pct", "less_pct"):
            eqr = 1 + v / 100 if k == "more_pct" else 1 - v / 100
            if any(x["kind"] == "ratio" and abs((x["value"] or 0) - eqr) < 0.005 for x in las):
                continue
            drop = {"percent", "more_pct", "less_pct", "ratio"}
            keep_same_value = False
        elif k == "percent":
            if las and not any(x["kind"] in ("more_pct", "less_pct") for x in las):
                continue
            drop, keep_same_value = {"more_pct", "less_pct"}, True
        elif k == "ratio":
            if src.get(n) in ("nights", "list"):
                drop, keep_same_value = {"ratio", "percent", "more_pct", "less_pct"}, True
            elif not las or all(x["kind"] in ("less", "more", "fixed") and (x["value"] or 0) < 10 for x in las):
                drop, keep_same_value = {"less", "more", "fixed"}, True
            else:
                continue
        else:                                              # less · more · fixed · exclude → AI가 그 사람 조건을 통째로 놓쳤을 때만
            if las:
                continue
            drop, keep_same_value = set(), True
        rule["adjustments"] = [x for x in rule["adjustments"]
                               if not (x["name"] == n and (x["kind"] in drop or (not keep_same_value and _eq(x["value"], v))))]
        rule["adjustments"].append(dict(ca))
        notes.append(f"{n} {k} {v:g}")
    if code.get("nights_total") and not rule.get("nights_total"):
        rule["nights_total"] = code["nights_total"]
    # ⑦ 일부 사람만 나누는 항목 · 단위 맞춤
    if code.get("items") and not rule.get("items"):
        rule["items"] = code["items"]
        for it in code["items"]:
            per = it["amount"] / len(it["members"])
            rule["adjustments"] = [x for x in rule["adjustments"] if not (
                x["name"] in it["members"] and x["kind"] in ("fixed", "more") and (_eq(x["value"], it["amount"]) or abs(x["value"] - per) < 1))]
        notes.append("항목 " + ", ".join(f"{it['amount']:,}원→{'·'.join(it['members'])}" for it in code["items"]))
    if code.get("round_unit") and not rule.get("round_unit"):
        rule["round_unit"] = code["round_unit"]
        notes.append(f"{code['round_unit']:,}원 단위")
    # ⑧ 코드가 찾은 되묻기 사유 (연쇄 관계·비율 주인 없음·외화·모호한 양·% 종류 모름·여러 결제자)
    if code.get("vague_reason") and "vague" not in (rule.get("missing") or []):
        rule["missing"] = ["vague"] + [m for m in (rule.get("missing") or []) if m != "vague"]
        rule["question"], rule["vague_reason"] = code.get("question"), code["vague_reason"]
        notes.append(f"되묻기({code['vague_reason']})")
    return notes


def _restricts(text: str, named: list[str], rule: dict[str, Any]) -> bool:
    """'진주랑 민재만 나눠' · '둘이서' · '끼리'처럼 참여자를 좁히는 말이 있는지."""
    t = _norm(text)
    if any(set(it["members"]) == set(named) for it in rule.get("items") or []):
        return False
    if "끼리" in t:
        return True
    nre = _name_re(named)
    if nre and re.search(rf"(?:{nre})(?:님|씨|이)?\s*만(?!\s*원)[^.,]{{0,12}}?(?:나눠|나누|내|계산|정산|부담|할게|하자)", t):
        return True
    stated = parse_people(t)
    return bool(stated and stated == len(named))


def _resolve_members(rule: dict[str, Any], known: list[str], text: str) -> list[str]:
    named = [m for m in (rule.get("members") or []) if m]
    known = [m for m in dict.fromkeys(known or []) if m]
    if named and known and set(named) < set(known) and not _restricts(text, named, rule):
        return known                                     # 조건에 나온 이름만 적은 것 → 방 참여자 전원
    return list(dict.fromkeys(named or known))


def _item_deltas(items: list[dict[str, Any]], active: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    """항목 금액을 그 사람들에게만 나눠 더함 (1원 단위, 남는 1원은 앞사람부터)."""
    out = []
    for it in items:
        ms = [m for m in it["members"] if m in active]
        if not ms:
            return [], f"{it.get('label') or '항목'} {it['amount']:,}원을 나눌 사람이 참여자 중에 없어요. 누가 나누는지 알려 주세요."
        q, rem = divmod(int(it["amount"]), len(ms))
        out += [{"name": m, "kind": "more", "value": q + (1 if i < rem else 0)} for i, m in enumerate(ms)]
    return out, None


def _fmt_parts(parts: list[int]) -> str:
    s = ""
    for i, p in enumerate(parts):
        s += (f"{p:,}원" if i == 0 else (f" + {p:,}원" if p >= 0 else f" − {-p:,}원"))
    return s


def _half_up(x: Fraction) -> int:
    return math.floor(x + Fraction(1, 2))


def _final_total(rule: dict[str, Any], total: int | None, members: list[str], adj: list[dict[str, Any]]) -> tuple[int | None, str | None]:
    """계산 순서(코드): %가 붙은 총액 / 금액 조각의 합 / 적힌 총액 → 1인당 금액 × 인원 (+ 조각) → 없으면 방의 현재 총액."""
    explicit, parts = rule.get("total_amount"), rule.get("amount_parts") or []
    pct, pp = rule.get("total_percent"), rule.get("per_person_amount")
    out = None
    if pct:
        base = rule.get("base_amount") or (sum(parts) if parts else None) or explicit or total
        if not base or base <= 0:
            return None, "몇 원에 붙는 %인가요? 원금을 알려 주세요. 예: 36,000원인데 10% 할인받았어"
        out = _half_up(Fraction(base) * Fraction(str(pct)) / 100)
        src = f"{_fmt_parts(parts)} = {sum(parts):,}원" if parts and not rule.get("base_amount") else f"{base:,}원"
        typ = rule.get("pct_type") or ("add" if pct > 100 else "portion")
        rule["total_note"] = (f"{src} + {pct - 100:g}% = {out:,}원" if typ == "add" else
                              f"{src}에서 {100 - pct:g}% 할인 = {out:,}원" if typ == "discount" else
                              f"{src}의 {pct:g}% = {out:,}원")
    elif parts:
        s = sum(parts)
        if explicit and rule.get("total_explicit") and explicit != s:
            out = explicit
        else:
            out = s
            if len(parts) >= 2:
                rule["total_note"] = f"{_fmt_parts(parts)} = {s:,}원"
        if out <= 0:
            return None, "빼는 금액이 더 커서 나눌 금액이 0원 이하예요. 금액을 다시 알려 주세요."
    elif explicit:
        out = explicit
    if pp:
        if pct:
            return None, "‘한 명당 금액’과 ‘%’를 함께 계산할 수 없어요. 총액이나 한 명당 금액 중 하나로 알려 주세요."
        try:
            unit_total = money.total_from_unit(pp, members, adj)
        except money.CalcError as e:
            return None, e.message
        n = len([m for m in members if m not in {a["name"] for a in adj if a.get("kind") == "exclude"}])
        if parts and not rule.get("total_explicit"):
            out = unit_total + sum(parts)
            rule["total_note"] = f"1인 {pp:,}원 기준 {n}명 {unit_total:,}원 + {_fmt_parts(parts)} = {out:,}원"
        elif explicit and explicit != unit_total:
            return None, (f"한 명당 {pp:,}원씩이면 총 {unit_total:,}원인데, 말한 총액은 {explicit:,}원이에요. "
                          f"어느 쪽으로 나눌까요?")
        else:
            out = unit_total
            rule["total_note"] = f"1인 {pp:,}원 × {n}명 = {out:,}원" if unit_total == pp * n else f"1인 {pp:,}원 기준 {n}명 = {out:,}원"
    return (out or total), None


def calculate(*, text: str, members: list[str], total: int | None = None, payer: str | None = None,
              subject: str | None = None, history: list[str] | None = None, flow: str | None = None) -> dict[str, Any]:
    """그룹 채팅/ Pie 채팅에서 받은 분담 조건을 계산한다.

    반환 status: ok | need_info | refused | error
    """
    ctx = [f"참여자: {', '.join(members) if members else '(모름)'}",
           f"현재 총액: {won(total) if total else '(모름)'}",
           f"정산 대상: {subject or '(모름)'}"]
    if history:
        ctx.append("이전 대화: " + " / ".join(h[:80] for h in history[-4:]))
    ex = pick_examples(text, members)
    if ex:
        ctx.append("비슷한 예시(형식만 참고, 숫자는 이번 요청에서):\n" + "\n".join(ex))
    ctx.append(f"요청: {text}")
    rule, meta = llm.client.call_tool(
        "settlement.analyze", SYSTEM, "\n".join(ctx), TOOL,
        mock=lambda: _mock_rule(text, members, total, subject), flow=flow, max_tokens=1000)
    metas = [meta]
    rule = normalize_rule(rule, members)
    if meta.get("mode") in ("tools", "json", "text"):   # Kiln 응답이 다음 행동을 정한 방식 (심사 기준: 응답 → 의사결정)
        llm.decision("settlement.analyze", flow, "Kiln 응답 → 분담 규칙 JSON: " + (
            "되묻기 " + ", ".join(rule.get("missing") or []) if rule.get("missing") else
            f"총액 {rule.get('total_amount') or rule.get('total_percent') or '방 총액'} · 조정 {len(rule.get('adjustments') or [])}개")
            + " → 금액은 코드가 계산(Stage 2, 0 토큰)")
    for k in ("total_explicit", "ratio_src", "nights_total", "vague_reason"):    # 코드만 정하는 값 (AI 출력에 있어도 무시)
        rule.pop(k, None)
    # 코드 안전망: 작은 모델이 문장 속 금액·%를 놓치거나 잘못 갈라도 코드가 직접 읽는다 (같은 질문 반복 방지, 0 tokens)
    code = normalize_rule(_mock_rule(text, members, total, subject), members)
    fixed = _merge_backstop(rule, code)
    if fixed:
        metas.append(llm.code_step("settlement.analyze", flow, "0 tokens (code-only): AI가 놓친 조건을 코드가 읽음 — " + ", ".join(fixed)))
    bad = prohibited_reason(" ".join([text, subject or ""] + (history or [])[-2:]))
    if bad or rule["prohibited"]:
        metas.append(llm.code_step("settlement.policy", flow, f"0 tokens (code-only): 불법 목적 차단 ({bad or 'AI 판단'})"))
        return {"status": "refused", "code": "PROHIBITED_PURPOSE", "question": REFUSE_MSG, "rule": rule, "metas": metas}
    if "vague" in (rule.get("missing") or []):
        return {"status": "need_info", "missing": ["vague"], "question": rule.get("question") or "모호한 조건이 있어요. 정확한 금액이나 비율로 알려주세요.",
                "rule": rule, "metas": metas}
    if rule.get("pct_unknown"):
        n = rule["pct_unknown"]
        return {"status": "need_info", "missing": ["vague"], "rule": rule, "metas": metas,
                "question": f"{n:g}%가 무엇에 붙는지 알려 주세요. 예: 부가세 {n:g}% 더해서 / {n:g}% 할인받았어 / 진주는 {n:g}% 더"}

    final_members = _resolve_members(rule, members, text)
    adjustments = list(rule["adjustments"])
    excluded = {a["name"] for a in adjustments if a["kind"] == "exclude"}
    active = [m for m in final_members if m not in excluded]
    if rule.get("nights_total"):                         # '3박 중 진주는 2박' → 나머지 사람은 전체 박수
        adjusted = {a["name"] for a in adjustments}
        adjustments += [{"name": m, "kind": "ratio", "value": rule["nights_total"]} for m in active if m not in adjusted]
    rule["adjustments"] = adjustments
    item_adj, err = _item_deltas(rule.get("items") or [], active)
    if err:
        return {"status": "need_info", "missing": ["members"], "question": err, "rule": rule, "metas": metas}
    calc_adj = adjustments + item_adj
    final_total, err = _final_total(rule, total, final_members, calc_adj)
    if err:
        return {"status": "need_info", "missing": ["total_amount"], "question": err, "rule": rule, "metas": metas}
    if rule.get("total_note"):
        metas.append(llm.code_step("settlement.calculate", flow, f"0 tokens (code-only): 총액 = {rule['total_note']}"))
    missing = []
    if not final_total:
        missing.append("total_amount")
    if len(final_members) < 2:
        missing.append("members")
    stated = parse_people(text)
    if stated and stated not in (len(final_members), len(active)) and "나머지" not in text and not rule.get("items"):
        missing.append("members")
        rule["question"] = (f"{stated}명이 누구인가요? 지금 참여자는 {', '.join(final_members)}이에요." if final_members
                            else f"{stated}명이 누구인가요? 참여자 이름을 알려주세요.")
    if missing:
        q = rule.get("question") or ("나눌 총금액과 참여자를 알려주세요." if len(missing) == 2 else
                                     ("나눌 총금액은 얼마인가요?" if missing == ["total_amount"] else "누구와 나누시나요?"))
        return {"status": "need_info", "missing": missing, "question": q, "rule": rule, "metas": metas}
    items_sum = sum(it["amount"] for it in rule.get("items") or [])
    if items_sum and not rule.get("per_person_amount") and items_sum > final_total:
        return {"status": "need_info", "missing": ["total_amount"], "rule": rule, "metas": metas,
                "question": f"일부 사람만 나누는 항목 합({items_sum:,}원)이 총액({final_total:,}원)보다 커요. 총액을 다시 알려 주세요."}

    rp = rule.get("payer")
    said = bool(rp and re.search(re.escape(rp) + r".{0,8}(결제|계산|냈|샀|카드|긁|주문)", text))
    # 문장에서 '진주가 결제했어'처럼 결제자를 말했으면 그 사람이 받는 사람 (에스크로 지급 대상)
    payer_final = rp if (said and rp in final_members) else (
        payer if payer in final_members else (rp if rp in final_members else final_members[0]))
    try:
        shares = money.compute_shares(int(final_total), final_members, calc_adj)
    except money.CalcError as e:
        return {"status": "error", "code": e.code, "question": e.message, "rule": rule, "metas": metas}
    if rule.get("round_unit"):
        unit = rule["round_unit"]
        keep = {a["name"] for a in adjustments if a["kind"] == "fixed"}
        rs = money.round_shares(shares, unit, payer_final, keep)
        if rs is None:
            rule["round_note"] = f"{unit:,}원 단위로 맞추면 결제자 몫이 0원 아래라 1원 단위 그대로 뒀어요"
        else:
            anchor = payer_final if payer_final in dict(shares) else shares[0][0]
            diff = dict(rs)[anchor] - dict(shares)[anchor]
            shares = rs
            rule["round_note"] = f"{unit:,}원 단위로 맞춤" + (f" (차액 {diff:+,}원은 {anchor}님 몫에서 조정)" if diff else "")
    assert sum(a for _, a in shares) == int(final_total), "합계 검증 실패"
    metas.append(llm.code_step("settlement.calculate", flow, "0 tokens (code-only): Σshare == total 검증"))

    pre = money.policy_check(total=int(final_total), shares=shares, payer=payer_final,
                             per_person_cap=rule.get("per_person_cap"), total_cap=rule.get("total_cap"))
    subject = subject or rule.get("subject")
    fallback = _default_purpose(subject, {**rule, "payer": payer_final})
    purpose = sanitize_purpose(rule.get("purpose") or "", final_members, fallback)
    return {
        "status": "ok",
        "total": int(final_total),
        "members": final_members,
        "payer": payer_final,
        "shares": [[n, a] for n, a in shares],
        "rule": {k: rule.get(k) for k in ("adjustments", "per_person_cap", "total_cap", "total_note", "items", "round_unit",
                                          "round_note", "amount_parts", "per_person_amount")},
        "rule_text": text,
        "subject": subject,
        "purpose": purpose,
        "warnings": [v.to_dict() for v in pre],
        "metas": metas,
    }


def describe(result: dict[str, Any], subject: str | None) -> str:
    """계산 결과를 사람이 읽는 문장으로 (코드 템플릿, 토큰 0)."""
    shares = result["shares"]
    amounts = {a for _, a in shares}
    head = f"{subject + ' ' if subject else ''}총 {won(result['total'])}을 {len(shares)}명 기준으로 계산했어요."
    if len(amounts) == 1:
        body = f" 1인 {won(shares[0][1])}씩 균등하게 부담해요."
    else:
        body = " " + ", ".join(f"{n} {won(a)}" for n, a in shares) + "."
    rule = result.get("rule") or {}
    if rule.get("total_note"):
        body += f" 총액은 {rule['total_note']}로 계산했어요."
    for it in rule.get("items") or []:
        body += f" {it.get('label') or '일부 항목'} {won(it['amount'])}은 {'·'.join(it['members'])}님만 나눴어요."
    if rule.get("round_note"):
        body += f" {rule['round_note']}."
    caps = []
    if rule.get("per_person_cap"):
        caps.append(f"1인 한도 {won(rule['per_person_cap'])}")
    if rule.get("total_cap"):
        caps.append(f"총 한도 {won(rule['total_cap'])}")
    tail = f" (지출 한도: {', '.join(caps)})" if caps else ""
    if result["warnings"]:
        tail += " ⚠️ " + " / ".join(w["message"] for w in result["warnings"]) + " → 이대로 요청하면 결제가 중단되고 중단 기록이 블록체인에 남아요."
    return head + body + tail


EXPLAIN_SYSTEM = """너는 Share Pie 정산 설명 담당이다. 코드가 계산한 결과(숫자)를 바꾸지 말고 그대로 인용해
왜 이렇게 나뉘었는지 한국어 2~3문장으로 설명한다. 한도 초과 경고가 있으면 결제가 중단된다는 점을 분명히 말한다. 이모지 금지."""


def explain(result: dict[str, Any], subject: str | None, flow: str | None = None) -> tuple[str, dict[str, Any]]:
    """Stage 3 — 계산 결과를 자연어로 설명 (settlement.explain). 숫자는 코드 결과 그대로."""
    facts = [f"정산: {subject or result.get('subject') or '공동 비용'} / 총 {won(result['total'])} / 결제자 {result['payer']}",
             "분담: " + ", ".join(f"{n} {won(a)}" for n, a in result["shares"]),
             f"조건 원문: {result['rule_text']}"]
    rule = result.get("rule") or {}
    adj = rule.get("adjustments") or []
    if adj:
        facts.append("적용 규칙: " + ", ".join(f"{a.get('name')} {a.get('kind')} {a.get('value')}" for a in adj if isinstance(a, dict)))
    if rule.get("total_note"):
        facts.append(f"총액 근거(코드 계산): {rule['total_note']}")
    if rule.get("items"):
        facts.append("일부만 나눈 항목: " + ", ".join(f"{it.get('label') or '항목'} {won(it['amount'])} → {'·'.join(it['members'])}"
                                                for it in rule["items"]))
    if rule.get("round_note"):
        facts.append(f"단위 맞춤: {rule['round_note']}")
    if result["warnings"]:
        facts.append("경고: " + " / ".join(w["message"] for w in result["warnings"]))
    text, meta = llm.client.call_text("settlement.explain", EXPLAIN_SYSTEM, "\n".join(facts),
                                      mock=lambda: describe(result, subject), flow=flow, max_tokens=500)
    if meta.get("mode") in ("tools", "json", "text"):
        llm.decision("settlement.explain", flow, f"Kiln 응답 → 결과 설명 {len(text)}자를 확인 카드·말풍선에 표시 (숫자는 코드 결과 그대로)")
    return text, meta
