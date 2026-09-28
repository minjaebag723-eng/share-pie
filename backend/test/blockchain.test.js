'use strict';

// 블록체인 입구(blockchainClient) MOCK 모드 검사 — 블록체인 환경변수 없이 실행된다
// - 멤버는 uid('u0', …)로만 받는다. 표시 이름('진주')을 넘기면 거부 (동명이인 지갑 충돌 방지)
// - MOCK 은 컨트랙트와 같은 상태 머신(LOCKED → DISPUTED → LOCKED/CANCELLED, 보류 후 RELEASED)·같은 에러 코드
// - MOCK 모드에서는 ethers를 불러오지 않는다 (npm install 전이어도 서버가 켜지는 보장)
require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');

for (const k of ['BLOCKCHAIN_RPC_URL', 'CONTRACT_ADDRESS', 'DEPLOYER_PRIVATE_KEY']) delete process.env[k];
process.env.SETTLEMENT_STORE_DIR = process.env.LOG_DIR; // 정산 저장소도 임시 폴더로
process.env.SETTLEMENT_HOLD_SECONDS = '600';

const blockchain = require('../src/blockchain/blockchainClient');
const { canonicalize, hashConditions, isConditionsHash } = require('../src/blockchain/conditionsHash');
const { approveSettlement } = require('../src/settlement/approveSettlement');
const store = require('../src/settlement/settlementStore');
const { readLog } = require('./helpers');

const UIDS = ['u0', 'u1', 'u2', 'u3'];
const SHARES = [5225, 10225, 10225, 10225];
const CONDITIONS = { members: UIDS, mode: 'ADJUST', itemName: '삼겹살', total: 35900, participants: UIDS, ratios: null, adjustments: { u0: -5000 }, items: null, totalBudget: null, payer: null };
const CHASH = hashConditions(CONDITIONS);

// ───────────────────────────────────────────── 조건 해시
test('canonicalize: 키 순서가 달라도 같은 문자열, undefined 제거·null 유지, 중첩 객체·배열 처리, 소수 금액은 에러', () => {
  const a = canonicalize({ b: 1, a: { d: [1, { z: 2, y: null }], c: 'x' } });
  const b = canonicalize({ a: { c: 'x', d: [1, { y: null, z: 2 }] }, b: 1 });
  assert.equal(a, b);
  assert.equal(a, '{"a":{"c":"x","d":[1,{"y":null,"z":2}]},"b":1}');
  assert.equal(canonicalize({ a: undefined, b: null, c: [1, undefined, 2] }), '{"b":null,"c":[1,2]}');
  assert.equal(canonicalize({ members: ['u1', 'u0'] }), '{"members":["u1","u0"]}'); // 배열 순서 유지
  assert.throws(() => canonicalize({ total: 100.5 }), (e) => e.code === 'INVALID_CONDITIONS' && /정수/.test(e.message));
  assert.throws(() => canonicalize({ total: NaN }), (e) => e.code === 'INVALID_CONDITIONS');
  assert.throws(() => hashConditions('문자열'), (e) => e.code === 'INVALID_CONDITIONS');
});

test('hashConditions: 같은 입력 → 같은 해시, 필드 하나 바꾸면 다른 해시, 0x+64hex', () => {
  assert.match(CHASH, /^0x[0-9a-f]{64}$/);
  const reordered = { payer: null, totalBudget: null, items: null, adjustments: { u0: -5000 }, ratios: null, participants: UIDS, total: 35900, itemName: '삼겹살', mode: 'ADJUST', members: UIDS };
  assert.equal(hashConditions(reordered), CHASH);
  assert.notEqual(hashConditions({ ...CONDITIONS, total: 35901 }), CHASH);
  assert.notEqual(hashConditions({ ...CONDITIONS, adjustments: { u0: -4999 } }), CHASH);
  assert.notEqual(hashConditions({ ...CONDITIONS, members: ['u0', 'u1', 'u3', 'u2'] }), CHASH); // 순서도 조건의 일부
  assert.equal(isConditionsHash(CHASH), true);
  assert.equal(isConditionsHash('0x' + '0'.repeat(64)), false);
  assert.equal(isConditionsHash('0x1234'), false);
});

