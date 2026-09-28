// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IERC20Minimal {
    function balanceOf(address owner) external view returns (uint256);
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
}

/// @title ShareLedger — Share Pie 정산 에스크로 + 자금추적 + 이의제기 장부 (테스트넷 전용)
/// @notice 흐름
///  1) createSettlement      : AI 에이전트 지갑이 코드로 검증된 분담표 등록
///  2) lockForSettlement     : 참여자가 MetaMask로 직접 자기 몫 예치 (잔액 부족이면 거부)
///     markOfflinePayment    : 현금으로 낸 참여자를 결제자 확인 후 에이전트가 기록
///  3) 전원 예치 → Locked    : 이의제기 가능 시간(disputeWindow) 동안 에스크로 보관
///  4) releaseToRecipient    : 이의제기 없이 시간이 지나면 누구나 호출 → 결제자에게 지급
///  5) raiseDispute → (refundParticipant) → resolveDispute : AI Dispute Agent 판정 실행
///  *) blockSettlement       : 지출 통제 위반 시 결제 없이 중단 기록 + 예치금 환불
/// @dev CLAUDE.md 5번 함수: charge_token(PieToken) / lock_for_settlement / release_to_recipient /
///      refund_participant / raise_dispute / resolve_dispute / mark_offline_payment
contract ShareLedger {
    enum Status { None, Open, Locked, Paid, Blocked, Disputed, Refunded }
    // 1 NORMAL_APPROVAL(정산 유지) · 2 GENUINE_ERROR(착오 → 환불) · 3 BAD_FAITH_DISPUTE(기각)
    uint8 public constant NORMAL_APPROVAL = 1;
    uint8 public constant GENUINE_ERROR = 2;
    uint8 public constant BAD_FAITH_DISPUTE = 3;

    // 참여자 상태: 0 대기 · 1 예치 · 2 현금(오프라인) · 3 환불됨 · 4 결제자 본인
    uint8 constant M_WAIT = 0;
    uint8 constant M_LOCKED = 1;
    uint8 constant M_OFFLINE = 2;
    uint8 constant M_REFUNDED = 3;
    uint8 constant M_PAYEE = 4;
    uint8 constant M_APPROVED = 5;   // 구매 대행: 결제 승인(인출 허락)만 하고 아직 돈은 안 빠져나간 상태

    struct Settlement {
        address token;
        address payee;          // 실제 결제(주문)한 사람 = 정산금 수령인
        uint256 total;
        uint256 collected;      // 확보된 금액 (결제자 본인 몫 + 예치 + 현금)
        uint256 escrowed;       // 지금 컨트랙트에 보관 중인 토큰
        bytes32 conditionHash;  // 자연어 분담 조건 원문의 keccak256
        Status status;
        uint64 createdAt;
        uint64 lockedAt;        // 전원 확보 시각 → 이의제기 기간 시작
        string purpose;         // AI가 작성한 송금 목적
    }

    uint256 public constant MAX_MEMBERS = 20;

    address public owner;
    mapping(address => bool) public isAgent;
    uint256 public disputeWindow = 3 minutes;

    mapping(bytes32 => Settlement) private _settlements;
    mapping(bytes32 => uint256) public releaseAfterOf;   // 잠금 시점에 확정한 지급 가능 시각 (이후 disputeWindow 변경에 영향 없음)
    // ── AI 구매 대행 (가상 결제 계좌) ──
    // 정산 건마다 이 컨트랙트 안에 가상 결제 계좌가 생긴다(payee = 가맹점 지갑).
    // 참여자 전원이 approvePurchase로 '내 몫 인출'을 승인하면, 에이전트가 executePurchase 한 번으로
    // 각자 지갑에서 정확히 자기 몫만 가상 계좌로 인출(transferFrom)하고 곧바로 가맹점에 결제한다 (한 트랜잭션 · 전부 성공 or 전부 취소).
    mapping(bytes32 => bool) public isPurchase;
    mapping(bytes32 => bytes32) public orderRefOf;
    mapping(bytes32 => uint256) public approvedCount;
    mapping(bytes32 => address[]) private _members;
    mapping(bytes32 => mapping(address => uint256)) public shareOf;
    mapping(bytes32 => mapping(address => uint8)) public memberState;

    // ── 사용자별 자금추적 ──
    mapping(address => uint256) public committedOf; // 진행 중 정산에 배정된 금액 (사용 예정)
    mapping(address => uint256) public escrowOf;    // 그중 에스크로에 예치된 금액
    mapping(address => uint256) public spentOf;     // 결제자에게 지급 완료된 금액 (실사용)

    event AgentSet(address indexed agent, bool enabled);
    event DisputeWindowSet(uint256 seconds_);
    event SettlementCreated(bytes32 indexed id, address indexed token, address indexed payee, uint256 total, bytes32 conditionHash, string purpose);
    event ShareAssigned(bytes32 indexed id, address indexed member, uint256 amount);
    event Locked(bytes32 indexed id, address indexed member, uint256 amount);
    event OfflinePaid(bytes32 indexed id, address indexed member, uint256 amount, address indexed confirmer);
    event FullyLocked(bytes32 indexed id, uint256 total, uint256 releaseAfter);
    event Paid(bytes32 indexed id, address indexed from, address indexed to, uint256 amount, string purpose);
    event Blocked(bytes32 indexed id, address indexed member, uint8 reasonCode, string note);
    event Refunded(bytes32 indexed id, address indexed member, uint256 amount);
    event DisputeRaised(bytes32 indexed id, address indexed by, string reason);
    event DisputeResolved(bytes32 indexed id, uint8 verdict, string note);
    event PurchaseApproved(bytes32 indexed id, address indexed member, uint256 amount);
    event Withdrawn(bytes32 indexed id, address indexed member, uint256 amount);   // AI가 지갑 → 가상 결제 계좌로 인출
    event PurchaseExecuted(bytes32 indexed id, address indexed merchant, uint256 total, bytes32 orderRef);

    modifier onlyOwner() {
        require(msg.sender == owner, "Ledger: not owner");
        _;
    }

    modifier onlyAgent() {
        require(isAgent[msg.sender], "Ledger: not agent");
        _;
    }

    constructor() {
        owner = msg.sender;
        isAgent[msg.sender] = true;
        emit AgentSet(msg.sender, true);
    }

    function setAgent(address agent, bool enabled) external onlyOwner {
        isAgent[agent] = enabled;
        emit AgentSet(agent, enabled);
    }

    function setDisputeWindow(uint256 seconds_) external onlyOwner {
        disputeWindow = seconds_;
        emit DisputeWindowSet(seconds_);
    }

    // ───────────── 1) 등록 ─────────────
    function createSettlement(
        bytes32 id,
        address token,
        address payee,
        address[] calldata members,
        uint256[] calldata shares,
        bytes32 conditionHash,
        string calldata purpose
    ) external onlyAgent {
        _create(id, token, payee, members, shares, conditionHash, purpose);
    }

    /// @notice AI 구매 대행용 등록: payee = 가맹점 지갑. 전원 approvePurchase → 에이전트 executePurchase(자동 인출·결제)
    function createPurchase(
        bytes32 id,
        address token,
        address merchant,
        address[] calldata members,
        uint256[] calldata shares,
        bytes32 conditionHash,
        string calldata purpose
    ) external onlyAgent {
        for (uint256 i = 0; i < members.length; i++) require(members[i] != merchant, "Ledger: merchant is member");
        isPurchase[id] = true;
        _create(id, token, merchant, members, shares, conditionHash, purpose);
    }

    function _create(
        bytes32 id,
        address token,
        address payee,
        address[] calldata members,
        uint256[] calldata shares,
        bytes32 conditionHash,
        string calldata purpose
    ) internal {
        require(_settlements[id].status == Status.None, "Ledger: id used");
        require(token != address(0) && payee != address(0), "Ledger: zero address");
        require(members.length == shares.length, "Ledger: length mismatch");
        require(members.length > 0 && members.length <= MAX_MEMBERS, "Ledger: bad member count");

        Settlement storage s = _settlements[id];
        s.token = token;
        s.payee = payee;
        s.conditionHash = conditionHash;
        s.status = Status.Open;
        s.createdAt = uint64(block.timestamp);
        s.purpose = purpose;

        _assign(id, members, shares);
        _emitCreated(id);

        if (s.collected == s.total) _fullyLocked(id);
    }

    function _assign(bytes32 id, address[] calldata members, uint256[] calldata shares) internal {
        Settlement storage s = _settlements[id];
        address payee = s.payee;
        for (uint256 i = 0; i < members.length; i++) {
            address m = members[i];
            uint256 amt = shares[i];
            require(m != address(0), "Ledger: zero member");
            require(amt > 0, "Ledger: zero share");
            require(shareOf[id][m] == 0, "Ledger: duplicate member");

            shareOf[id][m] = amt;
            _members[id].push(m);
            committedOf[m] += amt;
            s.total += amt;
            if (m == payee) {
                memberState[id][m] = M_PAYEE; // 결제자 본인 몫은 이미 가맹점에 지불
                s.collected += amt;
            }
            emit ShareAssigned(id, m, amt);
        }
    }

    function _emitCreated(bytes32 id) internal {
        Settlement storage s = _settlements[id];
        emit SettlementCreated(id, s.token, s.payee, s.total, s.conditionHash, s.purpose);
    }

    // ───────────── 2) 예치 · 현금 기록 ─────────────
    /// @notice lock_for_settlement — 참여자가 MetaMask로 직접 호출 (사전에 token.approve 필요)
    ///         잔액이 부족하면 거부 → 일부만 잠기는 상태를 만들지 않는다
    function lockForSettlement(bytes32 id) external {
        Settlement storage s = _settlements[id];
        require(!isPurchase[id], "Ledger: use approvePurchase");
        require(s.status == Status.Open, "Ledger: not open");
        uint256 amt = shareOf[id][msg.sender];
        require(amt > 0, "Ledger: not a member");
        require(memberState[id][msg.sender] == M_WAIT, "Ledger: already locked");
        require(IERC20Minimal(s.token).balanceOf(msg.sender) >= amt, "Ledger: insufficient PIE balance");

        memberState[id][msg.sender] = M_LOCKED;
        escrowOf[msg.sender] += amt;
        s.collected += amt;
        s.escrowed += amt;
        require(IERC20Minimal(s.token).transferFrom(msg.sender, address(this), amt), "Ledger: transferFrom failed");
        emit Locked(id, msg.sender, amt);

        if (s.collected == s.total) _fullyLocked(id);
    }

    /// @notice mark_offline_payment — 현금으로 낸 참여자를 결제자 확인 후 에이전트가 기록
    function markOfflinePayment(bytes32 id, address participant) external onlyAgent {
        Settlement storage s = _settlements[id];
        require(!isPurchase[id], "Ledger: purchase needs escrow");
        require(s.status == Status.Open, "Ledger: not open");
        uint256 amt = shareOf[id][participant];
        require(amt > 0, "Ledger: not a member");
        require(memberState[id][participant] == M_WAIT, "Ledger: already paid");

        memberState[id][participant] = M_OFFLINE;
        s.collected += amt;
        emit OfflinePaid(id, participant, amt, s.payee);

        if (s.collected == s.total) _fullyLocked(id);
    }

    function _fullyLocked(bytes32 id) internal {
        Settlement storage s = _settlements[id];
        s.status = Status.Locked;
        s.lockedAt = uint64(block.timestamp);
        releaseAfterOf[id] = block.timestamp + disputeWindow;
        emit FullyLocked(id, s.total, releaseAfterOf[id]);
        if (disputeWindow == 0 && !isPurchase[id]) _release(id);
    }

    // ───────────── 4) 지급 ─────────────
    /// @notice release_to_recipient — 이의제기 기간이 지나면 누구나 호출 가능
    function releaseToRecipient(bytes32 id) external {
        Settlement storage s = _settlements[id];
        require(s.status == Status.Locked, "Ledger: not locked");
        require(!isPurchase[id], "Ledger: purchase needs agent");
        require(block.timestamp >= releaseAfterOf[id], "Ledger: dispute window open");
        _release(id);
    }

    /// @notice 참여자가 자기 지갑에서 '내 몫 인출'을 승인 (MetaMask 서명). 돈은 아직 움직이지 않는다.
    /// 먼저 PIE.approve(ledger, 내 몫)으로 인출 한도를 줘야 하며, 잔액·한도가 모자라면 거부된다.
    function approvePurchase(bytes32 id) external {
        Settlement storage s = _settlements[id];
        require(isPurchase[id], "Ledger: not purchase");
        require(s.status == Status.Open, "Ledger: not open");
        uint256 amt = shareOf[id][msg.sender];
        require(amt > 0, "Ledger: not a member");
        require(memberState[id][msg.sender] == M_WAIT, "Ledger: already approved");
        require(IERC20Minimal(s.token).balanceOf(msg.sender) >= amt, "Ledger: insufficient PIE balance");
        require(IERC20Minimal(s.token).allowance(msg.sender, address(this)) >= amt, "Ledger: allowance too low");
        memberState[id][msg.sender] = M_APPROVED;
        approvedCount[id] += 1;
        emit PurchaseApproved(id, msg.sender, amt);
    }

    /// @notice 전원 승인 후 에이전트(AI)가 호출: 각자 지갑에서 자기 몫만 가상 계좌로 인출 → 가맹점에 결제.
    /// 한 명이라도 인출이 실패하면 트랜잭션 전체가 취소돼 일부만 빠져나가는 일이 없다.
    function executePurchase(bytes32 id, bytes32 orderRef) external onlyAgent {
        Settlement storage s = _settlements[id];
        require(isPurchase[id], "Ledger: not purchase");
        require(s.status == Status.Open, "Ledger: not open");
        address[] storage ms = _members[id];
        require(approvedCount[id] == ms.length, "Ledger: not all approved");
        s.status = Status.Paid;   // 외부 호출 전 상태 변경 (재진입 방지)
        orderRefOf[id] = orderRef;
        IERC20Minimal t = IERC20Minimal(s.token);
        for (uint256 i = 0; i < ms.length; i++) {
            address m = ms[i];
            uint256 amt = shareOf[id][m];
            memberState[id][m] = M_LOCKED;
            committedOf[m] -= amt;
            spentOf[m] += amt;
            require(t.transferFrom(m, address(this), amt), "Ledger: withdraw failed");
            emit Withdrawn(id, m, amt);
            emit Paid(id, m, s.payee, amt, s.purpose);
        }
        s.collected = s.total;
        require(t.transfer(s.payee, s.total), "Ledger: merchant payment failed");
        emit PurchaseExecuted(id, s.payee, s.total, orderRef);
    }

    function _release(bytes32 id) internal {
        Settlement storage s = _settlements[id];
        s.status = Status.Paid;
        address[] storage ms = _members[id];
        for (uint256 i = 0; i < ms.length; i++) {
            address m = ms[i];
            uint8 st = memberState[id][m];
            if (st == M_REFUNDED) continue;
            uint256 amt = shareOf[id][m];
            committedOf[m] -= amt;
            spentOf[m] += amt;
            if (st == M_LOCKED) escrowOf[m] -= amt;
            emit Paid(id, m, s.payee, amt, s.purpose);
        }
        uint256 payout = s.escrowed;
        s.escrowed = 0;
        if (payout > 0) {
            require(IERC20Minimal(s.token).transfer(s.payee, payout), "Ledger: payout failed");
        }
    }

    // ───────────── 5) 이의제기 ─────────────
    /// @notice raise_dispute — 참여자 본인 또는 에이전트(앱에서 대신 접수)
    function raiseDispute(bytes32 id, address by, string calldata reason) external {
        Settlement storage s = _settlements[id];
        require(s.status == Status.Locked, "Ledger: not disputable");
        require(block.timestamp < releaseAfterOf[id], "Ledger: window closed");
        require(shareOf[id][by] > 0, "Ledger: not a member");
        require(msg.sender == by || isAgent[msg.sender], "Ledger: not allowed");
        s.status = Status.Disputed;
        emit DisputeRaised(id, by, reason);
    }

    /// @notice refund_participant — GENUINE_ERROR 판정 시 에이전트가 호출
    function refundParticipant(bytes32 id, address participant) external onlyAgent {
        Settlement storage s = _settlements[id];
        require(s.status == Status.Disputed, "Ledger: not disputed");
        require(memberState[id][participant] == M_LOCKED, "Ledger: nothing to refund");
        uint256 amt = shareOf[id][participant];
        memberState[id][participant] = M_REFUNDED;
        escrowOf[participant] -= amt;
        committedOf[participant] -= amt;
        s.escrowed -= amt;
        require(IERC20Minimal(s.token).transfer(participant, amt), "Ledger: refund failed");
        emit Refunded(id, participant, amt);
    }

    /// @notice resolve_dispute — 1 유지 / 2 착오(환불 후 남은 금액 지급 또는 전액 환불 종료) / 3 기각
    function resolveDispute(bytes32 id, uint8 verdict, string calldata note) external onlyAgent {
        Settlement storage s = _settlements[id];
        require(s.status == Status.Disputed, "Ledger: not disputed");
        require(verdict >= NORMAL_APPROVAL && verdict <= BAD_FAITH_DISPUTE, "Ledger: bad verdict");
        emit DisputeResolved(id, verdict, note);
        if (verdict == GENUINE_ERROR && _allOthersRefunded(id)) {
            _closeRefunded(id); // 공동구매 취소 등 → 전원 환불로 종료
        } else {
            _release(id);       // 유지·기각, 또는 일부 환불 후 나머지 지급
        }
    }

    function _allOthersRefunded(bytes32 id) internal view returns (bool) {
        address[] storage ms = _members[id];
        for (uint256 i = 0; i < ms.length; i++) {
            uint8 st = memberState[id][ms[i]];
            if (st == M_LOCKED || st == M_OFFLINE) return false;
        }
        return true;
    }

    function _closeRefunded(bytes32 id) internal {
        Settlement storage s = _settlements[id];
        s.status = Status.Refunded;
        address[] storage ms = _members[id];
        for (uint256 i = 0; i < ms.length; i++) {
            address m = ms[i];
            if (memberState[id][m] == M_PAYEE) committedOf[m] -= shareOf[id][m];
        }
    }

    // ───────────── *) 지출 통제 중단 ─────────────
    /// reasonCode: 1 합계 불일치, 2 1인 예산 초과, 3 잔액 부족, 4 비허용 가맹점, 5 총예산 초과, 9 기타
    function blockSettlement(bytes32 id, address member, uint8 reasonCode, string calldata note) external onlyAgent {
        Settlement storage s = _settlements[id];
        require(s.status == Status.None || s.status == Status.Open, "Ledger: already closed");
        bool wasOpen = s.status == Status.Open;
        s.status = Status.Blocked;   // 외부 호출(토큰 전송) 전에 상태부터 바꿈 (재진입 방지)

        if (wasOpen) {
            address[] storage ms = _members[id];
            for (uint256 i = 0; i < ms.length; i++) {
                address m = ms[i];
                uint256 amt = shareOf[id][m];
                committedOf[m] -= amt;
                if (memberState[id][m] == M_APPROVED) memberState[id][m] = M_WAIT;   // 구매 승인 무효 (인출된 돈 없음)
                if (memberState[id][m] == M_LOCKED) {
                    memberState[id][m] = M_REFUNDED;
                    escrowOf[m] -= amt;
                    s.escrowed -= amt;
                    require(IERC20Minimal(s.token).transfer(m, amt), "Ledger: refund failed");
                    emit Refunded(id, m, amt);
                }
            }
        } else {
            s.createdAt = uint64(block.timestamp);
        }
        emit Blocked(id, member, reasonCode, note);
    }

    // ───────────── 조회 ─────────────
    function getSettlement(bytes32 id) external view returns (
        address token, address payee, uint256 total, uint256 collected, uint256 escrowed,
        bytes32 conditionHash, uint8 status, uint64 lockedAt, string memory purpose
    ) {
        Settlement storage s = _settlements[id];
        token = s.token;
        payee = s.payee;
        total = s.total;
        collected = s.collected;
        escrowed = s.escrowed;
        conditionHash = s.conditionHash;
        status = uint8(s.status);
        lockedAt = s.lockedAt;
        purpose = s.purpose;
    }

    function releaseAt(bytes32 id) external view returns (uint256) {
        Settlement storage s = _settlements[id];
        return s.lockedAt == 0 ? 0 : releaseAfterOf[id];
    }

    function getMembers(bytes32 id) external view returns (address[] memory members, uint256[] memory shares, uint8[] memory states) {
        address[] storage ms = _members[id];
        members = new address[](ms.length);
        shares = new uint256[](ms.length);
        states = new uint8[](ms.length);
        for (uint256 i = 0; i < ms.length; i++) {
            members[i] = ms[i];
            shares[i] = shareOf[id][ms[i]];
            states[i] = memberState[id][ms[i]];
        }
    }
}
