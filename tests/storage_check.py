"""베타 서버 준비 검사 — 동시 접속 설정과 베타 데이터 폴더.
실행: DATA_DIR=/tmp/sp-store LLM_MODE=mock CHAIN_MODE=mock KILN_API_KEY= APP_VERSION=beta-1 BETA_EXPORT_KEY=k123 \
      STORE_SAVE_DELAY=0.3 KILN_MAX_CONCURRENCY=1 KILN_QUEUE_WAIT=0.2 python tests/storage_check.py
"""
import io
import json
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
DATA = Path(os.environ.get("DATA_DIR", "/tmp/sp-store"))
DATA.mkdir(parents=True, exist_ok=True)
(DATA / "beta_dialogs.jsonl").write_text(json.dumps({"turn": "t_old0000001", "uid": "x", "user": "옛 위치 기록"}, ensure_ascii=False) + "\n",
                                         encoding="utf-8")   # v35 위치에 남은 기록 → 새 폴더로 옮겨져야 함

from agent import beta, config, llm, service, store, usage  # noqa: E402

fails = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label)
    if not c:
        fails.append(label)


print("[데이터 폴더]")
ok(config.BETA_DATA_DIR == (DATA / "beta").resolve() and beta.DIR.is_dir(), f"위치 {beta.DIR} (계정 DB와 다른 폴더)")
ok(not (DATA / "beta_dialogs.jsonl").exists() and "옛 위치 기록" in beta.DIALOGS.read_text(encoding="utf-8"), "v35 위치의 기록을 새 폴더로 옮김")
ok(beta.README.exists() and "보내는 법" in beta.README.read_text(encoding="utf-8"), "폴더 안내문(README.md)")

print("[db.json 저장 모아 하기 (STORE_SAVE_DELAY=0.3)]")
run = uuid.uuid4().hex[:4]
email = f"store.{run}@t.test"
code = service.send_code(email, "signup")["dev_code"]
service.signup("김민재", email, "pass1234", code=code)
before = email in (store._FILE.read_text(encoding="utf-8") if store._FILE.exists() else "")
ok(store.user_by_email(email) and not before, "바꾼 즉시: 메모리엔 있고 파일 쓰기는 모아 둠")
time.sleep(0.6)
ok(email in store._FILE.read_text(encoding="utf-8"), "0.3초 뒤 한 번에 저장")
service.send_code(f"x{run}@t.test", "signup")
store.flush()
ok(f"x{run}@t.test" in store._FILE.read_text(encoding="utf-8"), "flush()로 바로 저장 (서버 종료 때)")

print("[Kiln 기록 사본 — 이메일·제목 없이]")
me = store.user_by_email(email)
usage.set_actor(me)
with usage.scope("chat", "민재 생일 선물 010-1234-5678"), usage.tagged(turn="t_aaaaaaaaaa", scenario="S01", edited=False):
    usage.record("assistant.agent", flow="c-민재방", prompt_tokens=300, completion_tokens=50, latency_ms=900, mode="tools",
                 model="qwen3-32b", note="김민재 010-9999-0000 요청")
m = [json.loads(x) for x in beta.USAGE.read_text(encoding="utf-8").splitlines()][-1]
blob = json.dumps(m, ensure_ascii=False)
ok(m.get("uid") == beta.uid(email) and m.get("total_tokens") == 350 and m.get("scenario") == "S01" and m.get("version") == "beta-1",
   "사본: uid · 토큰 · 미션 · 버전")
ok(all(x not in blob for x in (email, "김민재", "민재 생일", "010-", "c-민재방")) and "user" not in m and "ctx" not in m,
   "이메일·실명·방 제목·전화번호·흐름 이름 없음")

print("[사용량 메모리 캐시]")
n0 = len(usage.read_all())
usage.record("x.test", flow="f", prompt_tokens=1, completion_tokens=1, latency_ms=0, mode="code")
ok(len(usage.read_all()) == n0 + 1, "기록하면 캐시에도 바로")
rows = usage.read_all()
rows.clear()
ok(len(usage.read_all()) == n0 + 1, "돌려준 목록을 바꿔도 캐시는 그대로")
with usage.USAGE_FILE.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"ts": time.time(), "stage": "outside", "mode": "code"}) + "\n")
ok(any(r.get("stage") == "outside" for r in usage.read_all()), "밖에서 파일에 쓴 줄도 다시 읽음")
usage.USAGE_FILE.unlink()
ok(usage.read_all() == [], "파일을 지우면 빈 목록 (보고서 새로 만들 때)")