// ───────────────────────────────────────────── MOCK 상태 머신
test('MOCK 모드: recordSettlementOnchain은 mock:true, LOCKED·confirm·holdUntil, release null, locks[].from·recipient에 uid 그대로', async () => {
  assert.equal(blockchain.IS_MOCK, true);
  const before = Math.floor(Date.now() / 1000);
  const r = await blockchain.recordSettlementOnchain({ settlementId: 'g1', members: UIDS, shares: SHARES, payer: null, conditionsHash: CHASH });
  assert.equal(r.mock, true);
  assert.equal(r.state, 'LOCKED');
  assert.equal(r.release, null);
  assert.equal(r.conditionsHash, CHASH);
  assert.equal(r.holdSeconds, 600); // env SETTLEMENT_HOLD_SECONDS
  assert.ok(r.holdUntil >= before + 600 && r.holdUntil <= before + 602);
  assert.equal(r.confirm.holdUntil, r.holdUntil);
  assert.equal(r.confirm.txHash, r.locks[r.locks.length - 1].txHash); // 마지막 lock = 인증서 TxHash
  assert.equal(r.viaEscrow, true);
  assert.equal(r.recipient, blockchain.ESCROW_RECIPIENT);
  assert.deepEqual(r.locks.map((l) => l.from), UIDS);
  assert.deepEqual(r.locks.map((l) => l.amount), SHARES);
  r.locks.forEach((l) => assert.match(l.txHash, /^0x[0-9a-f]{64}$/));
  assert.match(r.settlementOnchainId, /^0x[0-9a-f]{64}$/);
  assert.deepEqual(await blockchain.getSettlementState({ settlementOnchainId: r.settlementOnchainId }), {
    state: 'LOCKED', holdUntil: r.holdUntil, holdSeconds: 600, verdict: null, lockedCount: 4, participantCount: 4, totalLocked: 35900, conditionsHash: CHASH,
  });

  const withPayer = await blockchain.recordSettlementOnchain({ settlementId: 'g2', members: UIDS, shares: SHARES, payer: 'u0', conditionsHash: CHASH, holdSeconds: 0 });
  assert.equal(withPayer.viaEscrow, false);
  assert.equal(withPayer.recipient, 'u0');
  assert.equal(withPayer.holdSeconds, 0);
  assert.deepEqual(withPayer.locks.map((l) => l.from), ['u1', 'u2', 'u3']);
});

test('MOCK 상태 머신: 보류 전 release는 HOLD_NOT_ELAPSED, holdSeconds 0이면 즉시 RELEASED, 두 번 지급 INVALID_STATUS', async () => {
  const held = await blockchain.recordSettlementOnchain({ settlementId: 'h1', members: UIDS, shares: SHARES, conditionsHash: CHASH, holdSeconds: 600 });
  await assert.rejects(blockchain.releaseSettlement({ settlementOnchainId: held.settlementOnchainId }), (e) => e.code === 'HOLD_NOT_ELAPSED' && e.status === 409 && e.holdUntil === held.holdUntil);

  const quick = await blockchain.recordSettlementOnchain({ settlementId: 'h2', members: UIDS, shares: SHARES, conditionsHash: CHASH, holdSeconds: 0 });
  const rel = await blockchain.releaseSettlement({ settlementOnchainId: quick.settlementOnchainId });
  assert.equal(rel.state, 'RELEASED');
  assert.equal(rel.amount, 35900);
  assert.match(rel.txHash, /^0x[0-9a-f]{64}$/);
  await assert.rejects(blockchain.releaseSettlement({ settlementOnchainId: quick.settlementOnchainId }), (e) => e.code === 'INVALID_STATUS' && e.state === 'RELEASED');
  await assert.rejects(blockchain.raiseDispute({ settlementOnchainId: quick.settlementOnchainId, reason: 'x' }), (e) => e.code === 'INVALID_STATUS');
  await assert.rejects(blockchain.getSettlementState({ settlementOnchainId: '0x' + 'ab'.repeat(32) }), (e) => e.code === 'SETTLEMENT_NOT_FOUND' && e.status === 404);
});

