'use strict';

// ============================================================================
// ⚠️ MOCK — 블록체인 담당 팀원의 실제 컨트랙트/SDK로 교체할 파일
// ============================================================================
// 백엔드의 다른 코드는 이 파일의 함수만 호출한다. 실제 SDK가 준비되면
// 아래 함수들의 "내부"만 바꾸고, 함수 이름·반환 모양은 유지하면 된다.
//
// 함수 이름은 CLAUDE.md 5번 컨트랙트 시그니처를 camelCase로 옮긴 것:
//   lock_for_settlement(settlement_id, participant, amount) → lockForSettlement
//   release_to_recipient(settlement_id, recipient)          → releaseToRecipient
//
// 반환 모양(임시 확정):  { txHash: '0x…', block: '#18,204,331', mock: true }
//
// TODO(블록체인 연동):
//   1) 실제 SDK import 및 RPC/지갑 설정 (BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS)
//   2) lockForSettlement: 잔액 부족 시 컨트랙트가 거부 → 여기서 InsufficientBalanceError로 변환
//   3) 실제 트랜잭션 영수증에서 txHash / blockNumber 읽기
//   4) mock: true 제거
// ============================================================================

const crypto = require('crypto');

class InsufficientBalanceError extends Error {
  constructor(participant, amount) {
    super(`${participant}님의 PieCoin 잔액이 ${amount}보다 적어 잠금이 거부됐어요.`);
    this.name = 'InsufficientBalanceError';
    this.code = 'INSUFFICIENT_BALANCE';
    this.status = 409;
  }
}

// Pie(AI 정산 에이전트)가 분담금을 모아 두는 에스크로 — 멤버 중 먼저 결제한 사람(payer)이 없을 때의 수령처.
// 전원 분담금을 여기로 잠갔다가, 전원 승인 시 결제처로 지급(release)한다.
// TODO(블록체인 연동): 실제로는 정산 컨트랙트 주소 (CONTRACT_ADDRESS)
const ESCROW_RECIPIENT = 'SharePie 정산 에스크로';

let mockBlock = 18_300_000;

function mockTx(payload) {
  mockBlock += 1;
  const txHash = '0x' + crypto.createHash('sha256').update(JSON.stringify(payload) + Date.now() + Math.random()).digest('hex');
  return { txHash, block: '#' + mockBlock.toLocaleString('en-US'), mock: true };
}

// MOCK: 승인 시 참여자 분담금 잠금
async function lockForSettlement({ settlementId, participant, amount }) {
  // TODO(블록체인 연동): 실제 컨트랙트 호출. 잔액 부족이면 throw new InsufficientBalanceError(participant, amount)
  return mockTx({ fn: 'lock_for_settlement', settlementId, participant, amount });
}

// MOCK: 전원 승인 완료 시 잠긴 금액 지급 (recipient = 먼저 결제한 멤버, 또는 ESCROW_RECIPIENT → 결제처)
async function releaseToRecipient({ settlementId, recipient }) {
  // TODO(블록체인 연동): 실제 컨트랙트 호출
  return mockTx({ fn: 'release_to_recipient', settlementId, recipient });
}

module.exports = { lockForSettlement, releaseToRecipient, InsufficientBalanceError, ESCROW_RECIPIENT, IS_MOCK: true };
