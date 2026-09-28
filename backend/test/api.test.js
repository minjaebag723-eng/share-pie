'use strict';

// 실제 OpenAI SDK → 가짜 Kiln HTTP 서버로 전체 API 흐름 검증
// 가짜 서버는 Kiln 공식 문서의 동작을 흉내 냄: response_format → 빈 응답, 서비스 안 하는 모델 → 404 model_not_found
const { readLog } = require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('http');

process.env.SETTLEMENT_STORE_DIR = process.env.LOG_DIR; // approve가 쓰는 정산 저장소도 임시 폴더로

const FOUR = ['u0', 'u1', 'u2', 'u3']; // uid — /settlement/approve는 MOCK 포함 uid만 허용
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
    participants: 'all', ratios: null, adjustments: { u0: -5000 }, items: null,
    members: FOUR, totalBudget: null, payer: 'u0',
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
  const settlement = { members: FOUR, mode: 'ADJUST', itemName: '삼겹살', total: 35900, adjustments: { u0: -5000 }, totalBudget: null, payer: 'u0' };
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
  assert.deepEqual(Object.keys(cert), ['id', 'kind', 'title', 'date', 'rows', 'hash', 'block', 'rule', 'conditionsHash']);
  assert.match(cert.conditionsHash, /^0x[0-9a-f]{64}$/);
  assert.equal(onchain.conditionsHash, cert.conditionsHash);
  assert.equal(typeof onchain.conditionsCanonical, 'string');
  assert.equal(cert.kind, 'cert');
  assert.deepEqual(cert.rows, [['u0', 5225], ['u1', 10225], ['u2', 10225], ['u3', 10225]]); // rows는 uid 기준 — UI가 이름으로 표시
  assert.match(cert.hash, /^0x[0-9a-f]{64}$/);
  assert.match(cert.block, /^#[\d,]+$/);
  assert.match(cert.date, /^\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}$/);
  assert.equal(cert.rule, 'u0 5,000원 감면 후 4인 분담'); // TODO(uid 전환): 이름 표시는 analyze/approve 입력을 uid+이름으로 바꾼 뒤
  assert.deepEqual(group, { members: FOUR, shares: [5225, 10225, 10225, 10225], approvals: [true, true, true, true], status: '정산 완료', cert: cert.id });
  assert.equal(onchain.mock, true);
  assert.equal(onchain.locks.length, 3); // payer(u0) 제외
  assert.deepEqual(onchain.locks.map((l) => l.from), ['u1', 'u2', 'u3']); // locks[].from은 uid 그대로
  // 보류형 에스크로: 승인 시점에는 잠금 확정(confirm)까지만. 인증서 TxHash = confirm, 지급(release)은 보류 뒤 /settlement/release
  assert.equal(onchain.state, 'LOCKED');
  assert.equal(onchain.release, null);
  assert.equal(typeof onchain.holdUntil, 'number');
  assert.match(onchain.settlementOnchainId, /^0x[0-9a-f]{64}$/);
  assert.equal(cert.hash, onchain.confirm.txHash);
  assert.equal(cert.block, onchain.confirm.block);
  assert.equal(onchain.confirm.txHash, onchain.locks[onchain.locks.length - 1].txHash);
});

test('POST /settlement/approve: UI 정산 폼 방식(members/shares 직접) + 형식 검증', async () => {
  const ok = await post('/settlement/approve', { settlementId: 'g9', title: '브런치', approvals: [true, true, true], members: ['u0', 'u4', 'u6'], shares: [28000, 28000, 28000], payer: 'u0', rule: '3인 균등 분담' });
  assert.equal(ok.status, 200);
  assert.deepEqual(ok.body.cert.rows, [['u0', 28000], ['u4', 28000], ['u6', 28000]]);
  assert.equal(ok.body.cert.rule, '3인 균등 분담');
  const bad = await post('/settlement/approve', { settlementId: 'g9', title: '브런치', approvals: [true, true], members: ['u0', 'u4'], shares: [100.5, 3], payer: 'u0' });
  assert.equal(bad.status, 400);
  // 표시 이름을 멤버로 넘기면 MOCK에서도 거부 (동명이인 지갑 충돌 방지)
  const named = await post('/settlement/approve', { settlementId: 'g9', title: '브런치', approvals: [true, true], members: ['진주', '서연'], shares: [1000, 1000], payer: null });
  assert.equal(named.status, 400);
  assert.equal(named.body.error.code, 'INVALID_MEMBER_UID');
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
  const over = await post('/settlement/approve', { settlementId: 'g', title: 't', settlement: { ...base, payer: 'u0', totalBudget: 30000 }, approvals: [true, true, true, true] });
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
  const noId = await post('/dispute/raise', {}); // settlementOnchainId 없음 → 입력 검증 에러
  assert.deepEqual([noId.status, noId.body.error.code], [400, 'INVALID_INPUT']);
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