test('MOCK 상태 머신: raise → DISPUTED(동결) → resolve(GENUINE_ERROR) → CANCELLED → refund × N, 두 번 환불·판정 밖 값 거부', async () => {
  const r = await blockchain.recordSettlementOnchain({ settlementId: 'd1', members: UIDS, shares: SHARES, conditionsHash: CHASH, holdSeconds: 0 });
  const sid = r.settlementOnchainId;
  await assert.rejects(blockchain.resolveDispute({ settlementOnchainId: sid, verdict: 'NORMAL_APPROVAL' }), (e) => e.code === 'INVALID_STATUS'); // Disputed 아님
  await assert.rejects(blockchain.refundParticipant({ settlementOnchainId: sid, uid: 'u0' }), (e) => e.code === 'INVALID_STATUS');

  const raised = await blockchain.raiseDispute({ settlementOnchainId: sid, reason: '지현은 그날 참석하지 않았는데 포함됨' });
  assert.equal(raised.state, 'DISPUTED');
  assert.match(raised.reasonHash, /^0x[0-9a-f]{64}$/);
  await assert.rejects(blockchain.releaseSettlement({ settlementOnchainId: sid }), (e) => e.code === 'INVALID_STATUS' && e.state === 'DISPUTED'); // 동결
  await assert.rejects(blockchain.resolveDispute({ settlementOnchainId: sid, verdict: 'REFUND' }), (e) => e.code === 'INVALID_VERDICT' && e.status === 400);
  await assert.rejects(blockchain.resolveDispute({ settlementOnchainId: sid, verdict: 3 }), (e) => e.code === 'INVALID_VERDICT');

  const resolved = await blockchain.resolveDispute({ settlementOnchainId: sid, verdict: 'GENUINE_ERROR' });
  assert.deepEqual([resolved.verdict, resolved.verdictCode, resolved.state], ['GENUINE_ERROR', 1, 'CANCELLED']);
  for (let i = 0; i < UIDS.length; i++) {
    const ref = await blockchain.refundParticipant({ settlementOnchainId: sid, uid: UIDS[i] });
    assert.equal(ref.uid, UIDS[i]);
    assert.equal(ref.amount, SHARES[i]);
    assert.match(ref.txHash, /^0x[0-9a-f]{64}$/);
  }
  await assert.rejects(blockchain.refundParticipant({ settlementOnchainId: sid, uid: 'u0' }), (e) => e.code === 'ALREADY_REFUNDED');
  await assert.rejects(blockchain.refundParticipant({ settlementOnchainId: sid, uid: 'u9' }), (e) => e.code === 'NOT_LOCKED_PARTICIPANT');
  await assert.rejects(blockchain.refundParticipant({ settlementOnchainId: sid, uid: '진주' }), (e) => e.code === 'INVALID_MEMBER_UID');
  await assert.rejects(blockchain.releaseSettlement({ settlementOnchainId: sid }), (e) => e.code === 'INVALID_STATUS' && e.state === 'CANCELLED');
  assert.equal((await blockchain.getSettlementState({ settlementOnchainId: sid })).verdict, 'GENUINE_ERROR');

  // NORMAL_APPROVAL / BAD_FAITH_DISPUTE → LOCKED 복귀 → 환불 불가, 지급 가능
  const r2 = await blockchain.recordSettlementOnchain({ settlementId: 'd2', members: UIDS, shares: SHARES, conditionsHash: CHASH, holdSeconds: 0 });
  await blockchain.raiseDispute({ settlementOnchainId: r2.settlementOnchainId, reason: '이상해요' });
  const ok = await blockchain.resolveDispute({ settlementOnchainId: r2.settlementOnchainId, verdict: 'BAD_FAITH_DISPUTE' });
  assert.deepEqual([ok.verdictCode, ok.state], [2, 'LOCKED']);
  await assert.rejects(blockchain.refundParticipant({ settlementOnchainId: r2.settlementOnchainId, uid: 'u0' }), (e) => e.code === 'INVALID_STATUS');
  assert.equal((await blockchain.releaseSettlement({ settlementOnchainId: r2.settlementOnchainId })).state, 'RELEASED');
});

