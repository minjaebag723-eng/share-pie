'use strict';

// 실제 OpenAI SDK → 가짜 Kiln HTTP 서버로 전체 API 흐름 검증
// 가짜 서버는 Kiln 공식 문서의 동작을 흉내 냄: response_format → 빈 응답, 서비스 안 하는 모델 → 404 model_not_found
const { readLog } = require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');

const FOUR = ['진주', '진우', '민재', '지현'];
const SERVED_MODELS = ['qwen3-32b', 'deepseek-v4.1-flash'];
const kilnRequests = [];
let nextReplies = [];

const fakeKilnServer = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', () => {
    const parsed = JSON.parse(body);
    kilnRequests.push({ url: req.url, auth: req.headers.authorization, body: parsed });
    res.setHeader('Content-Type', 'application/json');
    if (!SERVED_MODELS.includes(parsed.model)) {
      res.statusCode = 404;
      return res.end(JSON.stringify({ error: { message: `model ${parsed.model} not found`, type: 'invalid_request_error', code: 'model_not_found' } }));
    }
    const content = parsed.response_format ? '' : (nextReplies.shift() ?? '{}');
    res.end(JSON.stringify({
      id: 'x', object: 'chat.completion', model: parsed.model,
      choices: [{ index: 0, message: { role: 'assistant', content }, finish_reason: 'stop' }],
      usage: { prompt_tokens: 120, completion_tokens: 45, total_tokens: 165, cost: 0.0003 },
    }));
  });
});

let app;
let base;
let server;

test.before(async () => {
  await new Promise((r) => fakeKilnServer.listen(0, r));
  process.env.KILN_API_KEY = 'sk-bk-test';
  process.env.KILN_BASE_URL = `http://127.0.0.1:${fakeKilnServer.address().port}/v1`;
  process.env.KILN_MODEL = 'qwen3-32b';
  app = require('../src/server');
  server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  base = `http://127.0.0.1:${server.address().port}`;
});

test.after(() => {
  server.close();
  fakeKilnServer.close();
});

async function post(path, body, raw = false) {
  const res = await fetch(base + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: raw ? body : JSON.stringify(body) });
  return { status: res.status, body: await res.json() };
}

test('POST /settlement/analyze: Kiln 스펙대로 호출 + 토큰 로그 + UI 모양 응답', async () => {
  nextReplies = [JSON.stringify({
    needsClarification: false, clarificationQuestion: null, mode: 'ADJUST', itemName: '삼겹살', total: 35900,
    participants: 'all', ratios: null, adjustments: { 진주: -5000 }, items: null,
    members: FOUR, totalBudget: null, payer: '진주',
  })];
  const r = await post('/settlement/analyze', { text: '삼겹살 35,900원, 진주는 5천원 적게 내고 나머지 세 명이 나눠줘. 진주가 결제했어.', previousState: { members: FOUR } });
  assert.equal(r.status, 200);
  assert.deepEqual(r.body.shares, [5225, 10225, 10225, 10225]);
  assert.equal(r.body.confirmData.mode, 'ADJUST');

  assert.equal(kilnRequests.length, 1);
  assert.equal(kilnRequests[0].body.response_format, undefined); // Kiln 미지원 → 절대 보내지 않음
  assert.equal(kilnRequests[0].url, '/v1/chat/completions');
  assert.equal(kilnRequests[0].auth, 'Bearer sk-bk-test');
  assert.equal(kilnRequests[0].body.model, 'qwen3-32b');

  const tokenLog = readLog('token-usage.jsonl');
  const analyze = tokenLog.filter((t) => t.stage === 'settlement.analyze' && t.ok);
  assert.equal(analyze.at(-1).promptTokens, 120);
  assert.equal(analyze.at(-1).completionTokens, 45);
  assert.equal(analyze.at(-1).cost, 0.0003);
  assert.ok(tokenLog.some((t) => t.stage === 'settlement.calculate' && t.note === 'code-only'));
});

