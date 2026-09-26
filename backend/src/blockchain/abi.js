'use strict';

// contracts/contracts/SharePieSettlement.sol · PieCoin.sol 의 호출용 ABI (사람이 읽을 수 있는 형식)
// 컨트랙트 함수 시그니처를 바꾸면 여기도 같이 바꿔야 한다.

const SETTLEMENT_ABI = [
  'function owner() view returns (address)',
  'function pieCoin() view returns (address)',
  'function charge_token(address user, uint256 amount)',
  'function open_settlement(bytes32 settlementId, address[] participants, uint256[] amounts)',
  'function lock_for_settlement(bytes32 settlementId, address participant, uint256 amount)',
  'function release_to_recipient(bytes32 settlementId, address recipient)',
  'function getSettlement(bytes32 settlementId) view returns (tuple(bool opened, bool released, uint256 participantCount, uint256 lockedCount, uint256 totalExpected, uint256 totalLocked, address recipient))',
  'function isLocked(bytes32 settlementId, address participant) view returns (bool)',
  'error InsufficientBalance(address participant, uint256 balance, uint256 required)',
  'error SettlementAlreadyOpened(bytes32 settlementId)',
  'error SettlementNotOpened(bytes32 settlementId)',
  'error SettlementAlreadyReleased(bytes32 settlementId)',
  'error InvalidParticipants()',
  'error UnexpectedAmount(address participant, uint256 expected, uint256 given)',
  'error AlreadyLocked(address participant)',
  'error NotAllLocked(uint256 locked, uint256 required)',
  'error ZeroAddress()',
  'error OwnableUnauthorizedAccount(address account)',
];

const PIECOIN_ABI = [
  'function balanceOf(address account) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
];

module.exports = { SETTLEMENT_ABI, PIECOIN_ABI };
