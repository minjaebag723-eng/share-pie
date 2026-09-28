"""Share Pie 백엔드 (포트 8000). 실행: python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000

- Starlette 사용 (FastAPI의 기반 엔진 그대로, 의존성 최소화). 모든 로직은 agent/service.py 에 있음.
- 같은 서버가 frontend/ 를 "/" 로 서빙 → 폰에서 같은 주소로 접속하면 CORS 문제 없음.
- 응답 형식 (고정):
    성공 {"ok": true,  "data": {...}}
    실패 {"ok": false, "error": {"code": "...", "message": "...", "stage": "...", "details": ...}}
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from urllib.parse import parse_qs, quote

from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Mount, Route
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles


class NoCacheStatic(StaticFiles):
    """프론트 파일을 바꾼 뒤 브라우저가 옛 화면을 캐시로 보여 주지 않도록."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import config, service
from agent import usage as usage_log  # noqa: E402
from agent import beta as beta_mod  # noqa: E402
from agent.service import ServiceError  # noqa: E402


# ───────────── 요청 스키마 (docs/API.md 와 동일) ─────────────
class HistoryItem(BaseModel):
    role: str  # user | bot
    text: str = ""
    intent: str | None = None
    needs_info: bool = False


class ChatReq(BaseModel):
    message: str
    chat_id: str | None = None
    user: str | None = None
    history: list[HistoryItem] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    scenario: str | None = None      # 베타 기능 예시 id (S01~S13)
    edited: bool | None = None       # 예시 문장을 고쳐 보냈는지


class BetaConsentReq(BaseModel):
    agree: bool


class BetaFeedbackReq(BaseModel):
    turn: str
    rating: str                      # up | down
    reason: str | None = None
    note: str | None = None


class CalcReq(BaseModel):
    text: str
    members: list[str] = Field(default_factory=list)
    total: int | None = None
    payer: str | None = None
    subject: str | None = None
    history: list[str] = Field(default_factory=list)
    flow: str | None = None


class ProposeReq(BaseModel):
    group_name: str
    group_id: str | None = None
    members: list[str]
    shares: list[tuple[str, int]]
    total: int
    payer: str
    rule_text: str = ""
    purpose: str = ""
    per_person_cap: int | None = None
    total_cap: int | None = None
    merchant: str | None = None
    mode: str | None = None
    allowed_merchants: list[str] | None = None
    purchase: bool = False                      # AI 구매 대행 (가상 결제 계좌 → 가맹점 자동 결제)
    product: dict[str, Any] | None = None       # {name, url, qty, units}


class SyncReq(BaseModel):
    tx_hash: str | None = None


class AnalyzeReq(CalcReq):
    pass


class Stage2Req(BaseModel):
    total: int
    members: list[str]
    adjustments: list[dict[str, Any]] = Field(default_factory=list)
    payer: str | None = None
    per_person_cap: int | None = None
    total_cap: int | None = None
    flow: str | None = None


class ExplainReq(BaseModel):
    result: dict[str, Any]
    subject: str | None = None
    flow: str | None = None


class ApproveReq(BaseModel):
    settlement_id: str
    name: str
    tx_hash: str | None = None


class OfflineReq(BaseModel):
    settlement_id: str
    participant: str
    confirmer: str


class DisputeRaiseReq(BaseModel):
    settlement_id: str
    by: str
    reason: str


class SidReq(BaseModel):
    settlement_id: str
    flow: str | None = None


class SignupReq(BaseModel):
    name: str
    email: str
    password: str
    code: str | None = None
    pie_id: str | None = None


class PieIdReq(BaseModel):
    id: str


class LocateReq(BaseModel):
    lat: float
    lng: float
    save: bool = True


class ProfileReq(BaseModel):
    pie_id: str | None = None
    address: str | None = None


class CodeReq(BaseModel):
    email: str
    purpose: str = "signup"


class ResetReq(BaseModel):
    email: str
    code: str
    password: str


class ChangePwReq(BaseModel):
    old_password: str
    new_password: str


class PwReq(BaseModel):
    password: str


class FindIdReq(BaseModel):
    name: str


class LoginReq(BaseModel):
    email: str
    password: str


class NameReq(BaseModel):
    name: str


class ShopSearchReq(BaseModel):
    query: str
    history: list[str] = Field(default_factory=list)
    flow: str | None = None


class MemberReq(BaseModel):
    name: str
    wallet: str | None = None


class MockLockReq(BaseModel):
    sid: str
    name: str


class AiPayReq(BaseModel):
    amount: int | None = None
    tx_hash: str | None = None


class TamperReq(BaseModel):
    sid: str
    name: str
    amount: int


# ───────────── 공통 ─────────────
async def run(fn):
    """AI·웹·체인 호출은 오래 걸리므로 스레드에서 실행 → 다른 폰의 요청(4초 폴링 등)이 멈추지 않게."""
    return await run_in_threadpool(fn)


def ok(data: Any) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data})


def fail(code: str, message: str, stage: str = "", status: int = 400, details: Any = None) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code, "message": message, "stage": stage, "details": details}},
                        status_code=status)


