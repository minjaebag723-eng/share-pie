'use strict';

// Shopping 모듈 — 예산 기준 1인당 비용 비교 (순수 코드, AI 미사용)
// CLAUDE.md 0번 원칙 6: 단순 목록/인기순 나열 금지. 반드시 예산·인원 조건으로 1인당 비용을 계산해 비교한다.
//
// 1인당 비용은 정산 코어와 똑같은 규칙(computeSettlement)으로 계산한다:
//   1원 단위 + 최대잉여법 (나누어떨어지지 않으면 몇 명이 1원씩 더 냄).
//   → 여기서 고른 상품을 그대로 정산으로 넘기면 금액이 한 푼도 달라지지 않는다.
//
// 예산 판정
// - perPerson(1인 예산): 가장 많이 내는 사람의 금액(perPerson) ≤ 1인 예산
// - total(전체 예산):    상품 가격 ≤ 전체 예산
//
// 정렬: 예산 이내 후보 먼저(1인당 비용 낮은 순) → 예산 초과 후보(초과액 적은 순)

const { computeSettlement } = require('../settlement/calculateSettlement');
const { won } = require('../utils/format');
const { InputError } = require('../errors');

const BUDGET_TYPES = ['perPerson', 'total'];
const DEFAULT_LIMIT = 5;

function isPositiveInt(v) {
  return Number.isSafeInteger(v) && v > 0;
}

// members가 없으면 인원수만큼 이름을 만든다
function resolveMembers({ members, headcount }) {
  if (Array.isArray(members) && members.length) {
    if (headcount != null && headcount !== members.length) throw new InputError(`headcount(${headcount})와 members 인원(${members.length})이 달라요.`);
    return [...members];
  }
  if (!Number.isSafeInteger(headcount) || headcount < 1 || headcount > 100) throw new InputError('headcount는 1~100 사이 정수여야 해요.');
  return Array.from({ length: headcount }, (_, i) => (i === 0 ? '나' : `참여자${i + 1}`));
}

function validateBudget(budget) {
  if (!budget || !BUDGET_TYPES.includes(budget.type) || !isPositiveInt(budget.amount)) {
    throw new InputError('budget은 { type: "perPerson" | "total", amount: 양의 정수 } 형태여야 해요.');
  }
  return { type: budget.type, amount: budget.amount };
}

function evaluate(product, members, budget) {
  const calc = computeSettlement({
    members,
    mode: 'EQUAL',
    itemName: product.name,
    total: product.price,
    totalBudget: budget.type === 'total' ? budget.amount : null,
    payer: null,
  });
  const perPerson = Math.max(...calc.shares); // 1원 차이가 나면 많이 내는 쪽 기준
  const overBudgetBy = budget.type === 'perPerson' ? Math.max(0, perPerson - budget.amount) : calc.overBudgetBy;
  return {
    ...product,
    perPerson,
    shares: calc.shares,
    withinBudget: overBudgetBy === 0,
    overBudgetBy,
    budgetLeft: overBudgetBy === 0 ? (budget.type === 'perPerson' ? budget.amount - perPerson : budget.amount - product.price) : 0,
  };
}

function buildSummary(best, candidates, n, budget) {
  const budgetText = budget.type === 'perPerson' ? `1인 ${won(budget.amount)}` : `전체 ${won(budget.amount)}`;
  if (!candidates.length) return `검색된 상품이 없어요. 다른 검색어로 다시 찾아볼까요?`;
  if (!best) {
    const c = candidates[0];
    return `${n}명 · ${budgetText} 예산 안에 들어오는 상품이 없어요. 가장 가까운 '${c.name}'은(는) 1인 ${won(c.perPerson)}으로 예산을 ${won(c.overBudgetBy)} 넘어요.`;
  }
  const within = candidates.filter((c) => c.withinBudget).length;
  return `${n}명 · ${budgetText} 예산으로 ${candidates.length}개 후보를 비교했어요. 예산 안에 드는 ${within}개 중 '${best.name}'(${won(best.price)})이(가) 1인 ${won(best.perPerson)}으로 가장 부담이 적어요.`;
}

// input: { products, members?, headcount?, budget: { type, amount }, limit? }
function compareCandidates({ products, members, headcount, budget, limit = DEFAULT_LIMIT }) {
  if (!Array.isArray(products)) throw new InputError('products는 배열이어야 해요.');
  const people = resolveMembers({ members, headcount });
  const b = validateBudget(budget);

  const evaluated = products
    .filter((p) => p && isPositiveInt(p.price))
    .map((p) => evaluate(p, people, b))
    .sort((x, y) => (x.withinBudget === y.withinBudget
      ? (x.withinBudget ? x.perPerson - y.perPerson : x.overBudgetBy - y.overBudgetBy)
      : (x.withinBudget ? -1 : 1)));

  const candidates = evaluated.slice(0, limit);
  const best = candidates.find((c) => c.withinBudget) || null;
  return {
    members: people,
    headcount: people.length,
    budget: b,
    candidates,
    bestId: best ? best.id : null,
    // 고른 상품을 그대로 POST /settlement/calculate 로 넘길 수 있는 형태
    settlementInput: best ? {
      members: people,
      mode: 'EQUAL',
      itemName: best.name,
      total: best.price,
      participants: people,
      totalBudget: b.type === 'total' ? b.amount : null,
      payer: null,
    } : null,
    summary: buildSummary(best, candidates, people.length, b),
    rule: '정산 코어와 동일: 1원 단위 균등 분배 (최대잉여법)',
  };
}

module.exports = { compareCandidates, resolveMembers, BUDGET_TYPES };
