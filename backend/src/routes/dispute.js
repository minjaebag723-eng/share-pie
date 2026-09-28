'use strict';

// Dispute 모듈 API (CLAUDE.md 6번 — 2순위)
//   /investigate : AI 판정만 (dispute.investigate, Kiln 호출)
//   /raise       : 이의제기 접수 → 온체인 raise_dispute (동결)          — 코드 전용
//   /resolve     : 판정 실행 → 온체인 resolve_dispute (+ GENUINE_ERROR 면 refund_participant × N) — 코드 전용, AI 호출 없음
const express = require('express');
const { investigateDispute } = require('../agents/investigateDispute');
const { raiseDispute, resolveDispute } = require('../settlement/settlementActions');

const router = express.Router();

// body: { originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute }
//   originalRequest: { text, structured }   structured = analyze 때 확정된 조건 (재계산 검증용, 선택)
//   settlementPlan:  { members, shares, payer }   payer: null이면 Pie 에스크로가 수령
//   approvalRecord / actualTransfer: [{ from, to, amount, txHash }]
//   dispute: { raisedBy, reason }  (선택)
router.post('/investigate', async (req, res) => {
  const { originalRequest = null, settlementPlan, approvalRecord, actualTransfer, dispute = null } = req.body || {};
  res.json(await investigateDispute(originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute));
});

// body: { settlementOnchainId, raisedBy(uid), reason }
// → { settlementOnchainId, dispute: { raisedBy, reason, reasonHash, txHash }, state:'DISPUTED', txHash, block }
router.post('/raise', async (req, res) => {
  const { settlementOnchainId, raisedBy = null, reason } = req.body || {};
  res.json(await raiseDispute({ settlementOnchainId, raisedBy, reason }));
});

// body: { settlementOnchainId, verdict, investigation? }   verdict: NORMAL_APPROVAL | GENUINE_ERROR | BAD_FAITH_DISPUTE
// → { settlementOnchainId, resolve: { txHash, block, verdict, verdictCode }, refunds: [{ uid, amount, txHash, ok }|{ uid, ok:false, error }], state, verdict }
router.post('/resolve', async (req, res) => {
  const { settlementOnchainId, verdict, investigation = null } = req.body || {};
  res.json(await resolveDispute({ settlementOnchainId, verdict, investigation }));
});

module.exports = router;
