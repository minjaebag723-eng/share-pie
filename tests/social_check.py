"""소셜 로그인 · 이메일 자동 채우기 점검 (가짜 OAuth 서버로 실제 HTTP 흐름 그대로).
python -m uvicorn tests.fake_oauth:app --port 8013 &
OAUTH_FAKE_BASE=http://127.0.0.1:8013 KAKAO_CLIENT_ID=k NAVER_CLIENT_ID=n NAVER_CLIENT_SECRET=s GOOGLE_CLIENT_ID=g GOOGLE_CLIENT_SECRET=s \
APPLE_CLIENT_ID=a APPLE_TEAM_ID=T APPLE_KEY_ID=K APPLE_PRIVATE_KEY=/tmp/apple.p8 LLM_MODE=mock python -m uvicorn backend.app:app --port 8000 &
python tests/social_check.py
"""
import json
import sys
from urllib.parse import parse_qs, unquote, urlparse

import httpx

API, FAKE = "http://127.0.0.1:8000", "http://127.0.0.1:8013"
c = httpx.Client(timeout=15, follow_redirects=False)
fails = []


def ok(cond, label):
    print(("  ✓ " if cond else "  ✗ ") + label)
    if not cond:
        fails.append(label)


def api(path, body=None, token=None, device=None):
    h = {}
    if token:
        h["Authorization"] = "Bearer " + token
    if device:
        h["X-SP-Device"] = device
    r = c.post(API + path, json=body, headers=h) if body is not None else c.get(API + path, headers=h)
    return r.json()


def social_round(provider, ident, apple_post=False, start_path=None):
    """버튼 → 각 사 → 콜백 → 앱(#sp_social=티켓)까지 브라우저처럼 따라간다. 반환: (fragment key, value)."""
    c.post(FAKE + "/control", json={"provider": provider, **ident})
    loc = start_path or c.get(f"{API}/api/auth/social/{provider}/start").headers["location"]
    r = c.get(loc)                                   # 가짜 각 사 로그인 → 콜백으로 리다이렉트
    cb = r.headers["location"]
    if apple_post:                                   # Apple은 form_post
        q = {k: v[0] for k, v in parse_qs(urlparse(cb).query).items()}
        q["user"] = json.dumps({"name": {"firstName": "민수", "lastName": "박"}})
        r2 = c.post(cb.split("?")[0], data=q)
    else:
        r2 = c.get(cb)
    frag = urlparse(r2.headers["location"]).fragment
    k, _, v = frag.partition("=")
    return k, unquote(v), cb


print("[설정]")
prov = api("/api/auth/social/providers")["data"]
ok([p["id"] for p in prov] == ["kakao", "naver", "google", "apple"] and all(p["enabled"] for p in prov), f"4개 회사 설정 확인: {prov}")

print("[Google 첫 가입 → 이름·Pie ID 입력 → 로그인]")
k, t, cb = social_round("google", {"sub": "g-100", "email": "mina@gmail.com", "verified": True, "name": "김미나"})
ok(k == "sp_social" and "/api/auth/social/google/callback" in cb, "콜백 → 앱으로 1회용 티켓 전달 (#sp_social)")
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "need_profile" and ex["email"] == "mina@gmail.com" and ex["emailVerified"] and ex["name"] == "김미나" and ex["pieId"],
   f"처음 온 사람 → 가입 마무리 단계 (이메일·이름·Pie ID 추천): {ex}")
done = api("/api/auth/social/complete", {"ticket": t, "name": "김미나", "pie_id": ex["pieId"]})["data"]
ok(done.get("token") and done["email"] == "mina@gmail.com" and done["social"] == ["google"] and not done["hasPassword"], "가입 완료 + 로그인 토큰")
me = api("/api/auth/me", token=done["token"])["data"]
ok(me["short"] == "미나", "토큰으로 내 정보 확인")
again = api("/api/auth/social/complete", {"ticket": t, "name": "김미나", "pie_id": ex["pieId"]})
ok(not again["ok"] and again["error"]["code"] == "SOCIAL_TICKET", "쓴 티켓은 다시 못 씀")
k, t, _ = social_round("google", {"sub": "g-100", "email": "mina@gmail.com", "verified": True, "name": "김미나"})
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "ok" and ex["token"] and ex["short"] == "미나", "두 번째부터는 바로 로그인")
r = api("/api/auth/login", {"email": "mina@gmail.com", "password": "whatever1"})
ok(not r["ok"] and r["error"]["code"] == "SOCIAL_ACCOUNT" and "Google" in r["error"]["message"], "소셜 가입 계정에 비밀번호 로그인 → Google로 로그인하라고 안내")

print("[이메일 가입자 + 같은 이메일 소셜 → 자동 연결]")
dev = "dev" + "a" * 20
code = api("/api/auth/email-code", {"email": "jun@naver.com", "purpose": "signup"})["data"]["dev_code"]
su = api("/api/auth/signup", {"name": "이준호", "email": "jun@naver.com", "password": "pass1234", "code": code, "pie_id": "junho"}, device=dev)
ok(su["ok"], "이메일로 가입")
k, t, _ = social_round("naver", {"sub": "n-7", "email": "jun@naver.com", "name": "이준호"})
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "ok" and ex["linked"] and ex["short"] == "준호" and "naver" in ex["social"], "확인된 같은 이메일 → 기존 계정에 네이버 연결 후 로그인")
k, t, _ = social_round("google", {"sub": "g-evil", "email": "jun@naver.com", "verified": False, "name": "가짜"})
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "need_profile" and not ex["emailVerified"], "확인 안 된 이메일은 기존 계정에 붙이지 않음 (계정 탈취 방지)")

