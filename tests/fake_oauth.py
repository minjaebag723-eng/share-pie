"""테스트용 가짜 소셜 로그인 서버 (카카오·네이버·Google·Apple 흉내).
실행: python -m uvicorn tests.fake_oauth:app --port 8013
서버는 OAUTH_FAKE_BASE=http://127.0.0.1:8013 로 띄운다. POST /control {provider, sub, email, verified, name}로 '다음 로그인할 사람'을 정한다.
"""
import base64
import json
import secrets
from urllib.parse import parse_qs, urlencode

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

NEXT: dict[str, dict] = {}
CODES: dict[str, tuple] = {}
TOKENS: dict[str, dict] = {}


async def control(req: Request):
    b = await req.json()
    NEXT[b["provider"]] = b
    return JSONResponse({"ok": True})


async def authorize(req: Request):
    p, q = req.path_params["p"], req.query_params
    if not q.get("client_id") or not q.get("redirect_uri") or not q.get("state"):
        return JSONResponse({"error": "invalid_request"}, 400)
    code = secrets.token_hex(8)
    CODES[code] = (p, NEXT.get(p), q["redirect_uri"])
    return RedirectResponse(q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"]}), 302)


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


async def token(req: Request):
    p = req.path_params["p"]
    f = {k: v[0] for k, v in parse_qs((await req.body()).decode()).items()}
    got = CODES.pop(f.get("code", ""), None)
    if not got or got[0] != p or got[2] != f.get("redirect_uri"):
        return JSONResponse({"error": "invalid_grant", "error_description": "bad code"}, 400)
    if p != "kakao" and not f.get("client_secret"):
        return JSONResponse({"error": "invalid_client"}, 401)
    if p == "apple" and f["client_secret"].count(".") != 2:
        return JSONResponse({"error": "invalid_client", "error_description": "client_secret must be JWT"}, 401)
    ident = got[1]
    if p == "apple":
        idt = _b64({"alg": "none"}) + "." + _b64({"sub": ident["sub"], "email": ident.get("email"),
                                                  "email_verified": "true" if ident.get("verified") else "false"}) + ".sig"
        return JSONResponse({"access_token": "x", "id_token": idt})
    at = secrets.token_hex(8)
    TOKENS[at] = ident
    return JSONResponse({"access_token": at, "token_type": "bearer"})


async def profile(req: Request):
    p = req.path_params["p"]
    ident = TOKENS.get((req.headers.get("authorization") or "")[7:])
    if not ident:
        return JSONResponse({"error": "unauthorized"}, 401)
    if p == "kakao":
        acc = {"profile": {"nickname": ident.get("name", "")}}
        if ident.get("email"):
            acc.update({"email": ident["email"], "is_email_verified": bool(ident.get("verified")), "is_email_valid": True})
        return JSONResponse({"id": int(ident["sub"]), "kakao_account": acc})
    if p == "naver":
        return JSONResponse({"resultcode": "00", "response": {"id": ident["sub"], "email": ident.get("email"), "name": ident.get("name")}})
    return JSONResponse({"sub": ident["sub"], "email": ident.get("email"), "email_verified": bool(ident.get("verified")), "name": ident.get("name")})


app = Starlette(routes=[Route("/control", control, methods=["POST"]), Route("/{p}/authorize", authorize),
                        Route("/{p}/token", token, methods=["POST"]), Route("/{p}/profile", profile)])
