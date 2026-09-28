"""환경설정. 모든 값은 .env 또는 환경변수로 바꿀 수 있습니다 (.env.example 참고)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """python-dotenv 없이 .env 를 읽는다 (의존성 최소화)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)))
    except ValueError:
        return default


# ── Kiln (FuriosaAI NPU) ──
KILN_BASE_URL = _get("KILN_BASE_URL", "https://api.bricksum.com/v1").rstrip("/")
KILN_API_KEY = _get("KILN_API_KEY")
KILN_MODEL = _get("KILN_MODEL", "qwen3-32b")
PIE_CHAT = _get("PIE_CHAT", "agent").lower()  # agent: 대화형 에이전트 · pipeline: 단계 고정 파이프라인
# auto: tool calling 먼저 시도 → 지원 안 되면 JSON 프롬프트로 자동 전환 / tools / json
KILN_TOOL_MODE = _get("KILN_TOOL_MODE", "auto")
KILN_REASONING_EFFORT = _get("KILN_REASONING_EFFORT", "low")  # 비우면 파라미터 자체를 안 보냄
KILN_REASONING_EFFORT_THINK = _get("KILN_REASONING_EFFORT_THINK", "medium")  # 판단이 어려운 단계(이의제기 판정 등)만
# 1(기본): KILN_MODEL(qwen3-32b)만 쓴다 — 없으면 다른 모델로 바꾸지 않고 규칙 기반 응답으로 대체 + 원인 표시
# 0: 예전처럼 이 키로 쓸 수 있는 다른 대화 모델을 자동으로 골라 씀
KILN_MODEL_STRICT = _get("KILN_MODEL_STRICT", "1") != "0"
KILN_TIMEOUT = _float("KILN_TIMEOUT", 45)
# live: Kiln 호출 / mock: 키 없이 규칙 기반 가짜 AI (팀 개발·오프라인 시연용)
LLM_MODE = _get("LLM_MODE", "live" if KILN_API_KEY else "mock")
if not KILN_API_KEY:
    LLM_MODE = "mock"  # 키가 없으면 항상 규칙 기반 (빈 키로 호출하지 않음)

# ── 에너지 추정 가정값 (README에 그대로 명시할 것) ──
# RNGD 카드 TDP 150W (FuriosaAI 공식 문서). 모델 서빙 카드 수는 대회 측 확인 필요 → 기본 1
NPU_POWER_WATTS = _float("NPU_POWER_WATTS", 150)
NPU_COUNT = _float("NPU_COUNT", 1)

# ── 블록체인 (BNB Smart Chain Testnet) ──
CHAIN_MODE = _get("CHAIN_MODE", "mock")  # mock / bsc
BSC_RPC_URL = _get("BSC_RPC_URL", "https://data-seed-prebsc-1-s1.bnbchain.org:8545")
BSC_CHAIN_ID = int(_get("BSC_CHAIN_ID", "97"))
BSC_EXPLORER = _get("BSC_EXPLORER", "https://testnet.bscscan.com").rstrip("/")
AGENT_PRIVATE_KEY = _get("AGENT_PRIVATE_KEY")
LEDGER_ADDRESS = _get("LEDGER_ADDRESS")
TOKEN_ADDRESS = _get("TOKEN_ADDRESS")
LEDGER_DEPLOY_BLOCK = int(_get("LEDGER_DEPLOY_BLOCK", "0") or 0)

