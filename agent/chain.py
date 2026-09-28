"""블록체인 계층 — 에이전트가 체인을 '읽고(잔액·장부) / 쓰고(등록·중단·판정) / 확정(지급)'.

CHAIN_MODE=bsc  → BNB Smart Chain Testnet (web3.py 필요)
CHAIN_MODE=mock → ShareLedger.sol·PieToken.sol 상태 전이를 그대로 흉내 낸 로컬 가짜 체인 (해시는 가짜)
두 구현은 같은 인터페이스를 가진다.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any

from . import abi, config

STATUS = {0: "none", 1: "open", 2: "locked", 3: "paid", 4: "blocked", 5: "disputed", 6: "refunded"}
MSTATE = {0: "wait", 1: "locked", 2: "offline", 3: "refunded", 4: "payee", 5: "approved"}
VERDICT = {"NORMAL_APPROVAL": 1, "GENUINE_ERROR": 2, "BAD_FAITH_DISPUTE": 3}
ZERO = "0x0000000000000000000000000000000000000000"
# [blockchain 담당] 화면·/api/health 에 보이는 네트워크 이름 — chainId 로 결정 (BSC_* 변수 이름은 호환용, 값은 어떤 EVM 테스트넷이든 됨)
NETWORK_NAMES = {11155111: "Ethereum Sepolia Testnet", 97: "BNB Smart Chain Testnet", 31337: "Hardhat Local"}


class ChainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ─────────────────────────── Mock ───────────────────────────
def _h(text: str) -> str:
    return "0x" + hashlib.sha3_256(text.encode()).hexdigest()


class MockChain:
    """ShareLedger.sol + PieToken.sol 을 1:1로 구현. data/mockchain.json 에 저장."""
    mode = "mock"

    def __init__(self) -> None:
        self.file = config.DATA_DIR / "mockchain.json"
        self._lock = threading.RLock()
        self.st = {"block": 18_000_000, "nonce": 0, "balance": {}, "committed": {}, "escrow": {},
                   "spent": {}, "settlements": {}, "txs": {}}
        if self.file.exists():
            self.st.update(json.loads(self.file.read_text(encoding="utf-8")))
        self.agent = "0xA6e4700000000000000000000000000000A6e470"
        self.ledger = "0x1ed6e70000000000000000000000000000001ed6"
        self.token = "0x91e0000000000000000000000000000000091e0"

    def info(self) -> dict[str, Any]:
        return {"mode": "mock", "network": "Share Pie 모의 체인 (로컬 시뮬레이션)", "chain_id": 97,
                "chain_id_hex": "0x61", "ledger": self.ledger, "token": self.token, "token_symbol": "PIE",
                "token_decimals": 0, "agent": self.agent, "explorer": None, "rpc": None,
                "dispute_window": self.dispute_window()}

    def dispute_window(self) -> int:
        return config.DISPUTE_WINDOW_SEC

    def settlement_id(self, sid: str) -> str:
        return _h("sharepie:" + sid)

    def condition_hash(self, text: str) -> str:
        return _h(text or "")

    def explorer_tx(self, tx_hash: str | None) -> str | None:
        return None

    def _save(self) -> None:
        tmp = self.file.with_suffix(".tmp")   # 쓰는 도중 꺼져도 파일이 깨지지 않게
        tmp.write_text(json.dumps(self.st, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.file)

    def _tx(self, events: list[dict[str, Any]], sender: str) -> dict[str, Any]:
        self.st["nonce"] += 1
        self.st["block"] += 1
        tx = _h(f"tx{self.st['nonce']}{time.time()}")
        for i, e in enumerate(events):
            e.update({"tx_hash": tx, "block": self.st["block"], "log_index": i})
        self.st["txs"][tx] = {"events": events, "block": self.st["block"], "from": sender}
        self._save()
        return {"tx_hash": tx, "block": self.st["block"], "events": events}

    def _add(self, key: str, addr: str, amt: int) -> None:
        d = self.st[key]
        d[addr.lower()] = d.get(addr.lower(), 0) + amt

    def _get(self, key: str, addr: str) -> int:
        return self.st[key].get(addr.lower(), 0)

    def _s(self, cid: str, *allowed: str) -> dict[str, Any]:
        s = self.st["settlements"].get(cid)
        if not s or (allowed and s["status"] not in allowed):
            raise ChainError("CHAIN_TX_FAILED", f"Ledger: bad status ({s['status'] if s else 'none'})")
        return s

    # 읽기
    def account(self, addr: str) -> dict[str, int]:
        return {"balance": self._get("balance", addr), "committed": self._get("committed", addr),
                "escrow": self._get("escrow", addr), "spent": self._get("spent", addr)}

    def get_settlement(self, cid: str) -> dict[str, Any]:
        s = self.st["settlements"].get(cid)
        if not s:
            return {"status": "none", "members": []}
        out = json.loads(json.dumps(s))
        out["release_at"] = s.get("release_after") or ((s["locked_at"] + self.dispute_window()) if s.get("locked_at") else 0)
        return out

    def events_from_tx(self, tx_hash: str) -> list[dict[str, Any]]:
        return (self.st["txs"].get(tx_hash) or {}).get("events", [])

    def scan_events(self, cid: str, from_block: int = 0) -> list[dict[str, Any]]:
        out = []
        for tx in self.st["txs"].values():
            out += [e for e in tx["events"] if e["args"].get("id") == cid]
        return sorted(out, key=lambda e: (e["block"], e.get("log_index", 0)))

    # 에이전트 쓰기
    def create_purchase(self, cid, merchant, members, shares, cond_hash, purpose) -> dict[str, Any]:
        """AI 구매 대행: payee = 가맹점 지갑 (컨트랙트 createPurchase 와 같음)."""
        if any(m.lower() == merchant.lower() for m in members):
            raise ChainError("CHAIN_TX_FAILED", "Ledger: merchant is member")
        return self.create_settlement(cid, merchant, members, shares, cond_hash, purpose, purchase=True)

    def approve_purchase(self, cid, addr) -> dict[str, Any]:
        """참여자 '내 몫 인출 승인' (MetaMask: PIE.approve + approvePurchase 를 모의)."""
        with self._lock:
            s = self._s(cid, "open")
            if not s.get("purchase"):
                raise ChainError("CHAIN_TX_FAILED", "Ledger: not purchase")
            m = next((x for x in s["members"] if x["address"].lower() == addr.lower()), None)
            if not m:
                raise ChainError("CHAIN_TX_FAILED", "Ledger: not a member")
            if m["state"] != "wait":
                raise ChainError("CHAIN_TX_FAILED", "Ledger: already approved")
            if self._get("balance", addr) < m["share"]:
                raise ChainError("CHAIN_TX_FAILED", "Ledger: insufficient PIE balance")
            m["state"] = "approved"
            s["approved"] = s.get("approved", 0) + 1
            return self._tx([{"event": "PurchaseApproved", "args": {"id": cid, "member": addr, "amount": m["share"]}}], addr)

    def execute_purchase(self, cid, order_ref) -> dict[str, Any]:
        """전원 승인 후 에이전트: 각자 지갑에서 몫만큼 가상 결제 계좌로 인출 → 가맹점 결제 (전부 성공 or 전부 취소)."""
        with self._lock:
            s = self._s(cid, "open")
            if not s.get("purchase"):
                raise ChainError("CHAIN_TX_FAILED", "Ledger: not purchase")
            if s.get("approved", 0) != len(s["members"]):
                raise ChainError("CHAIN_TX_FAILED", "Ledger: not all approved")
            for m in s["members"]:   # 원자성: 먼저 전원 잔액 확인 (실제 컨트랙트는 하나라도 실패하면 전체 revert)
                if self._get("balance", m["address"]) < m["share"]:
                    raise ChainError("CHAIN_TX_FAILED", "Ledger: withdraw failed")
            evs = []
            for m in s["members"]:
                self._add("balance", m["address"], -m["share"])
                self._add("committed", m["address"], -m["share"])
                self._add("spent", m["address"], m["share"])
                m["state"] = "locked"
                evs.append({"event": "Withdrawn", "args": {"id": cid, "member": m["address"], "amount": m["share"]}})
                evs.append({"event": "Paid", "args": {"id": cid, "from": m["address"], "to": s["payee"], "amount": m["share"],
                                                      "purpose": s["purpose"]}})
            s["collected"] = s["total"]
            s["status"] = "paid"
            s["order_ref"] = order_ref
            self._add("balance", s["payee"], s["total"])
            evs.append({"event": "PurchaseExecuted", "args": {"id": cid, "merchant": s["payee"], "total": s["total"], "orderRef": order_ref}})
            return self._tx(evs, self.agent)

    def create_settlement(self, cid, payee, members, shares, cond_hash, purpose, purchase: bool = False) -> dict[str, Any]:
        with self._lock:
            if cid in self.st["settlements"]:
                raise ChainError("CHAIN_TX_FAILED", "Ledger: id used")
            evs, collected, ms = [], 0, []
            for m, a in zip(members, shares):
                self._add("committed", m, a)
                is_payee = m.lower() == payee.lower()
                if is_payee:
                    collected += a
                ms.append({"address": m, "share": a, "state": "payee" if is_payee else "wait"})
                evs.append({"event": "ShareAssigned", "args": {"id": cid, "member": m, "amount": a}})
            total = sum(shares)
            self.st["settlements"][cid] = {"status": "open", "token": self.token, "payee": payee, "total": total,
                                           "collected": collected, "escrowed": 0, "condition_hash": cond_hash,
                                           "purpose": purpose, "locked_at": 0, "members": ms, "purchase": purchase}
            evs.append({"event": "SettlementCreated", "args": {"id": cid, "token": self.token, "payee": payee,
                                                               "total": total, "conditionHash": cond_hash, "purpose": purpose}})
            if collected == total and not purchase:
                evs += self._fully_locked(cid)
            return self._tx(evs, self.agent)

    def _fully_locked(self, cid) -> list[dict[str, Any]]:
        s = self.st["settlements"][cid]
        s["status"] = "locked"
        s["locked_at"] = int(time.time())
        s["release_after"] = s["locked_at"] + self.dispute_window()   # 컨트랙트 releaseAfterOf 와 같음
        evs = [{"event": "FullyLocked", "args": {"id": cid, "total": s["total"], "releaseAfter": s["release_after"]}}]
        if self.dispute_window() == 0:
            evs += self._release(cid)
        return evs

    def _release(self, cid) -> list[dict[str, Any]]:
        s = self.st["settlements"][cid]
        s["status"] = "paid"
        evs = []
        for m in s["members"]:
            if m["state"] == "refunded":
                continue
            self._add("committed", m["address"], -m["share"])
            self._add("spent", m["address"], m["share"])
            if m["state"] == "locked":
                self._add("escrow", m["address"], -m["share"])
            evs.append({"event": "Paid", "args": {"id": cid, "from": m["address"], "to": s["payee"],
                                                  "amount": m["share"], "purpose": s["purpose"]}})
        self._add("balance", s["payee"], s["escrowed"])
        s["escrowed"] = 0
        return evs

    def release(self, cid) -> dict[str, Any]:
        with self._lock:
            s = self._s(cid, "locked")
            if time.time() < (s.get("release_after") or s["locked_at"] + self.dispute_window()):
                raise ChainError("CHAIN_TX_FAILED", "Ledger: dispute window open")
            return self._tx(self._release(cid), self.agent)

    def mark_offline(self, cid, participant) -> dict[str, Any]:
        with self._lock:
            s = self._s(cid, "open")
            m = next((x for x in s["members"] if x["address"].lower() == participant.lower()), None)
            if not m or m["state"] != "wait":
                raise ChainError("CHAIN_TX_FAILED", "Ledger: already paid")
            m["state"] = "offline"
            s["collected"] += m["share"]
            evs = [{"event": "OfflinePaid", "args": {"id": cid, "member": participant, "amount": m["share"], "confirmer": s["payee"]}}]
            if s["collected"] == s["total"]:
                evs += self._fully_locked(cid)
            return self._tx(evs, self.agent)

    def raise_dispute(self, cid, by, reason) -> dict[str, Any]:
        with self._lock:
            s = self._s(cid, "locked")
            if time.time() >= (s.get("release_after") or s["locked_at"] + self.dispute_window()):
                raise ChainError("CHAIN_TX_FAILED", "Ledger: window closed")
            s["status"] = "disputed"
            return self._tx([{"event": "DisputeRaised", "args": {"id": cid, "by": by, "reason": reason}}], self.agent)

    def refund(self, cid, participant) -> dict[str, Any]:
        with self._lock:
            s = self._s(cid, "disputed")
            m = next((x for x in s["members"] if x["address"].lower() == participant.lower()), None)
            if not m or m["state"] != "locked":
                raise ChainError("CHAIN_TX_FAILED", "Ledger: nothing to refund")
            m["state"] = "refunded"
            self._add("escrow", participant, -m["share"])
            self._add("committed", participant, -m["share"])
            self._add("balance", participant, m["share"])
            s["escrowed"] -= m["share"]
            return self._tx([{"event": "Refunded", "args": {"id": cid, "member": participant, "amount": m["share"]}}], self.agent)

    def resolve(self, cid, verdict: int, note: str) -> dict[str, Any]:
        with self._lock:
            s = self._s(cid, "disputed")
            evs = [{"event": "DisputeResolved", "args": {"id": cid, "verdict": verdict, "note": note}}]
            if verdict == 2 and all(m["state"] not in ("locked", "offline") for m in s["members"]):
                s["status"] = "refunded"
                for m in s["members"]:
                    if m["state"] == "payee":
                        self._add("committed", m["address"], -m["share"])
            else:
                evs += self._release(cid)
            return self._tx(evs, self.agent)

    def block_settlement(self, cid, member, code, note) -> dict[str, Any]:
        with self._lock:
            s = self.st["settlements"].get(cid)
            evs = []
            if s and s["status"] != "open":
                raise ChainError("CHAIN_TX_FAILED", "Ledger: already closed")
            if s:
                for m in s["members"]:
                    self._add("committed", m["address"], -m["share"])
                    if m["state"] == "approved":
                        m["state"] = "wait"   # 구매 승인 무효 (인출된 돈 없음)
                    if m["state"] == "locked":
                        m["state"] = "refunded"
                        self._add("escrow", m["address"], -m["share"])
                        self._add("balance", m["address"], m["share"])
                        s["escrowed"] -= m["share"]
                        evs.append({"event": "Refunded", "args": {"id": cid, "member": m["address"], "amount": m["share"]}})
                s["status"] = "blocked"
            else:
                self.st["settlements"][cid] = {"status": "blocked", "members": [], "total": 0, "collected": 0, "escrowed": 0,
                                               "payee": ZERO, "purpose": "", "condition_hash": "0x" + "0" * 64, "locked_at": 0}
            evs.append({"event": "Blocked", "args": {"id": cid, "member": member or ZERO, "reasonCode": code, "note": note}})
            return self._tx(evs, self.agent)

    def charge(self, to: str, amount: int) -> dict[str, Any]:
        with self._lock:
            self._add("balance", to, amount)
            return self._tx([{"event": "Charged", "args": {"to": to, "amount": amount, "by": self.agent}}], self.agent)

    # 사용자(MetaMask 대신) — mock 전용
    # [blockchain 담당] 모의 체인은 가스가 필요 없다
    def native_balance(self, addr: str) -> float:
        return 1.0

    def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:
        return None

    def mock_transfer(self, frm: str, to: str, amount: int) -> dict[str, Any]:
        """PieToken.transfer 흉내 (AI 사용료 송금). 정산에 쓰기로 한 금액(사용 예정)은 건드리지 않는다."""
        with self._lock:
            free = self._get("balance", frm) - (self._get("committed", frm) - self._get("escrow", frm))
            if amount <= 0 or free < amount:
                raise ChainError("CHAIN_TX_FAILED", "PieToken: insufficient available balance")
            self._add("balance", frm, -amount)
            self._add("balance", to, amount)
            return self._tx([{"event": "Transfer", "args": {"from": frm, "to": to, "value": amount}}], frm)

    def verify_transfer(self, tx_hash: str, frm: str, to: str) -> int:
        tx = self.st["txs"].get(tx_hash) or {}
        return sum(int(e["args"]["value"]) for e in tx.get("events", []) if e["event"] == "Transfer"
                   and e["args"]["from"].lower() == frm.lower() and e["args"]["to"].lower() == to.lower())

    def mock_lock(self, cid: str, addr: str) -> dict[str, Any]:
        if (self.st["settlements"].get(cid) or {}).get("purchase"):
            return self.approve_purchase(cid, addr)
        with self._lock:
            s = self._s(cid, "open")
            m = next((x for x in s["members"] if x["address"].lower() == addr.lower()), None)
            if not m:
                raise ChainError("CHAIN_TX_FAILED", "Ledger: not a member")
            if m["state"] != "wait":
                raise ChainError("CHAIN_TX_FAILED", "Ledger: already locked")
            if self._get("balance", addr) < m["share"]:
                raise ChainError("CHAIN_TX_FAILED", "Ledger: insufficient PIE balance")
            m["state"] = "locked"
            self._add("balance", addr, -m["share"])
            self._add("escrow", addr, m["share"])
            s["collected"] += m["share"]
            s["escrowed"] += m["share"]
            evs = [{"event": "Locked", "args": {"id": cid, "member": addr, "amount": m["share"]}}]
            if s["collected"] == s["total"]:
                evs += self._fully_locked(cid)
            return self._tx(evs, addr)


# ─────────────────────────── BNB Testnet ───────────────────────────
class Web3Chain:
    mode = "bsc"
    EVENT_NAMES = ("SettlementCreated", "ShareAssigned", "Locked", "OfflinePaid", "FullyLocked", "Paid", "Blocked",
                   "Refunded", "DisputeRaised", "DisputeResolved", "PurchaseApproved", "Withdrawn", "PurchaseExecuted")

    def __init__(self) -> None:
        try:
            from web3 import Web3
        except ImportError as e:  # pragma: no cover
            raise ChainError("CHAIN_UNAVAILABLE", "web3 패키지가 없어요: pip install web3") from e
        for need, name in ((config.LEDGER_ADDRESS, "LEDGER_ADDRESS"), (config.TOKEN_ADDRESS, "TOKEN_ADDRESS"),
                           (config.AGENT_PRIVATE_KEY, "AGENT_PRIVATE_KEY")):
            if not need:
                raise ChainError("CHAIN_UNAVAILABLE", f".env 에 {name} 가 없어요")
        self.W = Web3
        self.w3 = Web3(Web3.HTTPProvider(config.BSC_RPC_URL, request_kwargs={"timeout": 20}))
        try:  # BSC는 PoA 체인 → extraData 미들웨어 (web3 v7+/v6 호환)
            from web3.middleware import ExtraDataToPOAMiddleware
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except ImportError:  # pragma: no cover
            from web3.middleware import geth_poa_middleware
            self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.acct = self.w3.eth.account.from_key(config.AGENT_PRIVATE_KEY)
        self.ledger_addr = Web3.to_checksum_address(config.LEDGER_ADDRESS)
        self.token_addr = Web3.to_checksum_address(config.TOKEN_ADDRESS)
        self.ledger = self.w3.eth.contract(address=self.ledger_addr, abi=abi.load_json("ShareLedger"))
        self.token = self.w3.eth.contract(address=self.token_addr, abi=abi.load_json("PieToken"))
        self._decimals: int | None = None
        self._symbol = "PIE"
        self._window: int | None = None
        self._send_lock = threading.Lock()
        self._nonce: int | None = None          # [베타 서버] 다음에 쓸 nonce (None = 체인에서 다시 읽기)
        self._serial_lock = threading.Lock()    # CHAIN_TX_PIPELINE=0 일 때 예전처럼 확정까지 한 건씩

    @property
    def decimals(self) -> int:
        if self._decimals is None:
            try:
                self._decimals = int(self.token.functions.decimals().call())
                self._symbol = self.token.functions.symbol().call()
            except Exception:
                self._decimals = 0
        return self._decimals

    def _units(self, won: int) -> int:
        return int(won) * 10 ** self.decimals

    def _won(self, units: int) -> int:
        return int(units) // 10 ** self.decimals

    def dispute_window(self) -> int:
        if self._window is None:
            try:
                self._window = int(self.ledger.functions.disputeWindow().call())
            except Exception:
                self._window = config.DISPUTE_WINDOW_SEC
        return self._window

    def info(self) -> dict[str, Any]:
        _ = self.decimals
        return {"mode": "bsc", "network": NETWORK_NAMES.get(config.BSC_CHAIN_ID, f"EVM 테스트넷 (chainId {config.BSC_CHAIN_ID})"), "chain_id": config.BSC_CHAIN_ID,
                "chain_id_hex": hex(config.BSC_CHAIN_ID), "ledger": self.ledger_addr, "token": self.token_addr,
                "token_symbol": self._symbol, "token_decimals": self.decimals, "agent": self.acct.address,
                "explorer": config.BSC_EXPLORER, "rpc": config.BSC_RPC_URL, "dispute_window": self.dispute_window()}

    def settlement_id(self, sid: str) -> str:
        return self.W.to_hex(self.W.keccak(text="sharepie:" + sid))

    def condition_hash(self, text: str) -> str:
        return self.W.to_hex(self.W.keccak(text=text or ""))

    def explorer_tx(self, tx_hash: str | None) -> str | None:
        return f"{config.BSC_EXPLORER}/tx/{tx_hash}" if tx_hash else None

    def _b32(self, hexstr: str) -> bytes:
        return self.W.to_bytes(hexstr=hexstr)

    def _cs(self, addr: str) -> str:
        return self.W.to_checksum_address(addr)

    # 읽기
    def account(self, addr: str) -> dict[str, int]:
        a = self._cs(addr)
        f = self.ledger.functions
        try:
            return {"balance": self._won(self.token.functions.balanceOf(a).call()),
                    "committed": self._won(f.committedOf(a).call()),
                    "escrow": self._won(f.escrowOf(a).call()),
                    "spent": self._won(f.spentOf(a).call())}
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"RPC 조회 실패: {e}") from e

    def get_settlement(self, cid: str) -> dict[str, Any]:
        try:
            s = self.ledger.functions.getSettlement(self._b32(cid)).call()
            ms, shares, states = self.ledger.functions.getMembers(self._b32(cid)).call()
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"RPC 조회 실패: {e}") from e
        locked_at = int(s[7])
        try:
            rel = int(self.ledger.functions.releaseAt(self._b32(cid)).call()) if locked_at else 0
        except Exception:  # noqa: BLE001
            rel = locked_at + self.dispute_window() if locked_at else 0
        try:
            purchase = bool(self.ledger.functions.isPurchase(self._b32(cid)).call())
        except Exception:  # noqa: BLE001
            purchase = False
        return {"purchase": purchase, "status": STATUS.get(int(s[6]), "none"), "token": s[0], "payee": s[1], "total": self._won(s[2]),
                "collected": self._won(s[3]), "escrowed": self._won(s[4]), "condition_hash": self.W.to_hex(s[5]),
                "locked_at": locked_at, "release_at": rel,
                "purpose": s[8],
                "members": [{"address": m, "share": self._won(a), "state": MSTATE.get(int(st), "wait")}
                            for m, a, st in zip(ms, shares, states)]}

    def _norm(self, ev) -> dict[str, Any]:
        args = {}
        for k, v in dict(ev["args"]).items():
            if isinstance(v, (bytes, bytearray)):
                v = self.W.to_hex(v)
            elif k in ("amount", "total") and isinstance(v, int):
                v = self._won(v)
            args[k] = v
        return {"event": ev["event"], "args": args, "tx_hash": self.W.to_hex(ev["transactionHash"]),
                "block": int(ev["blockNumber"]), "log_index": int(ev["logIndex"])}

    def _parse_receipt(self, rcpt) -> list[dict[str, Any]]:
        from web3.logs import DISCARD
        out = []
        for name in self.EVENT_NAMES:
            for ev in getattr(self.ledger.events, name)().process_receipt(rcpt, errors=DISCARD):
                out.append(self._norm(ev))
        return sorted(out, key=lambda e: e.get("log_index", 0))

    def events_from_tx(self, tx_hash: str) -> list[dict[str, Any]]:
        try:
            rcpt = self.w3.eth.get_transaction_receipt(tx_hash)
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"영수증 조회 실패: {e}") from e
        return self._parse_receipt(rcpt)

    def scan_events(self, cid: str, from_block: int = 0) -> list[dict[str, Any]]:
        """공개 RPC는 getLogs 범위 제한이 있어 2,000블록씩 나눠 조회."""
        latest = self.w3.eth.block_number
        start = max(from_block or config.LEDGER_DEPLOY_BLOCK or latest - 5000, latest - 50_000)
        out: list[dict[str, Any]] = []
        b = start
        while b <= latest:
            end = min(b + 1999, latest)
            for name in self.EVENT_NAMES:
                ev = getattr(self.ledger.events, name)
                try:
                    logs = ev.get_logs(from_block=b, to_block=end, argument_filters={"id": self._b32(cid)})
                except TypeError:  # web3 v6
                    logs = ev.get_logs(fromBlock=b, toBlock=end, argument_filters={"id": self._b32(cid)})
                out += [self._norm(x) for x in logs]
            b = end + 1
        return sorted(out, key=lambda e: (e["block"], e.get("log_index", 0)))

    # 에이전트 쓰기
    # [blockchain 담당] 가스 가격: 시세 × GAS_PRICE_MULTIPLIER, 최소 시세 + 0.5 gwei. 테스트넷은 가스가 공짜라 넉넉히 주는 편이 안전
    def _gas_price(self) -> int:
        gp = int(self.w3.eth.gas_price)
        price = max(int(gp * config.GAS_PRICE_MULTIPLIER), gp + int(self.w3.to_wei(0.5, "gwei")))
        if config.CHAIN_MAX_GAS_GWEI > 0:   # [베타 서버] 상한 — 가스 시세가 튀거나(스팸) 우리 트랜잭션이 시세를 끌어올려도 지갑이 바닥나지 않게
            price = min(price, int(self.w3.to_wei(config.CHAIN_MAX_GAS_GWEI, "gwei")))
        return price

    # [베타 서버] 에이전트 트랜잭션 줄 세우기 — nonce 배정·서명·전송만 잠금 안에서, 확정(영수증) 대기는 잠금 밖에서.
    # 예전엔 영수증까지 잠금을 쥐어 한 건씩만 나갔다(Sepolia 분당 약 4건). 이제 여러 사람의 트랜잭션이 같은 블록에 실린다.
    # 다른 곳(증거 스크립트 등)이 같은 지갑으로 보내 nonce가 어긋나면 체인에서 다시 읽고 재시도한다.
    _NONCE_ERR = ("nonce too low", "nonce too high", "replacement transaction underpriced", "invalid nonce")

    def _serial(self):
        import contextlib
        return self._serial_lock if not config.CHAIN_TX_PIPELINE else contextlib.nullcontext()

    def _broadcast(self, build):
        """build(nonce, gas_price) → 서명할 tx. 잠금 안에서 nonce를 배정해 보내고 해시를 돌려준다 (확정은 기다리지 않음)."""
        with self._send_lock:
            for attempt in range(3):
                if self._nonce is None:
                    self._nonce = self.w3.eth.get_transaction_count(self.acct.address, "pending")
                nonce = self._nonce
                signed = self.acct.sign_transaction(build(nonce, self._gas_price()))
                raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
                try:
                    h = self.w3.eth.send_raw_transaction(raw)
                except Exception as e:
                    self._nonce = None
                    if attempt < 2 and any(k in str(e).lower() for k in self._NONCE_ERR):
                        continue
                    raise
                self._nonce = nonce + 1
                return h

    def _send(self, fn) -> dict[str, Any]:
        def build(nonce: int, gas_price: int) -> dict[str, Any]:
            tx = fn.build_transaction({
                "from": self.acct.address,
                "nonce": nonce,
                "chainId": config.BSC_CHAIN_ID,
                # [blockchain 담당] 가스 가격 +25% 버퍼 — 정확히 gas_price 로 보내면 Sepolia 에서 mempool 에 걸려 120초 후 실패
                "gasPrice": gas_price,
            })
            tx["gas"] = int(tx.get("gas") or self.w3.eth.estimate_gas(tx)) * 12 // 10
            return tx
        try:
            with self._serial():
                h = self._broadcast(build)
                rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=config.CHAIN_TX_TIMEOUT_SEC)
        except Exception as e:
            raise ChainError("CHAIN_TX_FAILED", f"트랜잭션 실패: {e}") from e
        if rcpt["status"] != 1:
            raise ChainError("CHAIN_TX_FAILED", f"트랜잭션 revert: {self.W.to_hex(h)}")
        return {"tx_hash": self.W.to_hex(h), "block": int(rcpt["blockNumber"]), "events": self._parse_receipt(rcpt)}

    PURPOSE_MAX = 60   # [blockchain 담당] 가드 C — 온체인 문자열은 길이 = 가스. AI 가 목적 문구를 길게 써도 여기서 자른다

    def create_settlement(self, cid, payee, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createSettlement(
            self._b32(cid), self.token_addr, self._cs(payee), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), (purpose or "")[:self.PURPOSE_MAX]))

    def create_purchase(self, cid, merchant, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createPurchase(
            self._b32(cid), self.token_addr, self._cs(merchant), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), (purpose or "")[:self.PURPOSE_MAX]))

    def execute_purchase(self, cid, order_ref) -> dict[str, Any]:
        return self._send(self.ledger.functions.executePurchase(self._b32(cid), self._b32(order_ref)))

    def block_settlement(self, cid, member, code, note) -> dict[str, Any]:
        return self._send(self.ledger.functions.blockSettlement(self._b32(cid), self._cs(member or ZERO), int(code), note[:120]))

    def release(self, cid) -> dict[str, Any]:
        return self._send(self.ledger.functions.releaseToRecipient(self._b32(cid)))

    def mark_offline(self, cid, participant) -> dict[str, Any]:
        return self._send(self.ledger.functions.markOfflinePayment(self._b32(cid), self._cs(participant)))

    def raise_dispute(self, cid, by, reason) -> dict[str, Any]:
        return self._send(self.ledger.functions.raiseDispute(self._b32(cid), self._cs(by), reason[:200]))

    def refund(self, cid, participant) -> dict[str, Any]:
        return self._send(self.ledger.functions.refundParticipant(self._b32(cid), self._cs(participant)))

    def resolve(self, cid, verdict: int, note: str) -> dict[str, Any]:
        return self._send(self.ledger.functions.resolveDispute(self._b32(cid), int(verdict), note[:200]))

    def charge(self, to: str, amount: int) -> dict[str, Any]:
        return self._send(self.token.functions.chargeToken(self._cs(to), self._units(amount)))

    # [blockchain 담당] 가스 자동 지급 — 에이전트 지갑에서 네이티브 코인(ETH/tBNB) 소량 전송
    def native_balance(self, addr: str) -> float:
        try:
            return float(self.w3.from_wei(self.w3.eth.get_balance(self._cs(addr)), "ether"))
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"잔액 조회 실패: {e}") from e

    def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:
        value = self.w3.to_wei(eth, "ether")
        try:
            with self._serial():
                h = self._broadcast(lambda nonce, gas_price: {
                    "from": self.acct.address, "to": self._cs(to), "value": value,
                    "nonce": nonce, "chainId": config.BSC_CHAIN_ID, "gas": 21000, "gasPrice": gas_price})
                rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=config.CHAIN_TX_TIMEOUT_SEC)
        except Exception as e:
            raise ChainError("CHAIN_TX_FAILED", f"가스 지급 실패: {e}") from e
        if rcpt["status"] != 1:
            raise ChainError("CHAIN_TX_FAILED", f"가스 지급 revert: {self.W.to_hex(h)}")
        return {"tx_hash": self.W.to_hex(h), "block": int(rcpt["blockNumber"])}

    def verify_transfer(self, tx_hash: str, frm: str, to: str) -> int:
        """사용자가 MetaMask로 보낸 PieToken.transfer 영수증 확인 → frm→to 로 옮겨진 PIE(원 단위). 실패·미확정이면 0."""
        from web3.logs import DISCARD
        try:
            rcpt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"영수증 조회 실패: {e}") from e
        if rcpt["status"] != 1 or (rcpt.get("to") or "").lower() != self.token_addr.lower():
            return 0
        total = 0
        for ev in self.token.events.Transfer().process_receipt(rcpt, errors=DISCARD):
            a = dict(ev["args"])
            if a["from"].lower() == frm.lower() and a["to"].lower() == to.lower():
                total += int(a["value"])
        return self._won(total)


_chain: MockChain | Web3Chain | None = None


def get() -> MockChain | Web3Chain:
    global _chain
    if _chain is None:
        _chain = Web3Chain() if config.CHAIN_MODE == "bsc" else MockChain()
    return _chain
