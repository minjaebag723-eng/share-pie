'use strict';

require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { calculateSettlement, computeSettlement, SettlementInputError } = require('../src/settlement/calculateSettlement');

const FOUR = ['진주', '진우', '민재', '지현'];
const sum = (a) => a.reduce((x, y) => x + y, 0);

test('ADJUST: 삼겹살 35,900원, 진주 5,000원 적게 → UI 샘플 인증서와 동일', () => {
  const r = computeSettlement({ members: FOUR, mode: 'ADJUST', itemName: '삼겹살', total: 35900, adjustments: { 진주: -5000 } });
  assert.deepEqual(r.shares, [5225, 10225, 10225, 10225]);
  assert.equal(r.rule, '진주 5,000원 감면 후 4인 분담');
  assert.equal(r.modeLabel, '차등 분배');
});

test('ADJUST: 더 내기(+)도 지원', () => {
  const r = computeSettlement({ members: FOUR, mode: 'ADJUST', total: 40000, adjustments: { 진우: 4000 } });
  assert.deepEqual(r.shares, [9000, 13000, 9000, 9000]);
  assert.match(r.rule, /진우 4,000원 추가/);
});

test('EQUAL: 486,000원 4명 → 121,500원씩 / 10,000원 3명 → 1원은 최대잉여법', () => {
  assert.deepEqual(computeSettlement({ members: FOUR, mode: 'EQUAL', total: 486000 }).shares, [121500, 121500, 121500, 121500]);
  assert.deepEqual(computeSettlement({ members: ['a', 'b', 'c'], mode: 'EQUAL', total: 10000 }).shares, [3334, 3333, 3333]);
});

test('EQUAL + "지현 빼고": 빠진 멤버는 0원, members 평행 배열 유지', () => {
  const r = computeSettlement({ members: FOUR, mode: 'EQUAL', total: 30000, participants: ['진주', '진우', '민재'] });
  assert.deepEqual(r.shares, [10000, 10000, 10000, 0]);
  assert.equal(r.rule, '3인 균등 분담 (지현 제외)');
});

test('RATIO: 말하지 않은 사람은 (100 - 말한 비율)을 똑같이', () => {
  const r = computeSettlement({ members: FOUR, mode: 'RATIO', total: 100000, ratios: { 진주: 40 } });
  assert.deepEqual(r.ratios, { 진주: 40, 진우: 20, 민재: 20, 지현: 20 });
  assert.deepEqual(r.shares, [40000, 20000, 20000, 20000]);
});

test('RATIO: 말한 비율이 100% 이상인데 남은 사람이 있으면 에러 (0원 몫 방지)', () => {
  assert.throws(() => computeSettlement({ members: FOUR, mode: 'RATIO', total: 1000, ratios: { 진주: 60, 진우: 40 } }), SettlementInputError);
});

test('ITEM: 품목별 참여자끼리 나눈 뒤 합산, total은 코드가 합산', () => {
  const r = computeSettlement({
    members: FOUR,
    mode: 'ITEM',
    items: [
      { name: '숙소', price: 200000 },
      { name: '식비', price: 80000, participants: ['진주', '민재', '지현'] },
    ],
    totalBudget: 300000,
  });
  assert.equal(r.total, 280000);
  assert.deepEqual(r.shares, [76667, 50000, 76667, 76666]);
  assert.equal(r.withinBudget, true);
  assert.equal(r.rule, '항목별 분담 (숙소: 전원, 식비: 진주·민재·지현)');
});

test('예산 초과 감지', () => {
  const r = computeSettlement({ members: FOUR, mode: 'EQUAL', total: 320000, totalBudget: 300000 });
  assert.equal(r.withinBudget, false);
  assert.equal(r.overBudgetBy, 20000);
});

test('잘못된 입력은 SettlementInputError', () => {
  const bad = [
    { members: [], mode: 'EQUAL', total: 1000 },
    { members: ['a', 'a'], mode: 'EQUAL', total: 1000 },
    { members: FOUR, mode: 'SPLIT', total: 1000 },
    { members: FOUR, mode: 'EQUAL', total: 1000.5 },
    { members: FOUR, mode: 'EQUAL', total: 1000, participants: ['철수'] },
    { members: FOUR, mode: 'ITEM', items: [] },
    { members: FOUR, mode: 'ITEM', items: [{ name: '술', price: 1000, participants: ['철수'] }] },
    { members: FOUR, mode: 'RATIO', total: 1000, ratios: { 진주: -10 } },
    { members: FOUR, mode: 'ADJUST', total: 1000, adjustments: { 진주: -5000 } },
    { members: FOUR, mode: 'ADJUST', total: 1000, adjustments: {} },
    { members: FOUR, mode: 'EQUAL', total: 1000, payer: '철수' },
  ];
  bad.forEach((input) => assert.throws(() => computeSettlement(input), SettlementInputError, JSON.stringify(input)));
});

