"""베타 데이터 수집 — 목표 세 가지를 위한 기록.

1) 학습 데이터(AI 지능 향상): '대화를 AI 개선에 쓰는 데 동의'한 사용자의 턴만 저장한다 (data/beta_dialogs.jsonl).
   이름은 가명으로, 이메일·전화번호·지갑 주소·긴 번호는 지운다. 답마다 👍/👎(+이유)를 받아(data/beta_feedback.jsonl)
   좋은 답은 예시 후보, 나쁜 답은 평가 문제 후보로 내보낸다 (가이드라인 ②·평가 세트 형식).
2) 토큰 효율(베타 ↔ 정식 비교): 모든 Kiln 기록에 앱 버전(APP_VERSION) · 턴 id · 시나리오 id가 붙는다 (usage.jsonl).
   같은 시나리오(기능 예시)를 그대로 보낸 턴끼리 버전별 '턴당 토큰·호출·지연·에너지'를 비교한다. 텍스트는 쓰지 않는다.
3) 심사 기준 충족: 기능 예시가 end-to-end 정산, 조건을 바꾼 재실행, 지출 통제 중단, 분쟁 증거 검토를 직접 해 보게 유도하고,
   보고서가 그 실행 수를 센다.
동의는 언제든 철회할 수 있고, 철회하면 그 사람의 저장된 대화·의견을 지운다.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import defaultdict
from typing import Any

from . import config, store, usage

# ── 베타 데이터 폴더 (BETA_DATA_DIR) — 비식별 데이터만. 계정·비밀번호가 든 db.json과 따로 두어 이 폴더만 보내면 된다 ──
DIR = config.BETA_DATA_DIR
DIALOGS = DIR / "dialogs.jsonl"          # 동의한 사람의 턴 (학습 데이터)
FEEDBACK = DIR / "feedback.jsonl"        # 답 평가 👍/👎
USAGE = DIR / "usage.jsonl"              # Kiln 기록 사본 (이메일·제목 없이) — 토큰 효율·버전 비교
EVENTS = DIR / "events.jsonl"            # 동의·철회·미션 완료
SETTLEMENTS = DIR / "settlements.jsonl"  # 정산 요약 (이름 없이) — 심사 기준 증거
REPORT_MD, REPORT_JSON = DIR / "report.md", DIR / "report.json"
MANIFEST, README = DIR / "manifest.json", DIR / "README.md"
_OLD = {config.DATA_DIR / "beta_dialogs.jsonl": DIALOGS, config.DATA_DIR / "beta_feedback.jsonl": FEEDBACK}   # v34~35 위치
_lock = threading.Lock()

CATEGORIES = [("core", "정산 — 핵심 기능"), ("control", "지출 통제 · 증거"), ("shop", "추천 — 상황 인식"),
              ("mate", "그룹방 Pie mate"), ("howto", "사용법")]
# where: chat(1:1 Pie) · group(그룹방) · action(버튼으로 하는 일) / bench: 버전 비교용 기준 과제(문장을 그대로 보낸 턴만 비교)
# goal: train(학습 데이터) · token(토큰 효율 비교) · criteria(심사 기준) — 어떤 데이터를 얻으려는 예시인지
SCENARIOS: list[dict[str, Any]] = [
    {"id": "S01", "cat": "core", "where": "chat", "title": "똑같이 나누기", "text": "삼겹살 38,900원 넷이 똑같이 나눠줘",
     "desc": "금액은 AI가 아니라 앱 코드가 1원 단위로 계산해요.", "tags": ["settle"], "goal": ["token", "criteria"], "bench": True},
    {"id": "S02", "cat": "core", "where": "chat", "title": "여러 조건 섞기",
     "text": "치킨 2만 피자 1.8만 배달비 3천 넷이 나누는데 진주는 5천원 덜 내게 해줘",
     "desc": "금액 여러 개와 차등 조건을 한 문장으로 말해 보세요.", "tags": ["settle"], "goal": ["train", "token"], "bench": True},
    {"id": "S03", "cat": "core", "where": "chat", "title": "퍼센트 조건", "text": "한정식 15만원인데 부가세 10% 별도래 여섯이 나눠줘",
     "desc": "%가 더하는 건지, 할인인지 Pie가 알아듣는지 봐요.", "tags": ["settle"], "goal": ["train", "token"], "bench": True},
    {"id": "S04", "cat": "core", "where": "chat", "title": "대화 중에 조건 바꾸기", "text": "숙소 30만원 넷이 나눠줘",
     "follow": "아 총액 32만원이었어", "desc": "보낸 뒤 이어지는 두 번째 문장으로 조건을 바꿔 보세요. 앞 조건을 기억하는지 봐요.",
     "tags": ["settle", "settle_change"], "goal": ["train", "token", "criteria"], "bench": True},
    {"id": "S05", "cat": "core", "where": "chat", "title": "애매하게 말해 보기", "text": "총 5만원인데 진주는 조금 더 내게 해줘",
     "desc": "Pie가 추측하지 않고 꼭 필요한 한 가지만 되묻는지 봐요.", "tags": ["settle_ask"], "goal": ["train"], "bench": False},
    {"id": "S06", "cat": "control", "where": "group", "title": "예산 한도 넘겨 보기",
     "text": "8만원 넷이 똑같이 나누는데 1인 1만5천원 넘으면 안 돼", "follow": "그럼 총액 6만원으로 바꿀게",
     "desc": "한도를 넘는 정산은 결제 없이 멈추고 중단 기록이 블록체인에 남아요. 이어서 금액을 줄여 다시 해 보세요.",
     "tags": ["settle", "settle_change"], "goal": ["criteria", "train"], "bench": False},
    {"id": "S07", "cat": "control", "where": "action", "title": "이의제기로 기록 검토받기", "text": "금액이 조건이랑 달라요",
     "desc": "모두 예치한 정산 카드에서 '문제가 있나요? 이의제기'를 누르고 이 사유를 적어 보세요. AI가 기록을 대조해 판정해요.",
     "tags": ["dispute"], "goal": ["criteria"], "bench": False},
    {"id": "S08", "cat": "shop", "where": "chat", "title": "싸게 고르기", "text": "월말이라 거지다 넷이 치킨 시키자 6만원 안에서",
     "desc": "상황을 읽고 '가격' 위주로 고르면서 다른 방향도 하나 섞는지 봐요.", "tags": ["shop"], "goal": ["train", "token"], "bench": True},
    {"id": "S09", "cat": "shop", "where": "chat", "title": "좋은 걸로 고르기", "text": "민재 생일인데 제대로 된 걸로 시키자 넷이 10만원",
     "desc": "같은 음식이어도 상황이 바뀌면 추천이 달라지는지 봐요.", "tags": ["shop"], "goal": ["train"], "bench": False},
    {"id": "S10", "cat": "shop", "where": "chat", "title": "알아서 골라 달라기", "text": "아무거나 시켜줘 우리 넷 8만",
     "desc": "방향이 없을 때 되묻지 않고 여러 방향으로 골라 주는지 봐요.", "tags": ["shop"], "goal": ["train"], "bench": False},
    {"id": "S11", "cat": "mate", "where": "group", "title": "이름만 불러 보기", "text": "파이야",
     "desc": "그룹방에서 이름만 부르면 방 상황을 보고 할 일 하나를 제안해요.", "tags": ["name_call"], "goal": ["train"], "bench": False},
    {"id": "S12", "cat": "mate", "where": "group", "title": "진행 상황 묻기", "text": "파이야 누가 아직 안 냈어?",
     "desc": "정산이 시작된 방에서 물어보세요. 방 기록만 보고 답하는지 봐요. (이름 없이 물으면 아직 Pie mate가 답하지 않아요)", "tags": ["status"], "goal": ["train"], "bench": False},
    {"id": "S13", "cat": "howto", "where": "chat", "title": "앱 사용법 묻기", "text": "AI 요금제는 어떻게 돼?",
     "desc": "Pie가 앱 설명서(지식 문서)를 찾아 사실대로 답하는지 봐요.", "tags": ["howto"], "goal": ["train", "token"], "bench": True},
]
_BY_ID = {s["id"]: s for s in SCENARIOS}
REASONS = ["금액이 틀렸어요", "엉뚱한 답이에요", "안 물어봐도 됐어요", "없는 기능·버튼을 말했어요", "너무 길어요", "기타"]
PSEUDO = ["가온", "나래", "다온", "라희", "마루", "보람", "새봄", "아라", "주원", "하람", "윤슬", "초롱"]
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
_WALLET = re.compile(r"0x[0-9a-fA-F]{40}")
_LONGNUM = re.compile(r"\d[\d -]{9,}\d")


def enabled() -> bool:
    return config.BETA_ENABLED


def scenario(sid: Any) -> dict[str, Any] | None:
    return _BY_ID.get(str(sid or "").upper())


def uid(email: str) -> str:
    return hashlib.sha256(f"{config.BETA_SALT}|{(email or '').lower()}".encode()).hexdigest()[:12]


def new_turn() -> str:
    return "t_" + uuid.uuid4().hex[:10]


def _rec(email: str) -> dict[str, Any]:
    return dict(store.kv_get("beta_users", email) or {})


def status(me: dict[str, Any]) -> dict[str, Any]:
    rec = _rec(me["email"])
    done = rec.get("done") or {}
    return {"enabled": enabled(), "version": config.APP_VERSION, "consent": rec.get("consent"),
            "consentAt": rec.get("consentAt"), "done": len([s for s in SCENARIOS if s["id"] in done]), "total": len(SCENARIOS),
            "categories": [{"id": c, "label": label} for c, label in CATEGORIES], "reasons": REASONS,
            "scenarios": [{**{k: s[k] for k in ("id", "cat", "where", "title", "text", "desc", "bench")}, "follow": s.get("follow"),
                           "done": s["id"] in done} for s in SCENARIOS]}


def set_consent(me: dict[str, Any], agree: bool) -> dict[str, Any]:
    rec = _rec(me["email"])
    rec.update(consent=bool(agree), consentAt=time.time(), version=config.APP_VERSION)
    store.kv_put("beta_users", me["email"], rec)
    event(me["email"], "consent" if agree else "consent_withdrawn")
    if not agree:
        purge(me["email"])                          # 철회하면 저장된 대화·의견을 지운다
    return status(me)


def purge(email: str) -> int:
    u, n = uid(email), 0
    with _lock:
        for path in (DIALOGS, FEEDBACK):
            if not path.exists():
                continue
            keep = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    if json.loads(line).get("uid") == u:
                        n += 1
                        continue
                except json.JSONDecodeError:
                    pass
                keep.append(line)
            path.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
    return n


def mark_done(email: str | None, sid: str | None) -> None:
    if not (email and scenario(sid)):
        return
    rec = _rec(email)
    done = dict(rec.get("done") or {})
    if sid.upper() not in done:
        done[sid.upper()] = time.time()
        rec["done"] = done
        store.kv_put("beta_users", email, rec)
        event(email, "mission_done", scenario=sid.upper())


def scrub(texts: list[str], names: list[Any]) -> list[str]:
    """이메일·전화번호·지갑 주소·긴 번호를 지우고, 사람 이름은 기록 안에서 일관된 가명으로 바꾼다 (문장 구조는 학습에 필요해서 남김).
    names: 이름 또는 (실명, 짧은 이름) 묶음 — 한 사람의 여러 표기는 같은 가명으로, 긴 표기부터 바꿔 성만 남는 일이 없게."""
    pid: dict[str, int] = {}                     # 표기 → 사람 번호 (같은 표기가 겹치면 같은 사람으로 합침)
    nxt = 0
    for n in names:
        vs = [v for v in (n if isinstance(n, (list, tuple)) else [n]) if v and len(v) >= 2]
        if not vs:
            continue
        i = next((pid[v] for v in vs if v in pid), None)
        if i is None:
            i, nxt = nxt, nxt + 1
        for v in vs:
            pid.setdefault(v, i)
    variants = sorted(pid.items(), key=lambda x: -len(x[0]))
    alias: dict[int, str] = {}
    out = []
    for t in texts:
        t = _EMAIL.sub("[이메일]", t or "")
        t = _WALLET.sub("[지갑]", t)
        t = _PHONE.sub("[전화번호]", t)
        t = _LONGNUM.sub("[번호]", t)
        for v, i in variants:
            if v in t:
                a = alias.setdefault(i, PSEUDO[len(alias) % len(PSEUDO)])
                t = t.replace(v, a)
        out.append(t)
    return out


def known_names() -> list[tuple[str, str]]:
    """가입자의 (실명, 짧은 이름) — 대화에 나오면 가명으로. 가입하지 않은 사람의 이름은 알 수 없어 남을 수 있다(내보낸 뒤 검토)."""
    return [(u.get("name") or "", u.get("short") or "") for u in store.users_raw()]


def _append(path, row: dict[str, Any]) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def event(email: str | None, kind: str, **data: Any) -> None:
    if enabled() and email:
        _append(EVENTS, {"ts": round(time.time(), 3), "version": config.APP_VERSION, "uid": uid(email), "event": kind, **data})


_MIRROR_KEYS = ("ts", "version", "turn", "scenario", "edited", "stage", "where", "mode", "model", "prompt_tokens",
                "completion_tokens", "total_tokens", "latency_ms", "energy_wh", "plan", "counted")


def mirror_usage(row: dict[str, Any]) -> None:
    """usage.jsonl 한 줄의 비식별 사본 (이메일 → uid, 흐름 이름·제목 → 해시, 메모는 이름·연락처 지움)."""
    if not enabled():
        return
    out = {k: row[k] for k in _MIRROR_KEYS if k in row}
    if row.get("user"):
        out["uid"] = uid(row["user"])
    if row.get("flow"):
        out["flow"] = hashlib.sha256(str(row["flow"]).encode()).hexdigest()[:10]
    if row.get("note"):
        out["note"] = scrub([str(row["note"])[:300]], known_names())[0]
    _append(USAGE, out)


def log_turn(email: str | None, *, channel: str, flow: str | None, turn: str, sid: str | None, edited: bool | None,
             text: str, history: list[str], replies: list[dict[str, Any]], tags: dict[str, Any], names: list[str]) -> bool:
    """동의한 사람의 턴만 저장. 반환: 저장했는지."""
    if not (enabled() and email):
        return False
    if sid:
        mark_done(email, sid)
    if _rec(email).get("consent") is not True:
        return False
    reply = "\n".join((m.get("text") or "") for m in replies if m.get("text") and m.get("from") != "user")
    s = scrub([text] + list(history) + [reply], known_names() + names)     # 가입자 (실명, 짧은 이름) 묶음을 먼저
    b = tags.get("brain") or {}
    _append(DIALOGS, {"ts": round(time.time(), 3), "version": config.APP_VERSION, "uid": uid(email), "turn": turn,
                      "flow": hashlib.sha256(str(flow).encode()).hexdigest()[:10] if flow else None, "channel": channel,
                      "scenario": sid, "edited": edited, "tags": b.get("tags"), "knowledge": b.get("knowledge"),
                      "examples": b.get("examples"), "user": s[0], "history": s[1:-1], "reply": s[-1],
                      "tokens": tags.get("tokens", 0), "calls": tags.get("calls", 0), "limited": tags.get("limited", False)})
    return True


def feedback(me: dict[str, Any], turn: str, rating: str, reason: str | None = None, note: str | None = None) -> dict[str, Any]:
    if rating not in ("up", "down") or not re.fullmatch(r"t_[0-9a-f]{10}", str(turn or "")):
        raise ValueError("rating은 up/down, turn은 답에 붙은 id")
    consent = _rec(me["email"]).get("consent") is True
    row = {"ts": round(time.time(), 3), "version": config.APP_VERSION, "uid": uid(me["email"]), "turn": turn, "rating": rating,
           "reason": reason if reason in REASONS else None,
           "note": (scrub([note[:200]], known_names())[0] if (note and consent) else None)}   # 자유 의견 글은 동의한 사람만
    _append(FEEDBACK, row)
    return {"ok": True, "turn": turn, "rating": rating}


def _read(path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _latest_feedback() -> dict[str, dict[str, Any]]:
    fb: dict[str, dict[str, Any]] = {}
    for r in _read(FEEDBACK):
        fb[r["turn"]] = r                          # 같은 답에 다시 누르면 마지막 것
    return fb


def export(kind: str = "train") -> str:
    """train: 👎가 아닌 턴 → 예시(examples.jsonl) 후보 / eval: 👎 턴 → 평가 문제(pie_eval.jsonl) 후보 / raw: 전부.
    사람이 검토해 ideal·must를 채운 뒤 pie_brain·tests로 옮긴다 (가이드라인 작업 순서의 '베타에서 틀린 문장 추가')."""
    fb, lines = _latest_feedback(), []
    for d in _read(DIALOGS):
        f = fb.get(d["turn"]) or {}
        rating = f.get("rating")
        if kind == "train" and rating == "down":
            continue
        if kind == "eval" and rating != "down":
            continue
        who = PSEUDO[0]
        base = {"id": f"beta-{d['turn']}", "tags": d.get("tags") or [], "mode": "group" if d.get("channel") == "group" else "chat",
                "history": [{"who": "?", "text": h} for h in d.get("history") or []], "user": {"who": who, "text": d["user"]},
                "scenario": d.get("scenario"), "edited": d.get("edited"), "version": d.get("version")}
        if kind == "train":
            row = {**base, "ideal": d["reply"], "why": "베타 실제 대화 — 검토 후 다듬어 쓰기", "feedback": rating}
        elif kind == "eval":
            row = {**base, "must": [], "must_not": [], "reply_was": d["reply"], "reason": f.get("reason"), "note": f.get("note")}
        else:
            row = {**d, "feedback": rating, "reason": f.get("reason")}
        lines.append(json.dumps(row, ensure_ascii=False))
    return "".join(x + "\n" for x in lines)


def report() -> dict[str, Any]:
    """공개 요약 (텍스트 없음): 시나리오 × 버전별 턴당 토큰·호출·지연·에너지, 피드백, 심사 기준 실행 수, 참여 현황."""
    turns: dict[str, dict[str, Any]] = defaultdict(lambda: {"tokens": 0, "calls": 0, "latency_ms": 0, "energy_wh": 0.0,
                                                           "fallback": False, "limited": False})
    for r in usage.read_all():
        t = r.get("turn")
        if not t:
            continue
        a = turns[t]
        a.update(version=r.get("version") or "?", scenario=r.get("scenario"), edited=r.get("edited"), channel=r.get("where") or "chat")
        if r.get("mode") in ("tools", "json", "text"):
            a["tokens"] += int(r.get("total_tokens") or 0)
            a["calls"] += 1
            a["latency_ms"] += int(r.get("latency_ms") or 0)
            a["energy_wh"] += float(r.get("energy_wh") or 0)
        elif r.get("mode") == "fallback":
            a["fallback"] = True
            a["limited"] = a["limited"] or str(r.get("note") or "").startswith("AI_LIMIT")
    fb = _latest_feedback()
    groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for t, a in turns.items():
        groups[(a.get("scenario") or "-", a["version"])].append((t, a))
    rows = []
    for (sid, ver), items in sorted(groups.items()):
        n = len(items)
        same = [a for _t, a in items if a.get("edited") is False]          # 예시 문장 그대로 보낸 턴 = 버전 비교용
        ups = sum(1 for t, _a in items if (fb.get(t) or {}).get("rating") == "up")
        downs = sum(1 for t, _a in items if (fb.get(t) or {}).get("rating") == "down")
        avg = lambda xs, k: round(sum(x[k] for x in xs) / len(xs), 1) if xs else None   # noqa: E731
        sc = scenario(sid) or {}
        rows.append({"scenario": sid, "title": sc.get("title", "자유 입력"), "bench": bool(sc.get("bench")), "version": ver, "turns": n,
                     "asIs": len(same), "avgTokens": avg([a for _t, a in items], "tokens"), "avgTokensAsIs": avg(same, "tokens"),
                     "avgCalls": avg([a for _t, a in items], "calls"), "avgLatencyMs": avg([a for _t, a in items], "latency_ms"),
                     "whPerTurn": round(sum(a["energy_wh"] for _t, a in items) / n, 6) if n else 0,
                     "fallbackShare": round(sum(1 for _t, a in items if a["fallback"]) / n, 3) if n else 0,
                     "up": ups, "down": downs})
    versions = {}
    for ver in sorted({a["version"] for a in turns.values()}):
        xs = [(t, a) for t, a in turns.items() if a["version"] == ver]
        rated = [(fb.get(t) or {}).get("rating") for t, _a in xs if fb.get(t)]
        versions[ver] = {"turns": len(xs), "avgTokens": round(sum(a["tokens"] for _t, a in xs) / len(xs), 1) if xs else 0,
                         "avgCalls": round(sum(a["calls"] for _t, a in xs) / len(xs), 2) if xs else 0,
                         "upRate": round(rated.count("up") / len(rated), 3) if rated else None, "rated": len(rated)}
    recs = store.all_settlements()
    by_group: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by_group[r.get("group_id")].append(r)
    cond = lambda r: (r.get("total"), r.get("per_person_cap"), r.get("total_cap"), tuple(r.get("allowed_merchants") or []))  # noqa: E731
    users = store.kv_all("beta_users")
    reasons = defaultdict(int)
    for f in fb.values():
        if f.get("reason"):
            reasons[f["reason"]] += 1
    return {
        "generatedAt": time.time(), "version": config.APP_VERSION, "scenarios": rows, "versions": versions,
        "criteria": {"settlements": len(recs), "paid": sum(1 for r in recs if r.get("status") == "paid"),
                     "blockedBySpendingControl": sum(1 for r in recs if r.get("blocked")),
                     "conditionChangedReruns": sum(1 for g, rs in by_group.items() if g and len({cond(r) for r in rs}) >= 2),
                     "disputes": sum(1 for r in recs if r.get("dispute")),
                     "disputesJudged": sum(1 for r in recs if (r.get("dispute") or {}).get("verdict")),
                     "onchainTxs": sum(len(r.get("txs") or []) for r in recs)},
        "participation": {"betaUsers": len(users), "consented": sum(1 for u in users.values() if u.get("consent") is True),
                          "declined": sum(1 for u in users.values() if u.get("consent") is False),
                          "missionsDone": {s["id"]: sum(1 for u in users.values() if s["id"] in (u.get("done") or {})) for s in SCENARIOS},
                          "dialogsSaved": len(_read(DIALOGS)), "feedback": {"up": sum(1 for f in fb.values() if f["rating"] == "up"),
                                                                            "down": sum(1 for f in fb.values() if f["rating"] == "down"),
                                                                            "reasons": dict(reasons)}},
    }


def report_markdown(rep: dict[str, Any] | None = None) -> str:
    r = rep or report()
    L = [f"# Share Pie 베타 보고서 ({r['version']})", "",
         "## 1. 버전별 비교 (턴당 평균)", "", "| 버전 | 턴 | 토큰 | Kiln 호출 | 👍 비율 (평가 수) |", "|---|---|---|---|---|"]
    for v, x in r["versions"].items():
        rate = "-" if x["upRate"] is None else f"{x['upRate'] * 100:.0f}%"
        L.append(f"| {v} | {x['turns']} | {x['avgTokens']:,} | {x['avgCalls']} | {rate} ({x['rated']}) |")
    L += ["", "## 2. 기능 예시(시나리오)별 — 같은 과제를 버전별로", "",
          "| 시나리오 | 버전 | 턴 | 예시 그대로 | 턴당 토큰 | 그대로 보낸 턴의 토큰 | 호출 | 지연(ms) | Wh/턴 | 대체 비율 | 👍/👎 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in r["scenarios"]:
        L.append(f"| {x['scenario']} {x['title']}{' ★' if x['bench'] else ''} | {x['version']} | {x['turns']} | {x['asIs']} | {x['avgTokens']} | "
                 f"{x['avgTokensAsIs'] if x['avgTokensAsIs'] is not None else '-'} | {x['avgCalls']} | {x['avgLatencyMs']} | {x['whPerTurn']:.5f} | "
                 f"{x['fallbackShare']:.0%} | {x['up']}/{x['down']} |")
    c, p = r["criteria"], r["participation"]
    L += ["", "★ = 기준 과제. 버전 비교는 '예시 그대로' 보낸 턴의 토큰으로 한다 (같은 입력).", "",
          "## 3. 심사 기준 실행 수", "",
          f"- 정산 {c['settlements']}건 (지급 완료 {c['paid']}) · 온체인 트랜잭션 {c['onchainTxs']}건",
          f"- 지출 통제로 중단 {c['blockedBySpendingControl']}건 · 같은 방에서 조건을 바꿔 다시 실행 {c['conditionChangedReruns']}방",
          f"- 이의제기 {c['disputes']}건 (판정 {c['disputesJudged']}건)", "",
          "## 4. 참여", "",
          f"- 베타 사용자 {p['betaUsers']}명 · 대화 제공 동의 {p['consented']}명 · 거절 {p['declined']}명 · 저장된 턴 {p['dialogsSaved']}개",
          f"- 피드백 👍 {p['feedback']['up']} · 👎 {p['feedback']['down']}" +
          (" · 이유: " + ", ".join(f"{k} {v}" for k, v in p['feedback']['reasons'].items()) if p['feedback']['reasons'] else ""),
          "- 미션 완료: " + ", ".join(f"{k} {v}" for k, v in p["missionsDone"].items())]
    return "\n".join(L)



# ───────────── 폴더 관리: 안내문 · 옛 위치 옮기기 · 스냅샷 · 묶음(zip) ─────────────
FOLDER_README = """# Share Pie 베타 데이터 폴더