test('conditionsHash 없이 recordSettlementOnchain을 부르면 MISSING_CONDITIONS_HASH (MOCK 포함)', async () => {
  for (const bad of [undefined, null, '', '0x' + '0'.repeat(64), '0x1234']) {
    await assert.rejects(
      blockchain.recordSettlementOnchain({ settlementId: 'g', members: UIDS, shares: SHARES, conditionsHash: bad }),
      (e) => e.code === 'MISSING_CONDITIONS_HASH' && e.status === 400,
      String(bad),
    );
  }
});

test('MOCK 모드: members에 표시 이름("진주")을 넣으면 INVALID_MEMBER_UID 에러', async () => {
  for (const bad of [['진주', 'u1'], ['u0', 'u 1'], ['u0', '']]) {
    await assert.rejects(
      blockchain.recordSettlementOnchain({ settlementId: 'g', members: bad, shares: [1000, 1000], conditionsHash: CHASH }),
      (e) => e.code === 'INVALID_MEMBER_UID' && e.status === 400 && /uid여야 해요/.test(e.message),
      JSON.stringify(bad),
    );
  }
  await assert.rejects(blockchain.recordSettlementOnchain({ settlementId: 'g', members: UIDS, shares: SHARES, payer: '진주', conditionsHash: CHASH }), (e) => e.code === 'INVALID_MEMBER_UID');
  await assert.rejects(blockchain.chargeToken('진주', 100), (e) => e.code === 'INVALID_MEMBER_UID');
  await assert.rejects(blockchain.getBalance('진주'), (e) => e.code === 'INVALID_MEMBER_UID');
  assert.equal(await blockchain.getBalance('u0'), null); // MOCK에는 PieCoin 잔액 개념이 없음
});

// ───────────────────────────────────────────── approve → 저장소 → 라우트 (release / raise / resolve)
test('MOCK approve: cert.hash = confirm(잠금 확정) TxHash, onchain에 state·holdUntil·settlementOnchainId·conditionsHash, 저장소에 기록', async () => {
  const settlement = { ...CONDITIONS };
  const r = await approveSettlement({ settlementId: 'g-hash', title: '삼겹살', settlement, approvals: [true, true, true, true] });
  assert.equal(r.onchain.mock, true);
  assert.equal(r.onchain.state, 'LOCKED');
  assert.equal(r.onchain.release, null);
  assert.equal(typeof r.onchain.holdUntil, 'number');
  assert.equal(r.cert.hash, r.onchain.confirm.txHash);
  assert.equal(r.cert.block, r.onchain.confirm.block);
  assert.match(r.onchain.conditionsHash, /^0x[0-9a-f]{64}$/);
  assert.equal(r.cert.conditionsHash, r.onchain.conditionsHash);
  assert.equal(r.onchain.conditionsCanonical, canonicalize(settlement));
  assert.equal(hashConditions(JSON.parse(r.onchain.conditionsCanonical)), r.onchain.conditionsHash); // 원문 → 재해시 = 기록값
  assert.equal(r.onchain.conditionsHash, CHASH);
  assert.equal(r.group.status, '정산 완료'); // UI 호환 유지

  const rec = store.getSettlement(r.onchain.settlementOnchainId);
  assert.deepEqual([rec.settlementId, rec.title, rec.members, rec.shares, rec.payer, rec.state, rec.verdict], ['g-hash', '삼겹살', UIDS, SHARES, null, 'LOCKED', null]);
  assert.equal(rec.conditionsHash, CHASH);
  assert.equal(rec.txs.confirm.txHash, r.cert.hash);
  assert.equal(rec.txs.release, null);
  assert.ok(fs.existsSync(store.storeFile()));
  assert.ok(!JSON.stringify(rec).includes('sk-bk-')); // 비밀값 없음
});