async def body(request: Request, model: type[BaseModel]) -> BaseModel:
    try:
        raw = await request.json()
    except Exception:
        raise ServiceError("BAD_REQUEST", "JSON 본문이 필요해요", request.url.path)
    try:
        return model.model_validate(raw)
    except ValidationError as e:
        raise ServiceError("BAD_REQUEST", "요청 형식이 올바르지 않아요", request.url.path, 422,
                           [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()])


def endpoint(fn):
    async def wrapper(request: Request):
        try:
            return ok(await fn(request))
        except ServiceError as e:
            return fail(e.code, e.message, e.stage, e.status, e.details)
        except Exception as e:  # 예상 못 한 에러도 같은 형식으로
            traceback.print_exc()
            return fail("INTERNAL", f"서버 오류: {e}", request.url.path, 500)
    return wrapper


# ───────────── 로그인 확인 (Authorization: Bearer <token>) ─────────────
def _token(req: Request) -> str | None:
    h = req.headers.get("authorization") or ""
    return h[7:].strip() if h.lower().startswith("bearer ") else None


async def need(req: Request, name: str | None = None, stage: str = "auth") -> dict[str, Any] | None:
    """로그인한 사용자. name을 주면 '본인 요청'인지 확인 (남의 이름으로 결제·취소·이의제기 방지)."""
    u = await run(lambda: service.session_user(_token(req)))
    if not u:
        if config.AUTH_REQUIRED:
            raise ServiceError("UNAUTHORIZED", "로그인이 필요해요. 다시 로그인해 주세요.", stage, 401)
        return None
    if name is not None and name != u["short"]:
        raise ServiceError("FORBIDDEN", "본인 계정으로만 할 수 있는 작업이에요.", stage, 403)
    usage_log.set_actor(u)      # 이 요청에서 부르는 Kiln 호출은 이 사람의 AI 사용량(AI원)으로 기록
    return u


def _member_of(sid: str, u: dict[str, Any] | None) -> None:
    if u is None:
        return
    rec = service.store.get(sid)
    if rec and not any(m["name"] == u["short"] for m in rec["members"]) and rec.get("payer") != u["short"]:
        raise ServiceError("FORBIDDEN", "이 정산의 참여자만 볼 수 있어요.", "settlement", 403)


# ───────────── 라우트 ─────────────
@endpoint
async def health(_: Request):
    return await run(lambda: service.health())


@endpoint
async def cfg(_: Request):
    return await run(lambda: service.config_info())


@endpoint
async def chat(req: Request):
    b = await body(req, ChatReq)
    u = await need(req, stage="chat")
    user = u["short"] if u else b.user
    return await run(lambda: service.chat(b.message, [h.model_dump() for h in b.history], b.context, b.chat_id, user,
                                          scenario=b.scenario, edited=b.edited))


@endpoint
async def calculate(req: Request):
    b = await body(req, CalcReq)
    await need(req, stage="settlement.analyze")
    return await run(lambda: service.calculate(b.text, b.members, b.total, b.payer, b.subject, b.history, b.flow))


@endpoint
async def propose(req: Request):
    b = await body(req, ProposeReq)
    u = await need(req, stage="settlement.request")
    return await run(lambda: service.propose_request(u["short"] if u else None, **{**b.model_dump(), "shares": [list(x) for x in b.shares]}))


@endpoint
async def sync(req: Request):
    b = await body(req, SyncReq)
    _member_of(req.path_params["sid"], await need(req, stage="settlement.sync"))
    return await run(lambda: service.sync(req.path_params["sid"], b.tx_hash))


@endpoint
async def get_settlement(req: Request):
    _member_of(req.path_params["sid"], await need(req, stage="settlement"))
    return await run(lambda: service.get_settlement(req.path_params["sid"]))


@endpoint
async def list_settlements(req: Request):
    await need(req, req.query_params.get("member"), stage="settlement.list")
    return await run(lambda: service.list_for(req.query_params.get("member")))


@endpoint
async def register(req: Request):
    b = await body(req, MemberReq)
    await need(req, b.name, stage="wallet.register")
    return await run(lambda: service.register_member(b.name, b.wallet))


@endpoint
async def members(req: Request):
    await need(req)
    return await run(lambda: service.store.members())


@endpoint
async def wallet(req: Request):
    return await run(lambda: service.wallet(req.path_params["address"]))


@endpoint
async def usage(req: Request):
    return await run(lambda: service.usage_summary(req.query_params.get("flow")))


async def usage_md(req: Request):
    return PlainTextResponse((await run(lambda: service.usage_summary(req.query_params.get("flow"))))["markdown"],
                             media_type="text/markdown; charset=utf-8")


@endpoint
async def b_status(req: Request):
    u = await _login(req)
    return await run(lambda: service.beta_status(u))


@endpoint
async def b_consent(req: Request):
    b = await body(req, BetaConsentReq)
    u = await _login(req)
    return await run(lambda: service.beta_consent(u, b.agree))


@endpoint
async def b_feedback(req: Request):
    b = await body(req, BetaFeedbackReq)
    u = await _login(req)
    return await run(lambda: service.beta_feedback(u, b.turn, b.rating, b.reason, b.note))