이 폴더에는 **베타에서 모은 데이터만** 들어 있어요. 사람은 되돌릴 수 없는 id(`uid`)로, 대화 속 이름은 가명으로 바뀌어 있고
이메일·전화번호·지갑 주소·계좌번호·비밀번호는 없어요. 계정·정산 원본(`db.json`)은 서버의 data 폴더에 따로 있고 여기로 오지 않아요.

**보내는 법**: 이 폴더를 통째로 복사하거나, 관리자 링크 `/api/beta/bundle.zip?key=…` 또는 `python deploy/beta_bundle.py`로 zip을 만들어요.
받은 쪽은 `manifest.json`의 줄 수·sha256으로 빠짐없이 왔는지 확인해요.

| 파일 | 무엇 | 쓰는 곳 |
|---|---|---|
| dialogs.jsonl | '대화 제공'에 동의한 사람의 턴 (비식별) | 학습: 예시·평가 문제 후보 |
| feedback.jsonl | 답 평가 👍/👎와 이유 | 좋은 답 / 나쁜 답 라벨 |
| usage.jsonl | Kiln 호출 기록 사본 (토큰·지연·에너지·버전·턴·미션) | 토큰 효율 · 베타↔정식 비교 |
| events.jsonl | 동의 · 철회 · 미션 완료 | 참여 분석 |
| settlements.jsonl | 정산 요약 (상태·금액·한도·중단 코드·이의제기 판정·트랜잭션 해시) | 심사 기준 증거 |
| report.md · report.json | 요약 보고서 (버전 비교 · 미션별 토큰 · 심사 기준 실행 수 · 참여) | 발표 |
| manifest.json | 파일별 줄 수 · 크기 · sha256 · 기간 · 만든 시각 | 받은 데이터 확인 |

