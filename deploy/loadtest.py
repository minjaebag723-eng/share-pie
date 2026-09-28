"""100명 동시 접속 부하 테스트 — 실제 화면이 서버에 보내는 요청을 흉내 낸다.

  1) 서버 켜기 (가짜 Kiln에 지연을 줘서 실제 AI 응답 시간을 흉내):
       FAKE_KILN_DELAY=2 python -m uvicorn tests.fake_kiln:app --port 8011
       DATA_DIR=/tmp/sp-load LLM_MODE=live KILN_API_KEY=x KILN_BASE_URL=http://127.0.0.1:8011/v1 CHAIN_MODE=mock \\
         python -m uvicorn deploy.asgi:app --port 8000 --workers 1
  2) python deploy/loadtest.py --base http://127.0.0.1:8000 --users 100 --duration 90
실제 서버에 돌릴 때는 --prefix를 바꿔 테스트 계정을 구분하고, 끝나면 그 계정은 지우거나 데이터 폴더를 비운 뒤 베타를 시작하세요.

사용자마다: 가입·로그인 → 4초마다 화면 새로고침(방·알림·친구·정산 + 두 번에 한 번 AI 사용량) · 20~40초마다 Pie 1:1 대화(베타 미션 문장)
· 30~60초마다 그룹방 메시지(절반은 정산 조건 → Pie mate가 답함). 따로 0.5초마다 /healthz로 서버 반응 속도를 잰다.
결과: 요청 종류별 건수 · 실패 · 지연 p50/p95/p99 · 초당 처리량 (+ --json 파일).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import defaultdict

import httpx

STATS: dict[str, list[float]] = defaultdict(list)
ERRS: dict[str, int] = defaultdict(int)
ERR_SAMPLES: dict[str, str] = {}
CHATS = ["삼겹살 38,900원 넷이 똑같이 나눠줘", "AI 요금제는 어떻게 돼?", "월말이라 거지다 넷이 치킨 시키자 6만원 안에서",
         "한정식 15만원인데 부가세 10% 별도래 여섯이 나눠줘", "총 5만원인데 진주는 조금 더 내게 해줘", "충전 어디서 해?"]
GROUP_SETTLE = ["치킨 3만2천원 넷이 똑같이 나눠줘", "파이야 누가 아직 안 냈어?", "8만원 넷이 똑같이 나누는데 1인 1만5천원 넘으면 안 돼"]
GROUP_CHAT = ["ㅋㅋㅋ 오늘 날씨 좋다", "내일 몇 시에 만나?", "사진 올려줘", "와이파이 느리다"]


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def call(c: httpx.AsyncClient, kind: str, method: str, url: str, **kw):
    t0 = time.perf_counter()
    try:
        r = await c.request(method, url, **kw)
        dt = (time.perf_counter() - t0) * 1000
        STATS[kind].append(dt)
        if r.status_code >= 400:
            ERRS[kind] += 1
            ERR_SAMPLES.setdefault(kind, f"HTTP {r.status_code}: {r.text[:120]}")
            return None
        return r.json() if "json" in (r.headers.get("content-type") or "") else r.text
    except Exception as e:  # noqa: BLE001
        STATS[kind].append((time.perf_counter() - t0) * 1000)
        ERRS[kind] += 1
        ERR_SAMPLES.setdefault(kind, repr(e)[:160])
        return None


def data(x):
    return x.get("data", x) if isinstance(x, dict) else x


async def make_user(c: httpx.AsyncClient, prefix: str, i: int, sem: asyncio.Semaphore) -> dict | None:
    email = f"{prefix}{i:03d}@load.test"
    async with sem:
        code = data(await call(c, "setup.code", "POST", "/api/auth/email-code", json={"email": email, "purpose": "signup"}) or {})
        u = data(await call(c, "setup.signup", "POST", "/api/auth/signup",
                            json={"name": f"부하{i:03d}", "email": email, "password": "load-test-1234", "code": (code or {}).get("dev_code")}) or {})
        if not (u or {}).get("token"):
            u = data(await call(c, "setup.login", "POST", "/api/auth/login", json={"email": email, "password": "load-test-1234"}) or {})
    return u if (u or {}).get("token") else None


async def user_loop(base: str, u: dict, gid: str | None, until: float) -> None:
    h = {"Authorization": f"Bearer {u['token']}"}
    async with httpx.AsyncClient(base_url=base, headers=h, timeout=60) as c:
        await call(c, "page.index", "GET", "/")
        await call(c, "page.config", "GET", "/api/config")
        n, next_chat, next_group = 0, time.time() + random.uniform(3, 25), time.time() + random.uniform(5, 40)
        chat_id = "c" + uuid.uuid4().hex[:10]
        await asyncio.sleep(random.uniform(0, 4))
        while time.time() < until:
            t_poll = time.time()
            await call(c, "poll.groups", "GET", "/api/groups")
            await asyncio.gather(call(c, "poll.notifs", "GET", "/api/notifs"), call(c, "poll.friends", "GET", "/api/friends"))
            await call(c, "poll.settlements", "GET", f"/api/settlements?member={u['short']}")
            if n % 2 == 0:
                await call(c, "poll.ai_usage", "GET", "/api/ai/usage")
            n += 1
            if time.time() >= next_chat:
                sc = random.choice(["S01", "S13", "S08", None])
                await call(c, "pie.chat", "POST", "/api/chat", json={"message": random.choice(CHATS), "chat_id": chat_id, "user": u["short"],
                                                                     "history": [], "context": {}, "scenario": sc, "edited": False if sc else None})
                next_chat = time.time() + random.uniform(20, 40)
            if gid and time.time() >= next_group:
                text = random.choice(GROUP_SETTLE if random.random() < 0.5 else GROUP_CHAT)
                await call(c, "group.message", "POST", f"/api/groups/{gid}/messages",
                           json={"id": "m" + uuid.uuid4().hex[:12], "from": u["short"], "text": text})
                next_group = time.time() + random.uniform(30, 60)
            await asyncio.sleep(max(0.0, 4 - (time.time() - t_poll)))


async def probe(base: str, until: float) -> None:
    async with httpx.AsyncClient(base_url=base, timeout=30) as c:
        while time.time() < until:
            await call(c, "probe.healthz", "GET", "/healthz")
            await asyncio.sleep(0.5)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--users", type=int, default=100)
    ap.add_argument("--duration", type=int, default=90)
    ap.add_argument("--prefix", default="load")
    ap.add_argument("--json", help="결과를 JSON으로도 저장")
    a = ap.parse_args()
    t0 = time.time()
    async with httpx.AsyncClient(base_url=a.base, timeout=120) as c:
        sem = asyncio.Semaphore(10)
        users = [u for u in await asyncio.gather(*(make_user(c, a.prefix, i, sem) for i in range(a.users))) if u]
        print(f"계정 {len(users)}/{a.users}명 준비 ({time.time() - t0:.1f}초)")
        rooms = []
        for k in range(0, len(users) - 3, 4):
            grp = users[k:k + 4]
            g = data(await call(c, "setup.group", "POST", "/api/groups/create", headers={"Authorization": f"Bearer {grp[0]['token']}"},
                                json={"name": f"부하방{k // 4:02d}", "members": [x["short"] for x in grp]}) or {})
            rooms += [(x, (g or {}).get("id")) for x in grp]
        in_room = {x["email"]: gid for x, gid in rooms}
    for k in [k for k in STATS if k.startswith("setup.")]:
        STATS.pop(k)
    print(f"그룹방 {len(rooms) // 4}개 · {a.users}명이 {a.duration}초 동안 사용 시작")
    until = time.time() + a.duration
    t_run = time.time()
    await asyncio.gather(probe(a.base, until), *(user_loop(a.base, u, in_room.get(u["email"]), until) for u in users))
    run_sec = time.time() - t_run
    total = sum(len(v) for v in STATS.values())
    rows = []
    for k in sorted(STATS):
        xs = STATS[k]
        rows.append({"kind": k, "n": len(xs), "errors": ERRS.get(k, 0), "p50": round(pct(xs, 50)), "p95": round(pct(xs, 95)),
                     "p99": round(pct(xs, 99)), "max": round(max(xs)) if xs else 0, "mean": round(statistics.mean(xs)) if xs else 0})
    print(f"\n{'요청':<18}{'건수':>7}{'실패':>6}{'p50ms':>8}{'p95ms':>8}{'p99ms':>8}{'최대ms':>9}")
    for r in rows:
        print(f"{r['kind']:<18}{r['n']:>7}{r['errors']:>6}{r['p50']:>8}{r['p95']:>8}{r['p99']:>8}{r['max']:>9}")
    errs = sum(ERRS.values())
    print(f"\n총 {total:,}건 · 초당 {total / run_sec:.1f}건 · 실패 {errs}건 ({errs / max(1, total):.2%})")
    for k, v in ERR_SAMPLES.items():
        print(f"  실패 예: {k} → {v}")
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump({"users": len(users), "duration": a.duration, "rps": round(total / run_sec, 1), "errors": errs, "rows": rows}, f,
                      ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
