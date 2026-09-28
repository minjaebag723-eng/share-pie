'use strict';

// 승인 이후의 온체인 행동 (코드 전용 — AI 호출 없음)
//   releaseSettlement : 보류가 끝난 정산을 결제처(또는 payer)에게 지급        → /settlement/release
//   raiseDispute      : 이의제기 접수 → 체인 동결(Disputed)                  → /dispute/raise
//   resolveDispute    : 판정 실행. GENUINE_ERROR 면 참여자 전원 환불 시도      → /dispute/resolve
// 판정은 CLAUDE.md 7번의 3개만 허용. "단순 변심" 같은 판정 없는 환불 경로는 없다 (팀 결정 대기).
// CLAUDE.md 11번: 코드의 금액 불일치 확인(compareRecords) 없이 AI verdict 만으로 환불을 실행하지 않는다 — resolveDispute 가 강제한다.
// CLAUDE.md 12번: "AI 응답 값 → 실행된 행동" 을 events.jsonl 에 한 줄로 남긴다 (dispute.action).
//
// chain 인자: 기본은 blockchainClient(env 로 실제 체인/MOCK 결정). 로컬 Hardhat 통합 테스트는 onchainClient 를 직접 주입한다.

const blockchain = require('../blockchain/blockchainClient');
const { assertUid, VERDICT_NAMES } = require('../blockchain/errors');
const { getSettlement, updateSettlement } = require('./settlementStore');
const { compareRecords } = require('../dispute/compareRecords');
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

async function releaseSettlement({ settlementOnchainId }, chain = blockchain) {
  requireId(settlementOnchainId);
  const rec = getSettlement(settlementOnchainId);
  // payer 가 명시된 정산은 payer 에게, 아니면 결제처(MERCHANT_ADDRESS)로 — 사용자에게 다시 묻지 않는다
  const release = await chain.releaseSettlement({ settlementOnchainId, recipientUid: rec.payer || null });
  const next = updateSettlement(settlementOnchainId, { state: 'RELEASED', txs: { release } });
  logEvent('settlement.release', { settlementOnchainId, settlementId: rec.settlementId, recipient: rec.recipient, amount: release.amount, txHash: release.txHash, action: 'release_to_recipient 호출' });
  return { settlementOnchainId, release, state: next.state, recipient: rec.recipient };
}

async function raiseDispute({ settlementOnchainId, raisedBy, reason }, chain = blockchain) {
  requireId(settlementOnchainId);
  if (typeof reason !== 'string' || !reason.trim()) throw new InputError('이의제기 사유(reason)가 필요해요.');
  const rec = getSettlement(settlementOnchainId);
  if (raisedBy !== undefined && raisedBy !== null) {
    assertUid(raisedBy);
    if (!rec.members.includes(raisedBy)) throw new InputError(`raisedBy '${raisedBy}'은(는) 이 정산의 멤버가 아니에요.`);
  }
  const raised = await chain.raiseDispute({ settlementOnchainId, reason: reason.trim() });
  const dispute = { raisedBy: raisedBy ?? null, reason: reason.trim(), reasonHash: raised.reasonHash, txHash: raised.txHash, block: raised.block, raisedAt: new Date().toISOString() };
  const next = updateSettlement(settlementOnchainId, { state: 'DISPUTED', dispute, txs: { dispute: { txHash: raised.txHash, block: raised.block } } });
  logEvent('dispute.raise', { settlementOnchainId, settlementId: rec.settlementId, raisedBy: dispute.raisedBy, reason: dispute.reason, txHash: raised.txHash, action: 'raise_dispute 호출 → 체인 동결(DISPUTED)' });
  return { settlementOnchainId, dispute, state: next.state, txHash: raised.txHash, block: raised.block };
}

// 판정 실행에 쓸 "코드의 불일치 확인 결과(facts)"를 정한다.
//  (1) investigation = /dispute/investigate 응답 전체 ({ verdict, mismatchDetected, mismatchPoint, expectedAmount, actualAmount, explanation })
//  (2) 또는 investigate 입력(originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute) → compareRecords 를 직접 다시 돌린다 (AI 재호출 없음)
//  둘 다 없으면 INVESTIGATION_REQUIRED
function resolveFacts({ investigation, originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute }) {
  if (investigation && typeof investigation === 'object' && typeof investigation.mismatchDetected === 'boolean') {
    return {
      source: 'investigation',
      mismatchDetected: investigation.mismatchDetected,
      mismatchPoint: investigation.mismatchPoint ?? null,
      expectedAmount: investigation.expectedAmount ?? null,
      actualAmount: investigation.actualAmount ?? null,
      aiVerdict: investigation.verdict ?? null,
      explanation: investigation.explanation ?? null,
    };
  }
  if (settlementPlan && approvalRecord && actualTransfer) {
    const f = compareRecords({ originalRequest: originalRequest ?? null, settlementPlan, approvalRecord, actualTransfer, dispute: dispute ?? null });
    return {
      source: 'compareRecords',
      mismatchDetected: f.mismatchDetected,
      mismatchPoint: f.mismatchPoint,
      expectedAmount: f.expectedAmount,
      actualAmount: f.actualAmount,
      mismatches: f.mismatches,
      aiVerdict: null,
      explanation: null,
    };
  }
  throw new InputError(
    'investigation(= /dispute/investigate 응답) 또는 investigate 입력(settlementPlan, approvalRecord, actualTransfer)이 필요해요. 코드의 불일치 확인 없이는 판정을 실행하지 않아요.',
    'INVESTIGATION_REQUIRED',
    400,
  );
}

