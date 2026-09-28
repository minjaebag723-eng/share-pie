"""분담금 계산 + 지출 통제 정책 — 전부 결정론적 코드 (LLM 산수 오류 방지, 토큰 0).

LLM이 뽑아준 '규칙(rule)'만 받아 계산한다.
rule = {
  "total_amount": int|None,
  "adjustments": [{"name": str, "kind": "less"|"more"|"fixed"|"exclude"|"ratio"|"percent"|"more_pct"|"less_pct",
                   "value": number}],
  "per_person_cap": int|None, "total_cap": int|None, "payer": str|None
}
계산은 분수(Fraction)로 정확히 한 뒤 1원 단위로 최대잔여법 반올림 → Σ share == total 보장.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from .textutil import to_int, to_num


class CalcError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def match_member(name, members: list[str]) -> str | None:
    """'김진주'·'진주님' → 멤버 '진주' (LLM이 성까지 붙이거나 호칭을 붙여도 연결)."""
    if not name:
        return None
    n = str(name).strip()
    if n in members:
        return n
    n2 = n.removesuffix("님").removesuffix("씨").strip()
    if n2 in members:
        return n2
    hits = [m for m in members if m and (n2.endswith(m) or m.endswith(n2)) and min(len(m), len(n2)) >= 2]
    return hits[0] if len(hits) == 1 else None


def _frac(v) -> Fraction:
    """1.2 → 6/5 (이진 소수 오차 없이 정확한 분수로 계산 — 1원 단위 반올림이 흔들리지 않게)."""
    return Fraction(str(v)) if isinstance(v, float) else Fraction(v)


def _parse_adjustments(members: list[str], adjustments: list[dict[str, Any]]):
    excluded, fixed, delta, weight, pct, mult = set(), {}, {}, {}, {}, {}
    for a in adjustments or []:
        if not isinstance(a, dict):
            continue
        name, kind = match_member(a.get("name"), members), a.get("kind")
        value = to_int(a.get("value"), 0) or 0
        num = to_num(a.get("value"), 0) or 0
        if not name:
            continue  # LLM이 없는 사람을 지어내도 무시
        if kind == "exclude":
            excluded.add(name)
        elif kind == "fixed":
            fixed[name] = value
        elif kind == "less":
            delta[name] = delta.get(name, 0) - abs(value)
        elif kind == "more":
            delta[name] = delta.get(name, 0) + abs(value)
        elif kind == "ratio" and num > 0:
            weight[name] = _frac(num)                       # 1.5배·절반(0.5)도 그대로
        elif kind == "percent" and num > 0:
            pct[name] = _frac(num)
        elif kind == "more_pct" and 0 < num <= 500:        # '남보다 N% 더' → 다른 사람 몫의 (1 + N%)배
            mult[name] = mult.get(name, Fraction(1)) * (1 + _frac(num) / 100)
        elif kind == "less_pct" and 0 < num < 100:         # '남보다 N% 덜' → (1 − N%)배
            mult[name] = mult.get(name, Fraction(1)) * (1 - _frac(num) / 100)
    return excluded, fixed, delta, weight, pct, mult


def _weights(flex: list[str], weight, pct, mult) -> dict[str, Fraction]:
    if pct:  # 'A 40%, 나머지 균등' → 언급 안 된 사람은 남은 %를 똑같이 (N% 더·덜이 있으면 그만큼 기울여)
        named = [m for m in flex if m in pct]
        others = [m for m in flex if m not in pct]
        left = 100 - sum(pct[m] for m in named)
        if left < 0:
            raise CalcError("CALC_ERROR", f"비율 합계가 100%를 넘어요 ({float(100 - left):g}%).")
        if others and left <= 0:
            raise CalcError("CALC_ERROR", "나머지 사람에게 남는 비율이 없어요. 비율을 다시 알려 주세요.")
        w = {m: pct[m] for m in named}
        mo = {m: mult.get(m, Fraction(1)) * weight.get(m, Fraction(1)) for m in others}
        for m in others:
            w[m] = left * mo[m] / sum(mo.values())
        return w
    return {m: weight.get(m, Fraction(1)) * mult.get(m, Fraction(1)) for m in flex}


def compute_shares(total: int, members: list[str], adjustments: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """share_i = weight_i · x + delta_i,  Σ share = total  →  x 를 풀고 1원 단위 최대잔여법으로 반올림.

    예) 총 35,900 / 진주 5,000원 적게 → x = (35,900 + 5,000)/4 = 10,225 → 진주 5,225, 나머지 10,225
    예) 총 30,000 / 진주 20% 더(more_pct) → 가중치 1.2 : 1 : 1 → 진주 11,250, 나머지 9,375
    """
    total = to_int(total)
    if not total or total <= 0:
        raise CalcError("CALC_ERROR", "총액이 0원 이하예요.")
    if not members:
        raise CalcError("CALC_ERROR", "참여자가 없어요.")

    excluded, fixed, delta, weight, pct, mult = _parse_adjustments(members, adjustments)
    active = [m for m in members if m not in excluded]
    flex = [m for m in active if m not in fixed]
    rest = total - sum(fixed.values())
    if not flex:
        if rest != 0:
            raise CalcError("CALC_ERROR", f"고정 금액 합계가 총액과 {abs(rest):,}원 차이나요.")
        return [(m, fixed.get(m, 0)) for m in active]

    w = _weights(flex, weight, pct, mult)
    if sum(w.values()) <= 0:
        raise CalcError("CALC_ERROR", "나눌 비율이 0이에요. 조건을 다시 알려 주세요.")
    x = (rest - sum(delta.get(m, 0) for m in flex)) / sum(w.values())
    raw = {m: w[m] * x + delta.get(m, 0) for m in flex}
    floor = {m: math.floor(raw[m]) for m in flex}
    remainder = rest - sum(floor.values())
    for m in sorted(flex, key=lambda k: (-(raw[k] - floor[k]), flex.index(k)))[:remainder]:
        floor[m] += 1

    shares = [(m, fixed[m] if m in fixed else int(floor[m])) for m in active]
    neg = [m for m, v in shares if v < 0]
    if neg:
        raise CalcError("CALC_ERROR", f"{', '.join(neg)}님의 부담액이 0원 아래로 내려가요. 조건을 확인해 주세요.")
    assert sum(v for _, v in shares) == total, "합계 검증 실패"
    return shares


def total_from_unit(unit: int, members: list[str], adjustments: list[dict[str, Any]]) -> int:
    """'한 명당 X원씩' → 총액 (조정 없는 사람이 정확히 X원을 내도록: Σ(w_i·X + delta_i) + Σfixed)."""
    unit = to_int(unit)
    if not unit or unit <= 0:
        raise CalcError("CALC_ERROR", "1인당 금액이 0원 이하예요.")
    excluded, fixed, delta, weight, pct, mult = _parse_adjustments(members, adjustments)
    if pct:
        raise CalcError("CALC_ERROR", "‘한 명당 금액’과 ‘전체의 N%’는 함께 쓸 수 없어요. 둘 중 하나로 알려 주세요.")
    flex = [m for m in members if m not in excluded and m not in fixed]
    w = _weights(flex, weight, pct, mult)
    t = sum(w[m] * unit + delta.get(m, 0) for m in flex) + sum(fixed.values())
    return int(round(t))


def round_shares(shares: list[tuple[str, int]], unit: int, anchor: str | None,
                 keep: set[str] | None = None) -> list[tuple[str, int]] | None:
    """'천원 단위로' → 나머지 사람 몫을 unit 단위로 반올림하고 차액은 anchor(결제자)가 맡는다. Σ는 그대로.
    anchor 몫이 0원 아래로 내려가면 None (단위 맞춤 불가)."""
    names = [n for n, _ in shares]
    if not names or not unit or unit <= 1:
        return shares
    out = dict(shares)
    total = sum(out.values())
    anchor = anchor if anchor in out else names[0]
    for n in names:
        if n != anchor and n not in (keep or set()):
            out[n] = (out[n] + unit // 2) // unit * unit
    out[anchor] = total - sum(v for n, v in out.items() if n != anchor)
    if out[anchor] < 0:
        return None
    return [(n, out[n]) for n in names]


# ── 지출 통제 ──
REASON = {
    "SUM_MISMATCH": (1, "분담액 합계가 총액과 달라요"),
    "OVER_PERSON_CAP": (2, "1인 예산 한도를 넘었어요"),
    "INSUFFICIENT_BALANCE": (3, "지갑 가용 잔액이 부족해요"),
    "MERCHANT_NOT_ALLOWED": (4, "허용되지 않은 가맹점이에요"),
    "OVER_TOTAL_CAP": (5, "총 예산 한도를 넘었어요"),
}


@dataclass
class Violation:
    code: str
    member: str | None
    message: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reason_code(self) -> int:
        return REASON[self.code][0]

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "reason_code": self.reason_code, "member": self.member,
                "message": self.message, "detail": self.detail}

    def chain_note(self) -> str:
        """체인에 남는 메모 — 공개 장부이므로 실명 없이 숫자만."""
        d = self.detail
        if self.code == "OVER_PERSON_CAP":
            return f"share {d['share']} > cap {d['cap']}"
        if self.code == "INSUFFICIENT_BALANCE":
            return f"share {d['share']} > available {d['available']}"
        if self.code == "OVER_TOTAL_CAP":
            return f"total {d['total']} > cap {d['cap']}"
        if self.code == "SUM_MISMATCH":
            return f"sum {d['sum']} != total {d['total']}"
        if self.code == "MERCHANT_NOT_ALLOWED":
            return "merchant not allowed"
        return self.code


def merchant_allowed(merchant: str, allowed: list[str]) -> bool:
    """허용 가맹점 검사. 짧은 영문 이름(CU·SSG)은 단어 단위로만 일치 (예: 'CU'가 'Cucina'에 걸리지 않게)."""
    import re
    raw = (merchant or "").lower()
    m = raw.replace(" ", "")
    for a in allowed or []:
        if not a:
            continue
        al = a.lower().replace(" ", "")
        if re.fullmatch(r"[a-z0-9]{1,4}", al):
            if re.search(rf"(?<![a-z0-9]){re.escape(al)}(?![a-z0-9])", raw):
                return True
        elif al in m:
            return True
    return False


def policy_check(*, total: int, shares: list[tuple[str, int]], payer: str | None,
                 per_person_cap: int | None = None, total_cap: int | None = None,
                 merchant: str | None = None, allowed_merchants: list[str] | None = None,
                 available: dict[str, int] | None = None) -> list[Violation]:
    """결제 전에 반드시 통과해야 하는 검사. 하나라도 걸리면 정산은 '중단'되고 체인에 Blocked가 남는다."""
    v: list[Violation] = []
    per_person_cap, total_cap = to_int(per_person_cap), to_int(total_cap)
    s = sum(a for _, a in shares)
    if s != total:
        v.append(Violation("SUM_MISMATCH", None, f"분담액 합계 {s:,}원 ≠ 총액 {total:,}원", {"sum": s, "total": total}))
    if total_cap and total > total_cap:
        v.append(Violation("OVER_TOTAL_CAP", None, f"총액 {total:,}원이 총 예산 {total_cap:,}원을 넘어요",
                           {"total": total, "cap": total_cap}))
    if per_person_cap:
        for name, amt in shares:
            if amt > per_person_cap:
                v.append(Violation("OVER_PERSON_CAP", name, f"{name}님 {amt:,}원 > 1인 한도 {per_person_cap:,}원",
                                   {"share": amt, "cap": per_person_cap}))
    if merchant and allowed_merchants and not merchant_allowed(merchant, allowed_merchants):
        v.append(Violation("MERCHANT_NOT_ALLOWED", None, f"'{merchant}'은(는) 허용 가맹점이 아니에요 (허용: {', '.join(allowed_merchants)})",
                           {"merchant": merchant}))
    if available is not None:
        for name, amt in shares:
            if name == payer:
                continue  # 결제자 본인 몫은 이미 가맹점에 지불
            av = available.get(name)
            if av is not None and av < amt:
                v.append(Violation("INSUFFICIENT_BALANCE", name, f"{name}님 가용 잔액 {av:,}원 < 부담액 {amt:,}원",
                                   {"share": amt, "available": av}))
    return v
