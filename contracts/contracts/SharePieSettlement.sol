// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ============================================================================
// SharePieSettlement — 정산 코어 온체인 기록 (CLAUDE.md 5번 ★ 함수 + Dispute 모듈 함수)
// ⚠️ 테스트넷(Sepolia) 전용. PieCoin은 실화폐 가치가 없다. 메인넷에 배포하지 않는다.
//
// 흐름 (서버의 운영자 지갑 = owner 가 모든 트랜잭션에 서명하는 데모용 수탁 구조)
//   1) charge_token(user, amount)                                    PieCoin 발급(충전)
//   2) open_settlement(id, participants[], amounts[], conditionsHash, holdSeconds)
//        정산 등록: 누가 얼마를 잠가야 하는지 + 승인 조건 해시 + 보류 기간          → Opened
//   3) lock_for_settlement(id, participant, amount)                  참여자별 분담금을 에스크로(이 컨트랙트)로 잠금
//        - 잔액 < amount 이면 InsufficientBalance 로 거부 (그 참여자는 한 푼도 잠기지 않음)
//        - 등록된 금액과 다르면 거부. 마지막 참여자가 잠그는 순간 전원 잠금 완료  → Locked (holdUntil 저장, SettlementConfirmed)
//          이 트랜잭션이 정산 인증서의 TxHash 가 된다
//   4) 보류(hold) 기간 — 실제 커머스의 "구매확정 전 보류"와 같은 구조
//        - raise_dispute(id, reason)        Locked → Disputed (동결: 지급 불가)
//        - resolve_dispute(id, verdict)     Disputed → Locked (NORMAL_APPROVAL / BAD_FAITH_DISPUTE) 또는 Cancelled (GENUINE_ERROR)
//        - refund_participant(id, p)        Cancelled 에서 각 참여자에게 잠근 금액 그대로 환불
//   5) release_to_recipient(id, recipient)  Locked 이고 holdUntil 이 지난 뒤에만 총액을 한 번에 지급 → Released
//
// 판정 코드 (CLAUDE.md 7번 — 3개뿐, 그 밖의 값은 InvalidVerdict)
//   0 = NORMAL_APPROVAL, 1 = GENUINE_ERROR, 2 = BAD_FAITH_DISPUTE
//
// "일부만 잠긴 채 지급되는" 상황 방지
//   - release 는 전원 잠금(Locked) 상태에서만 실행된다.
//   - 백엔드는 lock 을 보내기 전에 전원의 잔액을 먼저 확인하고, 한 명이라도 부족하면 아무 트랜잭션도 보내지 않는다.
// ============================================================================

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {PieCoin} from "./PieCoin.sol";

