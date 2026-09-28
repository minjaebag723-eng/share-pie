'use strict';

// ============================================================================
// 블록체인 입구 — 백엔드의 다른 코드는 이 파일만 부른다
// ============================================================================
// - backend/.env 에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY 가 모두 있으면 → 실제 Sepolia 호출
// - 하나라도 비어 있으면 → MOCK (가짜 txHash + 메모리 상태 머신). 블록체인 설정이 없는 팀원도 화면·백엔드를 그대로 쓸 수 있게.
// ⚠️ 테스트넷 전용. PieCoin은 실화폐 가치가 없다.
//
// 공개 함수 (실제 체인·MOCK 동일 인터페이스, members·payer·uid는 모두 UI의 uid 'u0','u1',…)
//   recordSettlementOnchain({ settlementId, members, shares, payer, conditionsHash, holdSeconds })
//     → { mock, state:'LOCKED', recipient, viaEscrow, conditionsHash, holdSeconds, holdUntil, settlementOnchainId,
//         open, locks:[{ from, to, amount, txHash }], confirm:{ txHash, block, holdUntil }, release:null }
//   releaseSettlement({ settlementOnchainId, recipientUid? })      → { txHash, block, amount, explorerUrl, state:'RELEASED' }
//   raiseDispute({ settlementOnchainId, reason })                  → { txHash, block, reasonHash, state:'DISPUTED' }
//   resolveDispute({ settlementOnchainId, verdict })               → { txHash, block, verdict, verdictCode, state }
//   refundParticipant({ settlementOnchainId, uid })                → { uid, address, amount, txHash, block }
//   getSettlementState({ settlementOnchainId })                    → { state, holdUntil, verdict, lockedCount, participantCount }
//   표시 이름('진주')을 넘기면 MOCK/실제 체인 모두 INVALID_MEMBER_UID 에러 (동명이인 지갑 충돌 방지)
//   conditionsHash 없으면 MISSING_CONDITIONS_HASH. 상태 규칙 위반은 INVALID_STATUS / HOLD_NOT_ELAPSED 등 같은 코드.
//
// ethers·onchainClient·members는 실제 체인 모드에서 처음 쓸 때만 불러온다 (getOnchainClient).
// → MOCK 모드에서는 ethers가 설치돼 있지 않아도(npm install 전) 서버가 정상으로 켜진다.
// ============================================================================

const crypto = require('crypto');
const { InsufficientBalanceError, BlockchainError, ESCROW_RECIPIENT, assertUid, holdSecondsFromEnv, verdictCodeOf, VERDICT_NAMES } = require('./errors'); // errors.js는 ethers 없이 동작
const { isConditionsHash } = require('./conditionsHash'); // @noble/hashes 사용, ethers 없음

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

// ── MOCK: 메모리 상태 머신 (컨트랙트와 같은 규칙·같은 에러 코드) ────────────────
// ⚠️ 서버를 다시 켜면 MOCK 상태는 사라진다 (정산 기록 자체는 settlementStore가 파일로 보관)
let mockBlock = 18_300_000;
function mockTx(payload) {
  mockBlock += 1;
  const txHash = '0x' + crypto.createHash('sha256').update(JSON.stringify(payload) + Date.now() + Math.random()).digest('hex');
  return { txHash, block: '#' + mockBlock.toLocaleString('en-US'), mock: true };
}
const mockAddress = (uid) => '0x' + crypto.createHash('sha256').update(`sharepie-mock-uid:${uid}`).digest('hex').slice(-40);
const nowSec = () => Math.floor(Date.now() / 1000);

// settlementOnchainId → { state, participants:[{uid, amount, refunded}], totalLocked, holdUntil, verdict, disputed, recipient }
const mockStore = new Map();

function mockGet(settlementOnchainId) {
  const s = mockStore.get(settlementOnchainId);
  if (!s) throw new BlockchainError('체인에 없는 정산 id예요.', 'SETTLEMENT_NOT_FOUND', 404);
  return s;
}
function requireState(s, expected) {
  if (s.state !== expected) throw new BlockchainError(`현재 상태(${s.state})에서는 할 수 없는 동작이에요.`, 'INVALID_STATUS', 409, { state: s.state });
}