test('라우트: /settlement/release 보류 전 409 HOLD_NOT_ELAPSED → holdSeconds 0 정산은 200 RELEASED', async () => {
  const app = require('../src/server');
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = async (p, body) => { const res = await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return { status: res.status, body: await res.json() }; };
  try {
    const held = await post('/settlement/approve', { settlementId: 'r-held', title: '보류', settlement: CONDITIONS, approvals: [true, true, true, true] });
    assert.equal(held.status, 200);
    const early = await post('/settlement/release', { settlementOnchainId: held.body.onchain.settlementOnchainId });
    assert.equal(early.status, 409);
    assert.equal(early.body.error.code, 'HOLD_NOT_ELAPSED');

    const quick = await post('/settlement/approve', { settlementId: 'r-quick', title: '즉시', settlement: CONDITIONS, approvals: [true, true, true, true], holdSeconds: 0 });
    const rel = await post('/settlement/release', { settlementOnchainId: quick.body.onchain.settlementOnchainId });
    assert.equal(rel.status, 200);
    assert.equal(rel.body.state, 'RELEASED');
    assert.match(rel.body.release.txHash, /^0x[0-9a-f]{64}$/);
    assert.equal(store.getSettlement(quick.body.onchain.settlementOnchainId).state, 'RELEASED');

    const bad = await post('/settlement/release', { settlementOnchainId: 'nope' });
    assert.equal(bad.status, 400);
    const missing = await post('/settlement/release', { settlementOnchainId: '0x' + 'cd'.repeat(32) });
    assert.equal(missing.status, 404);
    assert.equal(missing.body.error.code, 'SETTLEMENT_NOT_FOUND');
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('라우트: /dispute/raise → /dispute/resolve GENUINE_ERROR → refunds N건 + dispute.action 로그 / NORMAL_APPROVAL → 환불 0건', async () => {
  const app = require('../src/server');
  const server = app.listen(0);
  await new Promise((r) => server.once('listening', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  const post = async (p, body) => { const res = await fetch(base + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return { status: res.status, body: await res.json() }; };
  try {
    const ap = await post('/settlement/approve', { settlementId: 'run2', title: '삼겹살', settlement: CONDITIONS, approvals: [true, true, true, true] });
    const sid = ap.body.onchain.settlementOnchainId;

    const notMember = await post('/dispute/raise', { settlementOnchainId: sid, raisedBy: 'u9', reason: 'x' });
    assert.equal(notMember.status, 400);
    const raised = await post('/dispute/raise', { settlementOnchainId: sid, raisedBy: 'u1', reason: '지현은 그날 참석하지 않았는데 포함됨' });
    assert.equal(raised.status, 200);
    assert.equal(raised.body.state, 'DISPUTED');
    assert.equal(raised.body.dispute.raisedBy, 'u1');
    assert.match(raised.body.txHash, /^0x[0-9a-f]{64}$/);
    const frozen = await post('/settlement/release', { settlementOnchainId: sid });
    assert.equal(frozen.body.error.code, 'INVALID_STATUS'); // 동결

    const badVerdict = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'REFUND' });
    assert.equal(badVerdict.status, 400);
    assert.equal(badVerdict.body.error.code, 'INVALID_VERDICT');

    // A-2 규칙: 코드의 불일치 확인 없이는 판정을 실행하지 않는다 — 온체인 호출 0 (상태 DISPUTED 유지)
    const noInv = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'GENUINE_ERROR' });
    assert.deepEqual([noInv.status, noInv.body.error.code], [400, 'INVESTIGATION_REQUIRED']);
    const noMismatch = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'GENUINE_ERROR', investigation: { verdict: 'GENUINE_ERROR', mismatchDetected: false, mismatchPoint: null, explanation: '착오' } });
    assert.deepEqual([noMismatch.status, noMismatch.body.error.code], [409, 'MISMATCH_NOT_FOUND']);
    const unresolved = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'NORMAL_APPROVAL', investigation: { verdict: 'NORMAL_APPROVAL', mismatchDetected: true, mismatchPoint: '계산 단계', explanation: 'x' } });
    assert.deepEqual([unresolved.status, unresolved.body.error.code], [409, 'MISMATCH_UNRESOLVED']);
    assert.equal((await blockchain.getSettlementState({ settlementOnchainId: sid })).state, 'DISPUTED'); // 셋 다 온체인 호출 없음
    // investigate 입력을 주면 compareRecords 를 직접 다시 돌려 facts 를 만든다 (기록 일치 → GENUINE_ERROR 거부)
    const locks = ap.body.onchain.locks.map((l) => ({ from: l.from, to: l.to, amount: l.amount, txHash: l.txHash }));
    const viaCompare = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'GENUINE_ERROR', originalRequest: { text: 'x', structured: CONDITIONS }, settlementPlan: { members: UIDS, shares: SHARES, payer: null }, approvalRecord: locks, actualTransfer: locks, dispute: { raisedBy: 'u1', reason: 'x' } });
    assert.deepEqual([viaCompare.status, viaCompare.body.error.code], [409, 'MISMATCH_NOT_FOUND']);

    const resolved = await post('/dispute/resolve', { settlementOnchainId: sid, verdict: 'GENUINE_ERROR', investigation: { verdict: 'GENUINE_ERROR', mismatchDetected: true, mismatchPoint: '계산 단계', expectedAmount: 5225, actualAmount: 8975, explanation: '참여자 착오' } });
    assert.equal(resolved.status, 200);
    assert.deepEqual([resolved.body.facts.mismatchDetected, resolved.body.facts.mismatchPoint, resolved.body.facts.source], [true, '계산 단계', 'investigation']);
    assert.equal(resolved.body.state, 'CANCELLED');
    assert.equal(resolved.body.refunds.length, 4);
    assert.ok(resolved.body.refunds.every((r) => r.ok && /^0x[0-9a-f]{64}$/.test(r.txHash)));
    assert.deepEqual(resolved.body.refunds.map((r) => [r.uid, r.amount]), UIDS.map((u, i) => [u, SHARES[i]]));
    const rec = store.getSettlement(sid);
    assert.deepEqual([rec.state, rec.verdict, rec.txs.refunds.length, rec.dispute.raisedBy], ['CANCELLED', 'GENUINE_ERROR', 4, 'u1']);

    // CLAUDE.md 12번: verdict → 행동 → txHash 한 줄
    const action = readLog('events.jsonl').filter((e) => e.type === 'dispute.action' && e.settlementOnchainId === sid).at(-1);
    assert.ok(action, 'dispute.action 로그가 있어야 함');
    assert.equal(action.responseKey, 'verdict=GENUINE_ERROR');
    assert.equal(action.action, 'refund_participant × 4/4');
    assert.equal(action.txHashes.length, 4);
    assert.equal(action.investigation.mismatchPoint, '계산 단계');
    assert.equal(action.summary, 'mismatchDetected=true, mismatchPoint=계산 단계 → verdict=GENUINE_ERROR → refund_participant × 4/4');
    assert.deepEqual([store.getSettlement(sid).investigation.mismatchDetected, store.getSettlement(sid).facts.mismatchPoint], [true, '계산 단계']);

    // NORMAL_APPROVAL(불일치 없음) → 환불 0건, LOCKED 복귀 — investigate 입력(compareRecords)으로 facts 확인
    const ap2 = await post('/settlement/approve', { settlementId: 'run2-ok', title: '삼겹살', settlement: CONDITIONS, approvals: [true, true, true, true], holdSeconds: 0 });
    const sid2 = ap2.body.onchain.settlementOnchainId;
    await post('/dispute/raise', { settlementOnchainId: sid2, raisedBy: 'u2', reason: '계산이 틀린 것 같아요' });
    const locks2 = ap2.body.onchain.locks.map((l) => ({ from: l.from, to: l.to, amount: l.amount, txHash: l.txHash }));
    const kept = await post('/dispute/resolve', { settlementOnchainId: sid2, verdict: 'NORMAL_APPROVAL', originalRequest: { text: 'x', structured: CONDITIONS }, settlementPlan: { members: UIDS, shares: SHARES, payer: null }, approvalRecord: locks2, actualTransfer: locks2 });
    assert.equal(kept.body.facts.source, 'compareRecords');
    assert.equal(kept.status, 200);
    assert.deepEqual([kept.body.state, kept.body.refunds.length], ['LOCKED', 0]);
    const kaction = readLog('events.jsonl').filter((e) => e.type === 'dispute.action' && e.settlementOnchainId === sid2).at(-1);
    assert.match(kaction.action, /정산 유지/);
    assert.equal((await post('/settlement/release', { settlementOnchainId: sid2 })).body.state, 'RELEASED');
  } finally {
    await new Promise((r) => server.close(r));
  }
});