@endpoint
async def b_report(_: Request):
    """공개 요약 (대화 글 없음): 시나리오 × 버전별 턴당 토큰, 심사 기준 실행 수, 참여 현황."""
    return await run(service.beta_report)


async def b_report_md(_: Request):
    return PlainTextResponse((await run(service.beta_report))["markdown"], media_type="text/markdown; charset=utf-8")


async def b_export(req: Request):
    """학습·평가 후보 내보내기 (비식별 대화) — 관리자(BETA_ADMIN_EMAILS) 로그인 또는 ?key=BETA_EXPORT_KEY 만."""
    key = req.query_params.get("key") or ""
    ok_key = bool(config.BETA_EXPORT_KEY) and key == config.BETA_EXPORT_KEY
    u = None
    if not ok_key:
        try:
            u = await need(req, stage="beta.export")
        except ServiceError:
            u = None                              # 로그인 안 함 → 아래에서 403
    if not ok_key and not (u and (u.get("email") or "").lower() in config.BETA_ADMIN_EMAILS):
        return JSONResponse({"ok": False, "error": {"code": "FORBIDDEN", "message": "베타 데이터 내보내기는 관리자만 할 수 있어요."}}, status_code=403)
    kind = req.query_params.get("kind") or "train"
    txt = await run(lambda: beta_mod.export(kind if kind in ("train", "eval", "raw") else "train"))
    return PlainTextResponse(txt, media_type="application/x-ndjson; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="share_pie_beta_{kind}.jsonl"'})


async def usage_csv(req: Request):
    """호출 한 줄 = 한 행 (단계·구간·토큰·지연·에너지·응답 반영). 개인정보 없이 흐름 id로만 묶는다."""
    return PlainTextResponse(await run(lambda: service.usage_calls_csv(req.query_params.get("flow"))), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="share_pie_kiln_calls.csv"'})


@endpoint
async def dev_lock(req: Request):
    b = await body(req, MockLockReq)
    return await run(lambda: service.mock_lock(b.sid, b.name))


@endpoint
async def dev_tamper(req: Request):
    b = await body(req, TamperReq)
    return await run(lambda: service.mock_tamper(b.sid, b.name, b.amount))


def _device(req: Request) -> str | None:
    return req.headers.get("x-sp-device")


@endpoint
async def signup(req: Request):
    b = await body(req, SignupReq)
    u = await run(lambda: service.signup(b.name, b.email, b.password, b.code, b.pie_id))
    service.remember_device(_device(req), u["email"])     # 다음에 로그인 화면에 이 이메일을 채움
    return u


@endpoint
async def login(req: Request):
    b = await body(req, LoginReq)
    u = await run(lambda: service.login(b.email, b.password))
    service.remember_device(_device(req), u["email"])
    return u


@endpoint
async def a_remembered(req: Request):
    """이 기기에서 이메일로 가입·로그인한 마지막 이메일 (로그인 화면 자동 채우기). 소셜 로그인은 기록하지 않음."""
    return await run(lambda: service.remembered(_device(req)))


@endpoint
async def a_forget(req: Request):
    return await run(lambda: service.forget_device(_device(req)))


# ── 소셜 로그인: start·callback은 브라우저가 페이지째 이동하는 주소라 JSON 대신 리다이렉트 ──
def _base_url(req: Request) -> str:
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL
    proto = (req.headers.get("x-forwarded-proto") or req.url.scheme).split(",")[0].strip()
    host = (req.headers.get("x-forwarded-host") or req.headers.get("host") or req.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}"


def _callback_uri(req: Request, provider: str) -> str:
    return f"{_base_url(req)}/api/auth/social/{provider}/callback"


def _to_app(req: Request, key: str, value: str) -> RedirectResponse:
    # 티켓은 # 뒤(fragment)로 넘김 → 서버 로그·Referer에 남지 않음
    return RedirectResponse(f"{_base_url(req)}/#{key}={quote(value, safe='')}", status_code=303)


@endpoint
async def a_social_providers(_: Request):
    return service.social_providers()


async def a_social_start(req: Request):
    p = req.path_params["provider"]
    try:
        url = await run(lambda: service.social_start(p, _callback_uri(req, p)))
        return RedirectResponse(url, status_code=302)
    except ServiceError as e:
        return _to_app(req, "sp_social_error", e.message)


async def a_social_callback(req: Request):
    p = req.path_params["provider"]
    q = dict(req.query_params)
    if req.method == "POST":           # Apple은 form_post (multipart 패키지 없이 직접 파싱)
        raw = (await req.body()).decode("utf-8", "replace")
        q.update({k: v[0] for k, v in parse_qs(raw).items()})
    try:
        ticket = await run(lambda: service.social_callback(p, q.get("code"), q.get("state"), q.get("error"), q.get("user")))
        return _to_app(req, "sp_social", ticket)
    except ServiceError as e:
        return _to_app(req, "sp_social_error", e.message)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        return _to_app(req, "sp_social_error", f"소셜 로그인 처리 중 오류가 났어요 ({type(e).__name__})")


class TicketReq(BaseModel):
    ticket: str


class SocialCompleteReq(BaseModel):
    ticket: str
    name: str
    pie_id: str | None = None
    email: str | None = None
    code: str | None = None


@endpoint
async def a_social_exchange(req: Request):
    b = await body(req, TicketReq)
    return await run(lambda: service.social_exchange(b.ticket))


@endpoint
async def a_social_complete(req: Request):
    b = await body(req, SocialCompleteReq)
    return await run(lambda: service.social_complete(b.ticket, b.name, b.pie_id, b.email, b.code))


@endpoint
async def a_social_link(req: Request):
    u = await need(req)
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "auth.social", 401)
    p = req.path_params["provider"]
    return await run(lambda: service.social_link_start(u, p, _callback_uri(req, p)))


@endpoint
async def a_social_unlink(req: Request):
    u = await need(req)
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "auth.social", 401)
    return await run(lambda: service.social_unlink(u, req.path_params["provider"]))