function mockRecordSettlement({ settlementId, members, shares, payer = null, conditionsHash, holdSeconds }) {
  if (!Array.isArray(members) || !Array.isArray(shares) || members.length !== shares.length) {
    throw new BlockchainError('members와 shares 길이가 달라요.', 'INVALID_INPUT', 400);
  }
  members.forEach(assertUid); // 실제 체인 모드와 같은 uid 검사 (addressOf를 거치지 않으므로 여기서)
  if (payer !== null) assertUid(payer);
  if (!isConditionsHash(conditionsHash)) {
    throw new BlockchainError('conditionsHash가 없어요. 승인 조건을 hashConditions()로 해시해서 넘겨 주세요.', 'MISSING_CONDITIONS_HASH', 400);
  }
  const hold = holdSeconds === undefined || holdSeconds === null ? holdSecondsFromEnv() : holdSeconds;
  if (!Number.isSafeInteger(hold) || hold < 0) throw new BlockchainError('holdSeconds는 0 이상의 정수여야 해요.', 'INVALID_INPUT', 400);

  const recipient = payer || ESCROW_RECIPIENT;
  const participants = members
    .map((uid, i) => ({ uid, amount: shares[i], refunded: false }))
    .filter((p) => p.uid !== payer && p.amount > 0);
  if (!participants.length) throw new BlockchainError('잠글 분담금이 없어요.', 'INVALID_INPUT', 400);

  const settlementOnchainId = '0x' + crypto.createHash('sha256').update(`${settlementId}:${Date.now()}:${Math.random()}`).digest('hex');
  const open = mockTx({ fn: 'open_settlement', settlementId, conditionsHash });
  const locks = participants.map((p) => {
    const tx = mockTx({ fn: 'lock_for_settlement', settlementId, uid: p.uid, amount: p.amount });
    return { from: p.uid, to: recipient, amount: p.amount, txHash: tx.txHash, block: tx.block };
  });
  const last = locks[locks.length - 1];
  const holdUntil = nowSec() + hold;
  const totalLocked = participants.reduce((a, p) => a + p.amount, 0);
  mockStore.set(settlementOnchainId, { state: 'LOCKED', participants, totalLocked, holdUntil, holdSeconds: hold, verdict: null, disputed: false, recipient, conditionsHash });

  return {
    mock: true,
    settlementOnchainId,
    state: 'LOCKED',
    recipient,
    viaEscrow: !payer,
    conditionsHash,
    holdSeconds: hold,
    holdUntil,
    open: { txHash: open.txHash, block: open.block },
    locks,
    confirm: { txHash: last.txHash, block: last.block, holdUntil, explorerUrl: null }, // 마지막 lock = 인증서 TxHash
    release: null,
  };
}

function mockRelease({ settlementOnchainId, recipientUid = null }) {
  const s = mockGet(settlementOnchainId);
  requireState(s, 'LOCKED');
  if (nowSec() < s.holdUntil) throw new BlockchainError(`보류 기간이 아직 지나지 않았어요 (holdUntil: ${s.holdUntil}).`, 'HOLD_NOT_ELAPSED', 409, { holdUntil: s.holdUntil });
  if (recipientUid) assertUid(recipientUid);
  s.state = 'RELEASED';
  const tx = mockTx({ fn: 'release_to_recipient', settlementOnchainId, recipient: recipientUid || s.recipient });
  return { txHash: tx.txHash, block: tx.block, amount: s.totalLocked, explorerUrl: null, recipientAddress: recipientUid ? mockAddress(recipientUid) : null, state: 'RELEASED' };
}

