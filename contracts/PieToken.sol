// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title PieToken (PIE, PieCoin) — Share Pie 테스트넷 전용 토큰. 실제 화폐 가치 없음.
/// @notice 1 PIE = 1원 표기용. decimals = 0 이라서 금액 변환이 필요 없습니다.
/// @dev charge_token: 에이전트(minter)가 사용자에게 발급 → 사용자는 가스비 없이 충전
///      claim: 사용자가 직접 1시간마다 100,000 PIE (에이전트가 없을 때 대비)
contract PieToken {
    string public constant name = "PieCoin (Share Pie Testnet)";
    string public constant symbol = "PIE";
    uint8 public constant decimals = 0;

    uint256 public constant FAUCET_AMOUNT = 100000;
    uint256 public constant FAUCET_COOLDOWN = 1 hours;
    uint256 public constant MAX_CHARGE = 1000000;

    address public owner;
    mapping(address => bool) public isMinter;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(address => uint256) public lastClaimAt;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
    event Charged(address indexed to, uint256 amount, address indexed by);

    constructor() {
        owner = msg.sender;
        isMinter[msg.sender] = true;
    }

    function setMinter(address minter, bool enabled) external {
        require(msg.sender == owner, "PIE: not owner");
        isMinter[minter] = enabled;
    }

    /// @notice charge_token(user_address, amount) — 에이전트가 PieCoin 발급
    function chargeToken(address to, uint256 amount) external {
        require(isMinter[msg.sender], "PIE: not minter");
        require(amount > 0 && amount <= MAX_CHARGE, "PIE: bad amount");
        _mint(to, amount, msg.sender);
    }

    /// @notice 사용자가 직접 충전 (1시간 1회)
    function claim() external {
        require(block.timestamp >= lastClaimAt[msg.sender] + FAUCET_COOLDOWN, "PIE: faucet cooldown");
        lastClaimAt[msg.sender] = block.timestamp;
        _mint(msg.sender, FAUCET_AMOUNT, msg.sender);
    }

    function transfer(address to, uint256 value) external returns (bool) {
        _transfer(msg.sender, to, value);
        return true;
    }

    function approve(address spender, uint256 value) external returns (bool) {
        allowance[msg.sender][spender] = value;
        emit Approval(msg.sender, spender, value);
        return true;
    }

    function transferFrom(address from, address to, uint256 value) external returns (bool) {
        uint256 allowed = allowance[from][msg.sender];
        if (allowed != type(uint256).max) {
            require(allowed >= value, "PIE: insufficient allowance");
            allowance[from][msg.sender] = allowed - value;
        }
        _transfer(from, to, value);
        return true;
    }

    function _mint(address to, uint256 amount, address by) internal {
        require(to != address(0), "PIE: mint to zero");
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
        emit Charged(to, amount, by);
    }

    function _transfer(address from, address to, uint256 value) internal {
        require(to != address(0), "PIE: transfer to zero");
        require(balanceOf[from] >= value, "PIE: insufficient balance");
        balanceOf[from] -= value;
        balanceOf[to] += value;
        emit Transfer(from, to, value);
    }
}