test('calculateSettlement는 settlement.calculate 0 tokens(code-only)를 로그에 남김', () => {
  const { readLog } = require('./helpers');
  calculateSettlement({ members: FOUR, mode: 'EQUAL', total: 4000 });
  const last = readLog('token-usage.jsonl').at(-1);
  assert.equal(last.stage, 'settlement.calculate');
  assert.equal(last.totalTokens, 0);
  assert.equal(last.note, 'code-only');
});

// ── UI 계산 엔진과의 일치 검증 ─────────────────────────────────────────────
// 저장소 루트의 최신 Share*.html에서 calc* 함수들을 그대로 꺼내 실행해, 백엔드 결과와 1원까지 비교한다.
// (UI 확인 카드에서 본 금액 = 서버가 승인 때 다시 계산한 금액이어야 하므로)
function loadUiEngine() {
  const root = path.join(__dirname, '..', '..');
  const files = fs.readdirSync(root).filter((f) => /^share.*\.html$/i.test(f))
    .map((f) => ({ f, t: fs.statSync(path.join(root, f)).mtimeMs })).sort((a, b) => b.t - a.t);
  if (!files.length) return null;
  const html = fs.readFileSync(path.join(root, files[0].f), 'utf8');
  const start = html.indexOf('  parseAmount(input){');
  const end = html.indexOf('  parseSettlementText(');
  if (start === -1 || end === -1) return null;
  const body = html.slice(start, end).replace(/\/\/ =+[\s\S]*?(?=\n\s*parseSettlementText|$)/, '');
  return vm.runInNewContext(`(class { parseWon(){ return 0; } ${body} })`);
}

test('UI 계산 엔진(Share*.html)과 무작위 1,000건 결과 일치', (t) => {
  const Engine = loadUiEngine();
  if (!Engine) return t.skip('UI 파일에서 계산 엔진을 찾지 못함');
  const ui = new Engine();
  const rnd = (n) => Math.floor(Math.random() * n);

  for (let k = 0; k < 1000; k++) {
    const n = 2 + rnd(7);
    const members = Array.from({ length: n }, (_, i) => `m${i}`);
    const participants = members.filter((_, i) => i < 2 || Math.random() < 0.8);
    const total = 1000 + rnd(500000);
    const mode = ['EQUAL', 'RATIO', 'ADJUST', 'ITEM'][k % 4];
    let input;
    let runUi;
    if (mode === 'EQUAL') {
      input = { members, mode, total, participants };
      runUi = () => ui.calcEqual(participants, total);
    } else if (mode === 'RATIO') {
      const ratios = {};
      participants.forEach((p) => { ratios[p] = 1 + rnd(60); });
      input = { members, mode, total, participants, ratios };
      runUi = () => ui.calcRatio(participants, ratios, total);
    } else if (mode === 'ADJUST') {
      const adjustments = { [participants[0]]: -(1 + rnd(Math.floor(total / participants.length))) };
      if (Math.random() < 0.5) adjustments[participants[1]] = 1 + rnd(5000);
      input = { members, mode, total, participants, adjustments };
      runUi = () => ui.calcAdjust(participants, adjustments, total);
    } else {
      const items = Array.from({ length: 1 + rnd(4) }, (_, i) => ({ name: `item${i}`, price: 1000 + rnd(200000), participants: participants.filter((_, j) => j === 0 || Math.random() < 0.7) }));
      input = { members, mode, participants, items };
      runUi = () => ui.calcItem(participants, items).results;
    }

    let uiResults;
    try {
      uiResults = runUi();
    } catch (uiErr) {
      // UI가 거부하는 입력(예: 조정액이 너무 큼)은 백엔드도 거부해야 일치
      assert.throws(() => computeSettlement(input), SettlementInputError, `UI만 거부: ${uiErr.message} ${JSON.stringify(input)}`);
      continue;
    }
    const expected = members.map((m) => { const r = uiResults.find((x) => x.name === m); return r ? r.amount : 0; });
    const r = computeSettlement(input);
    assert.deepEqual(r.shares, expected, `${mode} ${JSON.stringify(input)}`);
    assert.equal(sum(r.shares), r.total);
  }
});