class GroupReq(BaseModel):
    model_config = {"extra": "allow"}
    id: str | None = None


class MsgReq(BaseModel):
    model_config = {"extra": "allow"}
    id: str | None = None
    text: str | None = None


class ResolveReq(BaseModel):
    accepted: bool


class ChatSaveReq(BaseModel):
    model_config = {"extra": "allow"}
    id: str


def _uname(u) -> str:
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "auth", 401)
    return u["short"]


@endpoint
async def g_list(req: Request):
    me = _uname(await need(req))
    return await run(lambda: service.groups_for(me))


@endpoint
async def g_create(req: Request):
    b = await body(req, GroupReq)
    me = _uname(await need(req))
    return await run(lambda: service.group_create(me, b.model_dump()))


@endpoint
async def g_update(req: Request):
    b = await body(req, GroupReq)
    me = _uname(await need(req))
    return await run(lambda: service.group_update(me, req.path_params["gid"], b.model_dump(exclude={"id"})))


@endpoint
async def g_msg(req: Request):
    b = await body(req, MsgReq)
    me = _uname(await need(req))
    gid = req.path_params["gid"]
    m = await run(lambda: service.group_message(me, gid, b.model_dump()))
    # Pie mate가 방금 메시지를 읽고 답할지 판단 → 답은 방에 저장(다른 폰은 폴링으로 받음) + 보낸 폰에는 바로 돌려줌
    try:
        ex = b.model_extra or {}          # 베타 기능 예시로 보낸 메시지면 scenario·edited가 같이 온다
        replies = await run(lambda: service.group_pie(me, gid, m["id"], scenario=ex.get("scenario"), edited=ex.get("edited"))) \
            if m.get("from") != "sys" else []
    except Exception as e:  # noqa: BLE001 — Pie 실패가 메시지 전송 실패가 되면 안 됨
        print(f"[group.pie 실패] {gid}: {e}", flush=True)
        replies = []
    return {**m, "replies": replies}


@endpoint
async def g_resolve(req: Request):
    b = await body(req, ResolveReq)
    me = _uname(await need(req))
    return await run(lambda: service.group_resolve(me, req.path_params["gid"], req.path_params["mid"], b.accepted))


@endpoint
async def ai_usage(req: Request):
    u = await need(req, stage="ai.usage")
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "ai.usage", 401)
    return await run(lambda: service.ai_usage(u))


@endpoint
async def ai_pay(req: Request):
    b = await body(req, AiPayReq)
    u = await need(req, stage="ai.pay")
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "ai.pay", 401)
    return await run(lambda: service.ai_pay(u, b.amount, b.tx_hash))


@endpoint
async def c_list(req: Request):
    me = _uname(await need(req))
    return await run(lambda: service.chats_for(me))


@endpoint
async def c_save(req: Request):
    b = await body(req, ChatSaveReq)
    me = _uname(await need(req))
    return await run(lambda: service.chat_save(me, b.model_dump()))


@endpoint
async def c_delete(req: Request):
    me = _uname(await need(req))
    return await run(lambda: service.chat_delete(me, req.path_params["cid"]))


@endpoint
async def u_check_id(req: Request):
    return service.check_pie_id(req.query_params.get("id", ""))


@endpoint
async def u_by_id(req: Request):
    u = await need(req)
    return await run(lambda: service.user_by_pie_public(req.path_params["pid"], u))


@endpoint
async def f_list(req: Request):
    u = await need(req)
    return service.friends_list(u) if u else []


@endpoint
async def f_add(req: Request):
    b = await body(req, PieIdReq)
    u = await need(req)
    return await run(lambda: service.friend_add(u, b.id))


@endpoint
async def f_remove(req: Request):
    b = await body(req, PieIdReq)
    u = await need(req)
    return await run(lambda: service.friend_remove(u, b.id))


async def _login(req: Request) -> dict[str, Any]:
    u = await need(req)
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "auth", 401)
    return u


def _friend_route(fn_name: str):
    @endpoint
    async def h(req: Request):
        b = await body(req, PieIdReq)
        u = await _login(req)
        return await run(lambda: getattr(service, fn_name)(u, b.id))
    return h


