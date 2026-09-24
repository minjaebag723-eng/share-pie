'use strict';

const { fakeKiln, restoreKiln, readLog } = require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const { extractJson } = require('../src/kilnClient');
const { interpretConditions } = require('../src/agents/interpretConditions');
const { explainSettlement } = require('../src/agents/explainSettlement');
const { investigateDispute } = require('../src/agents/investigateDispute');
const { computeSettlement } = require('../src/settlement/calculateSettlement');

const FOUR = ['진주', '진우', '민재', '지현'];
const j = (o) => JSON.stringify(o);

test.afterEach(() => restoreKiln());

// ---------------------------------------------------------------- JSON 추출
test('extractJson: <think>, 코드펜스, 앞뒤 잡담이 있어도 JSON만 꺼냄', () => {
  assert.deepEqual(extractJson('<think>계산해보자</think>\n```json\n{"a":1}\n```'), { a: 1 });
  assert.deepEqual(extractJson('결과입니다: {"a":{"b":2}} 끝'), { a: { b: 2 } });
  assert.throws(() => extractJson(''));
  assert.throws(() => extractJson('[1,2]'));
  assert.throws(() => extractJson('JSON 없음'));
});

// ------------------------------------------------------- interpretConditions
// 새 UI 확인 카드 모양: { mode, itemName, total, participants, ratios, adjustments, items }
const AI_OK = {
  needsClarification: false,
  clarificationQuestion: null,
  mode: 'ITEM',
  itemName: '여러 품목',
  total: null,
  participants: 'all',
  ratios: null,
  adjustments: null,
  items: [
    { name: '숙소', price: 200000, participants: 'all' },
    { name: '렌터카', price: 120000, participants: 'all' },
    { name: '식비', price: 80000, participants: ['진주', '민재', '지현'] },
  ],
  members: ['진우', '진주', '민재', '지현'], // AI가 순서를 바꿔도
  totalBudget: 400000,
  payer: null,
};
const ITEM_SHARES = [106667, 80000, 106667, 106666];
const ADJ = { needsClarification: false, clarificationQuestion: null, mode: 'ADJUST', itemName: '삼겹살', total: 35900, participants: 'all', ratios: null, adjustments: { 진주: -5000 }, items: null, members: FOUR, totalBudget: null, payer: null };

test('interpretConditions: 응답 스키마(confirmData) + 코드가 계산한 shares + UI 순서 유지', async () => {
  const calls = fakeKiln(['```json\n' + j(AI_OK) + '\n```']);
  const r = await interpretConditions('숙소 20만원이랑 렌터카 12만원은 4명이 똑같이, 식비 8만원은 진우 빼고. 40만원 넘으면 안 돼.', { members: FOUR });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].stage, 'settlement.analyze');
  assert.deepEqual(Object.keys(r), ['needsClarification', 'clarificationQuestion', 'confirmData', 'members', 'shares', 'totalBudget', 'payer', 'calculation']);
  assert.deepEqual(Object.keys(r.confirmData), ['mode', 'itemName', 'total', 'participants', 'ratios', 'adjustments', 'items']);
  assert.equal(r.confirmData.total, 400000); // ITEM 합계는 코드가 계산
  assert.deepEqual(r.confirmData.items[2], { name: '식비', price: 80000, participants: ['진주', '민재', '지현'] });
  assert.deepEqual(r.members, FOUR); // 그룹 순서 그대로 (approvals와 인덱스 일치)
  assert.deepEqual(r.shares, ITEM_SHARES);
  assert.equal(r.calculation.withinBudget, true);
});

test('interpretConditions: ADJUST — "진주 5천원 적게" → UI 샘플과 같은 금액', async () => {
  fakeKiln([j(ADJ)]);
  const r = await interpretConditions('삼겹살 35,900원, 진주는 5천원 적게 내고 나머지 세 명이 나눠줘', { members: FOUR });
  assert.deepEqual(r.confirmData.adjustments, { 진주: -5000 });
  assert.deepEqual(r.shares, [5225, 10225, 10225, 10225]);
});