test('Run 1.5 (MOCK): 예산 40,000→30,000 → OVER_BUDGET, u3 잔액 부족 → INSUFFICIENT_BALANCE — 둘 다 온체인 0건 + settlement.abort 로그', async () => {
  const path = require('path');
  const { runRun15 } = require(path.join(__dirname, '..', '..', 'contracts', 'scripts', 'run1_5-over-budget'));
  // MOCK 잔액: chargeToken 으로 충전한 uid 만 추적. 충전 안 한 uid 는 null(무제한)
  assert.equal(await blockchain.getBalance('u9'), null);
  await blockchain.chargeToken('u9', 500);
  assert.equal(await blockchain.getBalance('u9'), 500);

  const log = await runRun15({ allowMock: true, quiet: true });
  assert.equal(log.mock, true);
  assert.equal(log.aiCalls, 0);
  assert.equal(log.cases.length, 2);
  const [c1, c2] = log.cases;
  assert.deepEqual([c1.aborted, c1.code, c1.status, c1.detail.overBudgetBy, c1.detail.onchainTx], [true, 'OVER_BUDGET', 409, 5900, 0]);
  assert.deepEqual([c2.aborted, c2.code, c2.status, c2.detail.participant, c2.detail.balancePIE, c2.detail.onchainTx], [true, 'INSUFFICIENT_BALANCE', 409, 'u3', 100, 0]);
  assert.equal(log.allAborted, true);

  const aborts = readLog('events.jsonl').filter((e) => e.type === 'settlement.abort');
  const over = aborts.find((e) => e.code === 'OVER_BUDGET');
  const bal = aborts.find((e) => e.code === 'INSUFFICIENT_BALANCE');
  assert.ok(over && bal, 'settlement.abort 로그 2건');
  assert.match(over.summary, /overBudgetBy 5900.*코드 판정 OVER_BUDGET.*중단/);
  assert.match(bal.summary, /u3.*코드 판정 INSUFFICIENT_BALANCE.*중단/);
  assert.match(over.aiRole, /AI는 조건 해석/);
  assert.equal(over.action, '승인 거부 — 온체인 트랜잭션 0건');
  // 실패한 approve 는 저장소에도 남지 않는다
  assert.ok(!store.listSettlements().some((r) => r.settlementId === 'run1_5-budget' || r.settlementId === 'run1_5-balance'));
});