print("[카카오: 이메일 못 받음 → 메일 인증 후 가입]")
k, t, _ = social_round("kakao", {"sub": "9001", "name": "박소연"})
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "need_profile" and not ex["emailVerified"] and ex["email"] == "", "이메일 없음 → 인증 필요")
r = api("/api/auth/social/complete", {"ticket": t, "name": "박소연", "pie_id": "soyeon", "email": "so@test.com"})
ok(not r["ok"] and r["error"]["code"] in ("CODE_REQUIRED", "CODE_MISMATCH"), "인증번호 없이는 가입 안 됨: " + r["error"]["code"])
code = api("/api/auth/email-code", {"email": "so@test.com", "purpose": "signup"})["data"]["dev_code"]
r = api("/api/auth/social/complete", {"ticket": t, "name": "박소연", "pie_id": "soyeon", "email": "so@test.com", "code": code})["data"]
ok(r["email"] == "so@test.com" and r["social"] == ["kakao"], "메일 인증 후 카카오 가입")
so_token = r["token"]

print("[Apple (form_post · 이름은 첫 로그인 때만)]")
k, t, _ = social_round("apple", {"sub": "a-1", "email": "x1@privaterelay.appleid.com", "verified": True}, apple_post=True)
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(k == "sp_social" and ex["status"] == "need_profile" and ex["name"] == "박민수", f"Apple POST 콜백 + 이름 받기: {ex.get('name')}")

print("[보안]")
start = c.get(f"{API}/api/auth/social/google/start").headers["location"]
c.post(FAKE + "/control", json={"provider": "google", "sub": "g-100", "email": "mina@gmail.com", "verified": True})
cb = c.get(start).headers["location"]
c.get(cb)
r = c.get(cb)                                      # 같은 state 재사용
ok("sp_social_error" in r.headers["location"], "state는 1회용 (재사용 → 에러)")
bad = c.get(f"{API}/api/auth/social/google/callback?code=x&state=forged").headers["location"]
ok("sp_social_error" in bad, "위조 state 거부")
cancel = c.get(f"{API}/api/auth/social/kakao/callback?error=access_denied&state=nope").headers["location"]
ok("sp_social_error" in cancel, "취소·오류는 앱에 메시지로 전달")

print("[로그인 상태에서 계정 연결 · 해제 · 탈퇴]")
link = api("/api/auth/social/google/link", {}, token=so_token)["data"]
k, t, _ = social_round("google", {"sub": "g-so", "email": "so@gmail.com", "verified": True}, start_path=link["url"])
ex = api("/api/auth/social/exchange", {"ticket": t})["data"]
ok(ex["status"] == "linked" and ex["social"] == ["google", "kakao"], "내 계정에 Google 추가 연결")
r = api("/api/auth/social/google/unlink", {}, token=so_token)["data"]
ok(r["social"] == ["kakao"], "연결 해제")
r = api("/api/auth/social/kakao/unlink", {}, token=so_token)
ok(not r["ok"] and r["error"]["code"] == "LAST_LOGIN_METHOD", "비밀번호 없는 계정의 마지막 소셜은 해제 불가")
r = api("/api/auth/withdraw", {"password": "아무거나"}, token=so_token)
ok(not r["ok"], "소셜 계정 탈퇴는 ‘탈퇴’ 입력 필요")
r = api("/api/auth/withdraw", {"password": "탈퇴"}, token=so_token)
ok(r["ok"], "‘탈퇴’ 입력 후 탈퇴")
k, t, _ = social_round("kakao", {"sub": "9001", "name": "박소연"})
ok(api("/api/auth/social/exchange", {"ticket": t})["data"]["status"] == "need_profile", "탈퇴하면 소셜 연결도 삭제 → 다시 가입 단계")

print("[이메일 자동 채우기 (기기별, 서버 저장)]")
ok(api("/api/auth/remembered", device=dev)["data"]["email"] == "jun@naver.com", "가입한 기기 → 로그인 화면에 가입 이메일")
ok(api("/api/auth/remembered", device="other" + "b" * 20)["data"]["email"] is None, "다른 기기에는 안 보임")
ok(api("/api/auth/remembered")["data"]["email"] is None, "기기 ID 없으면 없음")
api("/api/auth/login", {"email": "jun@naver.com", "password": "pass1234"}, device="phone" + "c" * 20)
ok(api("/api/auth/remembered", device="phone" + "c" * 20)["data"]["email"] == "jun@naver.com", "이메일 로그인한 기기도 기억")
api("/api/auth/remembered/forget", {}, device=dev)
ok(api("/api/auth/remembered", device=dev)["data"]["email"] is None, "기억 지우기")

print("✓ 전체 통과" if not fails else f"✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
