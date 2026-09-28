"""소셜 로그인 (카카오 · 네이버 · Google · Apple) — OAuth 2.0 인가 코드 방식.

흐름 (브라우저가 페이지째 이동하므로 CORS 없음):
  앱 버튼 → GET /api/auth/social/{p}/start → 각 사 로그인 화면
  → 각 사가 GET(애플은 POST) /api/auth/social/{p}/callback?code&state 로 돌려보냄
  → 서버가 code를 토큰으로 바꾸고 프로필(고유 id·이메일·이름)을 읽음 → 1회용 티켓을 만들어 앱(/#sp_social=티켓)으로 보냄
  → 앱이 POST /api/auth/social/exchange {ticket} → 로그인 완료(token) 또는 첫 가입이면 이름·Pie ID 입력 단계

키는 .env에만 둔다 (코드·저장소에 넣지 않음). 설정이 없는 회사 버튼은 '아직 준비 안 됨' 안내만 한다.
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from . import config

NAMES = {"kakao": "카카오", "naver": "네이버", "google": "Google", "apple": "Apple"}


class SocialError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _ep(provider: str) -> dict[str, str]:
    """각 사 주소. OAUTH_FAKE_BASE가 있으면 테스트용 가짜 서버로 (tests/fake_oauth.py)."""
    fake = config.OAUTH_FAKE_BASE.rstrip("/")
    if fake:
        return {k: f"{fake}/{provider}/{k}" for k in ("authorize", "token", "profile")}
    return {
        "kakao": {"authorize": "https://kauth.kakao.com/oauth/authorize", "token": "https://kauth.kakao.com/oauth/token",
                  "profile": "https://kapi.kakao.com/v2/user/me"},
        "naver": {"authorize": "https://nid.naver.com/oauth2.0/authorize", "token": "https://nid.naver.com/oauth2.0/token",
                  "profile": "https://openapi.naver.com/v1/nid/me"},
        "google": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
                   "profile": "https://openidconnect.googleapis.com/v1/userinfo"},
        "apple": {"authorize": "https://appleid.apple.com/auth/authorize", "token": "https://appleid.apple.com/auth/token",
                  "profile": ""},
    }[provider]


def _creds(provider: str) -> tuple[str, str]:
    return {
        "kakao": (config.KAKAO_CLIENT_ID, config.KAKAO_CLIENT_SECRET),
        "naver": (config.NAVER_CLIENT_ID, config.NAVER_CLIENT_SECRET),
        "google": (config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET),
        "apple": (config.APPLE_CLIENT_ID, ""),
    }[provider]


def configured(provider: str) -> bool:
    if provider not in NAMES:
        return False
    cid, sec = _creds(provider)
    if provider == "kakao":
        return bool(cid)                       # 카카오는 client_secret 선택
    if provider == "apple":
        return bool(cid and config.APPLE_TEAM_ID and config.APPLE_KEY_ID and config.APPLE_PRIVATE_KEY)
    return bool(cid and sec)


def providers() -> list[dict[str, Any]]:
    return [{"id": p, "name": n, "enabled": configured(p)} for p, n in NAMES.items()]


def authorize_url(provider: str, redirect_uri: str, state: str) -> str:
    cid, _ = _creds(provider)
    q: dict[str, str] = {"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "state": state}
    if provider == "kakao":
        q["scope"] = "profile_nickname account_email"   # 이메일은 동의 항목 설정이 돼 있어야 받음 (없어도 가입 가능)
        q["prompt"] = "select_account"
    elif provider == "google":
        q.update({"scope": "openid email profile", "prompt": "select_account", "access_type": "online"})
    elif provider == "apple":
        q.update({"scope": "name email", "response_mode": "form_post"})
    elif provider == "naver":
        q["auth_type"] = "reprompt"
    return _ep(provider)["authorize"] + "?" + urlencode(q)


def _apple_secret() -> str:
    """Apple은 client_secret 대신 .p8 키로 서명한 JWT(ES256)를 쓴다."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    except ImportError as e:
        raise SocialError("SOCIAL_NOT_CONFIGURED", "Apple 로그인에는 cryptography 패키지가 필요해요 (pip install cryptography)") from e
    raw = config.APPLE_PRIVATE_KEY
    pem = Path(raw).read_text() if raw and not raw.lstrip().startswith("-----") and Path(raw).exists() else raw.replace("\\n", "\n")
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()   # noqa: E731
    now = int(time.time())
    head = b64(json.dumps({"alg": "ES256", "kid": config.APPLE_KEY_ID}).encode())
    body = b64(json.dumps({"iss": config.APPLE_TEAM_ID, "iat": now, "exp": now + 600, "aud": "https://appleid.apple.com",
                           "sub": config.APPLE_CLIENT_ID}).encode())
    der = key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{head}.{body}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def _jwt_payload(tok: str) -> dict[str, Any]:
    """id_token 내용 읽기. 서버가 TLS로 토큰 엔드포인트에서 직접 받은 토큰이라 서명 검증 없이 써도 됨 (OIDC 3.1.3.7)."""
    part = tok.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def _truthy(v: Any) -> bool:
    return v is True or str(v).lower() == "true"


