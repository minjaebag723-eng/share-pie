"""Pie의 두뇌 — agent/pie_brain/ 파일을 읽어 대화형 Pie(1:1)·Pie mate(그룹방) 프롬프트를 조립한다.

'Pie mate 학습 가이드라인' 순서 그대로:
  ① 공통 성격(persona.md, 두 채널 100% 같은 문장) → ② 모드 규칙(modes.md의 ## chat | ## group)
  → 도구 쓰는 법(코드 규칙, assistant.TOOL_RULES) → ③ 상황 정보(오늘·대화 상대·동네·방 정보)
  → ④ 관련 지식 최대 2조각(키워드 관련도가 기준 이상인 것만, 800자 이내)
  → ⑤ 예시 대화 최대 3개(이번 메시지의 태그·채널이 맞는 것, 750자 이내)
  → 최근 대화 → 이번 메시지 (뒤의 둘은 assistant.run이 붙인다)
정산 조건 해석(Stage 1)·결과 설명(Stage 3)·분쟁 판정·구매 조건 해석은 정확도용 전용 프롬프트라 여기 들어가지 않는다.
파일을 고치면 다음 호출부터 반영된다 (파일 수정 시각을 보고 다시 읽음).
"""
from __future__ import annotations

import json
import re
import threading
import zlib
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent / "pie_brain"
KNOW_LIMIT, KNOW_MAX_CHARS, KNOW_MIN_SCORE = 2, 800, 2      # 가이드라인: 지식 최대 2조각 · 800자 · 관련도 기준
EX_LIMIT, EX_MAX_CHARS = 3, 750                              # 가이드라인: 예시 최대 3개 · 750자
TAGS = ("settle", "settle_ask", "settle_change", "status", "pending", "shop", "dispute", "howto",
        "name_call", "refuse", "offtopic")

_lock = threading.Lock()
_cache: dict[str, Any] = {"sig": None}
_NAME = re.compile(r"(쉐어\s*파이|파이\s*메이트|파이봇|파메|파이|pie\s*mate|pie)\s*(야|아|님|씨)?[\s,!?~.]*", re.I)


def _sig() -> tuple:
    files = [DIR / "persona.md", DIR / "modes.md", DIR / "examples.jsonl"] + sorted((DIR / "knowledge").glob("*.md"))
    return tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files if f.exists())


def _sections(text: str, level: str = "## ") -> dict[str, str]:
    out, name, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith(level):
            if name is not None:
                out[name] = "\n".join(buf).strip()
            name, buf = line[len(level):].strip(), []
        elif name is not None:
            buf.append(line)
    if name is not None:
        out[name] = "\n".join(buf).strip()
    return out


def _chunks(path: Path) -> list[dict[str, Any]]:
    out = []
    for title, body in _sections(path.read_text(encoding="utf-8")).items():
        lines = body.splitlines()
        kw = next((ln.split(":", 1)[1] for ln in lines if ln.startswith("키워드:")), "")
        bullets = [ln for ln in lines if not ln.startswith("키워드:") and ln.strip()]
        out.append({"file": path.stem, "title": title, "keywords": [k.strip() for k in kw.split(",") if k.strip()],
                    "text": f"## {title}\n" + "\n".join(bullets)})
    return out


def _load() -> dict[str, Any]:
    with _lock:
        sig = _sig()
        if _cache["sig"] == sig:
            return _cache
        persona = (DIR / "persona.md").read_text(encoding="utf-8").strip() if (DIR / "persona.md").exists() else ""
        modes = _sections((DIR / "modes.md").read_text(encoding="utf-8")) if (DIR / "modes.md").exists() else {}
        chunks = [c for f in sorted((DIR / "knowledge").glob("*.md")) for c in _chunks(f)]
        examples = []
        if (DIR / "examples.jsonl").exists():
            for line in (DIR / "examples.jsonl").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        examples.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        _cache.clear()
        _cache.update(sig=sig, persona=persona, modes=modes, chunks=chunks, examples=examples)
        return _cache


def ready() -> bool:
    return bool(_load().get("persona"))


def stats() -> dict[str, Any]:
    c = _load()
    return {"persona_chars": len(c["persona"]), "modes": sorted(c["modes"]), "chunks": len(c["chunks"]), "examples": len(c["examples"])}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def strip_speaker(text: str) -> str:
    """그룹방 대화는 '이름: 내용' 형식 — 태그 판단에는 내용만."""
    return re.sub(r"^[^:\n]{1,20}:\s*", "", (text or "").strip())


