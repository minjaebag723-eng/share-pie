'use strict';

// 정산 코어 API (CLAUDE.md 6번 — 1순위)
const express = require('express');
const { interpretConditions } = require('../agents/interpretConditions');
const { explainSettlement } = require('../agents/explainSettlement');
const { calculateSettlement } = require('../settlement/calculateSettlement');
const { approveSettlement } = require('../settlement/approveSettlement');

const router = express.Router();

// Stage 1 (AI) + Stage 2 (코드) — 자연어 조건 → 구조화 + members/shares
// body: { text, previousState }   previousState: 직전 analyze 응답, 첫 턴이면 그룹의 { members }
// 응답의 confirmData = UI 확인 카드 데이터 { mode, itemName, total, participants, ratios, adjustments, items }
router.post('/analyze', async (req, res) => {
  const { text, previousState = null } = req.body || {};
  res.json(await interpretConditions(text, previousState));
});

// Stage 2 (코드 전용, 0 tokens) — 구조화된 조건 → 금액 계산
// body: { members, mode, itemName, total, participants, ratios, adjustments, items, totalBudget, payer }
//   (= { members, ...confirmData })  mode: EQUAL | RATIO | ADJUST | ITEM
router.post('/calculate', (req, res) => {
  res.json(calculateSettlement(req.body));
});

// Stage 3 (AI) — 계산 결과 → 자연어 설명
// body: { calculatedResult }  (= /calculate 응답 또는 /analyze 응답의 calculation)
router.post('/explain', async (req, res) => {
  const { calculatedResult } = req.body || {};
  res.json(await explainSettlement(calculatedResult));
});

// 전원 승인 → 온체인 기록(현재 MOCK) → 인증서 발급
// body: { settlementId, title, settlement: { members, ...confirmData, totalBudget, payer }, approvals }
router.post('/approve', async (req, res) => {
  res.json(await approveSettlement(req.body || {}));
});

module.exports = router;
