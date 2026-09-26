// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ============================================================================
// PieCoin (PIE) — SharePie 정산용 테스트 토큰
// ⚠️ 테스트넷(Sepolia) 전용. 실화폐 가치가 전혀 없으며, 실제 돈·계좌·메인넷과 연결하지 않는다.
//
// - 1 PIE = 화면 표시상 1원 (decimals = 0, 원 단위 정수 금액을 그대로 사용)
// - 발행(mint)과 정산 이동(settlementTransfer)은 소유자(= SharePieSettlement 컨트랙트)만 할 수 있다.
//   멤버가 approve 서명을 하지 않아도 정산 컨트랙트가 분담금을 잠글 수 있게 하기 위함 (데모용 수탁 구조).
// ============================================================================

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

contract PieCoin is ERC20, Ownable {
    constructor(address settlementContract) ERC20("PieCoin (Testnet Only)", "PIE") Ownable(settlementContract) {}

    /// @dev 원 단위 정수 금액을 그대로 쓰기 위해 소수점 자리 없음
    function decimals() public pure override returns (uint8) {
        return 0;
    }

    /// @notice 테스트용 PieCoin 발행 (정산 컨트랙트의 charge_token에서만 호출)
    function mint(address to, uint256 amount) external onlyOwner {
        _mint(to, amount);
    }

    /// @notice 정산 컨트랙트가 참여자의 분담금을 에스크로로 옮길 때 사용 (approve 불필요)
    /// @dev 잔액이 부족하면 ERC20 표준 에러(ERC20InsufficientBalance)로 전체가 되돌려진다
    function settlementTransfer(address from, address to, uint256 amount) external onlyOwner {
        _transfer(from, to, amount);
    }
}
