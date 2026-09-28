'use strict';

// 승인 이후의 온체인 행동 (코드 전용 — AI 호출 없음)
//   releaseSettlement : 보류가 끝난 정산을 결제처(또는 payer)에게 지급        → /settlement/release
//   raiseDispute      : 이의제기 접수 → 체인 동결(Disputed)                  → /dispute/raise
//   resolveDispute    : 판정 실행. GENUINE_ERROR 면 참여자 전원 환불 시도      → /dispute/resolve
// 판정은 CLAUDE.md 7번의 3개만 허용. "단순 변심" 같은 판정 없는 환불 경로는 없다 (팀 결정 대기).
// CLAUDE.md 12번: "AI 응답 값 → 실행된 행동" 을 events.jsonl 에 한 줄로 남긴다 (dispute.action).

const blockchain = require('../blockchain/blockchainClient');
const { assertUid, VERDICT_NAMES } = require('../blockchain/errors');
const { getSettlement, updateSettlement } = require('./settlementStore');
const { logEvent } = require('../logger');
const { InputError } = require('../errors');

function requireId(settlementOnchainId) {
  if (typeof settlementOnchainId !== 'string' || !/^0x[0-9a-fA-F]{64}$/.test(settlementOnchainId)) {
    throw new InputError('settlementOnchainId(0x + 64자리 hex)가 필요해요.');
  }
  return settlementOnchainId;
}

// 이 정산에서 분담금을 잠근 참여자 (payer·0원 멤버 제외) — 환불 대상
function lockedParticipants(rec) {
  return rec.members.map((uid, i) => ({ uid, amount: rec.shares[i] })).filter((p) => p.uid !== rec.payer && p.amount > 0);
}

async function releaseSettlement({ settlementOnchainId }) {
  requireId(settlementOnchainId);
  const rec = getSettlement(settlementOnchainId);
  // payer 가 명시된 정산은 payer 에게, 아니면 결제처(MERCHANT_ADDRESS)로 — 사용자에게 다시 묻지 않는다
  const release = await blockchain.releaseSettlement({ settlementOnchainId, recipientUid: rec.payer || null });
  const next = updateSettlement(settlementOnchainId, { state: 'RELEASED', txs: { release } });
  logEvent('settlement.release', { settlementOnchainId, settlementId: rec.settlementId, recipient: rec.recipient, amount: release.amount, txHash: release.txHash, action: 'release_to_recipient 호출' });
  return { settlementOnchainId, release, state: next.state, recipient: rec.recipient };
}

async function raiseDispute({ settlementOnchainId, raisedBy, reason }) {
  requireId(settlementOnchainId);
  if (typeof reason !== 'string' || !reason.trim()) throw new InputError('이의제기 사유(reason)가 필요해요.');
  const rec = getSettlement(settlementOnchainId);
  if (raisedBy !== undefined && raisedBy !== null) {
    assertUid(raisedBy);
    if (!rec.members.includes(raisedBy)) throw new InputError(`raisedBy '${raisedBy}'은(는) 이 정산의 멤버가 아니에요.`);
  }
  const raised = await blockchain.raiseDispute({ settlementOnchainId, reason: reason.trim() });
  const dispute = { raisedBy: raisedBy ?? null, reason: reason.trim(), reasonHash: raised.reasonHash, txHash: raised.txHash, block: raised.block, raisedAt: new Date().toISOString() };
  const next = updateSettlement(settlementOnchainId, { state: 'DISPUTED', dispute, txs: { dispute: { txHash: raised.txHash, block: raised.block } } });
  logEvent('dispute.raise', { settlementOnchainId, settlementId: rec.settlementId, raisedBy: dispute.raisedBy, reason: dispute.reason, txHash: raised.txHash, action: 'raise_dispute 호출 → 체인 동결(DISPUTED)' });
  return { settlementOnchainId, dispute, state: next.state, txHash: raised.txHash, block: raised.block };
}

// verdict: 'NORMAL_APPROVAL' | 'GENUINE_ERROR' | 'BAD_FAITH_DISPUTE' (그 밖은 400 INVALID_VERDICT)
// investigation(선택): /dispute/investigate 의 AI 결과 — 로그에 근거로 남긴다
async function resolveDispute({ settlementOnchainId, verdict, investigation = null }) {
  requireId(settlementOnchainId);
  if (!VERDICT_NAMES.includes(verdict)) {
    throw new InputError(`verdict는 ${VERDICT_NAMES.join(' / ')} 중 하나여야 해요 (받은 값: ${JSON.stringify(verdict)}).`, 'INVALID_VERDICT', 400);
  }
  const rec = getSettlement(settlementOnchainId);
  const resolve = await blockchain.resolveDispute({ settlementOnchainId, verdict });

  // GENUINE_ERROR → 에스크로에서 참여자 전원에게 환불. 한 명이 실패해도 나머지는 계속 시도하고 결과를 남긴다
  const refunds = [];
  if (verdict === 'GENUINE_ERROR') {
    for (const p of lockedParticipants(rec)) {
      try {
        const r = await blockchain.refundParticipant({ settlementOnchainId, uid: p.uid });
        refunds.push({ uid: p.uid, amount: r.amount, txHash: r.txHash, block: r.block, ok: true });
      } catch (err) {
        refunds.push({ uid: p.uid, amount: p.amount, ok: false, error: { code: err.code || 'REFUND_FAILED', message: err.message } });
      }
    }
  }

  const state = resolve.state;
  const next = updateSettlement(settlementOnchainId, { state, verdict, resolvedAt: new Date().toISOString(), txs: { resolve: { txHash: resolve.txHash, block: resolve.block, verdict }, refunds } });

  const action = verdict === 'GENUINE_ERROR'
    ? `refund_participant × ${refunds.filter((r) => r.ok).length}/${refunds.length}`
    : verdict === 'NORMAL_APPROVAL' ? '정산 유지·이의 기각 (LOCKED 복귀)' : '이의 기각·근거 기록 공개 (LOCKED 복귀)';
  // CLAUDE.md 12번: AI 응답 값(verdict) → 실행된 행동 → TxHash 를 한 줄로
  logEvent('dispute.action', {
    settlementOnchainId,
    settlementId: rec.settlementId,
    responseKey: `verdict=${verdict}`,
    verdict,
    action,
    resolveTxHash: resolve.txHash,
    txHashes: refunds.filter((r) => r.ok).map((r) => r.txHash),
    failedRefunds: refunds.filter((r) => !r.ok).map((r) => ({ uid: r.uid, code: r.error.code })),
    state,
    investigation: investigation ? { verdict: investigation.verdict, mismatchPoint: investigation.mismatchPoint ?? null, explanation: investigation.explanation ?? null } : null,
  });
  return { settlementOnchainId, resolve, refunds, state: next.state, verdict };
}

module.exports = { releaseSettlement, raiseDispute, resolveDispute, lockedParticipants };