## 필드
- 공통: `ts`(초 단위 시각) · `version`(앱 버전: beta-1 / 1.0 …) · `uid`(사람) · `turn`(한 번의 질문-답) · `scenario`(베타 미션 S01~S13, 자유 입력이면 없음)
- dialogs: `channel`(chat 1:1 · group 그룹방) `edited`(미션 예시를 고쳐 보냈는지) `tags`(말 유형) `knowledge`·`examples`(프롬프트에 들어간 지식·예시)
  `user`·`history`·`reply`(비식별 글) `tokens`·`calls`(이 턴의 Kiln 토큰·호출) `limited`(구독 한도로 규칙 답)
- feedback: `rating`(up/down) `reason`(아쉬운 이유) `note`(자유 의견, 동의한 사람만)
- usage: `stage`(워크플로 단계) `mode`(tools·json·text = Kiln 호출 · code = 코드만 · fallback = 규칙 답 · decision = 응답→결정 기록)
  `prompt_tokens`·`completion_tokens`·`total_tokens` `latency_ms` `energy_wh`(추정) `plan` `counted`(구독 한도에 들어감) `note`
- 동의를 철회하면 그 사람의 dialogs·feedback 줄은 지워져요. usage·events는 글 없는 통계라 남아요.

## 버전 비교
같은 미션을 '예시 그대로'(`edited: false`) 보낸 턴끼리 `version`별 턴당 토큰을 비교해요 (report.md 2번 표).
"""


def ensure_dir() -> None:
    """폴더를 만들고, 옛 위치(data/beta_*.jsonl)의 기록을 옮기고, 안내문을 최신으로."""
    DIR.mkdir(parents=True, exist_ok=True)
    for old, new in _OLD.items():
        if old.exists() and old.resolve() != new.resolve():
            with _lock:
                with new.open("a", encoding="utf-8") as f:
                    f.write(old.read_text(encoding="utf-8"))
                old.unlink()
    if not README.exists() or README.read_text(encoding="utf-8") != FOLDER_README:
        README.write_text(FOLDER_README, encoding="utf-8")


def _settlement_rows() -> list[dict[str, Any]]:
    rows = []
    for r in store.all_settlements():
        bl = r.get("blocked") or {}
        rows.append({
            "id": hashlib.sha256(str(r.get("id")).encode()).hexdigest()[:10],
            "group": hashlib.sha256(str(r.get("group_id")).encode()).hexdigest()[:10] if r.get("group_id") else None,
            "status": r.get("status"), "total": r.get("total"), "members": len(r.get("members") or []),
            "perPersonCap": r.get("per_person_cap"), "totalCap": r.get("total_cap"),
            "allowedMerchants": len(r.get("allowed_merchants") or []), "network": r.get("network"),
            "blocked": {k: bl.get(k) for k in ("code", "reason_code", "tx_hash", "block") if bl.get(k) is not None} if isinstance(bl, dict) and bl else None,
            "violations": [v.get("code") for v in (r.get("violations") or []) if isinstance(v, dict)],
            "verdict": (r.get("dispute") or {}).get("verdict") if isinstance(r.get("dispute"), dict) else None,
            "txs": [{k: t.get(k) for k in ("kind", "tx_hash", "block") if t.get(k) is not None} for t in (r.get("txs") or []) if isinstance(t, dict)],
            "createdAt": r.get("created_at"), "updatedAt": r.get("updated_at")})
    return rows


def _lines(path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for _ in f)


def _sha256(path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot() -> dict[str, Any]:
    """보고서·정산 요약·목록(manifest)을 지금 기준으로 다시 쓴다. 베타 서버는 BETA_SNAPSHOT_SEC마다, 묶기 전에도 부른다."""
    ensure_dir()
    rep = report()
    with _lock:
        REPORT_JSON.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        REPORT_MD.write_text(report_markdown(rep), encoding="utf-8")
        SETTLEMENTS.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in _settlement_rows()), encoding="utf-8")
    ts = [r.get("ts") for r in _read(USAGE) if r.get("ts")]
    files = {}
    for f in sorted(DIR.iterdir()):
        if f.is_file() and f.name != MANIFEST.name:
            files[f.name] = {"bytes": f.stat().st_size, "lines": _lines(f) if f.suffix == ".jsonl" else None, "sha256": _sha256(f)}
    man = {"app": "Share Pie", "version": config.APP_VERSION, "generatedAt": time.time(),
           "generatedAtText": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), "folder": str(DIR),
           "range": {"from": min(ts) if ts else None, "to": max(ts) if ts else None}, "files": files,
           "participation": rep.get("participation"), "criteria": rep.get("criteria")}
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return man


def storage_info() -> dict[str, Any]:
    ensure_dir()
    files = [{"name": f.name, "bytes": f.stat().st_size, "lines": _lines(f) if f.suffix == ".jsonl" else None}
             for f in sorted(DIR.iterdir()) if f.is_file()]
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    return {"folder": str(DIR), "version": config.APP_VERSION, "files": files, "totalBytes": sum(f["bytes"] for f in files),
            "diskFreeBytes": shutil.disk_usage(DIR).free, "snapshotAt": man.get("generatedAtText"),
            "download": "/api/beta/bundle.zip?key=…  (또는 관리자 로그인)"}


def bundle_file(out_dir=None) -> "Path":
    """폴더를 zip 하나로 (최신 스냅샷 포함). 반환: zip 경로. 안에는 beta-data/ 아래 파일만."""
    from pathlib import Path as _P
    snapshot()
    out = _P(out_dir) if out_dir else _P(tempfile.gettempdir())
    out.mkdir(parents=True, exist_ok=True)
    name = f"sharepie-beta-data_{re.sub(r'[^0-9A-Za-z._-]', '-', config.APP_VERSION)}_{time.strftime('%Y%m%d-%H%M%S')}.zip"
    path = out / name
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:      # 잠금 없이 (묶는 동안에도 기록은 계속)
        for f in sorted(DIR.iterdir()):
            if f.is_file():
                z.write(f, f"beta-data/{f.name}")
    return path


if enabled():
    try:
        ensure_dir()
    except OSError as e:
        print(f"[beta] 데이터 폴더를 만들지 못했어요: {e}", flush=True)
if mirror_usage not in usage.HOOKS:
    usage.HOOKS.append(mirror_usage)
