'use strict';

// Dispute 모듈 API (CLAUDE.md 6번 — 2순위)
const express = require('express');
const { investigateDispute } = require('../agents/investigateDispute');

const router = express.Router();

// body: { originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute }
//   originalRequest: { text, structured }   structured = analyze 때 확정된 조건 (재계산 검증용, 선택)
//   settlementPlan:  { members, shares, payer }   payer: null이면 Pie 에스크로가 수령
//   approvalRecord / actualTransfer: [{ from, to, amount, txHash }]   ⚠️ MOCK 초안 모양
//   dispute: { raisedBy, reason }  (선택)
router.post('/investigate', async (req, res) => {
  const { originalRequest = null, settlementPlan, approvalRecord, actualTransfer, dispute = null } = req.body || {};
  res.json(await investigateDispute(originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute));
});

// TODO(블록체인 연동): raise_dispute / resolve_dispute(+refund_participant) 컨트랙트 확정 후 구현
router.post('/raise', (req, res) => {
  res.status(501).json({ error: { code: 'NOT_IMPLEMENTED', message: '블록체인 raise_dispute 연동 대기 중이에요.' } });
});
router.post('/resolve', (req, res) => {
  res.status(501).json({ error: { code: 'NOT_IMPLEMENTED', message: '블록체인 resolve_dispute 연동 대기 중이에요.' } });
});

module.exports = router;
