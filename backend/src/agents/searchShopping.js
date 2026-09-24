'use strict';

// Shopping 모듈 — 공동구매 상품 탐색 (선택적 확장, 정산 코어 없이는 의미 없음)
// 역할 분담
// - AI (stage 태그: shopping.search): 자연어 요청 → { query, headcount, budget } 구조화만. 금액 계산 안 함.
// - 코드: 상품 검색(SerpApi / 목 데이터) → 예산·인원 기준 1인당 비용 계산·비교 (compareCandidates)
// 다턴 처리: previousState(직전 응답의 conditions)를 받아 최신 조건 전체를 다시 구조화.
// 프론트가 조건을 이미 알면 conditions를 직접 보내 AI 호출을 건너뛸 수 있다 (0 tokens).

const { callKilnJson } = require('../kilnClient');
const { searchProducts } = require('../shopping/productSearch');
const { compareCandidates, BUDGET_TYPES } = require('../shopping/compareCandidates');
const { logEvent } = require('../logger');
const { InputError } = require('../errors');

const SYSTEM_PROMPT = `너는 정산 서비스 SharePie의 "공동구매 조건 구조화" 담당이다.
여러 명이 같이 살 상품을 찾는 사용자의 요청을 아래 JSON 형식으로만 변환한다.

[출력 규칙 — 반드시 지킬 것]
- 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 마크다운, 코드펜스를 절대 붙이지 않는다.
- 형식:
{
  "needsClarification": false,
  "clarificationQuestion": null,
  "query": "삼겹살 1kg",
  "headcount": 4,
  "budget": { "type": "perPerson", "amount": 10000 }
}

[필드 규칙]
- query: 쇼핑몰 검색창에 넣을 짧은 한국어 검색어. 인원·예산·"찾아줘" 같은 말은 빼고 상품만 쓴다.
- headcount: 함께 사는 인원수(정수). [현재 멤버]가 주어지면 그 인원수를 쓴다.
- budget.type: "1인 1만원", "한 명당 만원" → "perPerson" / "전체 5만원", "총 4만원 이하" → "total"
- budget.amount: 원 단위 정수 ("1만원" → 10000, "3만 5천원" → 35000). 문장에 적힌 금액만 옮기고 계산하지 않는다.
  1인 예산을 전체 예산으로 바꾸는 등의 곱셈·나눗셈을 절대 하지 않는다.

[모호한 조건]
- 상품, 인원수, 예산 중 하나라도 알 수 없으면 임의로 정하지 않는다.
  "needsClarification": true, "clarificationQuestion": "한 문장 질문" 으로 답하고 나머지 필드는 알 수 있는 만큼만 채운다.
  예) "몇 명이 함께 구매하시나요? 그리고 1인 예산은 어느 정도인가요?"
- "적당히", "싸게"처럼 금액이 없는 예산 표현도 되묻는다.

[대화 중 조건 변경]
- [이전 조건]이 주어지면 그 조건을 유지한 채 이번 발언의 변경 사항만 반영해서 최신 조건 전체를 다시 출력한다.
  (예: 이전 조건 + "6명으로 바꿔줘" → query·budget 유지, headcount만 6)`;

function isPositiveInt(v) {
  return Number.isSafeInteger(v) && v > 0;
}

function validateConditions(c) {
  const errors = [];
  if (!c || typeof c !== 'object') return ['조건 객체가 필요합니다'];
  if (typeof c.query !== 'string' || !c.query.trim()) errors.push('query는 비어 있지 않은 문자열이어야 합니다');
  if (!Number.isSafeInteger(c.headcount) || c.headcount < 1 || c.headcount > 100) errors.push('headcount는 1~100 사이 정수여야 합니다');
  if (!c.budget || !BUDGET_TYPES.includes(c.budget.type)) errors.push('budget.type은 "perPerson" 또는 "total"이어야 합니다');
  if (!c.budget || !isPositiveInt(c.budget.amount)) errors.push('budget.amount는 원 단위 양의 정수여야 합니다');
  return errors;
}

function tidy(c) {
  return { query: c.query.trim(), headcount: c.headcount, budget: { type: c.budget.type, amount: c.budget.amount } };
}