// verdict: 'NORMAL_APPROVAL' | 'GENUINE_ERROR' | 'BAD_FAITH_DISPUTE' (그 밖은 400 INVALID_VERDICT)
// 규칙 (온체인 호출 전에 검사):
//   GENUINE_ERROR 인데 불일치가 없으면 409 MISMATCH_NOT_FOUND   — AI verdict 만으로 환불하지 않는다
//   NORMAL/BAD_FAITH 인데 불일치가 있으면 409 MISMATCH_UNRESOLVED — 불일치를 두고 기각하지도 않는다
async function resolveDispute({ settlementOnchainId, verdict, investigation = null, originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute }, chain = blockchain) {
  requireId(settlementOnchainId);
  if (!VERDICT_NAMES.includes(verdict)) {
    throw new InputError(`verdict는 ${VERDICT_NAMES.join(' / ')} 중 하나여야 해요 (받은 값: ${JSON.stringify(verdict)}).`, 'INVALID_VERDICT', 400);
  }
  const rec = getSettlement(settlementOnchainId);
  const facts = resolveFacts({ investigation, originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute });

  if (verdict === 'GENUINE_ERROR' && !facts.mismatchDetected) {
    throw new InputError('코드의 기록 비교에서 금액 불일치가 발견되지 않았어요. GENUINE_ERROR(환불)는 불일치가 확인된 경우에만 실행할 수 있어요.', 'MISMATCH_NOT_FOUND', 409);
  }
  if (verdict !== 'GENUINE_ERROR' && facts.mismatchDetected) {
    throw new InputError(`코드의 기록 비교에서 불일치(${facts.mismatchPoint ?? '위치 미상'})가 발견됐어요. 불일치를 둔 채 ${verdict}로 기각할 수 없어요.`, 'MISMATCH_UNRESOLVED', 409);
  }

  const resolve = await chain.resolveDispute({ settlementOnchainId, verdict });

  // GENUINE_ERROR → 에스크로에서 참여자 전원에게 환불. 한 명이 실패해도 나머지는 계속 시도하고 결과를 남긴다
  const refunds = [];
  if (verdict === 'GENUINE_ERROR') {
    for (const p of lockedParticipants(rec)) {
      try {
        const r = await chain.refundParticipant({ settlementOnchainId, uid: p.uid });
        refunds.push({ uid: p.uid, amount: r.amount, txHash: r.txHash, block: r.block, ok: true });
      } catch (err) {
        refunds.push({ uid: p.uid, amount: p.amount, ok: false, error: { code: err.code || 'REFUND_FAILED', message: err.message } });
      }
    }
  }

  const state = resolve.state;
  const investigationSummary = { source: facts.source, aiVerdict: facts.aiVerdict, mismatchDetected: facts.mismatchDetected, mismatchPoint: facts.mismatchPoint, expectedAmount: facts.expectedAmount, actualAmount: facts.actualAmount, explanation: facts.explanation };
  const next = updateSettlement(settlementOnchainId, {
    state, verdict, resolvedAt: new Date().toISOString(), investigation: investigationSummary, facts: { mismatchDetected: facts.mismatchDetected, mismatchPoint: facts.mismatchPoint, mismatches: facts.mismatches ?? null },
    txs: { resolve: { txHash: resolve.txHash, block: resolve.block, verdict }, refunds },
  });

  const action = verdict === 'GENUINE_ERROR'
    ? `refund_participant × ${refunds.filter((r) => r.ok).length}/${refunds.length}`
    : verdict === 'NORMAL_APPROVAL' ? '정산 유지·이의 기각 (LOCKED 복귀)' : '이의 기각·근거 기록 공개 (LOCKED 복귀)';
  // CLAUDE.md 12번: 코드 확인 결과 → AI 응답 값(verdict) → 실행된 행동 → TxHash 를 한 줄로
  logEvent('dispute.action', {
    settlementOnchainId,
    settlementId: rec.settlementId,
    summary: `mismatchDetected=${facts.mismatchDetected}${facts.mismatchPoint ? `, mismatchPoint=${facts.mismatchPoint}` : ''} → verdict=${verdict} → ${action}`,
    responseKey: `verdict=${verdict}`,
    verdict,
    action,
    facts: { source: facts.source, mismatchDetected: facts.mismatchDetected, mismatchPoint: facts.mismatchPoint, expectedAmount: facts.expectedAmount, actualAmount: facts.actualAmount },
    resolveTxHash: resolve.txHash,
    txHashes: refunds.filter((r) => r.ok).map((r) => r.txHash),
    failedRefunds: refunds.filter((r) => !r.ok).map((r) => ({ uid: r.uid, code: r.error.code })),
    state,
    investigation: investigationSummary,
  });
  return { settlementOnchainId, resolve, refunds, state: next.state, verdict, facts: investigationSummary };
}

module.exports = { releaseSettlement, raiseDispute, resolveDispute, resolveFacts, lockedParticipants };