# ── 인터넷 상품 검색 (키가 있는 소스만 자동으로 켜짐) ──
NAVER_CLIENT_ID = _get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = _get("NAVER_CLIENT_SECRET")
NAVER_API_BASE = _get("NAVER_API_BASE", "https://openapi.naver.com").rstrip("/")
SERPER_API_KEY = _get("SERPER_API_KEY")  # serper.dev — 구글 쇼핑·검색 결과 (가입 시 2,500회 무료, 카드 불필요)
SERPER_API_BASE = _get("SERPER_API_BASE", "https://google.serper.dev").rstrip("/")
SERPAPI_API_KEY = _get("SERPAPI_API_KEY")  # serpapi.com — 구글 쇼핑·검색 (Serper 대신 쓸 때. 키는 64자)
SERPAPI_API_BASE = _get("SERPAPI_API_BASE", "https://serpapi.com").rstrip("/")
if not SERPAPI_API_KEY and len(SERPER_API_KEY) == 64 and all(ch in "0123456789abcdef" for ch in SERPER_API_KEY.lower()):
    SERPAPI_API_KEY, SERPER_API_KEY = SERPER_API_KEY, ""      # SERPER 칸에 SerpApi 키(64자)를 넣었으면 SerpApi로
TAVILY_API_KEY = _get("TAVILY_API_KEY")
TAVILY_API_BASE = _get("TAVILY_API_BASE", "https://api.tavily.com").rstrip("/")
COUPANG_ACCESS_KEY = _get("COUPANG_ACCESS_KEY")
COUPANG_SECRET_KEY = _get("COUPANG_SECRET_KEY")
COUPANG_API_BASE = _get("COUPANG_API_BASE", "https://api-gateway.coupang.com").rstrip("/")
WEB_TIMEOUT = _float("WEB_TIMEOUT", 6)
WEB_ALLOW_PRIVATE = _get("WEB_ALLOW_PRIVATE") == "1"  # 테스트 전용 (내부망 페이지 읽기 허용)

# ── 지출 통제 정책 ──
# 허용 가맹점: 이 이름이 판매처 이름에 포함되면 허용 (사용자가 "쿠팡만"처럼 말하면 그 정산은 그걸로 좁혀짐)
ALLOWED_MERCHANTS = [m.strip() for m in _get(
    "ALLOWED_MERCHANTS",
    "Share Pie 공동구매,Share Pie 배달 공동주문,네이버,스마트스토어,쿠팡,11번가,G마켓,옥션,SSG,신세계,롯데,컬리,오아시스,"
    "GS SHOP,GS25,CU,세븐일레븐,이마트,홈플러스,CJ,공식몰,공식스토어").split(",") if m.strip()]
