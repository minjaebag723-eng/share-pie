"""메일 설정 확인: py scripts/check_mail.py 받을주소@gmail.com
.env 의 SMTP 설정으로 테스트 메일을 실제로 보내고, 실패하면 원인을 알려 줘요."""
import smtplib
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import config, mailer  # noqa: E402

to = sys.argv[1] if len(sys.argv) > 1 else config.SMTP_USER
print(f"SMTP 서버 {config.SMTP_HOST or '(없음)'}:{config.SMTP_PORT}  보내는 계정 {config.SMTP_USER or '(없음)'}  "
      f"비밀번호 {'*' * len(config.SMTP_PASSWORD) if config.SMTP_PASSWORD else '(없음)'} ({len(config.SMTP_PASSWORD)}자)")
if not mailer.configured():
    sys.exit("✗ .env 에 SMTP_HOST / SMTP_USER / SMTP_PASSWORD 가 비어 있어요 → 지금은 개발 모드(인증번호가 서버 창·화면에 표시)")
if " " in config.SMTP_PASSWORD:
    print("⚠️ 비밀번호에 띄어쓰기가 있어요. Gmail 앱 비밀번호 16자리는 띄어쓰기 없이 붙여 넣으세요.")
try:
    mailer.send_code(to, "123456", "signup")
    print(f"✓ {to} 로 테스트 메일(인증번호 123456)을 보냈어요. 받은편지함·스팸함을 확인하세요.")
except mailer.MailError as e:
    m = str(e)
    print("✗ 발송 실패:", m[:300])
    if "535" in m or "Username and Password not accepted" in m or "BadCredentials" in m:
        print("  → 로그인 거부: Gmail은 ‘일반 비밀번호’가 아니라 ‘앱 비밀번호(16자리)’를 넣어야 해요.")
        print("    https://myaccount.google.com/apppasswords (2단계 인증을 먼저 켜야 메뉴가 보여요)")
    elif "timed out" in m or "Connection" in m or "getaddrinfo" in m:
        print("  → 서버에 연결이 안 돼요: SMTP_HOST·SMTP_PORT 확인, 학교/회사 와이파이가 587 포트를 막았는지 확인 (핫스팟으로 시도)")
    elif "Sender address rejected" in m or "553" in m:
        print("  → 보내는 주소 거부: MAIL_FROM 을 비우거나 SMTP_USER 와 같은 주소로 두세요.")
