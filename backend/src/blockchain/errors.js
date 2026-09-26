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
  constructor(message, code = 'BLOCKCHAIN_ERROR', status = 502) {
    super(message);
    this.name = 'BlockchainError';
    this.code = code;
    this.status = status;
  }
}

module.exports = { ESCROW_RECIPIENT, InsufficientBalanceError, BlockchainError };