@endpoint
async def f_requests(req: Request):
    u = await _login(req)
    return await run(lambda: service.friend_requests(u))


class NotifReadReq(BaseModel):
    ids: list[str] | None = None


@endpoint
async def n_list(req: Request):
    u = await _login(req)
    return await run(lambda: service.notifs_for(u))


@endpoint
async def n_read(req: Request):
    b = await body(req, NotifReadReq)
    u = await _login(req)
    return await run(lambda: service.notifs_read(u, b.ids))


class MuteReq(BaseModel):
    muted: bool


class RenameReq(BaseModel):
    name: str


class InviteReq(BaseModel):
    ids: list[str]


@endpoint
async def g_read(req: Request):
    u = await _login(req)
    return await run(lambda: service.group_read(u["short"], req.path_params["gid"]))


@endpoint
async def g_mute(req: Request):
    b = await body(req, MuteReq)
    u = await _login(req)
    return await run(lambda: service.group_mute(u["short"], req.path_params["gid"], b.muted))


@endpoint
async def g_rename(req: Request):
    b = await body(req, RenameReq)
    u = await _login(req)
    return await run(lambda: service.group_rename(u["short"], req.path_params["gid"], b.name))


@endpoint
async def g_invite(req: Request):
    b = await body(req, InviteReq)
    u = await _login(req)
    return await run(lambda: service.group_invite(u, req.path_params["gid"], b.ids))


@endpoint
async def g_join(req: Request):
    u = await _login(req)
    return await run(lambda: service.group_join(u["short"], req.path_params["gid"]))


class SplitApproveReq(BaseModel):
    split_id: str | None = None


class SplitRejectReq(BaseModel):
    reason: str = ""


@endpoint
async def g_split_start(req: Request):
    """확인 카드 '확인' → 분담표 승인 요청 (정산 대상 전원 승인 시 서버가 온체인 정산 요청)."""
    b = await body(req, ProposeReq)
    u = await _login(req)
    kw = {**b.model_dump(), "shares": [list(x) for x in b.shares]}
    return await run(lambda: service.split_start(u["short"], req.path_params["gid"], kw))


@endpoint
async def g_split_approve(req: Request):
    b = await body(req, SplitApproveReq)
    u = await _login(req)
    return await run(lambda: service.split_approve(u["short"], req.path_params["gid"], b.split_id))


@endpoint
async def g_split_reject(req: Request):
    b = await body(req, SplitRejectReq)
    u = await _login(req)
    return await run(lambda: service.split_reject(u["short"], req.path_params["gid"], b.reason))


class SubscribeReq(BaseModel):
    plan: str
    tx_hash: str | None = None


@endpoint
async def a_sub(req: Request):
    u = await _login(req)
    return await run(lambda: service.ai_sub(u))


@endpoint
async def a_subscribe(req: Request):
    b = await body(req, SubscribeReq)
    u = await _login(req)
    return await run(lambda: service.ai_subscribe(u, b.plan, b.tx_hash))


@endpoint
async def a_sub_cancel(req: Request):
    u = await _login(req)
    return await run(lambda: service.ai_sub_cancel(u))


@endpoint
async def cal(req: Request):
    """정산 캘린더: 내가 참여한 정산을 실제 날짜(서버 시계 · KST)별로."""
    u = await _login(req)
    return await run(lambda: service.calendar_for(u["short"]))


@endpoint
async def g_leave(req: Request):
    u = await _login(req)
    q = req.query_params
    return await run(lambda: service.group_leave(u["short"], req.path_params["gid"], declined=q.get("declined") == "1"))


class RefundReq(BaseModel):
    settlement_id: str
    reason: str
    note: str = ""


@endpoint
async def s_refund(req: Request):
    b = await body(req, RefundReq)
    u = await _login(req)
    return await run(lambda: service.refund_request(u, b.settlement_id, b.reason, b.note))


@endpoint
async def a_locate(req: Request):
    b = await body(req, LocateReq)
    u = await need(req, stage="geo")
    return await run(lambda: service.locate(u, b.lat, b.lng, b.save))


@endpoint
async def a_profile(req: Request):
    b = await body(req, ProfileReq)
    u = await need(req)
    return await run(lambda: service.update_profile(u, b.pie_id, b.address))


@endpoint
async def a_code(req: Request):
    b = await body(req, CodeReq)
    return await run(lambda: service.send_code(b.email, b.purpose))


@endpoint
async def a_me(req: Request):
    return service.me(await need(req))


@endpoint
async def a_logout(req: Request):
    return service.logout(_token(req))


@endpoint
async def a_reset(req: Request):
    b = await body(req, ResetReq)
    return await run(lambda: service.reset_password(b.email, b.code, b.password))


@endpoint
async def a_change(req: Request):
    b = await body(req, ChangePwReq)
    u = await need(req)
    return await run(lambda: service.change_password(u, b.old_password, b.new_password))


@endpoint
async def a_find(req: Request):
    b = await body(req, FindIdReq)
    return await run(lambda: service.find_id(b.name))


