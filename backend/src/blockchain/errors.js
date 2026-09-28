'use strict';

// MOCK 모드에서도 쓰는 블록체인 공통 값·에러 — ethers에 의존하지 않는다
// (ethers는 실제 체인 모드일 때만 blockchainClient가 불러온다)

// Pie(AI 정산 에이전트)가 분담금을 모아 두는 에스크로 — payer가 없을 때의 수령처 이름
const ESCROW_RECIPIENT = 'SharePie 정산 에스크로';

class InsufficientBalanceError extends Error {
  constructor(participant, amount, balance = null) {
    super(`${participant}님의 PieCoin 잔액${balance === null ? '' : `(${balance} PIE)`}이 분담금 ${amount} PIE보다 적어 잠금이 거부됐어요.`);
    this.name = 'InsufficientBalanceError';
    this.code = 'INSUFFICIENT_BALANCE';
    this.status = 409;
    this.participant = participant;
  }
}

class BlockchainError extends Error {
  constructor(message, code = 'BLOCKCHAIN_ERROR', status = 502, details = null) {
    super(message);
    this.name = 'BlockchainError';
    this.code = code;
    this.status = status;
    if (details) Object.assign(this, details); // 예: { holdUntil }, { state }
  }
}

// 보류 기간(초) — 팀 결정 전이라 상수로 박지 않고 env SETTLEMENT_HOLD_SECONDS (기본 600)
const DEFAULT_HOLD_SECONDS = 600;
function holdSecondsFromEnv() {
  const raw = process.env.SETTLEMENT_HOLD_SECONDS;
  if (raw === undefined || raw === '') return DEFAULT_HOLD_SECONDS;
  const n = Number(raw);
  if (!Number.isSafeInteger(n) || n < 0) throw new BlockchainError(`SETTLEMENT_HOLD_SECONDS는 0 이상의 정수여야 해요 (받은 값: ${raw}).`, 'BLOCKCHAIN_NOT_CONFIGURED', 503);
  return n;
}

// 판정 코드 (CLAUDE.md 7번 — 3개뿐). 컨트랙트·백엔드·문서에서 동일: 0/1/2
const VERDICT_NAMES = ['NORMAL_APPROVAL', 'GENUINE_ERROR', 'BAD_FAITH_DISPUTE'];
function verdictCodeOf(verdict) {
  const code = VERDICT_NAMES.indexOf(verdict);
  if (code === -1) throw new BlockchainError(`verdict는 ${VERDICT_NAMES.join(' / ')} 중 하나여야 해요 (받은 값: ${JSON.stringify(verdict)}).`, 'INVALID_VERDICT', 400);
  return code;
}

// 멤버 식별자(uid) 형식 — UI가 붙이는 'u0', 'u1' 같은 고정 번호. 표시 이름('진주')은 동명이인이 있어 지갑 키로 쓰면 안 된다.
// 한글·공백이 들어오면 즉시 실패시켜 "이름으로 지갑을 만드는 실수"를 막는다. (MOCK 모드에서도 같은 검사를 쓴다)
const UID_PATTERN = /^[A-Za-z0-9._@-]{1,64}$/;

function assertUid(uid) {
  if (typeof uid !== 'string' || !UID_PATTERN.test(uid)) {
    throw new BlockchainError(`멤버 식별자는 uid여야 해요 (받은 값: ${JSON.stringify(uid)}). 표시 이름이 아니라 UI의 uid를 넘겨 주세요.`, 'INVALID_MEMBER_UID', 400);
  }
  return uid;
}

module.exports = { ESCROW_RECIPIENT, InsufficientBalanceError, BlockchainError, UID_PATTERN, assertUid, DEFAULT_HOLD_SECONDS, holdSecondsFromEnv, VERDICT_NAMES, verdictCodeOf };