test('POST /settlement/explain → /settlement/approve: 인증서가 UI 모양 그대로', async () => {
  const settlement = { members: FOUR, mode: 'ADJUST', itemName: '삼겹살', total: 35900, adjustments: { 진주: -5000 }, totalBudget: null, payer: '진주' };
  const calc = await post('/settlement/calculate', settlement);
  assert.equal(calc.status, 200);

  nextReplies = [JSON.stringify({ explanation: '진주 5,000원 감면 후 4인 분담으로 진주 5,225원, 나머지는 10,225원씩이에요.' })];
  const ex = await post('/settlement/explain', { calculatedResult: calc.body });
  assert.equal(ex.status, 200);
  assert.equal(ex.body.fallback, false);

  const notAll = await post('/settlement/approve', { settlementId: 'g1', title: '삼겹살 공동구매', settlement, approvals: [true, true, false, true] });
  assert.equal(notAll.status, 409);
  assert.equal(notAll.body.error.code, 'NOT_ALL_APPROVED');

  const ok = await post('/settlement/approve', { settlementId: 'g1', title: '삼겹살 공동구매', settlement, approvals: [true, true, true, true] });
  assert.equal(ok.status, 200);
  const { cert, group, onchain } = ok.body;
  assert.deepEqual(Object.keys(cert), ['id', 'kind', 'title', 'date', 'rows', 'hash', 'block', 'rule']);
  assert.equal(cert.kind, 'cert');
  assert.deepEqual(cert.rows, [['진주', 5225], ['진우', 10225], ['민재', 10225], ['지현', 10225]]);
  assert.match(cert.hash, /^0x[0-9a-f]{64}$/);
  assert.match(cert.block, /^#[\d,]+$/);
  assert.match(cert.date, /^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$/);
  assert.equal(cert.rule, '진주 5,000원 감면 후 4인 분담');
  assert.deepEqual(group, { members: FOUR, shares: [5225, 10225, 10225, 10225], approvals: [true, true, true, true], status: '정산 완료', cert: cert.id });
  assert.equal(onchain.mock, true);
  assert.equal(onchain.locks.length, 3); // payer(진주) 제외
});

test('POST /settlement/approve: UI 정산 폼 방식(members/shares 직접) + 형식 검증', async () => {
  const ok = await post('/settlement/approve', { settlementId: 'g9', title: '브런치', approvals: [true, true, true], members: ['진주', '서연', '하린'], shares: [28000, 28000, 28000], payer: '진주', rule: '3인 균등 분담' });
  assert.equal(ok.status, 200);
  assert.deepEqual(ok.body.cert.rows, [['진주', 28000], ['서연', 28000], ['하린', 28000]]);
  assert.equal(ok.body.cert.rule, '3인 균등 분담');
  const bad = await post('/settlement/approve', { settlementId: 'g9', title: '브런치', approvals: [true, true], members: ['진주', '서연'], shares: [100.5, 3], payer: '진주' });
  assert.equal(bad.status, 400);
});

test('GET /: UI 화면을 보여주고, .env 같은 다른 파일은 절대 노출하지 않음', async () => {
  const home = await fetch(base + '/');
  assert.equal(home.status, 200);
  assert.match(await home.text(), /data-dc-script/);
  assert.equal((await fetch(base + '/support.js')).status, 200);
  for (const p of ['/backend/.env', '/.env', '/assets/../backend/.env', '/assets/%2e%2e/backend/.env', '/CLAUDE.md']) {
    const r = await fetch(base + p);
    assert.notEqual(r.status, 200, p);
  }
});

test('POST /settlement/approve: payer 없음 = Pie 에스크로가 전원 분담금 수령 / 예산 초과는 진행 불가', async () => {
  const base = { members: FOUR, mode: 'EQUAL', total: 40000 };
  const escrow = await post('/settlement/approve', { settlementId: 'g', title: 't', settlement: { ...base, payer: null }, approvals: [true, true, true, true] });
  assert.equal(escrow.status, 200);
  assert.equal(escrow.body.onchain.viaEscrow, true);
  assert.equal(escrow.body.onchain.recipient, 'SharePie 정산 에스크로');
  assert.equal(escrow.body.onchain.locks.length, 4); // 요청자 포함 전원 잠금
  assert.ok(escrow.body.onchain.locks.every((l) => l.to === 'SharePie 정산 에스크로' && l.amount === 10000));
  const over = await post('/settlement/approve', { settlementId: 'g', title: 't', settlement: { ...base, payer: '진주', totalBudget: 30000 }, approvals: [true, true, true, true] });
  assert.equal(over.status, 409);
  assert.equal(over.body.error.code, 'OVER_BUDGET');
});

test('에러 응답은 항상 { error: { code, message } }', async () => {
  const badJson = await post('/settlement/calculate', '{oops', true);
  assert.deepEqual([badJson.status, badJson.body.error.code], [400, 'INVALID_JSON']);
  const badCalc = await post('/settlement/calculate', { members: FOUR, mode: 'ITEM', items: [] });
  assert.deepEqual([badCalc.status, badCalc.body.error.code], [400, 'INVALID_SETTLEMENT_INPUT']);
  const emptyText = await post('/settlement/analyze', { text: '' });
  assert.deepEqual([emptyText.status, emptyText.body.error.code], [400, 'INVALID_INPUT']);
  const notImpl = await post('/dispute/raise', {});
  assert.equal(notImpl.status, 501);
  const nf = await post('/nope', {});
  assert.equal(nf.status, 404);
});

test('서비스 안 하는 모델(gpt-oss-120b 등)이면 502 KILN_API_ERROR + model_not_found 안내', async () => {
  process.env.KILN_MODEL = 'gpt-oss-120b';
  try {
    const r = await post('/settlement/analyze', { text: '삼겹살 38,900원 4명', previousState: { members: FOUR } });
    assert.equal(r.status, 502);
    assert.equal(r.body.error.code, 'KILN_API_ERROR');
    assert.match(r.body.error.message, /404/);
  } finally {
    process.env.KILN_MODEL = 'qwen3-32b';
  }
});

test('GET /logs/tokens: 흐름별 합계', async () => {
  const res = await fetch(base + '/logs/tokens');
  const s = await res.json();
  assert.ok(s['settlement.analyze'].promptTokens >= 120);
  assert.equal(s['settlement.calculate'].totalTokens, 0);
  assert.ok(s['settlement.calculate'].calls >= 1);
});