def tags_for(text: str, channel: str = "chat", has_history: bool = False) -> list[str]:
    """이번 메시지 유형(가이드라인 ② 태그) — 예시를 고르는 기준. 코드 규칙이라 토큰 0."""
    t = strip_speaker(text)
    from . import settlement            # 순환 import 방지
    if settlement.prohibited_reason(t):
        return ["refuse"]
    core = _NAME.sub("", t).strip(" ,.!?~@")
    if channel == "group" and not core:
        return ["name_call"]
    money = re.search(r"\d|만\s*원|천\s*원|%|퍼센트|프로", core)
    split = re.search(r"나눠|나누|엔빵|[nN]빵|반반|반띵|더치|씩|정산|걷자|걷어|내게|덜\s*내|더\s*내|똑같이|각자\s*내|한\s*명당", core)
    people = re.search(r"[둘셋넷]이|다섯이|여섯이|일곱이|여덟이|\d+\s*명", core)
    shop = re.search(r"추천|시키자|시켜|사자|살까|골라|공구|공동구매|배달|메뉴|숙소|여행|선물|먹을|먹자", core)
    change = re.search(r"^(아|잠깐|아니|ㄴㄴ)\b|^(아|잠깐|아니|ㄴㄴ)\s|바꿔|빼줘|틀렸|였어|이었|단위로|온대|추가", core)
    tags: list[str] = []
    if re.search(r"이의|환불|잘못\s*(나|된|나눈|들어)|분쟁|판정|돌려받|빠져나|안\s*왔", core):
        tags.append("dispute")
    if re.search(r"안\s*냈|남음|남았|누가\s*아직|끝났|끝난\s*거|언제.{0,6}(받|가)|멈춘|현황|상태가|대기라", core):
        tags.append("status")
    if re.search(r"준비\s*중|시작이\s*안|안\s*시작|연결함|충전했|뭐\s*하면\s*돼|뭘\s*해야", core):
        tags.append("pending")
    if has_history and money and change and not shop:
        tags.append("settle_change")                     # 앞 조건을 이어서 바꿈 ("아 총액 32만원이었어")
    elif money and (split or (people and not shop)):
        vague = re.search(r"조금|적당히|많이\s*먹은|달러|유로|엔화|\d\s*:\s*\d|%야|프로야", core)
        tags.append("settle_ask" if vague else "settle")
    elif shop:
        tags.append("shop")
    if not tags and re.search(r"어떻게|어케|어디서|어딨|방법|버튼|뭐야|뭐예요|뭔가요|할\s*수\s*있|돼\?|안\s*돼|안\s*떠|안\s*와|얼마야|요금제", core):
        tags.append("howto")
    return (tags or ["offtopic"])[:2]


FACT_TAGS = {"howto", "status", "pending", "dispute"}      # 앱 사실을 묻는 질문은 키워드 하나만 맞아도 넣는다


def knowledge_for(text: str, limit: int = KNOW_LIMIT, min_score: float | None = None,
                  max_chars: int = KNOW_MAX_CHARS, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """질문 키워드와 가장 많이 겹치는 조각. 긴 키워드(4자 이상) 2점, 나머지 1점, 맞은 키워드가 조각 제목에도 있으면 +0.5.
    기준: 사실 질문(사용법·진행 상황·대기·이의제기)은 1점, 그 밖(정산·추천 등)은 2점 — 기준 미만이면 안 넣는다(토큰 절약)."""
    if min_score is None:
        min_score = 1 if FACT_TAGS & set(tags or []) else KNOW_MIN_SCORE
    t = _norm(strip_speaker(text))
    scored = []
    for c in _load()["chunks"]:
        hits = [_norm(k) for k in c["keywords"] if len(_norm(k)) >= 2 and _norm(k) in t]
        s = sum(2 if len(k) >= 4 else 1 for k in hits) + (0.5 if any(k in _norm(c["title"]) for k in hits) else 0)
        if s >= min_score:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    out, used = [], 0
    for _s, c in scored:
        if len(out) >= limit:
            break
        if used + len(c["text"]) <= max_chars:
            out.append(c)
            used += len(c["text"])
    return out


def render_example(e: dict[str, Any]) -> str:
    lines = [f"[방] {e['room']}"] if e.get("room") else []
    lines += [f"{h['who']}: {h['text']}" for h in (e.get("history") or [])[-2:]]
    lines += [f"{e['user']['who']}: {e['user']['text']}", f"Pie: {e['ideal']}"]
    return "\n".join(lines)


def examples_for(tags: list[str], channel: str = "chat", seed: str = "", limit: int = EX_LIMIT,
                 max_chars: int = EX_MAX_CHARS) -> list[dict[str, Any]]:
    """태그·채널이 맞는 예시. 같은 태그 안에서는 메시지마다 다른 예시가 먼저 오게 돌린다(결정적)."""
    pool = [e for e in _load()["examples"] if e.get("mode", "both") in ("both", channel)]
    picked: list[dict[str, Any]] = []
    for tag in tags:
        cands = [e for e in pool if tag in (e.get("tags") or []) and e not in picked]
        if cands:
            k = zlib.crc32(f"{seed}|{tag}".encode()) % len(cands)
            picked += (cands[k:] + cands[:k])
    out, used = [], 0
    for e in picked:
        n = len(render_example(e))
        if len(out) < limit and used + n <= max_chars:
            out.append(e)
            used += n
    return out


def compose(channel: str, *, tool_rules: str, situation: list[str], text: str,
            has_history: bool = False) -> tuple[str | None, dict[str, Any]]:
    """시스템 프롬프트 + 기록용 요약. 두뇌 파일이 없으면 (None, {}) → 예전 프롬프트로."""
    c = _load()
    if not c.get("persona"):
        return None, {}
    channel = "group" if channel == "group" else "chat"
    tags = tags_for(text, channel, has_history)
    know = knowledge_for(text, tags=tags)
    exs = examples_for(tags, channel, seed=text)
    parts = [c["persona"], c["modes"].get(channel, ""), tool_rules]
    if situation:
        parts.append("[상황 정보]\n" + "\n".join(situation))
    if know:
        parts.append("[관련 지식 — 앱이 실제로 동작하는 방식. 안내는 이 안의 사실만 쓴다]\n" + "\n\n".join(k["text"] for k in know))
    if exs:
        parts.append("[예시 대화 — 말투와 판단만 참고하고, 이름·금액은 지금 대화의 것을 쓴다]\n" + "\n\n".join(render_example(e) for e in exs))
    prompt = "\n\n".join(p for p in parts if p)
    meta = {"channel": channel, "tags": tags, "knowledge": [f"{k['file']}#{k['title']}" for k in know],
            "examples": [e.get("id") for e in exs], "chars": len(prompt),
            "knowledge_chars": sum(len(k["text"]) for k in know), "example_chars": sum(len(render_example(e)) for e in exs)}
    return prompt, meta