# 전원 예치 후 결제자에게 지급하기 전 이의제기 가능 시간(초). mock 체인에서 사용. 실제 체인은 컨트랙트 setDisputeWindow 값
DISPUTE_WINDOW_SEC = int(_get("DISPUTE_WINDOW_SEC", "180") or 0)
# PIE 충전 (에이전트가 chargeToken으로 발급 → 사용자 가스비 불필요)
CHARGE_AMOUNT = int(_get("CHARGE_AMOUNT", "100000") or 100000)
CHARGE_COOLDOWN_SEC = int(_get("CHARGE_COOLDOWN_SEC", "60") or 0)
# [blockchain 담당] 지갑 등록 시 가스(네이티브 코인) 자동 지급 — 실제 체인 모드에서만. 사용자가 faucet 없이 바로 예치할 수 있게.
GAS_DRIP_ETH = float(_get("GAS_DRIP_ETH", "0.002") or 0)                 # 0 이면 끔
GAS_DRIP_MIN_ETH = float(_get("GAS_DRIP_MIN_ETH", "0.001") or 0)         # 지갑 잔액이 이 값 미만일 때만 지급
GAS_DRIP_COOLDOWN_SEC = int(_get("GAS_DRIP_COOLDOWN_SEC", "86400") or 0) # 같은 지갑 재지급 간격 (기본 하루)
# [blockchain 담당] 트랜잭션 영수증 대기(초). 테스트넷 혼잡 시 2~4분 걸릴 수 있어 넉넉히
CHAIN_TX_TIMEOUT_SEC = int(_get("CHAIN_TX_TIMEOUT_SEC", "300") or 300)
# [베타 서버] 에이전트 트랜잭션을 여러 건 동시에 — nonce 배정·전송만 잠금 안, 확정(영수증) 대기는 잠금 밖. 0 = 예전처럼 한 건씩
CHAIN_TX_PIPELINE = _get("CHAIN_TX_PIPELINE", "1").lower() not in ("0", "false", "no", "off")
# [베타 서버] 지갑 등록 때 가스 지급을 뒤에서 — 등록 응답과 다른 사람 요청이 체인 확정을 기다리지 않게. 0 = 예전처럼 확정까지 기다림
GAS_DRIP_ASYNC = _get("GAS_DRIP_ASYNC", "1").lower() not in ("0", "false", "no", "off")
# [blockchain 담당] 가스 가격 배수 (2 = 현재 시세의 2배). 혼잡한 블록에서도 다음 블록에 실리게
GAS_PRICE_MULTIPLIER = float(_get("GAS_PRICE_MULTIPLIER", "2") or 2)
# [베타 서버] 가스 가격 상한(gwei). 0 = 없음. 시세×배수가 이 값을 넘으면 이 값으로 (시세가 계속 높으면 확정이 늦어질 수 있음)
CHAIN_MAX_GAS_GWEI = _float("CHAIN_MAX_GAS_GWEI", 0)
# [베타 서버] 체인 감시: 실제 체인이면 열린 정산의 체인 상태를 뒤에서 이 간격(초)마다 읽고 지급까지 처리 →
# 4초마다 오는 정산 목록 새로고침은 저장된 상태만 돌려준다 (사람 수만큼 체인을 읽지 않게). 0 = 예전처럼 새로고침마다 체인 읽기
CHAIN_WATCH = _get("CHAIN_WATCH", "1").lower() not in ("0", "false", "no", "off")
CHAIN_WATCH_SEC = _float("CHAIN_WATCH_SEC", 5)
CHAIN_WATCH_WORKERS = int(_float("CHAIN_WATCH_WORKERS", 8))       # 한 바퀴에 동시에 읽는 정산 수
# (예전 후불 방식의 단위) 1 AI원 = Kiln 토큰 1개 × 이 비율. 지금은 구독 한도가 토큰 수로 정해져서 표시에만 남아 있다
AI_WON_PER_TOKEN = float(_get("AI_WON_PER_TOKEN", "1") or 1)
AI_FEE_WALLET = _get("AI_FEE_WALLET", "")          # 구독료를 받는 지갑. 비우면 에이전트 지갑

# ── AI 구독 (Claude 요금제 벤치마킹: Free → Pro → Max 5x → Max 20x) ──
# 쓴 만큼 정산하지 않는다. 요금제가 '5시간 세션 한도'와 '주간 한도'(Kiln 실측 토큰 수)를 정하고, 넘으면 Kiln을 부르지 않는다.
# 기준은 Pro. Free = Pro의 1/5, Max 5x = Pro의 5배, Max 20x = Pro의 20배 (배수는 agent/quota.py PLANS).
# 기본값 근거: Pie 대화 한 번(도구 1회 + 답) ≈ 5,000 토큰 (SYSTEM 약 900 + 도구 설명 약 1,000 + 맥락, 2걸음)
#  → Pro 세션 125,000 ≈ 대화 약 25번 / 5시간, 주간 500,000 ≈ 약 100번. Free 세션은 약 5번.
AI_SESSION_HOURS = _float("AI_SESSION_HOURS", 5)
AI_WEEK_DAYS = _float("AI_WEEK_DAYS", 7)
AI_PRO_SESSION_TOKENS = int(_float("AI_PRO_SESSION_TOKENS", 125000))
AI_PRO_WEEK_TOKENS = int(_float("AI_PRO_WEEK_TOKENS", 500000))
AI_PRICE_PRO = int(_float("AI_PRICE_PRO", 4900))          # PIE / 월 (PIE는 테스트넷 토큰 · 실제 가치 없음)
AI_PRICE_MAX = int(_float("AI_PRICE_MAX", 24500))         # Pro의 5배 가격 = 5배 사용량
AI_PRICE_MAX20 = int(_float("AI_PRICE_MAX20", 49000))     # Max 5x의 2배 가격 = Pro의 20배 사용량

