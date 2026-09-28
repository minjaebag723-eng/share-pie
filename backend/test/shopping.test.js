'use strict';

const { fakeKiln, restoreKiln, readLog } = require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const { compareCandidates } = require('../src/shopping/compareCandidates');
const { searchProducts, normalizeSerpResult } = require('../src/shopping/productSearch');
const { searchShopping } = require('../src/agents/searchShopping');
const { computeSettlement } = require('../src/settlement/calculateSettlement');

const realFetch = global.fetch;
test.afterEach(() => {
  restoreKiln();
  global.fetch = realFetch;
  delete process.env.SHOPPING_PROVIDER;
  delete process.env.SHOPPING_API_KEY;
});

const PRODUCTS = [
  { id: 'a', name: '삼겹살 1.2kg', price: 35900 },
  { id: 'b', name: '목살 1.5kg', price: 39900 },
  { id: 'c', name: '혼합세트 1.4kg', price: 42900 },
];

test('compareCandidates: 1인 예산 기준 — 정산 코어와 같은 규칙으로 1인당 비용 계산', () => {
  const r = compareCandidates({ products: PRODUCTS, headcount: 4, budget: { type: 'perPerson', amount: 10000 } });
  const b = r.candidates.find((c) => c.id === 'b');
  // 39,900 / 4 = 9,975 (1원 단위, UI와 같은 규칙)
  assert.equal(b.perPerson, 9975);
  assert.deepEqual(b.shares, [9975, 9975, 9975, 9975]);
  assert.equal(b.withinBudget, true);
  const c = r.candidates.find((x) => x.id === 'c');
  assert.equal(c.withinBudget, false);
  assert.equal(c.overBudgetBy, 10725 - 10000);
  // 예산 이내 먼저(1인당 낮은 순) → 초과
  assert.deepEqual(r.candidates.map((x) => x.id), ['a', 'b', 'c']);
  assert.equal(r.bestId, 'a');
});

test('compareCandidates: 1원이 안 나누어떨어지면 많이 내는 사람 기준으로 예산 판정', () => {
  const r = compareCandidates({ products: [{ id: 'x', name: 'x', price: 10001 }], headcount: 2, budget: { type: 'perPerson', amount: 5000 } });
  assert.deepEqual(r.candidates[0].shares, [5001, 5000]);
  assert.equal(r.candidates[0].perPerson, 5001);
  assert.equal(r.candidates[0].overBudgetBy, 1);
});

test('compareCandidates: settlementInput을 정산 코어에 넘기면 같은 금액이 나온다', () => {
  const members = ['진주', '진우', '민재', '지현'];
  const r = compareCandidates({ products: PRODUCTS, members, budget: { type: 'total', amount: 40000 } });
  const best = r.candidates.find((c) => c.id === r.bestId);
  assert.deepEqual(computeSettlement(r.settlementInput).shares, best.shares);
  assert.equal(r.candidates.find((c) => c.id === 'c').overBudgetBy, 2900);
});

test('compareCandidates: 예산 안에 드는 상품이 없으면 bestId null + 초과액 적은 순', () => {
  const r = compareCandidates({ products: PRODUCTS, headcount: 4, budget: { type: 'perPerson', amount: 5000 } });
  assert.equal(r.bestId, null);
  assert.equal(r.settlementInput, null);
  assert.equal(r.candidates[0].id, 'a');
  assert.match(r.summary, /예산 안에 들어오는 상품이 없어요/);
});

test('normalizeSerpResult: 가격 없는 상품은 버리고 원 단위 정수로 변환', () => {
  assert.equal(normalizeSerpResult({ title: 'x' }, 0), null);
  assert.deepEqual(normalizeSerpResult({ title: ' 삼겹살 ', extracted_price: 12900.4, product_id: 'p1', source: '쿠팡' }, 0),
    { id: 'p1', name: '삼겹살', price: 12900, source: '쿠팡', link: null, thumbnail: null });
});

