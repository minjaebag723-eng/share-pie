"""컨트랙트 ABI — 사람이 읽는 형식(ethers v6 그대로 사용) + web3.py용 JSON 변환.

⚠️ Remix로 배포한 뒤 컴파일러가 만든 ABI와 다르면 Remix 쪽이 정답입니다.
   (Remix → Solidity Compiler → ABI 복사 → contracts/abi/*.json 에 덮어쓰면 web3.py가 그 파일을 우선 사용)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LEDGER_ABI = [
    "function createSettlement(bytes32 id, address token, address payee, address[] members, uint256[] shares, bytes32 conditionHash, string purpose)",
    "function lockForSettlement(bytes32 id)",
    "function createPurchase(bytes32 id, address token, address merchant, address[] members, uint256[] shares, bytes32 conditionHash, string purpose)",
    "function approvePurchase(bytes32 id)",
    "function executePurchase(bytes32 id, bytes32 orderRef)",
    "function isPurchase(bytes32 id) view returns (bool)",
    "function approvedCount(bytes32 id) view returns (uint256)",
    "function orderRefOf(bytes32 id) view returns (bytes32)",
    "function markOfflinePayment(bytes32 id, address participant)",
    "function releaseToRecipient(bytes32 id)",
    "function raiseDispute(bytes32 id, address by, string reason)",
    "function refundParticipant(bytes32 id, address participant)",
    "function resolveDispute(bytes32 id, uint8 verdict, string note)",
    "function blockSettlement(bytes32 id, address member, uint8 reasonCode, string note)",
    "function setAgent(address agent, bool enabled)",
    "function setDisputeWindow(uint256 seconds_)",
    "function disputeWindow() view returns (uint256)",
    "function getSettlement(bytes32 id) view returns (address token, address payee, uint256 total, uint256 collected, uint256 escrowed, bytes32 conditionHash, uint8 status, uint64 lockedAt, string purpose)",
    "function releaseAt(bytes32 id) view returns (uint256)",
    "function getMembers(bytes32 id) view returns (address[] members, uint256[] shares, uint8[] states)",
    "function shareOf(bytes32 id, address member) view returns (uint256)",
    "function memberState(bytes32 id, address member) view returns (uint8)",
    "function committedOf(address user) view returns (uint256)",
    "function escrowOf(address user) view returns (uint256)",
    "function spentOf(address user) view returns (uint256)",
    "function isAgent(address agent) view returns (bool)",
    "function owner() view returns (address)",
    "event AgentSet(address indexed agent, bool enabled)",
    "event DisputeWindowSet(uint256 seconds_)",
    "event SettlementCreated(bytes32 indexed id, address indexed token, address indexed payee, uint256 total, bytes32 conditionHash, string purpose)",
    "event ShareAssigned(bytes32 indexed id, address indexed member, uint256 amount)",
    "event Locked(bytes32 indexed id, address indexed member, uint256 amount)",
    "event OfflinePaid(bytes32 indexed id, address indexed member, uint256 amount, address indexed confirmer)",
    "event FullyLocked(bytes32 indexed id, uint256 total, uint256 releaseAfter)",
    "event Paid(bytes32 indexed id, address indexed from, address indexed to, uint256 amount, string purpose)",
    "event Blocked(bytes32 indexed id, address indexed member, uint8 reasonCode, string note)",
    "event Refunded(bytes32 indexed id, address indexed member, uint256 amount)",
    "event PurchaseApproved(bytes32 indexed id, address indexed member, uint256 amount)",
    "event Withdrawn(bytes32 indexed id, address indexed member, uint256 amount)",
    "event PurchaseExecuted(bytes32 indexed id, address indexed merchant, uint256 total, bytes32 orderRef)",
    "event DisputeRaised(bytes32 indexed id, address indexed by, string reason)",
    "event DisputeResolved(bytes32 indexed id, uint8 verdict, string note)",
]

TOKEN_ABI = [
    "function name() view returns (string)",
    "function symbol() view returns (string)",
    "function decimals() view returns (uint8)",
    "function totalSupply() view returns (uint256)",
    "function balanceOf(address owner) view returns (uint256)",
    "function allowance(address owner, address spender) view returns (uint256)",
    "function lastClaimAt(address user) view returns (uint256)",
    "function approve(address spender, uint256 value) returns (bool)",
    "function transfer(address to, uint256 value) returns (bool)",
    "function transferFrom(address from, address to, uint256 value) returns (bool)",
    "function claim()",
    "function chargeToken(address to, uint256 amount)",
    "function isMinter(address minter) view returns (bool)",
    "event Transfer(address indexed from, address indexed to, uint256 value)",
    "event Approval(address indexed owner, address indexed spender, uint256 value)",
    "event Charged(address indexed to, uint256 amount, address indexed by)",
]

_SIG = re.compile(r"^(function|event)\s+(\w+)\((.*?)\)\s*(view|pure|payable)?\s*(?:returns\s*\((.*)\))?$")


def _params(s: str, event: bool = False) -> list[dict]:
    out = []
    for i, part in enumerate([p.strip() for p in s.split(",") if p.strip()]):
        toks = part.split()
        item = {"type": toks[0], "name": ""}
        rest = toks[1:]
        if event:
            item["indexed"] = "indexed" in rest
            rest = [t for t in rest if t != "indexed"]
        if rest:
            item["name"] = rest[0]
        item["internalType"] = item["type"]
        out.append(item)
    return out


def to_json(human: list[str]) -> list[dict]:
    abi = []
    for line in human:
        m = _SIG.match(line.strip())
        if not m:
            raise ValueError(f"ABI 파싱 실패: {line}")
        kind, name, ins, mut, outs = m.groups()
        if kind == "event":
            abi.append({"type": "event", "name": name, "anonymous": False, "inputs": _params(ins, event=True)})
        else:
            abi.append({"type": "function", "name": name, "inputs": _params(ins),
                        "outputs": _params(outs or ""), "stateMutability": mut or "nonpayable"})
    return abi


_ABI_DIR = Path(__file__).resolve().parent.parent / "contracts" / "abi"


def load_json(kind: str) -> list[dict]:
    """contracts/abi/{ShareLedger,PieToken}.json 이 있으면 우선 사용 (Remix ABI 붙여넣기용)."""
    f = _ABI_DIR / f"{kind}.json"
    if f.exists():
        data = json.loads(f.read_text(encoding="utf-8"))
        return data["abi"] if isinstance(data, dict) and "abi" in data else data
    return to_json(LEDGER_ABI if kind == "ShareLedger" else TOKEN_ABI)