# ── 베타 데이터 수집 (agent/beta.py) ──
# 모든 Kiln 기록에 앱 버전이 붙는다 → 같은 과제(시나리오)의 턴당 토큰을 베타 ↔ 정식 버전으로 비교
APP_VERSION = _get("APP_VERSION", "beta-1")
BETA_ENABLED = _get("BETA_ENABLED", "1" if APP_VERSION.startswith("beta") else "0") != "0"
BETA_PLAN = _get("BETA_PLAN", "").lower()          # 베타 동안 구독 없는 사용자에게 줄 한도 (예: pro). 비우면 Free 한도
BETA_ADMIN_EMAILS = {e.strip().lower() for e in _get("BETA_ADMIN_EMAILS", "").split(",") if e.strip()}
BETA_EXPORT_KEY = _get("BETA_EXPORT_KEY", "")      # 내보내기 API 키 (관리자 로그인 대신 ?key=)
BETA_SALT = _get("BETA_SALT", "share-pie-beta")    # 사용자 id를 되돌릴 수 없게 바꾸는 값
BETA_SNAPSHOT_SEC = int(_float("BETA_SNAPSHOT_SEC", 0))   # 이 간격(초)마다 폴더의 보고서·목록 갱신 (0 = 끔 · 베타 서버는 600)

# ── 동시 접속 운영 (deploy/asgi.py가 베타 서버 기본값을 넣는다 — 로컬 실행·테스트는 예전 그대로) ──
STORE_SAVE_DELAY = _float("STORE_SAVE_DELAY", 0)          # db.json 저장을 이 시간(초) 동안 모아 한 번에. 0 = 바뀔 때마다 (베타 서버 1)
KILN_MAX_CONCURRENCY = int(_float("KILN_MAX_CONCURRENCY", 0))   # Kiln 동시 호출 상한. 0 = 제한 없음 (베타 서버 24)
KILN_QUEUE_WAIT = _float("KILN_QUEUE_WAIT", 20)           # 상한에 걸리면 기다리는 최대 초 → 넘으면 규칙 기반으로 먼저 답함

# ── 위치 (GPS 좌표 → 동네 이름) ── 카카오 REST 키가 있으면 카카오, 없으면 OpenStreetMap(키 불필요)
KAKAO_REST_KEY = _get("KAKAO_REST_KEY", "")
KAKAO_API_BASE = _get("KAKAO_API_BASE", "https://dapi.kakao.com").rstrip("/")
NOMINATIM_BASE = _get("NOMINATIM_BASE", "https://nominatim.openstreetmap.org").rstrip("/")

# ── 소셜 로그인 (각 사 개발자 콘솔에서 앱 등록 → 아래 키 입력 · 콜백 주소: <서버 주소>/api/auth/social/<회사>/callback) ──
PUBLIC_BASE_URL = _get("PUBLIC_BASE_URL", "").rstrip("/")     # 비우면 접속한 주소 그대로 (터널 주소가 바뀌면 콘솔 등록도 바꿔야 함)
KAKAO_CLIENT_ID = _get("KAKAO_CLIENT_ID", "") or KAKAO_REST_KEY   # 카카오 REST API 키 (카카오 로그인 활성화 필요)
KAKAO_CLIENT_SECRET = _get("KAKAO_CLIENT_SECRET", "")          # 보안 > Client Secret 을 켰을 때만
NAVER_CLIENT_ID = _get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = _get("NAVER_CLIENT_SECRET", "")
GOOGLE_CLIENT_ID = _get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = _get("GOOGLE_CLIENT_SECRET", "")
APPLE_CLIENT_ID = _get("APPLE_CLIENT_ID", "")      # Services ID (예: com.sharepie.web)
APPLE_TEAM_ID = _get("APPLE_TEAM_ID", "")
APPLE_KEY_ID = _get("APPLE_KEY_ID", "")
APPLE_PRIVATE_KEY = _get("APPLE_PRIVATE_KEY", "")  # AuthKey_XXXX.p8 파일 경로 (또는 PEM 내용)
OAUTH_FAKE_BASE = _get("OAUTH_FAKE_BASE", "")      # 테스트 전용 (tests/fake_oauth.py). 실제 운영에서는 비워 둔다

