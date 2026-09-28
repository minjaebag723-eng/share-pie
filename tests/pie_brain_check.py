"""Pie mate 학습 파일 형식 검사 — 「Pie mate 학습 가이드라인」 ①②③ · 평가 세트 · 절대 규칙 기준.

서버·Kiln 없이 파일만 읽어 검사한다 (토큰 0). 파일을 고칠 때마다 먼저 돌린다.
    py tests/pie_brain_check.py          → 오류가 있으면 종료 코드 1
    py tests/pie_brain_check.py --quiet  → 요약만

검사: persona(섹션 6개 순서·1,200자) · modes(chat/group·섹션당 300자) · examples(필드·태그·태그별 최소 개수·
ideal 250자·mode 비율·④ 상황/도메인) · knowledge(조각 400자·키워드 줄·30조각) · pie_eval(필드·80문제·④ 채점 문제) ·
예시↔평가↔계산 파일 문장 중복 · 개인정보(이메일·전화·지갑 주소·API 키) · 화면에 없는 버튼 이름(따옴표 문구, 경고).
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "agent" / "pie_brain"
UI = ROOT / "frontend" / "index.html"

TAG_MIN = {"settle": 8, "settle_ask": 6, "settle_change": 5, "status": 5, "pending": 3, "shop": 10,
           "dispute": 6, "howto": 8, "name_call": 3, "refuse": 3, "offtopic": 5}
SITUATIONS = ["가격", "양", "품질", "경험", "판단 없음"]
DOMAINS = ["음식·배달", "여행", "물품", "기타"]
MAIN_DOMAINS = ["음식·배달", "여행", "물품"]
MODES = {"both", "chat", "group"}
EXPECTS = {"card", "refuse", "ask", "silent"}
PERSONA_SECTIONS = ["정체성", "말투", "반드시", "금지", "되묻기", "답 형식"]
KNOWLEDGE_FILES = ["settle_flow", "rules", "use_cases", "wallet", "dispute", "groupbuy", "rooms", "ai_pay", "about"]
EX_FIELDS = {"id", "tags", "situation", "domain", "mode", "room", "history", "user", "ideal", "why", "bad"}
EV_FIELDS = {"id", "tags", "mode", "room", "history", "user", "must", "must_any", "must_not", "expect",
             "expect_situation", "expect_domain", "max_chars"}
TOOL_NAMES = re.compile(r"split_cost|search_products|web_search|menu_price_search|check_delivery_combos|set_split_rule")
PII = [(re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}"), "이메일"), (re.compile(r"01[016789]-?\d{3,4}-?\d{4}"), "전화번호"),
       (re.compile(r"0x[0-9a-fA-F]{40}"), "지갑 주소"), (re.compile(r"sk-[A-Za-z0-9_-]{10,}"), "API 키")]
MARKDOWN = re.compile(r"\*\*|`|^\s*#", re.M)
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
QUOTED = re.compile(r"'([^'\n]{2,40})'|‘([^’\n]{2,40})’")

errors: list[str] = []
warnings: list[str] = []
stats: list[str] = []


def err(where: str, msg: str) -> None:
    errors.append(f"✗ {where}: {msg}")


def warn(where: str, msg: str) -> None:
    warnings.append(f"! {where}: {msg}")


def norm(t: str) -> str:
    return re.sub(r"[\s\W_]+", "", t or "").lower()


def pii_check(where: str, text: str) -> None:
    for rx, label in PII:
        if rx.search(text or ""):
            err(where, f"개인정보·비밀값으로 보이는 {label}이(가) 들어 있음")


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        err(path.name, "파일이 없음")
        return rows
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            err(f"{path.name}:{n}", f"JSON 문법 오류 — {e}")
    return rows


def sections(text: str, level: str) -> list[tuple[str, str]]:
    """('## 제목', 본문) 목록 — 제목 앞 텍스트는 버림."""
    out, cur, buf = [], None, []
    for line in text.splitlines():
        if line.startswith(level + " ") and not line.startswith(level + "#"):
            if cur is not None:
                out.append((cur, "\n".join(buf).strip()))
            cur, buf = line[len(level) + 1:].strip(), []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out.append((cur, "\n".join(buf).strip()))
    return out


# ───────── ① persona.md ─────────
def check_persona() -> str:
    p = BRAIN / "persona.md"
    if not p.exists():
        err("persona.md", "파일이 없음")
        return ""
    t = p.read_text(encoding="utf-8")
    secs = sections(t, "#")
    names = [s[0] for s in secs]
    if names != PERSONA_SECTIONS:
        err("persona.md", f"섹션은 {PERSONA_SECTIONS} 순서로 6개여야 함 (지금: {names})")
    n = len(t.strip())
    if n > 1200:
        err("persona.md", f"{n}자 — 1,200자 이하여야 함")
    must = dict(secs).get("반드시", "")
    k = len([x for x in must.splitlines() if x.strip().startswith("-")])
    if k > 6:
        err("persona.md", f"'반드시' 항목 {k}개 — 6개 이하")
    if TOOL_NAMES.search(t):
        err("persona.md", "도구 이름은 persona에 쓰지 않음 (코드가 따로 넣음)")
    pii_check("persona.md", t)
    stats.append(f"persona {n}자 / 1,200")
    return t


# ───────── ② modes.md ─────────
def check_modes() -> str:
    p = BRAIN / "modes.md"
    if not p.exists():
        err("modes.md", "파일이 없음")
        return ""
    t = p.read_text(encoding="utf-8")
    secs = sections(t, "##")
    names = [s[0] for s in secs]
    if names != ["chat", "group"]:
        err("modes.md", f"섹션은 '## chat', '## group' 두 개여야 함 (지금: {names})")
    for name, body in secs:
        if len(body) > 300:
            err("modes.md", f"## {name} {len(body)}자 — 섹션당 300자 이하")
    stats.append("modes " + " · ".join(f"{n} {len(b)}자" for n, b in secs) + " / 300")
    return t


# ───────── ② examples.jsonl ─────────
def check_examples() -> list[dict]:
    rows = read_jsonl(BRAIN / "examples.jsonl")
    ids = Counter(r.get("id") for r in rows)
    for i, c in ids.items():
        if c > 1:
            err("examples", f"id 중복 {i}")
    tag_count: Counter = Counter()
    modes: Counter = Counter()
    sit: Counter = Counter()
    dom: Counter = Counter()
    for r in rows:
        w = f"examples {r.get('id', '?')}"
        extra = set(r) - EX_FIELDS
        if extra:
            err(w, f"모르는 필드 {sorted(extra)}")
        for f in ("id", "tags", "mode", "user", "ideal"):
            if f not in r:
                err(w, f"필수 필드 '{f}' 없음")
        tags = r.get("tags") or []
        if not (1 <= len(tags) <= 2) or any(x not in TAG_MIN for x in tags):
            err(w, f"tags는 목록의 태그 1~2개 (지금: {tags})")
        tag_count.update(tags)
        mode = r.get("mode")
        if mode not in MODES:
            err(w, f"mode는 both·chat·group (지금: {mode})")
        modes[mode] += 1
        if "shop" in tags:
            if r.get("situation") not in SITUATIONS:
                err(w, f"shop 예시는 situation 필수 {SITUATIONS}")
            if r.get("domain") not in DOMAINS:
                err(w, f"shop 예시는 domain 필수 {DOMAINS}")
            sit[r.get("situation")] += 1
            dom[r.get("domain")] += 1
        if ("name_call" in tags) and mode != "group":
            err(w, "name_call은 그룹에서만 의미 있음 → mode group")
        hist = r.get("history") or []
        if len(hist) > 4 or any(set(h) != {"who", "text"} for h in hist):
            err(w, "history는 {who, text} 최대 4개")
        u = r.get("user") or {}
        if set(u) != {"who", "text"} or not (u.get("text") or "").strip():
            err(w, "user는 {who, text}")
        ideal = r.get("ideal") or ""
        if len(ideal) > 250:
            err(w, f"ideal {len(ideal)}자 — 250자 이하")
        if MARKDOWN.search(ideal) or EMOJI.search(ideal):
            err(w, "ideal에 마크다운·이모지 금지 (앱은 일반 텍스트)")
        if "도구" in ideal or TOOL_NAMES.search(ideal):
            err(w, "ideal에 '도구'·도구 이름을 쓰지 않음")
        if mode == "both" and re.search(r"확인 카드|확인 · 정산 시작", ideal):
            err(w, "both 예시에 그룹 전용 표현(확인 카드) — mode를 group으로")
        pii_check(w, json.dumps(r, ensure_ascii=False))
    n = len(rows)
    if n < 62:
        err("examples", f"{n}개 — 62개 이상")
    for t, m in TAG_MIN.items():
        if tag_count[t] < m:
            err("examples", f"태그 {t} {tag_count[t]}개 — 최소 {m}개")
    both = modes["both"] / n if n else 0
    if both < 0.70:
        err("examples", f"both 비율 {both:.0%} — 70% 이상")
    for m in ("chat", "group"):
        share = modes[m] / n if n else 0
        if not 0.08 <= share <= 0.22:
            warn("examples", f"{m} 비율 {share:.0%} — 15% 안팎 권장")
    for s in SITUATIONS:
        if sit[s] < 2:
            err("examples", f"shop 상황 '{s}' {sit[s]}개 — 상황마다 2개 이상")
    for d in MAIN_DOMAINS:
        if dom[d] < 3:
            err("examples", f"shop 도메인 '{d}' {dom[d]}개 — 도메인별 3개 이상")
    stats.append(f"examples {n}개 · both {modes['both']} / chat {modes['chat']} / group {modes['group']} "
                 f"({both:.0%} both) · 태그 " + ", ".join(f"{t} {tag_count[t]}" for t in TAG_MIN))
    stats.append("  shop 상황 " + ", ".join(f"{s} {sit[s]}" for s in SITUATIONS) + " · 도메인 "
                 + ", ".join(f"{d} {dom[d]}" for d in DOMAINS))
    return rows


# ───────── ③ knowledge/*.md ─────────
def check_knowledge() -> list[tuple[str, str, str]]:
    kdir = BRAIN / "knowledge"
    chunks = []
    for name in KNOWLEDGE_FILES:
        p = kdir / f"{name}.md"
        if not p.exists():
            err("knowledge", f"{name}.md 없음")
            continue
        secs = sections(p.read_text(encoding="utf-8"), "##")
        if not secs:
            err(f"knowledge/{name}.md", "## 조각이 없음")
        for title, body in secs:
            w = f"knowledge/{name}.md ## {title}"
            size = len(f"## {title}\n{body}")
            if size > 400:
                err(w, f"{size}자 — 조각당 400자 이하 (길면 나누기)")
            if not re.search(r"^키워드:\s*\S", body, re.M):
                err(w, "'키워드:' 줄이 없음")
            if MARKDOWN.search(body.replace("키워드:", "")) or EMOJI.search(body):
                warn(w, "마크다운 기호·이모지가 있음")
            pii_check(w, body)
            chunks.append((name, title, body))
    for extra in sorted(set(x.stem for x in kdir.glob("*.md")) - set(KNOWLEDGE_FILES)):
        warn("knowledge", f"가이드라인 목록에 없는 파일 {extra}.md (로더가 읽는지 확인)")
    if len(chunks) < 30:
        err("knowledge", f"{len(chunks)}조각 — 30조각 이상")
    per = Counter(c[0] for c in chunks)
    stats.append(f"knowledge {len(chunks)}조각 · " + ", ".join(f"{k} {per[k]}" for k in KNOWLEDGE_FILES))
    return chunks


# ───────── 평가 세트 tests/pie_eval.jsonl ─────────
def check_eval() -> list[dict]:
    rows = read_jsonl(ROOT / "tests" / "pie_eval.jsonl")
    ids = Counter(r.get("id") for r in rows)
    for i, c in ids.items():
        if c > 1:
            err("pie_eval", f"id 중복 {i}")
    tag_count: Counter = Counter()
    sit: Counter = Counter()
    dom: Counter = Counter()
    expects: Counter = Counter()
    for r in rows:
        w = f"pie_eval {r.get('id', '?')}"
        extra = set(r) - EV_FIELDS
        if extra:
            err(w, f"모르는 필드 {sorted(extra)}")
        for f in ("id", "tags", "user"):
            if f not in r:
                err(w, f"필수 필드 '{f}' 없음")
        tags = r.get("tags") or []
        if not (1 <= len(tags) <= 2) or any(x not in TAG_MIN for x in tags):
            err(w, f"tags는 목록의 태그 1~2개 (지금: {tags})")
        tag_count.update(tags)
        mode = r.get("mode", "both")
        if mode not in MODES:
            err(w, f"mode는 both·chat·group (지금: {mode})")
        ex = r.get("expect")
        expects[ex or "(답 채점)"] += 1
        if ex is not None and ex not in EXPECTS:
            err(w, f"expect는 {sorted(EXPECTS)} 중 하나")
        if (ex == "silent" or "name_call" in tags) and mode != "group":
            err(w, "silent·name_call은 그룹에서만 의미 있음 → mode group")
        if "refuse" in tags and ex != "refuse":
            warn(w, "refuse 태그인데 expect가 refuse가 아님")
        for f in ("must", "must_any", "must_not"):
            v = r.get(f)
            if v is not None and (not isinstance(v, list) or not all(isinstance(x, str) and x for x in v)):
                err(w, f"{f}는 문자열 목록")
        if "max_chars" in r and not isinstance(r["max_chars"], int):
            err(w, "max_chars는 정수")
        if r.get("expect_situation") is not None and r["expect_situation"] not in SITUATIONS:
            err(w, f"expect_situation 값 {SITUATIONS}")
        if r.get("expect_domain") is not None and r["expect_domain"] not in DOMAINS:
            err(w, f"expect_domain 값 {DOMAINS}")
        if "shop" in tags and r.get("expect_situation"):
            sit[r["expect_situation"]] += 1
            dom[r.get("expect_domain")] += 1
        if ex is None and not (r.get("must") or r.get("must_any") or r.get("must_not")):
            warn(w, "채점 기준(expect·must·must_any·must_not)이 없음")
        pii_check(w, json.dumps(r, ensure_ascii=False))
    n = len(rows)
    if n < 80:
        err("pie_eval", f"{n}문제 — 80개 이상")
    if sum(sit.values()) < 10:
        err("pie_eval", f"expect_situation 달린 shop 문제 {sum(sit.values())}개 — 10개 이상")
    for s in SITUATIONS:
        if sit[s] < 2:
            err("pie_eval", f"shop 상황 '{s}' {sit[s]}문제 — 상황마다 2개 이상")
    for d in MAIN_DOMAINS:
        if dom[d] < 3:
            err("pie_eval", f"shop 도메인 '{d}' {dom[d]}문제 — 3개 이상")
    both = sum(1 for r in rows if r.get("mode", "both") == "both")
    stats.append(f"pie_eval {n}문제 · 두 모드로 돌릴 both {both}문제 → 채점 호출 {n + both}회 이상(도구 쓰면 최대 6배) · "
                 + ", ".join(f"{k} {v}" for k, v in expects.items()))
    stats.append("  태그 " + ", ".join(f"{t} {tag_count[t]}" for t in TAG_MIN) + " · shop 상황 "
                 + ", ".join(f"{s} {sit[s]}" for s in SITUATIONS))
    return rows


# ───────── 문장 중복 (시험 문제를 미리 보여주면 안 됨) ─────────
def check_overlap(examples: list[dict], evals: list[dict]) -> None:
    ex_texts = {norm((r.get("user") or {}).get("text")): r.get("id") for r in examples}
    calc = []
    for fn in (BRAIN / "calc_examples.jsonl", ROOT / "tests" / "calc_eval.jsonl"):
        if fn.exists():
            calc += [(fn.name, norm(r.get("text"))) for r in read_jsonl(fn)]
    for r in evals:
        t = norm((r.get("user") or {}).get("text"))
        w = f"pie_eval {r.get('id')}"
        if t in ex_texts:
            err(w, f"예시 {ex_texts[t]}와 같은 문장 — 평가 문제는 새로 쓰기")
            continue
        best = max(((difflib.SequenceMatcher(None, t, e).ratio(), i) for e, i in ex_texts.items()), default=(0, ""))
        if best[0] >= 0.85:
            warn(w, f"예시 {best[1]}와 거의 같은 문장 (유사도 {best[0]:.2f})")
        for name, c in calc:
            if t == c:
                err(w, f"{name}의 문장과 같음")
    for r in examples:
        t = norm((r.get("user") or {}).get("text"))
        for name, c in calc:
            if t == c:
                err(f"examples {r.get('id')}", f"{name}의 문장과 같음")


# ───────── 화면에 없는 버튼 이름 (경고) ─────────
def check_ui_quotes(examples: list[dict], chunks: list[tuple[str, str, str]], persona: str) -> None:
    if not UI.exists():
        warn("UI", "frontend/index.html 없음 — 버튼 이름 대조 생략")
        return
    ui = UI.read_text(encoding="utf-8")
    skip = set(SITUATIONS) | {"님"}
    seen: dict[str, str] = {}
    sources = [(f"examples {r.get('id')}", r.get("ideal") or "") for r in examples]
    sources += [(f"knowledge/{n}.md ## {t}", b) for n, t, b in chunks] + [("persona.md", persona)]
    for where, text in sources:
        for m in QUOTED.finditer(text):
            q = (m.group(1) or m.group(2)).strip()
            if q in skip or re.search(r"\d|[=:~]", q):
                continue
            if q not in ui and q not in seen:
                seen[q] = where
    for q, where in seen.items():
        warn(where, f"따옴표 문구 '{q}'가 frontend/index.html에 없음 — 버튼 이름이면 화면 글자와 맞추기")


def main() -> int:
    quiet = "--quiet" in sys.argv
    persona = check_persona()
    check_modes()
    ex = check_examples()
    kn = check_knowledge()
    ev = check_eval()
    check_overlap(ex, ev)
    check_ui_quotes(ex, kn, persona)
    print("── Pie mate 학습 파일 형식 검사 ──")
    for s in stats:
        print("  " + s)
    if not quiet:
        for w in warnings:
            print("  " + w)
    for e in errors:
        print("  " + e)
    print(f"── 결과: 오류 {len(errors)} · 경고 {len(warnings)} → {'통과' if not errors else '실패'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