// AI 응답 형식 검증 → { ok, value } 또는 { ok:false, errors }
function validateShoppingInterpretation(raw, members) {
  if (typeof raw.needsClarification !== 'boolean') return { ok: false, errors: ['needsClarification은 true 또는 false여야 합니다'] };
  if (raw.needsClarification) {
    if (typeof raw.clarificationQuestion !== 'string' || !raw.clarificationQuestion.trim()) {
      return { ok: false, errors: ['needsClarification이 true이면 clarificationQuestion에 질문 문장이 있어야 합니다'] };
    }
    return { ok: true, value: { needsClarification: true, clarificationQuestion: raw.clarificationQuestion.trim(), partial: raw } };
  }
  const errors = validateConditions(raw);
  if (members.length && raw.headcount !== members.length) errors.push(`headcount는 현재 멤버 인원수 ${members.length}여야 합니다`);
  return errors.length ? { ok: false, errors } : { ok: true, value: { needsClarification: false, conditions: tidy(raw) } };
}

// 되묻는 동안에도 알아낸 조건은 다음 턴 previousState로 넘길 수 있게 남긴다
function partialConditions(partial, prev) {
  const p = partial || {};
  return {
    query: typeof p.query === 'string' && p.query.trim() ? p.query.trim() : prev?.query ?? null,
    headcount: Number.isSafeInteger(p.headcount) && p.headcount > 0 ? p.headcount : prev?.headcount ?? null,
    budget: p.budget && BUDGET_TYPES.includes(p.budget.type) && isPositiveInt(p.budget.amount)
      ? { type: p.budget.type, amount: p.budget.amount } : prev?.budget ?? null,
  };
}

async function runComparison(conditions, members, limit) {
  const search = await searchProducts(conditions.query);
  const comparison = compareCandidates({
    products: search.products,
    members: members.length ? members : undefined,
    headcount: conditions.headcount,
    budget: conditions.budget,
    limit,
  });
  return { provider: search.provider, fallbackReason: search.fallbackReason, ...comparison };
}

// body: { text?, previousState?, conditions?, members?, limit? }
//   text + previousState  → AI가 조건 구조화 (shopping.search)
//   conditions            → AI 생략, 바로 검색·비교 (0 tokens)
async function searchShopping({ text, previousState = null, conditions = null, members = [], limit } = {}) {
  if (!Array.isArray(members)) throw new InputError('members는 이름 배열이어야 해요.');

  if (conditions) {
    const errors = validateConditions(conditions);
    if (errors.length) throw new InputError(`conditions 형식 오류: ${errors.join(' / ')}`);
    const c = tidy(conditions);
    const result = { needsClarification: false, clarificationQuestion: null, conditions: c, ...(await runComparison(c, members, limit)) };
    logEvent('shopping.search', { mode: 'structured', conditions: c, result });
    return result;
  }

  if (typeof text !== 'string' || !text.trim()) throw new InputError('text(찾을 상품 설명) 또는 conditions가 필요해요.');
  if (text.length > 2000) throw new InputError('text는 2,000자 이하로 보내 주세요.');
  const prev = previousState && typeof previousState === 'object' ? (previousState.conditions || previousState) : null;

  const ai = await callKilnJson({
    stage: 'shopping.search',
    system: SYSTEM_PROMPT,
    user: JSON.stringify({
      '현재 멤버': members.length ? members : '(없음 — 문장에서 인원수 파악)',
      '이전 조건': prev,
      '이번 발언': text.trim(),
    }),
    validate: (raw) => validateShoppingInterpretation(raw, members),
  });

  if (ai.needsClarification) {
    const result = {
      needsClarification: true,
      clarificationQuestion: ai.clarificationQuestion,
      conditions: partialConditions(ai.partial, prev),
      candidates: [],
      bestId: null,
      settlementInput: null,
      summary: null,
    };
    logEvent('shopping.search', { mode: 'text', text, previousState: prev, result });
    return result;
  }

  const result = { needsClarification: false, clarificationQuestion: null, conditions: ai.conditions, ...(await runComparison(ai.conditions, members, limit)) };
  logEvent('shopping.search', { mode: 'text', text, previousState: prev, result });
  return result;
}

module.exports = { searchShopping, validateShoppingInterpretation, validateConditions, SYSTEM_PROMPT };