# ── 메일 (회원가입 인증번호 · 비밀번호 재설정) ──
# Gmail: SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=내주소@gmail.com SMTP_PASSWORD=앱 비밀번호(16자리)
# 네이버: SMTP_HOST=smtp.naver.com SMTP_PORT=587 (네이버 메일 설정에서 SMTP 사용 켜기)
SMTP_HOST = _get("SMTP_HOST", "")
SMTP_PORT = int(_get("SMTP_PORT", "587") or 587)
SMTP_USER = _get("SMTP_USER", "")
SMTP_PASSWORD = _get("SMTP_PASSWORD", "")
MAIL_FROM = _get("MAIL_FROM", "") or SMTP_USER
# auto: SMTP가 없으면 개발 모드(인증번호를 서버 창·화면에 표시) / 0: 절대 표시 안 함 / 1: 항상 표시(테스트용)
MAIL_DEV_ECHO = _get("MAIL_DEV_ECHO", "auto").lower()
CODE_TTL_SEC = int(_get("CODE_TTL_SEC", "300") or 300)          # 인증번호 유효 시간 5분 (앱에 타이머 표시)
CODE_FREE_RESENDS = int(_get("CODE_FREE_RESENDS", "2") or 0)     # 재요청 2번까지는 바로
CODE_RESEND_SEC = int(_get("CODE_RESEND_SEC", "60") or 0)        # 그 뒤로는 1분 간격
CODE_HOURLY_MAX = int(_get("CODE_HOURLY_MAX", "10") or 10)
SESSION_DAYS = int(_get("SESSION_DAYS", "30") or 30)
AUTH_REQUIRED = _get("AUTH_REQUIRED", "1") != "0"   # 0이면 토큰 없이도 API 호출 허용 (옛 클라이언트 호환용)

# ── 서버 ──
# 계정·정산·채팅 기록 저장 위치. 기본은 사용자 홈 폴더(~/.sharepie-data) — 새 버전 zip을 다른 폴더에 풀어도
# 같은 계정이 그대로 남도록 프로젝트 폴더 밖에 둔다. (예전처럼 프로젝트 안에 두려면 .env에 DATA_DIR=data)
_HOME_DATA = Path.home() / ".sharepie-data"
_OLD_DATA = ROOT / "data"
_env_data = _get("DATA_DIR", "")
if _env_data:
    DATA_DIR = Path(_env_data) if Path(_env_data).is_absolute() else ROOT / _env_data
else:
    DATA_DIR = _HOME_DATA
    if not (_HOME_DATA / "db.json").exists() and (_OLD_DATA / "db.json").exists():
        import shutil   # 처음 한 번: 예전 위치(프로젝트/data)의 계정·기록을 옮겨 옴
        shutil.copytree(_OLD_DATA, _HOME_DATA, dirs_exist_ok=True)
        print(f"[데이터] 기존 계정·기록을 {_OLD_DATA} → {_HOME_DATA} 로 복사했어요", flush=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
# 베타에서 모은 데이터만 (비식별) 두는 폴더 — 계정·비밀번호가 든 db.json과 따로. 이 폴더만 통째로 보내면 된다
BETA_DATA_DIR = Path(_get("BETA_DATA_DIR") or str(DATA_DIR / "beta")).resolve()
CORS_ORIGINS = [o.strip() for o in _get(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5173,http://localhost:5500,http://127.0.0.1:5500",
).split(",") if o.strip()]