@endpoint
async def a_withdraw(req: Request):
    b = await body(req, PwReq)
    u = await need(req)
    return await run(lambda: service.withdraw(u, b.password))


@endpoint
async def users(req: Request):
    await need(req)
    return await run(lambda: service.users(req.query_params.get("q", "")))


@endpoint
async def charge(req: Request):
    b = await body(req, NameReq)
    await need(req, b.name, stage="wallet.charge")
    return await run(lambda: service.charge(b.name))


@endpoint
async def s_analyze(req: Request):
    b = await body(req, AnalyzeReq)
    await need(req, stage="settlement.analyze")
    return await run(lambda: service.analyze(b.text, b.members, b.total, b.payer, b.subject, b.history, b.flow))


@endpoint
async def s_calculate(req: Request):
    b = await body(req, Stage2Req)
    return await run(lambda: service.calculate_only(b.total, b.members, b.adjustments, b.payer, b.per_person_cap, b.total_cap, b.flow))


@endpoint
async def s_explain(req: Request):
    b = await body(req, ExplainReq)
    await need(req, stage="settlement.explain")
    return await run(lambda: service.explain_result(b.result, b.subject, b.flow))


@endpoint
async def s_approve(req: Request):
    b = await body(req, ApproveReq)
    await need(req, b.name, stage="settlement.approve")
    return await run(lambda: service.approve(b.settlement_id, b.name, b.tx_hash))


class CancelReq(BaseModel):
    settlement_id: str
    name: str


@endpoint
async def s_cancel(req: Request):
    b = await body(req, CancelReq)
    await need(req, b.name, stage="settlement.cancel")
    return await run(lambda: service.cancel_settlement(b.settlement_id, b.name))


@endpoint
async def s_offline(req: Request):
    b = await body(req, OfflineReq)
    await need(req, b.confirmer, stage="settlement.offline")
    return await run(lambda: service.offline_payment(b.settlement_id, b.participant, b.confirmer))


@endpoint
async def d_raise(req: Request):
    b = await body(req, DisputeRaiseReq)
    await need(req, b.by, stage="dispute.raise")
    return await run(lambda: service.dispute_raise(b.settlement_id, b.by, b.reason))


@endpoint
async def d_investigate(req: Request):
    b = await body(req, SidReq)
    _member_of(b.settlement_id, await need(req, stage="dispute.investigate"))
    out = await run(lambda: service.dispute_investigate(b.settlement_id, b.flow))
    out.pop("metas", None)
    return out


@endpoint
async def d_resolve(req: Request):
    b = await body(req, SidReq)
    _member_of(b.settlement_id, await need(req, stage="dispute.resolve"))
    return await run(lambda: service.dispute_resolve(b.settlement_id))


@endpoint
async def shop_search(req: Request):
    b = await body(req, ShopSearchReq)
    await need(req, stage="shopping.search")
    return await run(lambda: service.shopping_search(b.query, b.history, b.flow))


class ListingReq(BaseModel):
    group_id: str
    cap: int
    lat: float | None = None
    lng: float | None = None
    deadline_hours: int = 48
    note: str = ""


class GeoOptReq(BaseModel):
    lat: float | None = None
    lng: float | None = None


async def _me_user(req: Request) -> dict[str, Any]:
    u = await need(req, stage="groupbuy")
    if not u:
        raise ServiceError("UNAUTHORIZED", "로그인이 필요해요.", "groupbuy", 401)
    return u


@endpoint
async def gb_nearby(req: Request):
    """보는 사람의 현재 위치(저장 안 함) 기준 반경 안의 동네 공동구매 모집글. 위치가 없으면 같은 동네만."""
    u = await _me_user(req)
    q = req.query_params
    return await run(lambda: service.listings_nearby(u, q.get("lat"), q.get("lng"), q.get("radius") or 3))


@endpoint
async def gb_create(req: Request):
    b = await body(req, ListingReq)
    u = await _me_user(req)
    return await run(lambda: service.listing_create(u, b.group_id, b.cap, b.lat, b.lng, b.deadline_hours, b.note))


@endpoint
async def gb_join(req: Request):
    b = await body(req, GeoOptReq)
    u = await _me_user(req)
    return await run(lambda: service.listing_join(u, req.path_params["gid"], b.lat, b.lng))


@endpoint
async def gb_leave(req: Request):
    u = await _me_user(req)
    return await run(lambda: service.listing_leave(u, req.path_params["gid"]))


@endpoint
async def gb_close(req: Request):
    u = await _me_user(req)
    return await run(lambda: service.listing_close(u, req.path_params["gid"]))


@endpoint
async def dev_ff(req: Request):
    b = await body(req, SidReq)
    return await run(lambda: service.mock_fast_forward(b.settlement_id))


async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return fail("NOT_FOUND", "없는 API 경로예요", request.url.path, 404)
    return PlainTextResponse("Not Found", status_code=404)