test('chains.js: 메인넷 거부·Sepolia 기본·env 커스텀 테스트넷 (ethers 없이 동작)', () => {
  const chains = require('../src/blockchain/chains');
  assert.equal(chains.configuredChainId({}), 11155111);
  assert.equal(chains.configuredChainId({ CHAIN_ID: '424242' }), 424242);
  assert.equal(chains.describeChain(11155111).explorerTx('0xab'), 'https://sepolia.etherscan.io/tx/0xab');
  assert.throws(() => chains.assertAllowedChain(1), (e) => e.code === 'CHAIN_NOT_ALLOWED' && /메인넷/.test(e.message));
  assert.throws(() => chains.assertAllowedChain(8453), (e) => e.code === 'CHAIN_NOT_ALLOWED');
  assert.throws(() => chains.customChainFromEnv({ CHAIN_ID: '56' }), (e) => e.code === 'CHAIN_NOT_ALLOWED');
  const c = chains.assertAllowedChain(424242, { CHAIN_ID: '424242', CHAIN_NAME: 'contest', EXPLORER_TX_URL: 'https://x/tx/{hash}' });
  assert.deepEqual([c.name, c.custom, c.explorerTx('0x9')], ['contest', true, 'https://x/tx/0x9']);
  assert.equal(chains.customChainFromEnv({}), null);
});

test('MOCK 모드에서는 ethers가 로드되지 않음 (uid 검사·해시·상태 머신 모두 ethers 없이 동작)', () => {
  const loaded = Object.keys(require.cache).filter((k) => /[\\/]node_modules[\\/]ethers[\\/]/.test(k));
  assert.equal(loaded.length, 0);
  assert.ok(!Object.keys(require.cache).some((k) => /onchainClient\.js$/.test(k)));
  assert.ok(!Object.keys(require.cache).some((k) => /blockchain[\\/]members\.js$/.test(k)));
  assert.ok(Object.keys(require.cache).some((k) => /conditionsHash\.js$/.test(k))); // 해시 모듈은 로드됐지만 ethers는 아님
});

