'use strict';

// ============================================================================
// 블록체인 입구 — 백엔드의 다른 코드는 이 파일만 부른다
// ============================================================================
// - backend/.env 에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY 가 모두 있으면 → 실제 Sepolia 호출
// - 하나라도 비어 있으면 → MOCK (가짜 txHash). 블록체인 설정이 없는 팀원도 화면·백엔드를 그대로 쓸 수 있게.
// ⚠️ 테스트넷 전용. PieCoin은 실화폐 가치가 없다.
//
// /settlement/approve 에서 쓸 함수:
//   recordSettlementOnchain({ settlementId, members, shares, payer })   ← members·payer는 uid('u0', 'u1', …)
//   → { mock, recipient, viaEscrow, locks: [{ from, to, amount, txHash }], release: { txHash, block, ... } }  ← from·recipient도 uid
//   표시 이름('진주')을 넘기면 MOCK/실제 체인 모두 INVALID_MEMBER_UID 에러 (동명이인 지갑 충돌 방지)
//
// (구) lockForSettlement / releaseToRecipient 는 MOCK 모드 호환용으로만 남겨 둔다.
//
// ethers·onchainClient·members는 실제 체인 모드에서 처음 쓸 때만 불러온다 (getOnchainClient).
// → MOCK 모드에서는 ethers가 설치돼 있지 않아도(npm install 전) 서버가 정상으로 켜진다.
// ============================================================================

const crypto = require('crypto');
const { InsufficientBalanceError, BlockchainError, ESCROW_RECIPIENT, assertUid } = require('./errors'); // errors.js는 ethers 없이 동작

function isConfigured() {
  const { BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY } = process.env;
  return Boolean(BLOCKCHAIN_RPC_URL && CONTRACT_ADDRESS && DEPLOYER_PRIVATE_KEY);
}

const IS_MOCK = !isConfigured();

// ── 실제 체인 클라이언트 (처음 쓸 때 한 번만 연결) ────────────────────────────
let clientPromise = null;
function getOnchainClient() {
  if (!clientPromise) {
    const { ethers } = require('ethers');
    const { createOnchainClient } = require('./onchainClient');
    const pk = process.env.DEPLOYER_PRIVATE_KEY.startsWith('0x') ? process.env.DEPLOYER_PRIVATE_KEY : '0x' + process.env.DEPLOYER_PRIVATE_KEY;
    const provider = new ethers.JsonRpcProvider(process.env.BLOCKCHAIN_RPC_URL);
    const signer = new ethers.NonceManager(new ethers.Wallet(pk, provider)); // 잠금 트랜잭션을 연달아 보낼 때 nonce 충돌 방지
    clientPromise = createOnchainClient({ signer, contractAddress: process.env.CONTRACT_ADDRESS, merchantAddress: process.env.MERCHANT_ADDRESS || null })
      .catch((err) => { clientPromise = null; throw err; });
  }
  return clientPromise;
}

// ── MOCK ──────────────────────────────────────────────────────────────────
let mockBlock = 18_300_000;
function mockTx(payload) {
  mockBlock += 1;
  const txHash = '0x' + crypto.createHash('sha256').update(JSON.stringify(payload) + Date.now() + Math.random()).digest('hex');
  return { txHash, block: '#' + mockBlock.toLocaleString('en-US'), mock: true };
}

function mockRecordSettlement({ settlementId, members, shares, payer = null }) {
  if (!Array.isArray(members) || !Array.isArray(shares) || members.length !== shares.length) {
    throw new BlockchainError('members와 shares 길이가 달라요.', 'INVALID_INPUT', 400);
  }
  members.forEach(assertUid); // 실제 체인 모드와 같은 uid 검사 (addressOf를 거치지 않으므로 여기서)
  if (payer !== null) assertUid(payer);
  const recipient = payer || ESCROW_RECIPIENT;
  const locks = members
    .map((uid, i) => ({ uid, amount: shares[i] }))
    .filter((p) => p.uid !== payer && p.amount > 0)
    .map((p) => ({ from: p.uid, to: recipient, amount: p.amount, txHash: mockTx({ fn: 'lock_for_settlement', settlementId, ...p }).txHash }));
  return { mock: true, recipient, viaEscrow: !payer, locks, release: mockTx({ fn: 'release_to_recipient', settlementId, recipient }) };
}

// ── 공개 함수 ──────────────────────────────────────────────────────────────
async function recordSettlementOnchain(args) {
  if (IS_MOCK) return mockRecordSettlement(args);
  const client = await getOnchainClient();
  return client.recordSettlement(args);
}

async function chargeToken(uid, amount) {
  if (IS_MOCK) { assertUid(uid); return { uid, amount, ...mockTx({ fn: 'charge_token', uid, amount }) }; }
  return (await getOnchainClient()).chargeToken(uid, amount);
}

async function getBalance(uid) {
  if (IS_MOCK) { assertUid(uid); return null; } // MOCK에는 잔액 개념이 없음
  return (await getOnchainClient()).balanceOf(uid);
}

// (구) 참여자 한 명씩 부르는 방식 — 실제 체인에서는 open_settlement 없이 잠글 수 없으므로 MOCK에서만 동작
function legacyOnly(fn) {
  if (!IS_MOCK) {
    throw new BlockchainError(`실제 체인 모드에서는 ${fn} 대신 recordSettlementOnchain()을 호출해야 해요 (approveSettlement.js).`, 'BLOCKCHAIN_USE_RECORD', 500);
  }
}
async function lockForSettlement({ settlementId, participant, amount }) {
  legacyOnly('lockForSettlement');
  return mockTx({ fn: 'lock_for_settlement', settlementId, participant, amount });
}
async function releaseToRecipient({ settlementId, recipient }) {
  legacyOnly('releaseToRecipient');
  return mockTx({ fn: 'release_to_recipient', settlementId, recipient });
}

module.exports = {
  recordSettlementOnchain,
  chargeToken,
  getBalance,
  lockForSettlement,
  releaseToRecipient,
  isConfigured,
  InsufficientBalanceError,
  BlockchainError,
  ESCROW_RECIPIENT,
  IS_MOCK,
};
