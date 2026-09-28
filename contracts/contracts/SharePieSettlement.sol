// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ============================================================================
// SharePieSettlement — 정산 코어 온체인 기록 (CLAUDE.md 5번 ★ 함수)
// ⚠️ 테스트넷(Sepolia) 전용. PieCoin은 실화폐 가치가 없다. 메인넷에 배포하지 않는다.
//
// 흐름 (서버의 운영자 지갑 = owner 가 모든 트랜잭션에 서명)
//   1) charge_token(user, amount)                       PieCoin 발급(충전)
//   2) open_settlement(id, participants[], amounts[])   정산 등록: 누가 얼마를 잠가야 하는지 기록
//   3) lock_for_settlement(id, participant, amount)     참여자별 분담금을 이 컨트랙트(에스크로)로 잠금
//        - 잔액 < amount 이면 InsufficientBalance 에러로 거부 (그 참여자는 한 푼도 잠기지 않음)
//        - 등록된 금액과 다르면 거부
//   4) release_to_recipient(id, recipient)              전원 잠금이 끝난 경우에만 총액을 한 번에 지급
//
// "일부만 잠긴 채 지급되는" 상황 방지
//   - release는 등록된 참여자 전원이 잠금을 마친 경우에만 실행된다.
//   - 백엔드는 lock을 보내기 전에 전원의 잔액을 먼저 확인하고, 한 명이라도 부족하면 아무 트랜잭션도 보내지 않는다.
//   - (Dispute 모듈) 중간 실패 시 잠긴 금액 반환은 refund_participant로 처리 예정 — 지금 범위 아님
// ============================================================================

import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {PieCoin} from "./PieCoin.sol";

contract SharePieSettlement is Ownable {
    PieCoin public immutable pieCoin;

    struct Settlement {
        bool opened;
        bool released;
        uint256 participantCount;
        uint256 lockedCount;
        uint256 totalExpected;
        uint256 totalLocked;
        address recipient;
        bytes32 conditionsHash; // 승인된 정산 "조건"(방식·총액·감면·예산…)의 keccak256 — 제3자가 조건 원문을 다시 해시해 대조
    }

    mapping(bytes32 => Settlement) private settlements;
    mapping(bytes32 => mapping(address => uint256)) private expectedAmount;
    mapping(bytes32 => mapping(address => bool)) private lockedBy;

    event TokenCharged(address indexed user, uint256 amount);
    event SettlementOpened(bytes32 indexed settlementId, uint256 participantCount, uint256 totalExpected, bytes32 conditionsHash);
    event SettlementLocked(bytes32 indexed settlementId, address indexed participant, uint256 amount);
    event SettlementReleased(bytes32 indexed settlementId, address indexed recipient, uint256 amount);

    error InsufficientBalance(address participant, uint256 balance, uint256 required);
    error SettlementAlreadyOpened(bytes32 settlementId);
    error SettlementNotOpened(bytes32 settlementId);
    error SettlementAlreadyReleased(bytes32 settlementId);
    error InvalidParticipants();
    error UnexpectedAmount(address participant, uint256 expected, uint256 given);
    error AlreadyLocked(address participant);
    error NotAllLocked(uint256 locked, uint256 required);
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
    function open_settlement(bytes32 settlementId, address[] calldata participants, uint256[] calldata amounts, bytes32 conditionsHash) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (s.opened) revert SettlementAlreadyOpened(settlementId);
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
        s.opened = true;
        s.participantCount = participants.length;
        s.totalExpected = total;
        s.conditionsHash = conditionsHash;
        emit SettlementOpened(settlementId, participants.length, total, conditionsHash);
    }

    // ── ★ lock_for_settlement(settlement_id, participant, amount) ────────────
    function lock_for_settlement(bytes32 settlementId, address participant, uint256 amount) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (!s.opened) revert SettlementNotOpened(settlementId);
        if (s.released) revert SettlementAlreadyReleased(settlementId);
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
    }

    // ── ★ release_to_recipient(settlement_id, recipient) ────────────────────
    function release_to_recipient(bytes32 settlementId, address recipient) external onlyOwner {
        Settlement storage s = settlements[settlementId];
        if (!s.opened) revert SettlementNotOpened(settlementId);
        if (s.released) revert SettlementAlreadyReleased(settlementId);
        if (recipient == address(0)) revert ZeroAddress();
        if (s.lockedCount != s.participantCount) revert NotAllLocked(s.lockedCount, s.participantCount);

        s.released = true;
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

    function expectedOf(bytes32 settlementId, address participant) external view returns (uint256) {
        return expectedAmount[settlementId][participant];
    }

    function isLocked(bytes32 settlementId, address participant) external view returns (bool) {
        return lockedBy[settlementId][participant];
    }

    /// @notice 제3자 검증용: 등록된 조건 해시 (열리지 않은 정산이면 0)
    function conditionsHashOf(bytes32 settlementId) external view returns (bytes32) {
        return settlements[settlementId].conditionsHash;
    }
}