test('demo-all (MOCK): preflight → Run 1 → Run 1.5 → Run 2(가짜 Kiln) → release → verify 가 끝까지 돌고 summary.md 를 만든다', async () => {
  const path = require('path');
  const { fakeKiln, restoreKiln } = require('./helpers');
  const { runDemoAll } = require(path.join(__dirname, '..', '..', 'contracts', 'scripts', 'demo-all'));
  const prevHold = process.env.SETTLEMENT_HOLD_SECONDS;
  // 가짜 Kiln: dispute.investigate 1회 — 설명에는 facts 에 있는 숫자(5,225 / 8,975)만 쓴다 (AI 규칙 그대로 검증됨)
  const calls = fakeKiln([JSON.stringify({ verdict: 'GENUINE_ERROR', explanation: '계산 단계에서 u0의 분담금이 5,225원이어야 하는데 8,975원이 잠겼어요. 착오로 판정해 환불을 진행해요.' })]);
  try {
    const r = await runDemoAll({ quiet: true, outRoot: process.env.LOG_DIR, holdSeconds: 0 });
    assert.ok(fs.existsSync(r.summaryPath), 'summary.md 생성');
    for (const k of ['run1', 'run1_5', 'run2', 'release', 'verify', 'preflight']) assert.equal(r.results[k].ok, true, `${k} 성공: ${JSON.stringify(r.results[k].error || null)}`);
    assert.equal(r.results.mode, 'mock');
    assert.equal(r.results.preflight.data.mode, 'mock');
    assert.equal(r.results.run1_5.data.allAborted, true);
    assert.equal(r.results.run2.data.verdict, 'GENUINE_ERROR');
    assert.equal(r.results.run2.data.txHashes.refunds.length, 4);
    assert.equal(r.results.release.data.released, true); // holdSeconds 0 → 바로 지급
    assert.equal(r.results.verify.data.match, true);
    assert.deepEqual(calls.map((c) => c.stage), ['dispute.investigate']); // AI 호출은 Run 2 재조사 1회만
    for (const f of ['run1.json', 'run1_5.json', 'run2.json', 'release.json', 'results.json']) assert.ok(fs.existsSync(path.join(r.outDir, f)), f);

    const md = fs.readFileSync(r.summaryPath, 'utf8');
    assert.match(md, /모드: \*\*mock\*\*/);
    assert.match(md, /\| Run 1 \| open_settlement \| `0x[0-9a-f]+` \| MOCK \|/);
    assert.match(md, /\| Run 1 \| release_to_recipient \|/);
    assert.match(md, /\| Run 2 \| resolve_dispute \(GENUINE_ERROR\) \|/);
    assert.equal((md.match(/refund_participant #/g) || []).length, 4);
    assert.match(md, /OVER_BUDGET/); assert.match(md, /INSUFFICIENT_BALANCE/);
    assert.match(md, /verdict=\*\*GENUINE_ERROR\*\*/);
    assert.match(md, /\| dispute\.investigate \| \d+ \| \d+ \| \d+ \|/); // 단계별 토큰 표 (가짜 Kiln 은 chatCompletion 자체를 바꿔 토큰 로그가 남지 않는다)
    assert.match(md, /\| settlement\.calculate \| \d+ \(code-only\) \| 0 \| 0 \|/);
    assert.match(md, /✅ MATCH/);
    assert.match(md, /\[settlement\.abort\] .*OVER_BUDGET.*중단/);
    assert.match(md, /\[dispute\.action\] mismatchDetected=true.*verdict=GENUINE_ERROR.*refund_participant × 4\/4/);
  } finally {
    restoreKiln();
    if (prevHold === undefined) delete process.env.SETTLEMENT_HOLD_SECONDS; else process.env.SETTLEMENT_HOLD_SECONDS = prevHold;
  }
});
