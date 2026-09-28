"""실제 체인 점검 (로컬 테스트 노드 전용) — 체인 코드를 바꾼 뒤 베타 전에 한 번.

  1) 로컬 노드:  anvil          또는  cd hardhat && npx hardhat node        (둘 다 127.0.0.1:8545 · 기본 테스트 계정 사용)
  2) 컨트랙트 빌드 결과: cd hardhat && npm run compile   (없으면 PATH의 solc 또는 SOLC=경로 로 직접 컴파일)
  3) python tests/chain_local_check.py            (빠르게: --skip-freeze)

A. 흐름(정확성, 블록 2초): 새 지갑 등록 → 가스 자동 지급(뒤에서) → 충전 → 정산 등록 → 멤버 예치(각자 서명)
   → 이의제기 기간 뒤 체인 감시가 지급 → paid / 1인 한도 초과 → 온체인 중단
B. 멈춤(블록 12초 = Sepolia, 체인 읽기마다 150ms 지연 = 공용 RPC): 새 사용자 8명 지갑 연결·충전 / 정산 있는 12명 새로고침 /
   정산 만들기 중 다른 사람 요청 대기
컨트랙트를 새로 배포하고 임시 데이터 폴더를 쓰므로 실제 데이터·Sepolia에는 아무것도 보내지 않아요. chain id 31337·1337만 허용.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RPC = os.environ.get("LOCAL_RPC", "http://127.0.0.1:8545")
# 로컬 노드(anvil·hardhat) 기본 계정 0~4 — 공개된 테스트 키
KEYS = ["0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80", "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a", "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
        "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"]
fails: list[str] = []


def ok(c, label):
    print(("  ✓ " if c else "  ✗ ") + label, flush=True)
    if not c:
        fails.append(label)


def artifacts() -> dict[str, dict]:
    out = {}
    for name in ("PieToken", "ShareLedger"):
        for base in (ROOT / "hardhat" / "artifacts" / "contracts", ROOT / "artifacts" / "contracts"):
            f = base / f"{name}.sol" / f"{name}.json"
            if f.exists():
                j = json.loads(f.read_text(encoding="utf-8"))
                out[name] = {"abi": j["abi"], "bin": j["bytecode"]}
    if len(out) == 2:
        return out
    solc = os.environ.get("SOLC") or shutil.which("solc")
    if not solc:
        sys.exit("컨트랙트 빌드 결과가 없어요 → cd hardhat && npm run compile  (또는 SOLC=solc 경로)")
    r = subprocess.run([solc, "--optimize", "--combined-json", "abi,bin", "contracts/PieToken.sol", "contracts/ShareLedger.sol"],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        sys.exit(r.stderr)
    for k, v in json.loads(r.stdout)["contracts"].items():
        abi = v["abi"] if isinstance(v["abi"], list) else json.loads(v["abi"])
        out[k.split(":")[-1]] = {"abi": abi, "bin": "0x" + v["bin"]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-freeze", action="store_true")
    ap.add_argument("--rpc-delay", type=float, default=0.15)
    a = ap.parse_args()
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(RPC))
    cid = w3.eth.chain_id
    if cid not in (31337, 1337):
        sys.exit(f"chain id {cid} — 로컬 테스트 노드에서만 돌려요")
    fee = {"maxFeePerGas": w3.to_wei(3, "gwei"), "maxPriorityFeePerGas": w3.to_wei(1, "gwei")}
    agent = w3.eth.account.from_key(KEYS[0])

    def send(acct, fn_or_tx):
        tx = fn_or_tx.build_transaction({"from": acct.address, **fee}) if hasattr(fn_or_tx, "build_transaction") else fn_or_tx
        tx.update({"nonce": w3.eth.get_transaction_count(acct.address, "pending"), "chainId": cid})
        h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
        return w3.eth.wait_for_transaction_receipt(h, timeout=120)

    def mine(auto: bool, sec: int = 0) -> None:
        """auto=True: 트랜잭션마다 바로 블록 · False: sec초마다 블록 (순서 중요 — 반대로 하면 채굴이 멈춤)"""
        if auto:
            w3.provider.make_request("evm_setIntervalMining", [0])
            w3.provider.make_request("evm_setAutomine", [True])
        else:
            w3.provider.make_request("evm_setAutomine", [False])
            w3.provider.make_request("evm_setIntervalMining", [sec])
    mine(True, 0)
    art = artifacts()
    addr = {}
    for name in ("PieToken", "ShareLedger"):
        r = send(agent, w3.eth.contract(abi=art[name]["abi"], bytecode=art[name]["bin"]).constructor())
        addr[name] = r["contractAddress"]
    tok = w3.eth.contract(address=addr["PieToken"], abi=art["PieToken"]["abi"])
    led = w3.eth.contract(address=addr["ShareLedger"], abi=art["ShareLedger"]["abi"])
    send(agent, tok.functions.setMinter(agent.address, True))
    send(agent, led.functions.setDisputeWindow(6))
    print(f"로컬 체인 {cid} · 새로 배포 PieToken {addr['PieToken'][:10]}… ShareLedger {addr['ShareLedger'][:10]}… · 이의제기 기간 6초")

    os.environ.update({"CHAIN_MODE": "bsc", "BSC_RPC_URL": RPC, "BSC_CHAIN_ID": str(cid), "BSC_EXPLORER": "", "AGENT_PRIVATE_KEY": KEYS[0],
                       "LEDGER_ADDRESS": addr["ShareLedger"], "TOKEN_ADDRESS": addr["PieToken"], "LEDGER_DEPLOY_BLOCK": "0",
                       "DATA_DIR": tempfile.mkdtemp(prefix="sp-chaincheck-"), "LLM_MODE": "mock", "KILN_API_KEY": "", "SERPER_API_KEY": "",
                       "CHARGE_COOLDOWN_SEC": "0", "CHAIN_WATCH_SEC": "2", "DISPUTE_WINDOW_SEC": "6",
                       "CHAIN_MAX_GAS_GWEI": "3"})   # 로컬 노드는 우리 트랜잭션만 있어 시세×2가 되먹임되므로 상한
    sys.path.insert(0, str(ROOT))
    from eth_account import Account
    from agent import chain, service, store
    ch = chain.get()
    users = [Account.from_key(k) for k in KEYS[1:5]]
    names = ["가", "나", "다", "라"]

    def lock_members(sid: str, share: int) -> None:
        rec = store.get(sid)
        states = {m["address"].lower(): m["state"] for m in ch.get_settlement(rec["chain_id"]).get("members", [])}
        b32 = Web3.to_bytes(hexstr=rec["chain_id"])
        for n, u in zip(names, users):
            if states.get(u.address.lower()) == "wait":
                send(u, tok.functions.approve(addr["ShareLedger"], ch._units(share)))
                h = send(u, led.functions.lockForSettlement(b32))["transactionHash"]
                service.approve(sid, n, Web3.to_hex(h))

    print("\nA. 정산 흐름 (블록 2초)")
    mine(False, 2)
    fresh = Account.create()
    t = time.perf_counter()
    r = service.register_member("새내기", fresh.address)
    ok((r.get("gas") or {}).get("pending") or r.get("gas") is None, f"새 지갑 등록 {time.perf_counter() - t:.2f}초 · gas={r.get('gas')}")
    for _ in range(80):
        if store.kv_get("gas_drip", fresh.address.lower()):
            break
        time.sleep(0.5)
    ok(store.kv_get("gas_drip", fresh.address.lower()) is not None, f"가스 자동 지급 도착 ({w3.from_wei(w3.eth.get_balance(fresh.address), 'ether')} ETH)")
    for n, u in zip(names, users):
        service.register_member(n, u.address)
    ths = [threading.Thread(target=service.charge, args=(n,)) for n in names]
    [x.start() for x in ths]
    [x.join() for x in ths]
    ok(all(ch.account(u.address)["balance"] >= 100000 for u in users), "4명 충전 (동시에)")
    p = service.propose(group_name="치킨모임", members=names, shares=[[n, 8000] for n in names], total=32000, payer="가",
                        rule_text="3만2천원 넷이", purpose="치킨")
    sid = p.get("id") or (p.get("settlement") or {}).get("id")
    ok(store.get(sid)["status"] == "open", f"정산 등록 → open ({sid})")
    lock_members(sid, 8000)
    ok(store.get(sid)["status"] == "locked", "멤버 예치 → locked (이의제기 기간 6초)")
    t0 = time.time()
    while time.time() - t0 < 40 and store.get(sid)["status"] != "paid":
        service.list_for("나")
        time.sleep(0.5)
    rec = store.get(sid)
    ok(rec["status"] == "paid" and any(x["kind"] == "release" for x in rec["txs"]), f"체인 감시가 {time.time() - t0:.0f}초 뒤 지급 → {rec['status']}")
    b = service.propose(group_name="한도모임", members=names, shares=[[n, 20000] for n in names], total=80000, payer="가",
                        rule_text="8만원 넷이 1인 1만5천원 넘으면 안 돼", purpose="회식", per_person_cap=15000)
    brec = store.get(b.get("id") or (b.get("settlement") or {}).get("id"))
    ok(brec["status"] == "blocked" and (brec.get("blocked") or {}).get("tx_hash"), "1인 한도 초과 → 온체인 중단(Blocked)")

    if not a.skip_freeze:
        print(f"\nB. 멈춤 (블록 12초 · 체인 읽기 {a.rpc_delay * 1000:.0f}ms 지연)")
        orig = ch.w3.provider.make_request

        def slow(method, params):
            time.sleep(a.rpc_delay)
            return orig(method, params)
        ch.w3.provider.make_request = slow
        mine(False, 12)

        def measure(seconds: int, pollers: list[str], actions) -> tuple[list[float], list[float]]:
            lat, probe, stop = [], [], threading.Event()

            def poll(n):
                time.sleep(random.uniform(0, 4))
                while not stop.is_set():
                    t = time.perf_counter(); service.list_for(n); lat.append((time.perf_counter() - t) * 1000)
                    time.sleep(max(0, 4 - (time.perf_counter() - t)))

            def prober():
                while not stop.is_set():
                    t = time.perf_counter(); service.list_for("다른사람"); probe.append((time.perf_counter() - t) * 1000)
                    time.sleep(0.5)
            th = [threading.Thread(target=poll, args=(n,)) for n in pollers] + [threading.Thread(target=prober) for _ in range(3)]
            th += [threading.Thread(target=f) for f in actions]
            [x.start() for x in th]
            time.sleep(seconds)
            stop.set()
            [x.join(timeout=600) for x in th]
            return sorted(lat), sorted(probe)

        def show(label, xs):
            if not xs:
                return 0.0
            print(f"    {label}: {len(xs)}회 · p95 {xs[int(.95 * (len(xs) - 1))]:.0f}ms · 최대 {xs[-1]:.0f}ms · 1초 넘게 {sum(v > 1000 for v in xs) / len(xs):.0%}")
            return xs[-1]
        # B1. 베타 첫 순간
        joined = []

        def newbie(i):
            time.sleep(2 + i * 5)
            n = f"새{i}"
            t = time.perf_counter(); service.register_member(n, Account.create().address); joined.append(time.perf_counter() - t)
            service.charge(n)
        _, pr = measure(55, [f"조회{k}" for k in range(20)], [lambda i=i: newbie(i) for i in range(8)])
        m1 = show("새 사용자 8명 지갑 연결·충전 중 다른 사람 요청", pr)
        ok(m1 < 1500 and max(joined or [0]) < 3, f"베타 첫 순간: 지갑 연결 최대 {max(joined or [0]):.1f}초 · 다른 사람 최대 {m1 / 1000:.1f}초")
        # B2. 정산 있는 사람들의 새로고침 (체인 감시가 읽음)
        mine(True, 0)
        grp = [f"회원{i:02d}" for i in range(12)]
        for n in grp:
            service.register_member(n, Account.create().address)
        ths = [threading.Thread(target=service.charge, args=(n,)) for n in grp]
        [x.start() for x in ths]
        [x.join() for x in ths]
        for g in range(3):
            ms = grp[g * 4:(g + 1) * 4]
            service.propose(group_name=f"모임{g}", members=ms, shares=[[m, 10000] for m in ms], total=40000, payer=ms[0],
                            rule_text="4만원 넷이", purpose="저녁")
        mine(False, 12)
        lat, pr = measure(30, grp, [])
        m2 = max(show("정산 있는 12명 새로고침", lat), show("다른 사람 요청", pr))
        ok(m2 < 1500, f"새로고침이 체인을 읽지 않음: 최대 {m2 / 1000:.1f}초")
        # B3. 남은 멈춤: 정산 만들기 (전역 잠금 안에서 확정 대기)
        extra = [f"추가{i}" for i in range(4)]
        for n in extra:
            service.register_member(n, Account.create().address)
            service.charge(n)

        def make():
            time.sleep(3)
            service.propose(group_name="추가모임", members=extra, shares=[[m, 5000] for m in extra], total=20000, payer=extra[0],
                            rule_text="2만원 넷이", purpose="간식")
        _, pr = measure(30, [], [make])
        m3 = show("정산 만들기 1건 동안 다른 사람 요청", pr)
        print(f"  ℹ 남은 멈춤: 정산 만들기 1건마다 다른 사람 요청이 최대 {m3 / 1000:.1f}초 기다려요 (블록 1개 확정 대기 — 알려진 한계)")
        mine(True, 0)
    print("\n✓ 실제 체인 점검 통과" if not fails else f"\n✗ 실패 {len(fails)}건")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