test('interpretConditions: RATIO — 말한 사람 비율만 받고 나머지는 코드가 채움', async () => {
  fakeKiln([j({ ...ADJ, mode: 'RATIO', total: 100000, adjustments: null, ratios: { 진주: 40 } })]);
  const r = await interpretConditions('10만원, 진주 40% 나머지 균등', { members: FOUR });
  assert.deepEqual(r.confirmData.ratios, { 진주: 40, 진우: 20, 민재: 20, 지현: 20 });
  assert.deepEqual(r.shares, [40000, 20000, 20000, 20000]);
});

test('interpretConditions: EQUAL + "지현 빼고" → 지현 0원', async () => {
  fakeKiln([j({ ...ADJ, mode: 'EQUAL', total: 30000, adjustments: null, participants: ['진주', '진우', '민재'] })]);
  const r = await interpretConditions('3만원 지현 빼고 나눠줘', { members: FOUR });
  assert.deepEqual(r.confirmData.participants, ['진주', '진우', '민재']);
  assert.deepEqual(r.shares, [10000, 10000, 10000, 0]);
});

test('interpretConditions: JSON 파싱 실패 → 에러 로그 + 재요청', async () => {
  const calls = fakeKiln(['네, 정리해 드릴게요!', j(AI_OK)]);
  const r = await interpretConditions('조건', { members: FOUR });
  assert.equal(calls.length, 2);
  assert.match(calls[1].messages.at(-1).content, /JSON 파싱 실패/);
  assert.equal(r.needsClarification, false);
  assert.ok(readLog('events.jsonl').some((e) => e.type === 'ai.parse_error'));
});

test('interpretConditions: 없는 멤버를 넣으면 재요청, 끝까지 틀리면 AI_OUTPUT_INVALID', async () => {
  const bad = { ...AI_OK, members: ['진주', '진우', '민재', '철수'] };
  const calls = fakeKiln([j(bad)]);
  await assert.rejects(interpretConditions('조건', { members: FOUR }), (e) => e.code === 'AI_OUTPUT_INVALID');
  assert.equal(calls.length, 4); // 최초 1 + 재요청 3
});

test('interpretConditions: mode 밖의 값, total 없는 EQUAL은 재요청', async () => {
  const calls = fakeKiln([j({ ...ADJ, mode: 'SPLIT' }), j({ ...ADJ, mode: 'EQUAL', total: null, adjustments: null }), j(ADJ)]);
  const r = await interpretConditions('조건', { members: FOUR });
  assert.equal(calls.length, 3);
  assert.match(calls[1].messages.at(-1).content, /mode는/);
  assert.match(calls[2].messages.at(-1).content, /total은/);
  assert.equal(r.confirmData.mode, 'ADJUST');
});

test('interpretConditions: AI가 shares를 지어내도 무시하고 코드 값 사용', async () => {
  fakeKiln([j({ ...AI_OK, shares: [1, 2, 3, 4] })]);
  const r = await interpretConditions('조건', { members: FOUR });
  assert.deepEqual(r.shares, ITEM_SHARES);
});

test('interpretConditions: 모호하면 되묻기, 직전 금액은 유지', async () => {
  fakeKiln([j({ needsClarification: true, clarificationQuestion: "'조금 더'가 정확히 몇 원인가요?" })]);
  const prev = { members: FOUR, shares: [100, 200, 300, 400], confirmData: { mode: 'EQUAL', total: 1000 }, totalBudget: null, payer: null };
  const r = await interpretConditions('진우는 조금 더 내', prev);
  assert.equal(r.needsClarification, true);
  assert.equal(r.clarificationQuestion, "'조금 더'가 정확히 몇 원인가요?");
  assert.deepEqual(r.shares, [100, 200, 300, 400]);
  assert.deepEqual(r.confirmData, { mode: 'EQUAL', total: 1000 });
  assert.equal(r.calculation, null);
});