routes = [
    Route("/api/health", health),
    Route("/api/config", cfg),
    # 회원
    Route("/api/auth/signup", signup, methods=["POST"]),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/remembered", a_remembered),                      # 이 기기의 마지막 가입·로그인 이메일 (X-SP-Device)
    Route("/api/auth/remembered/forget", a_forget, methods=["POST"]),
    Route("/api/auth/social/providers", a_social_providers),          # [{id, name, enabled}]
    Route("/api/auth/social/exchange", a_social_exchange, methods=["POST"]),   # {ticket} → 로그인 or 가입 마무리 필요
    Route("/api/auth/social/complete", a_social_complete, methods=["POST"]),   # {ticket, name, pie_id, email?, code?}
    Route("/api/auth/social/{provider}/start", a_social_start),         # 브라우저 이동 → 각 사 로그인
    Route("/api/auth/social/{provider}/callback", a_social_callback, methods=["GET", "POST"]),
    Route("/api/auth/social/{provider}/link", a_social_link, methods=["POST"]),     # 로그인 상태에서 계정 연결 → {url}
    Route("/api/auth/social/{provider}/unlink", a_social_unlink, methods=["POST"]),
    Route("/api/auth/email-code", a_code, methods=["POST"]),        # 인증번호 발송 {email, purpose: signup|reset}
    Route("/api/auth/me", a_me),                                     # 토큰 확인 (자동 로그인)
    Route("/api/auth/logout", a_logout, methods=["POST"]),
    Route("/api/auth/reset-password", a_reset, methods=["POST"]),   # {email, code, password}
    Route("/api/auth/change-password", a_change, methods=["POST"]),
    Route("/api/auth/find-id", a_find, methods=["POST"]),           # 이름 → 가린 이메일
    Route("/api/auth/withdraw", a_withdraw, methods=["POST"]),
    Route("/api/users", users),
    Route("/api/users/check-id", u_check_id),                        # Pie ID 형식·중복 확인 (가입 화면)
    Route("/api/users/by-id/{pid}", u_by_id),                        # Pie ID로 사용자 찾기
    Route("/api/friends", f_list),
    Route("/api/friends/add", f_add, methods=["POST"]),              # {id} (예전 이름) = 친구 요청
    Route("/api/friends/requests", f_requests),                      # {in:[], out:[]}
    Route("/api/friends/request", _friend_route("friend_request"), methods=["POST"]),   # {id} 친구 요청 (상대가 먼저 요청했으면 바로 친구)
    Route("/api/friends/accept", _friend_route("friend_accept"), methods=["POST"]),
    Route("/api/friends/decline", _friend_route("friend_decline"), methods=["POST"]),
    Route("/api/friends/cancel", _friend_route("friend_cancel"), methods=["POST"]),
    Route("/api/notifs", n_list),                                    # 내 알림함 {items, unread}
    Route("/api/notifs/read", n_read, methods=["POST"]),             # {ids?} 없으면 모두 읽음
    Route("/api/settlement/refund-request", s_refund, methods=["POST"]),   # {settlement_id, reason, note} → AI 이의제기 판정
    Route("/api/friends/remove", f_remove, methods=["POST"]),
    Route("/api/auth/profile", a_profile, methods=["POST"]),         # {pie_id?, address?}
    Route("/api/geo/locate", a_locate, methods=["POST"]),            # {lat, lng} GPS → 동네 이름 (좌표는 저장 안 함)
    Route("/api/members/register", register, methods=["POST"]),
    Route("/api/members", members),
    Route("/api/wallet/charge", charge, methods=["POST"]),
    Route("/api/wallet/{address}", wallet),
    # 그룹 채팅방 (멤버 모두 같은 방) · Pie 대화 기록
    Route("/api/groups", g_list),
    Route("/api/groups/create", g_create, methods=["POST"]),
    Route("/api/groups/{gid}/update", g_update, methods=["POST"]),
    Route("/api/groups/{gid}/messages", g_msg, methods=["POST"]),
    Route("/api/groups/{gid}/read", g_read, methods=["POST"]),       # 읽음 표시 (안 읽은 수 0)
    Route("/api/groups/{gid}/mute", g_mute, methods=["POST"]),       # {muted}
    Route("/api/groups/{gid}/rename", g_rename, methods=["POST"]),   # {name} 1~20자
    Route("/api/groups/{gid}/invite", g_invite, methods=["POST"]),   # {ids:[Pie ID]} 친구만
    Route("/api/groups/{gid}/join", g_join, methods=["POST"]),       # 초대 참여
    Route("/api/groups/{gid}/leave", g_leave, methods=["POST"]),     # 나가기 (?declined=1 초대 거절)
    Route("/api/groups/{gid}/messages/{mid}/resolve", g_resolve, methods=["POST"]),
    Route("/api/groups/{gid}/split/start", g_split_start, methods=["POST"]),     # 분담표 승인 요청 (ProposeReq 형식)
    Route("/api/groups/{gid}/split/approve", g_split_approve, methods=["POST"]), # {split_id?} 내 승인 → 전원이면 온체인 정산 요청
    Route("/api/groups/{gid}/split/reject", g_split_reject, methods=["POST"]),   # {reason} 동의 안 함 / 요청자 취소('요청 취소')
    Route("/api/chats", c_list),
    Route("/api/chats/save", c_save, methods=["POST"]),
    Route("/api/chats/{cid}/delete", c_delete, methods=["POST"]),
    # Pie 채팅 (정산·공동구매·이의제기 자동 분기)
    Route("/api/chat", chat, methods=["POST"]),
    # ── 정산 코어 (CLAUDE.md 6번 이름) ──
    Route("/api/settlement/analyze", s_analyze, methods=["POST"]),        # Stage1(+2)
    Route("/api/settlement/calculate", s_calculate, methods=["POST"]),    # Stage2 코드 전용 0 tokens
    Route("/api/settlement/explain", s_explain, methods=["POST"]),        # Stage3
    Route("/api/settlement/request", propose, methods=["POST"]),          # 온체인 등록 (지출 통제 검사)
    Route("/api/settlement/approve", s_approve, methods=["POST"]),        # 참여자 예치 확정
    Route("/api/settlement/offline-payment", s_offline, methods=["POST"]),
    Route("/api/settlement/cancel", s_cancel, methods=["POST"]),           # 전원 예치 전 취소 → 예치금 환불
    Route("/api/settlement/{sid}/sync", sync, methods=["POST"]),
    Route("/api/settlement/{sid}", get_settlement),
    Route("/api/settlements", list_settlements),
    Route("/api/calendar", cal),                                          # 내 정산 캘린더 (실제 날짜 · KST)
    # ── Dispute 모듈 ──
    Route("/api/dispute/raise", d_raise, methods=["POST"]),
    Route("/api/dispute/investigate", d_investigate, methods=["POST"]),
    Route("/api/dispute/resolve", d_resolve, methods=["POST"]),
    # ── Shopping 모듈 ──
    Route("/api/shopping/search", shop_search, methods=["POST"]),
    # 동네 공동구매 모집 (GPS 근처) — 예시 상품 대신 실제 사용자가 올린 모집글
    Route("/api/groupbuy/nearby", gb_nearby),                                  # ?lat&lng&radius=1|3|5|10
    Route("/api/groupbuy/create", gb_create, methods=["POST"]),                # {group_id, cap, lat?, lng?, deadline_hours?, note?}
    Route("/api/groupbuy/{gid}/join", gb_join, methods=["POST"]),              # {lat?, lng?}
    Route("/api/groupbuy/{gid}/leave", gb_leave, methods=["POST"]),
    Route("/api/groupbuy/{gid}/close", gb_close, methods=["POST"]),
    # 이전 이름 (호환)
    Route("/api/settle/calculate", calculate, methods=["POST"]),
    Route("/api/settle/propose", propose, methods=["POST"]),
    Route("/api/settle/{sid}/sync", sync, methods=["POST"]),
    Route("/api/settle/{sid}", get_settlement),
    # 기록
    Route("/api/ai/usage", ai_usage),                                     # AI 전용 페이: 내 AI 토큰 세부내용 (AI원)
    Route("/api/ai/pay", ai_pay, methods=["POST"]),
    Route("/api/ai/sub", a_sub),                                          # AI 구독 상태 · 요금제 목록
    Route("/api/ai/subscribe", a_subscribe, methods=["POST"]),            # {plan, tx_hash?} 구독 시작·플랜 변경·해지 취소
    Route("/api/ai/sub/cancel", a_sub_cancel, methods=["POST"]),          # 해지 예약 (남은 기간까지 이용)                       # 누적 AI 사용량으로 송금 (Pie Pay → 사용료 지갑)
    Route("/api/usage", usage),
    Route("/api/usage/report.md", usage_md),
    Route("/api/usage/calls.csv", usage_csv),
    Route("/api/beta", b_status),                                         # 베타: 동의 상태 · 기능 예시(미션) · 완료
    Route("/api/beta/consent", b_consent, methods=["POST"]),              # {agree} 대화를 AI 개선에 쓰는 데 동의/철회(철회 시 삭제)
    Route("/api/beta/feedback", b_feedback, methods=["POST"]),            # {turn, rating:up|down, reason?, note?}
    Route("/api/beta/report", b_report),                                  # 공개 요약 (버전 비교 · 심사 기준 실행 수)
    Route("/api/beta/report.md", b_report_md),
    Route("/api/beta/export.jsonl", b_export),                            # 관리자: ?kind=train|eval|raw                              # 심사 제출용: 호출별 단계·토큰·지연·에너지·응답 반영
    # mock 전용
    Route("/api/dev/mock-lock", dev_lock, methods=["POST"]),
    Route("/api/dev/tamper", dev_tamper, methods=["POST"]),
    Route("/api/dev/fast-forward", dev_ff, methods=["POST"]),
    Mount("/", app=NoCacheStatic(directory=str(ROOT / "frontend"), html=True), name="frontend"),
]

app = Starlette(
    routes=routes,
    middleware=[Middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST", "OPTIONS"],
                           allow_headers=["Content-Type", "Authorization", "X-SP-Device"])],
    exception_handlers={404: not_found},
)


print(f"[데이터] 계정·정산 기록 위치: {config.DATA_DIR}  (가입자 {len(service.store.users())}명)", flush=True)
