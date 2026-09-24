'use strict';

// 분쟁 조사용 기록 비교 (순수 코드, AI 미사용)
// 최초요청 → 정산안 → 승인기록 → 실제송금 순서로 금액을 비교해 "처음 어긋난 지점"을 찾는다.
// expectedAmount / actualAmount / difference는 전부 여기서(코드) 계산한다. AI는 계산하지 않는다.
//
// ⚠️ MOCK/TODO: approvalRecord·actualTransfer의 모양은 블록체인 담당 SDK 확정 전 임시 초안.
//   한 건 = { from, to, amount, txHash }  (from=보내는/승인한 멤버, to=받는 곳: payer 또는 에스크로)
//   실제 SDK 반환값이 확정되면 normalizeRecords()만 수정하면 된다.

const { computeSettlement } = require('../settlement/calculateSettlement');
const { InputError } = require('../errors');
const { ESCROW_RECIPIENT } = require('../blockchain/blockchainClient');

const POINTS = { CALCULATION: '계산 단계', APPROVAL: '승인 단계', TRANSFER: '송금 단계' };

// TODO(블록체인 연동): 실제 SDK 레코드 → { from, to, amount, txHash } 변환
function normalizeRecords(records, label) {
  if (!Array.isArray(records)) throw new InputError(`${label}는 배열이어야 해요.`);
  return records.map((r, i) => {
    if (!r || typeof r.from !== 'string' || typeof r.to !== 'string') throw new InputError(`${label}[${i}]에 from/to가 없어요.`);
    if (!Number.isSafeInteger(r.amount) || r.amount < 0) throw new InputError(`${label}[${i}].amount는 0 이상의 정수여야 해요.`);
    return { from: r.from, to: r.to, amount: r.amount, txHash: r.txHash ?? null };
  });
}

function sumFromTo(records, from, to) {
  return records.filter((r) => r.from === from && r.to === to).reduce((s, r) => s + r.amount, 0);
}

function compareRecords({ originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute = null }) {
  const plan = settlementPlan;
  if (!plan || !Array.isArray(plan.members) || !Array.isArray(plan.shares) || plan.members.length !== plan.shares.length || !plan.members.length) {
    throw new InputError('settlementPlan.members와 shares는 길이가 같은 배열이어야 해요.');
  }
  if (!plan.shares.every((v) => Number.isSafeInteger(v) && v >= 0)) throw new InputError('settlementPlan.shares는 0 이상의 정수 배열이어야 해요.');
  const payer = plan.payer ?? null;
  if (payer !== null && !plan.members.includes(payer)) throw new InputError('settlementPlan.payer는 null(에스크로) 또는 멤버 중 한 명이어야 해요.');
  const recipient = payer || ESCROW_RECIPIENT; // payer가 없으면 Pie 에스크로가 전원 분담금을 받음
  const approvals = normalizeRecords(approvalRecord, 'approvalRecord');
  const transfers = normalizeRecords(actualTransfer, 'actualTransfer');

  const mismatches = [];

  // 1) 계산 단계: 최초요청의 구조화 조건으로 다시 계산한 금액 vs 정산안 금액
  let recomputed = null;
  if (originalRequest && originalRequest.structured) {
    recomputed = computeSettlement(originalRequest.structured);
    plan.members.forEach((m, i) => {
      const j = recomputed.members.indexOf(m);
      const expected = j === -1 ? 0 : recomputed.shares[j];
      if (expected !== plan.shares[i]) mismatches.push({ point: POINTS.CALCULATION, member: m, expectedAmount: expected, actualAmount: plan.shares[i] });
    });
  }

  // 2) 승인 단계, 3) 송금 단계 — payer 본인은 자기에게 보내지 않으므로 제외 (에스크로면 전원 대상)
  const perMember = plan.members.map((m, i) => {
    const planned = plan.shares[i];
    if (m === payer) return { member: m, planned, approved: null, transferred: null, isPayer: true };
    const approved = sumFromTo(approvals, m, recipient);
    const transferred = sumFromTo(transfers, m, recipient);
    if (approved !== planned) mismatches.push({ point: POINTS.APPROVAL, member: m, expectedAmount: planned, actualAmount: approved });
    if (transferred !== planned) mismatches.push({ point: POINTS.TRANSFER, member: m, expectedAmount: planned, actualAmount: transferred });
    return { member: m, planned, approved, transferred, isPayer: false };
  });

  const order = [POINTS.CALCULATION, POINTS.APPROVAL, POINTS.TRANSFER];
  mismatches.sort((a, b) => order.indexOf(a.point) - order.indexOf(b.point));
  mismatches.forEach((x) => { x.difference = x.expectedAmount - x.actualAmount; });

  // 이의제기한 사람과 관련된 불일치를 우선 보고, 없으면 가장 앞 단계의 불일치
  const raisedBy = dispute && dispute.raisedBy;
  const primary = mismatches.find((x) => x.member === raisedBy) || mismatches[0] || null;

  let expectedAmount = null;
  let actualAmount = null;
  if (primary) {
    ({ expectedAmount, actualAmount } = primary);
  } else if (raisedBy) {
    const row = perMember.find((r) => r.member === raisedBy && !r.isPayer);
    if (row) { expectedAmount = row.planned; actualAmount = row.transferred; }
  }

  return {
    mismatchDetected: mismatches.length > 0,
    mismatchPoint: primary ? primary.point : null,
    mismatchMember: primary ? primary.member : null,
    expectedAmount,
    actualAmount,
    difference: primary ? primary.difference : null,
    mismatches,
    perMember,
    payer,
    recipient,
    recomputedShares: recomputed ? recomputed.shares : null,
  };
}

module.exports = { compareRecords, normalizeRecords, POINTS };
