"""체인 점검 — 베타에서 실제 체인(Sepolia)을 쓸지 정할 때, 그리고 베타 중에.

  python deploy/chain_bench.py status   에이전트 지갑 잔액 · 가스비 · 확정 안 된 트랜잭션 · 정산 몇 건 분량 남았나 (읽기만)
  python deploy/chain_bench.py cost     지금까지 정산 기록에 남은 트랜잭션의 실제 가스·비용 (영수증 조회, 읽기만)
  python deploy/chain_bench.py freeze   [로컬 테스트 체인 전용] 누가 체인 작업을 하는 동안 다른 사람 화면이 얼마나 멈추나

freeze 준비 (완성본 컨트랙트로):
  1) anvil --block-time 12            ← 블록 12초 = Sepolia와 같은 속도 (Foundry의 anvil 또는 npx hardhat node)
  2) 블록체인 담당의 배포 스크립트로 로컬(127.0.0.1:8545)에 배포 → .env의 체인 주소·키를 로컬 값으로
  3) python deploy/chain_bench.py freeze
  판정: 새로고침이 한 번도 1.5초 넘게 멈추지 않으면 통과. 넘으면 체인 확정을 기다리는 동안 전역 잠금(STATE_LOCK)을 쥐고 있는 것 → 베타 전 수정 필요.
도커 서버에서: docker compose --env-file .env -f deploy/docker-compose.yml exec app python deploy/chain_bench.py status
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 로컬 테스트 체인(anvil·hardhat node) 기본 계정 1~3 (공개된 테스트 주소)
LOCAL_ADDRS = ["0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
               "0x90F79bf6EB2c4F870365E785982E1f101E93b906"]
GAS_PER_SETTLEMENT = 1_500_000   # v35 실측: 4명 정산 약 1.36M + 충전 4번 약 0.15M


def _client():
    from agent import chain
    c = chain.get()
    if not hasattr(c, "w3"):
        sys.exit("지금은 모의 체인(CHAIN_MODE=mock)이에요 — 가스비가 없어서 점검할 게 없어요.")
    return c


def status() -> None:
    c = _client()
    w3, a = c.w3, c.acct.address
    bal = w3.eth.get_balance(a) / 1e18
    gwei = w3.eth.gas_price / 1e9
    gap = w3.eth.get_transaction_count(a, "pending") - w3.eth.get_transaction_count(a, "latest")
    per = GAS_PER_SETTLEMENT * gwei / 1e9
    print(f"네트워크 {c.info().get('network')} (chain id {w3.eth.chain_id}) · 에이전트 {a}")
    print(f"잔액 {bal:.5f} ETH · 가스비 {gwei:.2f} gwei · 확정 안 된 트랜잭션 {gap}건")
    if per > 0:
        print(f"4명 정산 1건(충전 포함) ≈ {per:.5f} ETH → 지금 잔액으로 약 {int(bal / per):,}건")
    for price in (1, 5, 20):
        print(f"  참고: 400명 · 1인 정산 2건 가정 ≈ {290_000_000 * price / 1e9:.2f} ETH (가스 {price} gwei)")
    if gap >= 3:
        print("⚠ 확정 안 된 트랜잭션이 쌓였어요 — 가스비가 낮아 막혔을 수 있어요 (블록체인 담당 확인)")


def cost() -> None:
    from agent import store
    c = _client()
    w3 = c.w3
    by_kind: dict[str, list[tuple[int, int]]] = {}
    per_settlement = []
    for r in store.all_settlements():
        tot = 0
        for t in r.get("txs") or []:
            h = t.get("tx_hash")
            if not h:
                continue
            try:
                rc = w3.eth.get_transaction_receipt(h)
            except Exception:  # noqa: BLE001 — 모의 해시·다른 체인
                continue
            price = int(rc.get("effectiveGasPrice") or 0)
            by_kind.setdefault(t.get("kind") or "?", []).append((int(rc["gasUsed"]), price))
            tot += int(rc["gasUsed"]) * price
        if tot:
            per_settlement.append(tot / 1e18)
    if not by_kind:
        print("정산 기록에서 이 체인의 트랜잭션을 찾지 못했어요.")
        return
    print(f"{'종류':<18}{'건수':>6}{'평균 가스':>12}{'합계 ETH':>12}")
    total = 0.0
    for k, v in sorted(by_kind.items()):
        eth = sum(g * p for g, p in v) / 1e18
        total += eth
        print(f"{k:<18}{len(v):>6}{sum(g for g, _ in v) // len(v):>12,}{eth:>12.5f}")
    print(f"합계 {total:.5f} ETH · 정산 {len(per_settlement)}건 · 정산당 평균 {sum(per_settlement) / len(per_settlement):.5f} ETH")


def freeze(pollers: int, seconds: int) -> None:
    import os
    os.environ.setdefault("CHARGE_COOLDOWN_SEC", "0")
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="sp-freeze-")      # 실제 데이터를 건드리지 않게
    from agent import service
    c = _client()
    if c.w3.eth.chain_id not in (31337, 1337):
        sys.exit(f"chain id {c.w3.eth.chain_id} — freeze는 로컬 테스트 체인(anvil·hardhat node)에서만 돌려요 (실제 가스를 쓰니까)")
    for i, a in enumerate(LOCAL_ADDRS):
        service.register_member(f"점검{i}", a)
    lat: list[float] = []
    waits: list[float] = []
    stop = threading.Event()

    def poller(k: int) -> None:
        while not stop.is_set():
            t = time.perf_counter()
            service.list_for(f"조회{k}")
            lat.append((time.perf_counter() - t) * 1000)
            time.sleep(0.5)

    def charger(i: int) -> None:
        time.sleep(3 + i * seconds / 3)
        t = time.perf_counter()
        service.charge(f"점검{i}")
        waits.append(time.perf_counter() - t)

    ths = [threading.Thread(target=poller, args=(k,)) for k in range(pollers)] + [threading.Thread(target=charger, args=(i,)) for i in range(3)]
    for t in ths:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in ths:
        t.join()
    xs = sorted(lat)
    p95 = xs[int(0.95 * (len(xs) - 1))]
    print(f"충전 3건 — 각각 {', '.join(f'{w:.1f}초' for w in waits)}")
    print(f"다른 {pollers}명의 정산 새로고침 {len(xs)}회: p50 {xs[len(xs) // 2]:.0f}ms · p95 {p95:.0f}ms · 최대 {xs[-1]:.0f}ms · "
          f"1초 넘게 멈춤 {sum(v > 1000 for v in xs) / len(xs):.0%}")
    print("✓ 통과 — 체인 작업이 다른 사람을 막지 않아요" if xs[-1] < 1500 else
          f"✗ 멈춤 — 누군가 체인 작업을 하면 다른 사람 화면이 최대 {xs[-1] / 1000:.0f}초 멈춰요 (체인 확정을 기다리는 동안 전역 잠금을 쥠).\n"
          "  베타에서 실제 체인을 쓰려면 수정 필요 · 사용자가 많을수록 더 자주 멈춰요")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Share Pie 체인 점검")
    ap.add_argument("what", choices=["status", "cost", "freeze"])
    ap.add_argument("--pollers", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=45)
    a = ap.parse_args()
    {"status": status, "cost": cost}.get(a.what, lambda: freeze(a.pollers, a.seconds))()
