'use strict';

// contracts/contracts/SharePieSettlement.sol · PieCoin.sol 의 호출용 ABI (사람이 읽을 수 있는 형식)
// 컨트랙트 함수 시그니처를 바꾸면 여기도 같이 바꿔야 한다.

const SETTLEMENT_ABI = [
  'function owner() view returns (address)',
  'function pieCoin() view returns (address)',
  'function charge_token(address user, uint256 amount)',
  'function open_settlement(bytes32 settlementId, address[] participants, uint256[] amounts, bytes32 conditionsHash, uint64 holdSeconds)',
  'function lock_for_settlement(bytes32 settlementId, address participant, uint256 amount)',
  'function raise_dispute(bytes32 settlementId, string reason)',
  'function resolve_dispute(bytes32 settlementId, uint8 verdict)',
  'function refund_participant(bytes32 settlementId, address participant)',
  'function release_to_recipient(bytes32 settlementId, address recipient)',
  'function getSettlement(bytes32 settlementId) view returns (tuple(uint8 status, uint256 participantCount, uint256 lockedCount, uint256 totalExpected, uint256 totalLocked, address recipient, bytes32 conditionsHash, uint64 holdSeconds, uint64 holdUntil, uint8 verdict, bool disputed, bytes32 reasonHash))',
  'function statusOf(bytes32 settlementId) view returns (uint8)',
  'function holdUntilOf(bytes32 settlementId) view returns (uint64)',
  'function expectedOf(bytes32 settlementId, address participant) view returns (uint256)',
  'function isLocked(bytes32 settlementId, address participant) view returns (bool)',
  'function isRefunded(bytes32 settlementId, address participant) view returns (bool)',
  'function conditionsHashOf(bytes32 settlementId) view returns (bytes32)',
  'event SettlementOpened(bytes32 indexed settlementId, uint256 participantCount, uint256 totalExpected, bytes32 conditionsHash)',
  'event SettlementLocked(bytes32 indexed settlementId, address indexed participant, uint256 amount)',
  'event SettlementConfirmed(bytes32 indexed settlementId, uint256 totalLocked, uint64 holdUntil)',
  'event DisputeRaised(bytes32 indexed settlementId, bytes32 reasonHash, string reason)',
  'event DisputeResolved(bytes32 indexed settlementId, uint8 verdict)',
  'event SettlementCancelled(bytes32 indexed settlementId)',
  'event Refunded(bytes32 indexed settlementId, address indexed participant, uint256 amount)',
  'event SettlementReleased(bytes32 indexed settlementId, address indexed recipient, uint256 amount)',
  'error InsufficientBalance(address participant, uint256 balance, uint256 required)',
  'error SettlementAlreadyOpened(bytes32 settlementId)',
  'error SettlementNotOpened(bytes32 settlementId)',
  'error InvalidStatus(uint8 status)',
  'error HoldNotElapsed(uint64 holdUntil)',
  'error InvalidVerdict(uint8 verdict)',
  'error NotLockedParticipant(address participant)',
  'error AlreadyRefunded(address participant)',
  'error InvalidParticipants()',
  'error UnexpectedAmount(address participant, uint256 expected, uint256 given)',
  'error AlreadyLocked(address participant)',
  'error ZeroAddress()',
  'error MissingConditionsHash()',
  'error OwnableUnauthorizedAccount(address account)',
];

const PIECOIN_ABI = [
  'function balanceOf(address account) view returns (uint256)',
  'function decimals() view returns (uint8)',
  'function symbol() view returns (string)',
];

// 상태·판정 코드 (컨트랙트 enum 순서와 동일) — 백엔드·문서에서 같은 이름을 쓴다
const STATES = ['NONE', 'OPENED', 'LOCKED', 'DISPUTED', 'RELEASED', 'CANCELLED'];
const VERDICT_CODES = { NORMAL_APPROVAL: 0, GENUINE_ERROR: 1, BAD_FAITH_DISPUTE: 2 };
const VERDICT_NAMES = ['NORMAL_APPROVAL', 'GENUINE_ERROR', 'BAD_FAITH_DISPUTE'];

module.exports = { SETTLEMENT_ABI, PIECOIN_ABI, STATES, VERDICT_CODES, VERDICT_NAMES };
