"""메일 발송 (인증번호). SMTP가 설정돼 있으면 실제 발송, 없으면 개발 모드로 서버 창에 출력."""
from __future__ import annotations

import smtplib
import socket
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from . import config


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD)


def dev_echo() -> bool:
    """인증번호를 응답에 실어 화면에 보여 줄지 (SMTP 없이 시연·테스트할 때)."""
    if config.MAIL_DEV_ECHO in ("1", "true", "yes"):
        return True
    if config.MAIL_DEV_ECHO in ("0", "false", "no"):
        return False
    return not configured()


def send_code(to: str, code: str, purpose: str) -> str:
    """반환: 'smtp' | 'dev'."""
    what = {"signup": "회원가입", "reset": "비밀번호 재설정", "withdraw": "회원 탈퇴"}.get(purpose, "본인 확인")
    subject = f"[Share Pie] {what} 인증번호 {code}"
    body = (f"Share Pie {what} 인증번호는 {code} 입니다.\n"
            f"{config.CODE_TTL_SEC // 60}분 안에 앱에 입력해 주세요.\n\n"
            "본인이 요청하지 않았다면 이 메일을 무시하세요. 인증번호를 다른 사람에게 알려 주지 마세요.\n"
            "— Share Pie (해커톤 테스트 서비스 · PIE는 테스트넷 토큰으로 실제 가치가 없어요)")
    if not configured():
        print(f"[메일 개발 모드] {to} ← {what} 인증번호 {code}", flush=True)
        return "dev"
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("Share Pie", config.MAIL_FROM))
    msg["To"] = to
    msg.set_content(body)
    host = _host()
    pw = (config.SMTP_PASSWORD or "").replace(" ", "").strip()   # Gmail 앱 비밀번호는 띄어쓰기 포함으로 보여서 그대로 붙여 넣는 경우가 많음
    first = config.SMTP_PORT
    # 587이 끊기면 465(SSL)로, 465가 안 되면 587로 한 번 더 — 학교·카페 와이파이나 백신(메일 검사)이 한쪽 포트를 막는 경우가 많다
    ports = [first] + [p for p in (587, 465) if p != first]
    last: Exception | None = None
    tried: list[str] = []
    for port in ports:
        try:
            _send(host, port, pw, msg)
            if port != first:
                print(f"[메일] {first}번 포트가 끊겨서 {port}번으로 보냈어요. .env의 SMTP_PORT={port}로 바꾸면 더 빨라요.", flush=True)
            return "smtp"
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, socket.gaierror, UnicodeError) as e:
            last = e
            break                           # 설정 문제는 다른 포트로 해도 똑같다
        except Exception as e:   # noqa: BLE001 — 끊김·시간 초과·SSL 오류 → 다른 포트로 재시도
            last = e
            tried.append(f"{port}: {type(e).__name__} {str(e)[:80]}".strip())
            print(f"[메일] {host}:{port} 실패 ({type(e).__name__}: {e}) → " + ("다른 포트로 재시도" if port != ports[-1] else "포기"), flush=True)
    reason = explain(last) if last else "메일 발송 실패"
    if tried and not isinstance(last, smtplib.SMTPAuthenticationError):
        reason += " [서버 응답 — " + " / ".join(tried) + "]"   # 원인 추적용 원문 (비밀번호는 들어가지 않음)
    print(f"[메일 발송 실패] {to}: {reason} ({type(last).__name__}: {last})", flush=True)
    raise MailError(reason) from last


def _send(host: str, port: int, pw: str, msg: EmailMessage) -> None:
    if port == 465:
        with smtplib.SMTP_SSL(host, 465, context=ssl.create_default_context(), timeout=12) as s:
            s.login(config.SMTP_USER.strip(), pw)
            s.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=12) as s:
        s.ehlo()
        if s.has_extn("starttls"):
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
        elif "gmail" in host.lower():
            raise smtplib.SMTPServerDisconnected("STARTTLS를 지원하지 않는 연결 (중간에서 가로채는 네트워크일 수 있음)")
        if s.has_extn("auth"):
            s.login(config.SMTP_USER.strip(), pw)
        s.send_message(msg)


def _host() -> str:
    h = (config.SMTP_HOST or "").strip()
    if h.lower().startswith("stmp."):          # 흔한 오타 (stmp.gmail.com)
        print(f"[메일] SMTP_HOST 오타로 보여서 {h} → smtp.{h[5:]} 로 연결해요. .env를 고쳐 주세요.", flush=True)
        h = "smtp." + h[5:]
    return h


def explain(e: Exception) -> str:
    """관리자가 바로 고칠 수 있게 원인을 한국어로."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "메일 계정 로그인 실패 — .env의 SMTP_USER(보내는 Gmail 주소)와 SMTP_PASSWORD(앱 비밀번호 16자리)를 확인해 주세요"
    if isinstance(e, smtplib.SMTPRecipientsRefused):
        return "받는 메일 주소를 메일 서버가 거부했어요 — 주소를 확인해 주세요"
    if isinstance(e, smtplib.SMTPSenderRefused):
        return "보내는 주소(MAIL_FROM)를 메일 서버가 거부했어요 — SMTP_USER와 같은 주소를 쓰세요"
    if isinstance(e, socket.gaierror):
        return f"메일 서버 주소를 찾을 수 없어요 — SMTP_HOST({config.SMTP_HOST})가 smtp.gmail.com 인지 확인해 주세요"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "메일 서버 연결 시간 초과 — 네트워크(학교·회사 와이파이)가 587 포트를 막고 있을 수 있어요. SMTP_PORT=465로 바꿔 보세요"
    txt = str(e)
    if "4.7.0" in txt or "421" in txt or "Try again later" in txt or "too many" in txt.lower():
        return ("Gmail이 잠시 이 PC의 로그인을 막았어요 (틀린 비밀번호로 여러 번 시도하면 10~30분 동안 막혀요). "
                "앱 비밀번호를 새로 발급해 .env에 넣고 서버를 다시 켠 뒤, 15분쯤 지나서 한 번만 시도해 주세요")
    if isinstance(e, smtplib.SMTPServerDisconnected):
        return ("메일 서버(Gmail)가 연결을 끊었어요 — 587·465 포트 둘 다 막혔거나 중간에서 가로채고 있어요. "
                "휴대폰 핫스팟으로 서버 PC를 연결해 보거나, 백신의 ‘메일 검사/SMTP 보호’를 꺼 보세요")
    if isinstance(e, ssl.SSLError):
        return "메일 서버와 보안 연결(SSL)을 맺지 못했어요 — 백신·회사 네트워크가 SSL을 가로채는지 확인해 주세요"
    if isinstance(e, ConnectionRefusedError):
        return "메일 서버가 연결을 거부했어요 — SMTP_PORT(587 또는 465)를 확인해 주세요"
    if isinstance(e, UnicodeError):
        return "메일 설정에 한글·특수문자가 들어가 있어요 — SMTP_USER·SMTP_PASSWORD를 다시 복사해 넣어 주세요"
    return f"메일 발송 실패 ({type(e).__name__})"