def fetch_identity(provider: str, code: str, redirect_uri: str, state: str, apple_user: str | None = None) -> dict[str, Any]:
    """인가 코드 → {provider, sub, email, email_verified, name}."""
    if not configured(provider):
        raise SocialError("SOCIAL_NOT_CONFIGURED", f"{NAMES.get(provider, provider)} 로그인이 아직 설정되지 않았어요.")
    cid, sec = _creds(provider)
    ep = _ep(provider)
    data = {"grant_type": "authorization_code", "client_id": cid, "code": code, "redirect_uri": redirect_uri}
    if provider == "naver":
        data["state"] = state
    if provider == "apple":
        sec = _apple_secret()
    if sec:
        data["client_secret"] = sec
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as c:
            r = c.post(ep["token"], data=data, headers={"Accept": "application/json"})
            tok = r.json() if r.content else {}
            if r.status_code >= 400 or "error" in tok or not (tok.get("access_token") or tok.get("id_token")):
                msg = tok.get("error_description") or tok.get("error") or f"HTTP {r.status_code}"
                raise SocialError("SOCIAL_TOKEN_FAILED", f"{NAMES[provider]} 인증에 실패했어요 ({str(msg)[:120]}). 다시 시도해 주세요.")
            if provider == "apple":
                p = _jwt_payload(tok["id_token"])
                name = ""
                if apple_user:   # 이름은 첫 로그인 때만 form으로 한 번 온다
                    try:
                        nm = json.loads(apple_user).get("name") or {}
                        name = f"{nm.get('lastName', '')}{nm.get('firstName', '')}".strip()
                    except (ValueError, AttributeError):
                        pass
                return {"provider": provider, "sub": str(p["sub"]), "email": (p.get("email") or "").lower(),
                        "email_verified": _truthy(p.get("email_verified")), "name": name}
            pr = c.get(ep["profile"], headers={"Authorization": f"Bearer {tok['access_token']}"})
            prof = pr.json()
            if pr.status_code >= 400:
                raise SocialError("SOCIAL_PROFILE_FAILED", f"{NAMES[provider]} 프로필을 읽지 못했어요.")
    except httpx.HTTPError as e:
        raise SocialError("SOCIAL_UNREACHABLE", f"{NAMES[provider]} 서버에 연결하지 못했어요: {type(e).__name__}") from e
    except ValueError as e:
        raise SocialError("SOCIAL_PROFILE_FAILED", f"{NAMES[provider]} 응답을 읽지 못했어요.") from e
    if provider == "kakao":
        acc = prof.get("kakao_account") or {}
        email = (acc.get("email") or "").lower()
        return {"provider": provider, "sub": str(prof["id"]), "email": email,
                "email_verified": bool(email) and _truthy(acc.get("is_email_verified")) and _truthy(acc.get("is_email_valid", True)),
                "name": ((acc.get("profile") or {}).get("nickname") or (prof.get("properties") or {}).get("nickname") or "")}
    if provider == "naver":
        res = prof.get("response") or {}
        email = (res.get("email") or "").lower()
        # 네이버 '연락처 이메일'은 외부 주소일 수 있어서, 네이버 메일일 때만 확인된 주소로 본다
        return {"provider": provider, "sub": str(res["id"]), "email": email, "email_verified": email.endswith("@naver.com"),
                "name": res.get("name") or res.get("nickname") or ""}
    email = (prof.get("email") or "").lower()
    return {"provider": provider, "sub": str(prof["sub"]), "email": email, "email_verified": _truthy(prof.get("email_verified")),
            "name": prof.get("name") or ""}