contract SharePieSettlement is Ownable {
    PieCoin public immutable pieCoin;

    enum Status { None, Opened, Locked, Disputed, Released, Cancelled }

    uint8 public constant VERDICT_NORMAL_APPROVAL = 0;
    uint8 public constant VERDICT_GENUINE_ERROR = 1;
    uint8 public constant VERDICT_BAD_FAITH_DISPUTE = 2;

    struct Settlement {
        Status status;
        uint256 participantCount;
        uint256 lockedCount;
        uint256 totalExpected;
        uint256 totalLocked;
        address recipient;
        bytes32 conditionsHash; // 승인된 정산 "조건"(방식·총액·감면·예산…)의 keccak256 — 제3자가 조건 원문을 다시 해시해 대조
        uint64 holdSeconds;     // 보류 기간 (정산마다 지정, 팀 결정 전이라 상수로 두지 않음)
        uint64 holdUntil;       // 전원 잠금 시각 + holdSeconds. 이 시각 이후에만 release 가능
        uint8 verdict;          // 마지막 판정 코드 (분쟁이 없었으면 0)
        bool disputed;          // 분쟁이 한 번이라도 접수됐는지
        bytes32 reasonHash;     // 마지막 이의제기 사유의 keccak256 (원문은 DisputeRaised 이벤트에만)
    }

    mapping(bytes32 => Settlement) private settlements;
    mapping(bytes32 => mapping(address => uint256)) private expectedAmount;
    mapping(bytes32 => mapping(address => bool)) private lockedBy;
    mapping(bytes32 => mapping(address => bool)) private refundedBy;

    event TokenCharged(address indexed user, uint256 amount);
    event SettlementOpened(bytes32 indexed settlementId, uint256 participantCount, uint256 totalExpected, bytes32 conditionsHash);
    event SettlementLocked(bytes32 indexed settlementId, address indexed participant, uint256 amount);
    event SettlementConfirmed(bytes32 indexed settlementId, uint256 totalLocked, uint64 holdUntil); // 전원 잠금 완료 → 인증서 TxHash
    event DisputeRaised(bytes32 indexed settlementId, bytes32 reasonHash, string reason);
    event DisputeResolved(bytes32 indexed settlementId, uint8 verdict);
    event SettlementCancelled(bytes32 indexed settlementId);
    event Refunded(bytes32 indexed settlementId, address indexed participant, uint256 amount);
    event SettlementReleased(bytes32 indexed settlementId, address indexed recipient, uint256 amount);

    error InsufficientBalance(address participant, uint256 balance, uint256 required);
    error SettlementAlreadyOpened(bytes32 settlementId);
    error SettlementNotOpened(bytes32 settlementId);
    error InvalidStatus(Status status);          // 현재 상태에서 허용되지 않는 동작
    error HoldNotElapsed(uint64 holdUntil);      // 보류 기간이 아직 지나지 않음
    error InvalidVerdict(uint8 verdict);         // 판정 코드는 0·1·2 뿐
    error NotLockedParticipant(address participant);
    error AlreadyRefunded(address participant);
    error InvalidParticipants();
    error UnexpectedAmount(address participant, uint256 expected, uint256 given);
    error AlreadyLocked(address participant);
    error ZeroAddress();
    error MissingConditionsHash(); // 조건 해시 없이는 정산을 열 수 없다 (실수 방지)

    constructor() Ownable(msg.sender) {
        pieCoin = new PieCoin(address(this));
    }

    // ── ★ charge_token(user_address, amount) ────────────────────────────────
    function charge_token(address user, uint256 amount) external onlyOwner {
        if (user == address(0)) revert ZeroAddress();
        pieCoin.mint(user, amount);
        emit TokenCharged(user, amount);
    }

    // ── 정산 등록 (lock/release 조건 검증용, 팀 합의로 추가) ───────────────────
    // conditionsHash: 백엔드가 승인 시점의 정산 조건 JSON을 정규화해 keccak256한 값 (backend/src/blockchain/conditionsHash.js).
    //   제출 로그의 조건 원문을 누구나 다시 해시해 이 값과 대조할 수 있다 → "금액이 어떤 조건에서 나왔는지"를 체인이 고정.
    // holdSeconds: 전원 잠금 후 지급까지의 보류 기간. 0 허용(테스트·데모 편의).
    function open_settlement(bytes32 settlementId, address[] calldata participants, uint256[] calldata amounts, bytes32 conditionsHash, uint64 holdSeconds) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status != Status.None) revert SettlementAlreadyOpened(settlementId);
        if (conditionsHash == bytes32(0)) revert MissingConditionsHash();
        if (participants.length == 0 || participants.length != amounts.length) revert InvalidParticipants();

        uint256 total;
        for (uint256 i = 0; i < participants.length; i++) {
            address p = participants[i];
            if (p == address(0)) revert ZeroAddress();
            if (amounts[i] == 0 || expectedAmount[settlementId][p] != 0) revert InvalidParticipants(); // 0원·중복 금지
            expectedAmount[settlementId][p] = amounts[i];
            total += amounts[i];
        }
        s.status = Status.Opened;
        s.participantCount = participants.length;
        s.totalExpected = total;
        s.conditionsHash = conditionsHash;
        s.holdSeconds = holdSeconds;
        emit SettlementOpened(settlementId, participants.length, total, conditionsHash);
    }

    // ── ★ lock_for_settlement(settlement_id, participant, amount) ────────────
    function lock_for_settlement(bytes32 settlementId, address participant, uint256 amount) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status == Status.None) revert SettlementNotOpened(settlementId);
        if (s.status != Status.Opened) revert InvalidStatus(s.status);
        uint256 expected = expectedAmount[settlementId][participant];
        if (expected == 0 || expected != amount) revert UnexpectedAmount(participant, expected, amount);
        if (lockedBy[settlementId][participant]) revert AlreadyLocked(participant);

        // 잔액 부족이면 잠금 자체를 거부 — 이 참여자의 토큰은 전혀 움직이지 않는다
        uint256 balance = pieCoin.balanceOf(participant);
        if (balance < amount) revert InsufficientBalance(participant, balance, amount);

        lockedBy[settlementId][participant] = true;
        s.lockedCount += 1;
        s.totalLocked += amount;
        pieCoin.settlementTransfer(participant, address(this), amount);
        emit SettlementLocked(settlementId, participant, amount);

        // 전원 잠금 완료 → 보류 시작 (이 트랜잭션이 인증서의 TxHash)
        if (s.lockedCount == s.participantCount) {
            s.status = Status.Locked;
            s.holdUntil = uint64(block.timestamp) + s.holdSeconds;
            emit SettlementConfirmed(settlementId, s.totalLocked, s.holdUntil);
        }
    }

    // ── raise_dispute(settlement_id, reason) — Dispute 모듈 ─────────────────
    function raise_dispute(bytes32 settlementId, string calldata reason) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status == Status.None) revert SettlementNotOpened(settlementId);
        if (s.status != Status.Locked) revert InvalidStatus(s.status);
        s.status = Status.Disputed;
        s.disputed = true;
        s.reasonHash = keccak256(bytes(reason));
        emit DisputeRaised(settlementId, s.reasonHash, reason);
    }

    // ── resolve_dispute(settlement_id, verdict) — Dispute 모듈 ──────────────
    // 0·2 → Locked 로 복귀(holdUntil 그대로), 1(GENUINE_ERROR) → Cancelled (이후 refund_participant 로 환불)
    function resolve_dispute(bytes32 settlementId, uint8 verdict) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status == Status.None) revert SettlementNotOpened(settlementId);
        if (s.status != Status.Disputed) revert InvalidStatus(s.status);
        if (verdict > VERDICT_BAD_FAITH_DISPUTE) revert InvalidVerdict(verdict);
        s.verdict = verdict;
        if (verdict == VERDICT_GENUINE_ERROR) {
            s.status = Status.Cancelled;
            emit DisputeResolved(settlementId, verdict);
            emit SettlementCancelled(settlementId);
        } else {
            s.status = Status.Locked;
            emit DisputeResolved(settlementId, verdict);
        }
    }

    // ── refund_participant(settlement_id, participant) — Dispute 모듈 ───────
    function refund_participant(bytes32 settlementId, address participant) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status == Status.None) revert SettlementNotOpened(settlementId);
        if (s.status != Status.Cancelled) revert InvalidStatus(s.status);
        if (!lockedBy[settlementId][participant]) revert NotLockedParticipant(participant);
        if (refundedBy[settlementId][participant]) revert AlreadyRefunded(participant);
        uint256 amount = expectedAmount[settlementId][participant];
        refundedBy[settlementId][participant] = true;
        bool ok = pieCoin.transfer(participant, amount);
        require(ok, "PIE refund failed");
        emit Refunded(settlementId, participant, amount);
    }

    // ── ★ release_to_recipient(settlement_id, recipient) ────────────────────
    // Locked 이고 보류 기간이 지난 뒤에만. Disputed(동결)·Cancelled·Released 면 거부
    function release_to_recipient(bytes32 settlementId, address recipient) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.status == Status.None) revert SettlementNotOpened(settlementId);
        if (s.status != Status.Locked) revert InvalidStatus(s.status);
        if (block.timestamp < s.holdUntil) revert HoldNotElapsed(s.holdUntil);
        if (recipient == address(0)) revert ZeroAddress();

        s.status = Status.Released;
        s.recipient = recipient;
        uint256 amount = s.totalLocked;
        bool ok = pieCoin.transfer(recipient, amount);
        require(ok, "PIE transfer failed");
        emit SettlementReleased(settlementId, recipient, amount);
    }

    // ── 조회용 ────────────────────────────────────────────────────────────
    function getSettlement(bytes32 settlementId) external view returns (Settlement memory) {
        return settlements[settlementId];
    }

    function statusOf(bytes32 settlementId) external view returns (Status) {
        return settlements[settlementId].status;
    }

    function holdUntilOf(bytes32 settlementId) external view returns (uint64) {
        return settlements[settlementId].holdUntil;
    }

    function expectedOf(bytes32 settlementId, address participant) external view returns (uint256) {
        return expectedAmount[settlementId][participant];
    }

    function isLocked(bytes32 settlementId, address participant) external view returns (bool) {
        return lockedBy[settlementId][participant];
    }

    function isRefunded(bytes32 settlementId, address participant) external view returns (bool) {
        return refundedBy[settlementId][participant];
    }

    /// @notice 제3자 검증용: 등록된 조건 해시 (열리지 않은 정산이면 0)
    function conditionsHashOf(bytes32 settlementId) external view returns (bytes32) {
        return settlements[settlementId].conditionsHash;
    }
}
