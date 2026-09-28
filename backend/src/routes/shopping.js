'use strict';

// Shopping 모듈 API (CLAUDE.md 6번 — 3순위, 선택적 확장)
// 반드시 예산 기준 1인당 비용 계산 포함 (0번 원칙 6) — 단순 목록 반환 금지
const express = require('express');
const { searchShopping } = require('../agents/searchShopping');

const router = express.Router();

// body: { text, previousState, members, limit }   자연어 → AI 구조화 → 검색 → 1인당 비용 비교
//   또는 { conditions: { query, headcount, budget: { type, amount } }, members, limit }   AI 생략
router.post('/search', async (req, res) => {
  res.json(await searchShopping(req.body || {}));
});

module.exports = router;
