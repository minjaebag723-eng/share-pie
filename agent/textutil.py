"""한국어 금액/인원 파싱 — LLM 없이 코드로 처리하는 부분 (토큰 0)."""
from __future__ import annotations

import re

_NUM_WORDS = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}

# 한국어 금액: 35,900원 / 3만5천원 / 1.5만원 / 10만 / 1억 5천만원 / 2백만원 / 만2천원 / 만오천원 / 삼만오천원 / 이십만원 / 천오백원 / 만 원
# 숫자는 아라비아 숫자나 한글 숫자(일~구, 단위 바로 앞에서만). 단위(십·백·천·만·억)가 있거나 '원'이 붙어야 금액이다 → '4명'·'2kg' 제외.
# 단위나 한글 숫자로 시작하는 금액은 한글 바로 뒤에서 시작하지 않는다 → '진주만 2천원'의 '만'·'셋이 만원'의 '이'는 금액이 아님.
# 한글만으로 된 금액('만원'·'오천원')은 '원'이 있어야 한다 → '만약'·'천천히'·'이만 가자' 제외.
_NUM = r"\d[\d,]*(?:\.\d+)?"
_KN = "일이삼사오육칠팔구"
_KNV = {c: i + 1 for i, c in enumerate(_KN)}
_UV = {"십": 10, "백": 100, "천": 1_000, "만": 10_000, "억": 100_000_000}
_TOK = rf"(?:{_NUM}\s*[억만천백십]|[{_KN}][억만천백십]|[억만천백십])"
_CHUNK = re.compile(rf"(?:(?<![\d.,])(?=\d)|(?<![\d.,가-힣A-Za-z]))(?:{_TOK}\s*)+(?:{_NUM})?\s*(?:원(?!래))?"
                    rf"|(?<![\d.,]){_NUM}\s*원(?!래)")
_SEG = re.compile(rf"({_NUM})|([{_KN}])|([억만천백십])")


def _chunk_value(chunk: str) -> int:
    """한국어 수 읽기: 십·백·천은 작은 수를 쌓고, 만·억은 그 수(없으면 1)를 곱한다.
    '만2천' → 12,000 · '삼만오천' → 35,000 · '이십만' → 200,000 · '1억 5천만' → 150,000,000 · '3만5000' → 35,000."""
    big, small, cur = 0.0, 0.0, None
    for num, kn, unit in _SEG.findall(chunk.replace("원", "")):
        if num:
            cur = float(num.replace(",", ""))
        elif kn:
            cur = float(_KNV[kn])
        else:
            u = _UV[unit]
            if u < 10_000:
                small += (cur if cur is not None else 1) * u
            else:
                n = small + (cur or 0)
                big += (n if n else 1) * u
                small = 0.0
            cur = None
    return int(round(big + small + (cur or 0)))


def amount_spans(text: str) -> list[tuple[int, int, int]]:
    """문장 안의 금액을 (시작, 끝, 값)으로 등장 순서대로 (끝 공백 제외). 정산 해석이 '어느 금액이 어디에 붙었는지' 볼 때 쓴다."""
    out: list[tuple[int, int, int]] = []
    for m in _CHUNK.finditer(text or ""):
        chunk = m.group(0).rstrip()
        if not re.search(r"\d", chunk) and not chunk.endswith("원"):
            continue                                   # 한글만인데 '원'이 없으면 금액 아님
        if not re.search(r"[억만천백십]", chunk) and not chunk.endswith("원"):
            continue
        v = _chunk_value(chunk)
        if v > 0:
            out.append((m.start(), m.start() + len(chunk), v))
    return out


def parse_amounts(text: str) -> list[int]:
    """문장 안의 금액을 등장 순서대로 모두 반환 (코드 전용 · 토큰 0)."""
    return [v for _, _, v in amount_spans(text)]


def to_int(v, default=None):
    """LLM이 준 값을 정수로: 38900 / 38900.0 / "38,900원" / "15만원" / "4명" / "2개" → 정수, 못 읽으면 default."""
    if v is None or isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return int(round(v))
    t = str(v).strip()
    if not t:
        return default
    if re.search(r"\d\s*(억|만|천|백)|원", t):
        a = parse_amounts(t if "원" in t else t + "원")
        if a:
            return a[0]
    m = re.search(r"-?\d[\d,]*(\.\d+)?", t)
    if not m:
        return default
    try:
        return int(round(float(m.group(0).replace(",", ""))))
    except ValueError:
        return default


def to_num(v, default=None):
    """비율·퍼센트용 실수 (1.5배, 33.3%)."""
    if v is None or isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(\.\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else default


_GROUP_WORDS = {"둘": 2, "셋": 3, "넷": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}


def parse_people(text: str) -> int | None:
    """'4명' · '세 명' · '셋이(서)' · '넷이' → 인원 수. ('한 명당'·'1명당'은 인원이 아니라 1인 기준)"""
    m = re.search(r"(\d+)\s*명(?!\s*당)", text)
    if m:
        return int(m.group(1))
    for w, n in _NUM_WORDS.items():
        if re.search(rf"(?<![가-힣]){w}\s*명(?!\s*당)", text):
            return n
    m = re.search(r"(?<![가-힣])(둘|셋|넷|다섯|여섯|일곱|여덟|아홉)\s*(?:이서|이|서)(?:만|도|는|면)?(?![가-힣])", text or "")
    if m:
        return _GROUP_WORDS[m.group(1)]
    return None


def names_in(text: str, candidates: list[str]) -> list[str]:
    return [c for c in candidates if c and c in text]


def won(n: int) -> str:
    return f"{int(n):,}원"


def josa(word: str, pair: str = "은/는") -> str:
    """받침 유무로 조사 선택: josa('귤 5kg') → '귤 5kg은'"""
    a, b = pair.split("/")
    ch = word.rstrip()[-1:] if word.strip() else ""
    if "가" <= ch <= "힣":
        has = (ord(ch) - 0xAC00) % 28 != 0
    else:
        has = ch.lower() in "013678glnr"  # 숫자·영문 끝 (kg→그램, 1→일 …) 대략
    return word + (a if has else b)