print("[참여 이벤트 · 스냅샷 · 묶음]")
service.beta_consent(me, True)
beta.mark_done(email, "S02")
ev = [json.loads(x) for x in beta.EVENTS.read_text(encoding="utf-8").splitlines()]
ok({"consent", "mission_done"} <= {e["event"] for e in ev} and all(e["uid"] == beta.uid(email) for e in ev), "동의·미션 완료 이벤트 (uid)")
man = beta.snapshot()
ok({"dialogs.jsonl", "usage.jsonl", "events.jsonl", "report.md", "report.json", "settlements.jsonl", "README.md"} <= set(man["files"])
   and all(len(f["sha256"]) == 64 for f in man["files"].values()), f"manifest: 파일 {len(man['files'])}개 · 줄 수 · sha256")
zp = beta.bundle_file(DATA / "bundles")
with zipfile.ZipFile(zp) as z:
    names = z.namelist()
    allbytes = b"".join(z.read(n) for n in names)
ok(names and all(n.startswith("beta-data/") for n in names) and "beta-data/db.json" not in names, f"zip {zp.name}: beta-data/ 아래만 {len(names)}개")
ok(email.encode() not in allbytes and b"pass1234" not in allbytes and b"010-9999" not in allbytes, "zip 안에 이메일·비밀번호·전화번호 없음")
info = beta.storage_info()
ok(info["folder"] == str(beta.DIR) and info["totalBytes"] > 0 and info["diskFreeBytes"] > 0, "저장소 정보: 위치 · 용량 · 남은 디스크")

print("[Kiln 동시 호출 상한 (1개 · 0.2초 대기)]")
assert llm._SLOTS is not None
llm._SLOTS.acquire()
t0 = time.perf_counter()
try:
    llm.client._post("test.busy", None, {"messages": [{"role": "user", "content": "x"}]})
    ok(False, "자리가 없으면 KILN_BUSY")
except llm.LLMError as e:
    ok(e.code == "KILN_BUSY" and time.perf_counter() - t0 < 1.5, f"자리가 없으면 {time.perf_counter() - t0:.1f}초 기다린 뒤 KILN_BUSY → 규칙 기반 답")
finally:
    llm._SLOTS.release()

print("[베타 서버 진입점 (deploy/asgi.py)]")
from starlette.testclient import TestClient  # noqa: E402
from deploy.asgi import app  # noqa: E402
with TestClient(app) as c:
    ok(c.get("/healthz").json().get("ok") is True, "/healthz")
    ok(c.get("/api/beta/storage").status_code == 403 and c.get("/api/beta/bundle.zip?key=wrong").status_code == 403, "키 없으면 데이터 못 봄")
    r = c.get("/api/beta/storage", headers={"X-Beta-Key": "k123"})
    ok(r.status_code == 200 and r.json()["data"]["folder"] == str(beta.DIR), "관리자: 데이터 폴더 위치·파일")
    r = c.get("/api/beta/bundle.zip?key=k123")
    ok(r.status_code == 200 and zipfile.ZipFile(io.BytesIO(r.content)).namelist(), f"관리자: zip 내려받기 ({len(r.content):,} bytes)")
    big = c.get("/api/beta/report", headers={"Accept-Encoding": "gzip"})
    ok(big.status_code == 200, "기존 API는 그대로 (감싸기만)")
    ok(big.headers.get("content-encoding") == "gzip", "API 응답은 gzip 압축")
    ok(c.get("/", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") != "gzip", "화면 파일은 압축 안 함 (앞단 프록시 몫)")

print("[에이전트 지갑 감시 (가짜 체인 — 1시간에 0.06 ETH 소모 · 잔액 0.04 · 막힌 트랜잭션 4건)]")
import deploy.asgi as A  # noqa: E402


class _Eth:
    gas_price = int(5e9)

    def get_balance(self, a):
        return int(0.04e18)

    def get_transaction_count(self, a, kind):
        return 9 if kind == "pending" else 5


class _Client:
    w3 = type("W3", (), {"eth": _Eth()})()
    acct = type("Acct", (), {"address": "0x" + "ab" * 20})()

    def info(self):
        return {"network": "Sepolia"}


A._chain_hist.clear()
A._chain_hist.append((time.time() - 3600, 0.10))
cs = A.chain_sample(_Client())
ok(abs(cs["spentPerHourEth"] - 0.06) < 0.002 and cs["hoursLeft"] is not None and cs["hoursLeft"] < 1, f"시간당 소모 {cs['spentPerHourEth']} ETH · {cs['hoursLeft']}시간 뒤 바닥")
ok(cs["settlementsLeft"] == int(0.04 / (A.GAS_PER_SETTLEMENT * 5 / 1e9)) and cs["pendingTx"] == 4, f"정산 {cs['settlementsLeft']}건 분량 · 막힌 트랜잭션 4건")
ok(len(cs["warnings"]) == 3, "경고 3개: 잔액 부족 · 3시간 안에 바닥 · 막힌 트랜잭션")

print("\n✓ 전체 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
sys.exit(1 if fails else 0)