test('interpretConditions: 다턴 — 이전 confirmData를 AI에 넘기고 변경 반영', async () => {
  fakeKiln([j({ ...ADJ, mode: 'EQUAL', adjustments: null })]);
  const first = await interpretConditions('삼겹살 35,900원 다같이 나눠줘', { members: FOUR });
  const calls = fakeKiln([j(ADJ)]);
  const r = await interpretConditions('아, 진주는 5천원 적게 내자', first);
  const sent = JSON.parse(calls[0].messages[1].content);
  assert.equal(sent['이전 상태'].mode, 'EQUAL');
  assert.equal(sent['이전 상태'].total, 35900);
  assert.equal(r.confirmData.mode, 'ADJUST');
  assert.equal(r.shares.reduce((a, b) => a + b, 0), 35900);
});

test('interpretConditions: 조정액이 너무 커서 계산 불가 → 되묻기로 전환', async () => {
  fakeKiln([j({ ...ADJ, adjustments: { 진우: -900000 } })]);
  const r = await interpretConditions('진우 90만원 빼줘', { members: FOUR });
  assert.equal(r.needsClarification, true);
  assert.match(r.clarificationQuestion, /0원보다 작아져요/);
});

test('interpretConditions: 빈 text는 400 InputError', async () => {
  await assert.rejects(interpretConditions('  ', null), (e) => e.status === 400);
});

// --------------------------------------------------------- explainSettlement
const CALC = computeSettlement({ members: FOUR, mode: 'ADJUST', itemName: '삼겹살', total: 35900, adjustments: { 진주: -5000 }, totalBudget: 40000 });

test('explainSettlement: 계산 결과에 있는 숫자만 쓰면 통과', async () => {
  const text = '삼겹살 총 35,900원을 진주님 5,000원 감면 후 4인 분담으로 나눴어요. 진주 5,225원, 나머지 세 분은 10,225원씩이에요. 예산 40,000원 안이에요.';
  const calls = fakeKiln([j({ explanation: text })]);
  const r = await explainSettlement(CALC);
  assert.equal(calls[0].stage, 'settlement.explain');
  assert.deepEqual(r, { explanation: text, fallback: false });
});

test('explainSettlement: AI가 없는 금액을 쓰면 재요청, 계속 틀리면 코드 템플릿으로 대체', async () => {
  const calls = fakeKiln([j({ explanation: '1인당 8,975원이에요.' })]);
  const r = await explainSettlement(CALC);
  assert.equal(calls.length, 4);
  assert.match(calls[1].messages.at(-1).content, /8,975/);
  assert.equal(r.fallback, true);
  assert.match(r.explanation, /진주 5,225원/);
});

test('explainSettlement: "만/천" 표기 금지', async () => {
  const calls = fakeKiln([j({ explanation: '총 3만 5천9백원이에요.' }), j({ explanation: '총 35,900원이에요.' })]);
  const r = await explainSettlement(CALC);
  assert.equal(calls.length, 2);
  assert.equal(r.fallback, false);
});

// -------------------------------------------------------- investigateDispute
const PLAN = { members: FOUR, shares: [45000, 45000, 45000, 45000], payer: '진우' };
const OK_APPROVALS = [
  { from: '진주', to: '진우', amount: 45000, txHash: '0xa1' },
  { from: '민재', to: '진우', amount: 45000, txHash: '0xa2' },
  { from: '지현', to: '진우', amount: 45000, txHash: '0xa3' },
];

test('investigateDispute: 송금 단계 불일치 → GENUINE_ERROR, 금액은 코드가 채움', async () => {
  const transfers = [
    { from: '진주', to: '진우', amount: 4500, txHash: '0xb1' },
    { from: '민재', to: '진우', amount: 45000, txHash: '0xb2' },
    { from: '지현', to: '진우', amount: 45000, txHash: '0xb3' },
  ];
  const calls = fakeKiln([
    j({ verdict: 'NORMAL_APPROVAL', explanation: '문제 없어요.' }), // 사실과 모순 → 거부
    j({ verdict: 'GENUINE_ERROR', explanation: '진우님에게 45,000원을 보내야 했지만 실제로는 4,500원만 송금되어 40,500원 부족합니다.' }),
  ]);
  const r = await investigateDispute({ text: '4명 균등' }, PLAN, OK_APPROVALS, transfers, { raisedBy: '진우', reason: '돈이 덜 들어왔어요' });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].stage, 'dispute.investigate');
  assert.deepEqual(Object.keys(r), ['verdict', 'mismatchDetected', 'mismatchPoint', 'expectedAmount', 'actualAmount', 'explanation']);
  assert.equal(r.verdict, 'GENUINE_ERROR');
  assert.equal(r.mismatchDetected, true);
  assert.equal(r.mismatchPoint, '송금 단계');
  assert.equal(r.expectedAmount, 45000);
  assert.equal(r.actualAmount, 4500);
});

