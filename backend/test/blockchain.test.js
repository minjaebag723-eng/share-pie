'use strict';

// 블록체인 입구(blockchainClient) MOCK 모드 검사 — 블록체인 환경변수 없이 실행된다
// - 멤버는 uid('u0', …)로만 받는다. 표시 이름('진주')을 넘기면 거부 (동명이인 지갑 충돌 방지)
// - MOCK 모드에서는 ethers를 불러오지 않는다 (npm install 전이어도 서버가 켜지는 보장)
require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');

for (const k of ['BLOCKCHAIN_RPC_URL', 'CONTRACT_ADDRESS', 'DEPLOYER_PRIVATE_KEY']) delete process.env[k];
const blockchain = require('../src/blockchain/blockchainClient');
const { canonicalize, hashConditions, isConditionsHash } = require('../src/blockchain/conditionsHash');
const { approveSettlement } = require('../src/settlement/approveSettlement');

const UIDS = ['u0', 'u1', 'u2', 'u3'];
const SHARES = [5225, 10225, 10225, 10225];
const CONDITIONS = { members: UIDS, mode: 'ADJUST', itemName: '삼겹살', total: 35900, participants: UIDS, ratios: null, adjustments: { u0: -5000 }, items: null, totalBudget: null, payer: null };
const CHASH = hashConditions(CONDITIONS);

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

test('MOCK approve: 응답 onchain에 conditionsHash·conditionsCanonical, cert.conditionsHash와 같고 조건 원문을 다시 해시하면 일치', async () => {
  const settlement = { ...CONDITIONS };
  const r = await approveSettlement({ settlementId: 'g-hash', title: '삼겹살', settlement, approvals: [true, true, true, true] });
  assert.equal(r.onchain.mock, true);
  assert.match(r.onchain.conditionsHash, /^0x[0-9a-f]{64}$/);
  assert.equal(r.cert.conditionsHash, r.onchain.conditionsHash);
  assert.equal(r.onchain.conditionsCanonical, canonicalize(settlement));
  assert.equal(hashConditions(JSON.parse(r.onchain.conditionsCanonical)), r.onchain.conditionsHash); // 원문 → 재해시 = 기록값
  assert.equal(r.onchain.conditionsHash, CHASH);
  assert.match(r.onchain.open.txHash, /^0x[0-9a-f]{64}$/);
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

test('MOCK 모드: recordSettlementOnchain은 mock:true, locks[].from·recipient에 uid 그대로', async () => {
  assert.equal(blockchain.IS_MOCK, true);
  const r = await blockchain.recordSettlementOnchain({ settlementId: 'g1', members: UIDS, shares: SHARES, payer: null, conditionsHash: CHASH });
  assert.equal(r.mock, true);
  assert.equal(r.conditionsHash, CHASH);
  assert.equal(r.viaEscrow, true);
  assert.equal(r.recipient, blockchain.ESCROW_RECIPIENT);
  assert.deepEqual(r.locks.map((l) => l.from), UIDS);
  assert.deepEqual(r.locks.map((l) => l.amount), SHARES);
  r.locks.forEach((l) => assert.match(l.txHash, /^0x[0-9a-f]{64}$/));
  assert.match(r.release.txHash, /^0x[0-9a-f]{64}$/);

  const withPayer = await blockchain.recordSettlementOnchain({ settlementId: 'g2', members: UIDS, shares: SHARES, payer: 'u0', conditionsHash: CHASH });
  assert.equal(withPayer.viaEscrow, false);
  assert.equal(withPayer.recipient, 'u0');
  assert.deepEqual(withPayer.locks.map((l) => l.from), ['u1', 'u2', 'u3']);
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

test('MOCK 모드에서는 ethers가 로드되지 않음 (uid 검사도 ethers 없이 동작)', () => {
  const loaded = Object.keys(require.cache).filter((k) => /[\\/]node_modules[\\/]ethers[\\/]/.test(k));
  assert.equal(loaded.length, 0);
  assert.ok(!Object.keys(require.cache).some((k) => /onchainClient\.js$/.test(k)));
  assert.ok(!Object.keys(require.cache).some((k) => /blockchain[\\/]members\.js$/.test(k)));
  assert.ok(Object.keys(require.cache).some((k) => /conditionsHash\.js$/.test(k))); // 해시 모듈은 로드됐지만 ethers는 아님
});