test('searchProducts: 키 없음 → 목 데이터', async () => {
  const r = await searchProducts('삼겹살');
  assert.equal(r.provider, 'mock');
  assert.ok(r.products.length > 0);
});

test('searchProducts: SerpApi 에러 → 목 데이터로 대체 (데모가 멈추지 않음)', async () => {
  process.env.SHOPPING_API_KEY = 'bad';
  global.fetch = async () => ({ ok: false, status: 401, json: async () => ({ error: 'Invalid API key.' }) });
  const r = await searchProducts('삼겹살');
  assert.equal(r.provider, 'mock');
  assert.match(r.fallbackReason, /Invalid API key/);
});

test('searchProducts: SerpApi 정상 응답 → gl=kr, hl=ko로 검색', async () => {
  process.env.SHOPPING_API_KEY = 'good';
  let calledUrl;
  global.fetch = async (url) => {
    calledUrl = new URL(url);
    return { ok: true, status: 200, json: async () => ({ shopping_results: [{ title: '삼겹살 1kg', extracted_price: 19900, product_id: 's1' }, { title: '가격없음' }] }) };
  };
  const r = await searchProducts('삼겹살');
  assert.equal(r.provider, 'serpapi');
  assert.equal(calledUrl.searchParams.get('gl'), 'kr');
  assert.equal(calledUrl.searchParams.get('hl'), 'ko');
  assert.deepEqual(r.products.map((p) => p.price), [19900]);
});

test('searchShopping: AI는 조건만 구조화, 금액 비교는 코드 + shopping.search 토큰 로그', async () => {
  process.env.SHOPPING_PROVIDER = 'mock';
  const calls = fakeKiln([JSON.stringify({ needsClarification: false, clarificationQuestion: null, query: '삼겹살', headcount: 4, budget: { type: 'perPerson', amount: 10000 } })]);
  const r = await searchShopping({ text: '4명이서 먹을 삼겹살, 1인 1만원 정도로 찾아줘' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].stage, 'shopping.search');
  assert.equal(r.provider, 'mock');
  assert.ok(r.candidates.length > 0);
  assert.ok(r.candidates.every((c) => Number.isInteger(c.perPerson)));
  assert.ok(r.bestId);
  assert.ok(readLog('events.jsonl').some((e) => e.type === 'shopping.search'));
});

test('searchShopping: 예산이 없으면 되묻고, 알아낸 조건은 남긴다', async () => {
  fakeKiln([JSON.stringify({ needsClarification: true, clarificationQuestion: '1인 예산은 어느 정도인가요?', query: '딸기', headcount: 3, budget: null })]);
  const r = await searchShopping({ text: '3명이서 딸기 사자' });
  assert.equal(r.needsClarification, true);
  assert.deepEqual(r.conditions, { query: '딸기', headcount: 3, budget: null });
  assert.deepEqual(r.candidates, []);
});

test('searchShopping: 현재 멤버 수와 다른 headcount는 재요청', async () => {
  process.env.SHOPPING_PROVIDER = 'mock';
  const good = { needsClarification: false, clarificationQuestion: null, query: '삼겹살', headcount: 4, budget: { type: 'total', amount: 40000 } };
  const calls = fakeKiln([JSON.stringify({ ...good, headcount: 5 }), JSON.stringify(good)]);
  const r = await searchShopping({ text: '삼겹살 4만원 이하', members: ['진주', '진우', '민재', '지현'] });
  assert.equal(calls.length, 2);
  assert.deepEqual(r.members, ['진주', '진우', '민재', '지현']);
});

test('searchShopping: conditions를 직접 주면 AI 호출 없음 (0 tokens)', async () => {
  process.env.SHOPPING_PROVIDER = 'mock';
  const calls = fakeKiln(['{}']);
  const r = await searchShopping({ conditions: { query: '과일 딸기', headcount: 3, budget: { type: 'total', amount: 20000 } } });
  assert.equal(calls.length, 0);
  assert.equal(r.candidates[0].name, '제철 딸기 1kg');
  assert.equal(r.candidates[0].withinBudget, true);
});