function mockRaise({ settlementOnchainId, reason }) {
  const s = mockGet(settlementOnchainId);
  if (typeof reason !== 'string' || !reason.trim()) throw new BlockchainError('이의제기 사유(reason)가 필요해요.', 'INVALID_INPUT', 400);
  requireState(s, 'LOCKED');
  s.state = 'DISPUTED';
  s.disputed = true;
  const tx = mockTx({ fn: 'raise_dispute', settlementOnchainId, reason });
  return { txHash: tx.txHash, block: tx.block, reasonHash: '0x' + crypto.createHash('sha256').update(reason).digest('hex'), state: 'DISPUTED' };
}

function mockResolve({ settlementOnchainId, verdict }) {
  const s = mockGet(settlementOnchainId);
  const code = verdictCodeOf(verdict); // 3개 밖이면 INVALID_VERDICT
  requireState(s, 'DISPUTED');
  s.verdict = verdict;
  s.state = code === 1 ? 'CANCELLED' : 'LOCKED';
  const tx = mockTx({ fn: 'resolve_dispute', settlementOnchainId, verdict: code });
  return { txHash: tx.txHash, block: tx.block, verdict, verdictCode: code, state: s.state };
}

function mockRefund({ settlementOnchainId, uid }) {
  assertUid(uid);
  const s = mockGet(settlementOnchainId);
  requireState(s, 'CANCELLED');
  const p = s.participants.find((x) => x.uid === uid);
  if (!p) throw new BlockchainError(`${uid}은(는) 이 정산에 분담금을 잠근 적이 없어요.`, 'NOT_LOCKED_PARTICIPANT', 409);
  if (p.refunded) throw new BlockchainError(`${uid}은(는) 이미 환불됐어요.`, 'ALREADY_REFUNDED', 409);
  p.refunded = true;
  const tx = mockTx({ fn: 'refund_participant', settlementOnchainId, uid, amount: p.amount });
  return { uid, address: mockAddress(uid), amount: p.amount, txHash: tx.txHash, block: tx.block, explorerUrl: null };
}

function mockState({ settlementOnchainId }) {
  const s = mockGet(settlementOnchainId);
  return { state: s.state, holdUntil: s.holdUntil, holdSeconds: s.holdSeconds, verdict: s.verdict, lockedCount: s.participants.length, participantCount: s.participants.length, totalLocked: s.totalLocked, conditionsHash: s.conditionsHash };
}

// ── 공개 함수 ──────────────────────────────────────────────────────────────
async function recordSettlementOnchain(args) {
  if (IS_MOCK) return mockRecordSettlement(args);
  return (await getOnchainClient()).recordSettlement(args);
}

async function releaseSettlement(args) {
  if (IS_MOCK) return mockRelease(args);
  return (await getOnchainClient()).releaseSettlement(args);
}

async function raiseDispute(args) {
  if (IS_MOCK) return mockRaise(args);
  return (await getOnchainClient()).raiseDispute(args);
}

async function resolveDispute(args) {
  if (IS_MOCK) return mockResolve(args);
  return (await getOnchainClient()).resolveDispute(args);
}

async function refundParticipant(args) {
  if (IS_MOCK) return mockRefund(args);
  return (await getOnchainClient()).refundParticipant(args);
}

async function getSettlementState(args) {
  if (IS_MOCK) return mockState(args);
  return (await getOnchainClient()).getSettlementState(args);
}

async function chargeToken(uid, amount) {
  if (IS_MOCK) { assertUid(uid); return { uid, amount, ...mockTx({ fn: 'charge_token', uid, amount }) }; }
  return (await getOnchainClient()).chargeToken(uid, amount);
}

async function getBalance(uid) {
  if (IS_MOCK) { assertUid(uid); return null; } // MOCK에는 잔액 개념이 없음
  return (await getOnchainClient()).balanceOf(uid);
}

module.exports = {
  recordSettlementOnchain,
  releaseSettlement,
  raiseDispute,
  resolveDispute,
  refundParticipant,
  getSettlementState,
  chargeToken,
  getBalance,
  isConfigured,
  InsufficientBalanceError,
  BlockchainError,
  ESCROW_RECIPIENT,
  VERDICT_NAMES,
  IS_MOCK,
};