test('investigateDispute: 기록이 모두 일치 → GENUINE_ERROR 금지, 3개 밖 판정 금지', async () => {
  const calls = fakeKiln([
    j({ verdict: 'GENUINE_ERROR', explanation: '오류' }),
    j({ verdict: 'REFUND', explanation: '환불' }),
    j({ verdict: 'BAD_FAITH_DISPUTE', explanation: '승인 기록과 송금 기록이 모두 45,000원으로 일치하는데 승인한 적 없다고 주장하셨어요.' }),
  ]);
  const r = await investigateDispute(null, PLAN, OK_APPROVALS, OK_APPROVALS, { raisedBy: '진주', reason: '나는 승인한 적 없음' });
  assert.equal(calls.length, 3);
  assert.equal(r.verdict, 'BAD_FAITH_DISPUTE');
  assert.equal(r.mismatchDetected, false);
  assert.equal(r.mismatchPoint, null);
});

test('investigateDispute: 최초요청으로 재계산한 금액과 정산안이 다르면 계산 단계 불일치', async () => {
  fakeKiln([j({ verdict: 'GENUINE_ERROR', explanation: '계산 단계에서 45,000원이어야 할 금액이 40,000원으로 잡혔어요.' })]);
  const structured = { members: FOUR, mode: 'EQUAL', itemName: '숙소', total: 180000 };
  const plan = { ...PLAN, shares: [50000, 45000, 45000, 40000] };
  const r = await investigateDispute({ text: '숙소 18만원 4명', structured }, plan, OK_APPROVALS, OK_APPROVALS);
  assert.equal(r.mismatchPoint, '계산 단계');
});

test('investigateDispute: payer 없음 = Pie 에스크로 수령 → 전원(요청자 포함)의 송금을 에스크로 기준으로 비교', async () => {
  const { ESCROW_RECIPIENT } = require('../src/blockchain/blockchainClient');
  const plan = { members: FOUR, shares: [45000, 45000, 45000, 45000], payer: null };
  const recs = FOUR.map((m, i) => ({ from: m, to: ESCROW_RECIPIENT, amount: 45000, txHash: '0xe' + i }));
  const short = recs.map((r) => (r.from === '지현' ? { ...r, amount: 4500 } : r));
  fakeKiln([j({ verdict: 'GENUINE_ERROR', explanation: '지현님은 45,000원을 보내야 했지만 4,500원만 송금됐어요.' })]);
  const r = await investigateDispute(null, plan, recs, short, { raisedBy: '지현', reason: '금액이 이상해요' });
  assert.equal(r.mismatchPoint, '송금 단계');
  assert.equal(r.expectedAmount, 45000);
  assert.equal(r.actualAmount, 4500);
});

test('investigateDispute: 멤버가 아닌 payer는 400', async () => {
  await assert.rejects(investigateDispute(null, { ...PLAN, payer: '철수' }, [], []), (e) => e.status === 400);
});

// --------------------------------------------------------------- 토큰 로그
test('모든 Kiln 호출이 stage 태그와 함께 기록됨', () => {
  const { summarizeTokenUsage } = require('../src/logger');
  const s = summarizeTokenUsage();
  assert.deepEqual(Object.keys(s).slice(0, 4), ['settlement.analyze', 'settlement.calculate', 'settlement.explain', 'dispute.investigate']);
});
