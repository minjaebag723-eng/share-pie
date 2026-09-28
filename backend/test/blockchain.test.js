'use strict';

// 블록체인 입구(blockchainClient) MOCK 모드 검사 — 블록체인 환경변수 없이 실행된다
// - 멤버는 uid('u0', …)로만 받는다. 표시 이름('진주')을 넘기면 거부 (동명이인 지갑 충돌 방지)
// - MOCK 모드에서는 ethers를 불러오지 않는다 (npm install 전이어도 서버가 켜지는 보장)
require('./helpers');
const test = require('node:test');
const assert = require('node:assert/strict');

for (const k of ['BLOCKCHAIN_RPC_URL', 'CONTRACT_ADDRESS', 'DEPLOYER_PRIVATE_KEY']) delete process.env[k];
const blockchain = require('../src/blockchain/blockchainClient');

const UIDS = ['u0', 'u1', 'u2', 'u3'];
const SHARES = [5225, 10225, 10225, 10225];

test('MOCK 모드: recordSettlementOnchain은 mock:true, locks[].from·recipient에 uid 그대로', async () => {
  assert.equal(blockchain.IS_MOCK, true);
  const r = await blockchain.recordSettlementOnchain({ settlementId: 'g1', members: UIDS, shares: SHARES, payer: null });
  assert.equal(r.mock, true);
  assert.equal(r.viaEscrow, true);
  assert.equal(r.recipient, blockchain.ESCROW_RECIPIENT);
  assert.deepEqual(r.locks.map((l) => l.from), UIDS);
  assert.deepEqual(r.locks.map((l) => l.amount), SHARES);
  r.locks.forEach((l) => assert.match(l.txHash, /^0x[0-9a-f]{64}$/));
  assert.match(r.release.txHash, /^0x[0-9a-f]{64}$/);

  const withPayer = await blockchain.recordSettlementOnchain({ settlementId: 'g2', members: UIDS, shares: SHARES, payer: 'u0' });
  assert.equal(withPayer.viaEscrow, false);
  assert.equal(withPayer.recipient, 'u0');
  assert.deepEqual(withPayer.locks.map((l) => l.from), ['u1', 'u2', 'u3']);
});

test('MOCK 모드: members에 표시 이름("진주")을 넣으면 INVALID_MEMBER_UID 에러', async () => {
  for (const bad of [['진주', 'u1'], ['u0', 'u 1'], ['u0', '']]) {
    await assert.rejects(
      blockchain.recordSettlementOnchain({ settlementId: 'g', members: bad, shares: [1000, 1000] }),
      (e) => e.code === 'INVALID_MEMBER_UID' && e.status === 400 && /uid여야 해요/.test(e.message),
      JSON.stringify(bad),
    );
  }
  await assert.rejects(blockchain.recordSettlementOnchain({ settlementId: 'g', members: UIDS, shares: SHARES, payer: '진주' }), (e) => e.code === 'INVALID_MEMBER_UID');
  await assert.rejects(blockchain.chargeToken('진주', 100), (e) => e.code === 'INVALID_MEMBER_UID');
  await assert.rejects(blockchain.getBalance('진주'), (e) => e.code === 'INVALID_MEMBER_UID');
  assert.equal(await blockchain.getBalance('u0'), null); // MOCK에는 PieCoin 잔액 개념이 없음
});

test('MOCK 모드에서는 ethers가 로드되지 않음 (uid 검사도 ethers 없이 동작)', () => {
  const loaded = Object.keys(require.cache).filter((k) => /[\\/]node_modules[\\/]ethers[\\/]/.test(k));
  assert.equal(loaded.length, 0);
  assert.ok(!Object.keys(require.cache).some((k) => /onchainClient\.js$/.test(k)));
  assert.ok(!Object.keys(require.cache).some((k) => /blockchain[\\/]members\.js$/.test(k)));
});
