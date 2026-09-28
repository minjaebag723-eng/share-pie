'use strict';

// 실제 체인(Sepolia · 로컬 Hardhat · env 로 추가한 대회 테스트넷) 호출 — SharePieSettlement 컨트랙트
// ⚠️ 테스트넷 전용. 허용 목록(chains.js)에 없는 chainId·메인넷이면 아무 트랜잭션도 보내지 않는다.
//
// 상태 머신 (컨트랙트와 동일): NONE → OPENED → LOCKED(보류) → RELEASED
//                                              LOCKED → DISPUTED → LOCKED (NORMAL_APPROVAL / BAD_FAITH_DISPUTE)
//                                                                → CANCELLED (GENUINE_ERROR) → refund × N

const { ethers } = require('ethers');
const { SETTLEMENT_ABI, PIECOIN_ABI, STATES, VERDICT_CODES, VERDICT_NAMES } = require('./abi');
const { addressOf } = require('./members');
const { ESCROW_RECIPIENT, InsufficientBalanceError, BlockchainError, holdSecondsFromEnv, verdictCodeOf } = require('./errors');
const { isConditionsHash } = require('./conditionsHash');
const { assertAllowedChain, allowedChains } = require('./chains');

// 멤버는 모두 uid('u0', 'u1', …)로 받는다 (addressOf가 형식을 검사). 표시 이름은 절대 지갑 키로 쓰지 않는다.

const TX_TIMEOUT_MS = 180_000;

function formatBlock(n) {
  return '#' + Number(n).toLocaleString('en-US');
}

function toBytes32(v, label) {
  if (typeof v !== 'string' || !/^0x[0-9a-fA-F]{64}$/.test(v)) throw new BlockchainError(`${label}가 올바른 bytes32 값이 아니에요.`, 'INVALID_INPUT', 400);
  return v;
}

// signer: ethers Signer (서버는 NonceManager(Wallet), 테스트는 Hardhat signer)
async function createOnchainClient({ signer, contractAddress, merchantAddress = null }) {
  if (!ethers.isAddress(contractAddress)) throw new BlockchainError('CONTRACT_ADDRESS가 올바른 주소가 아니에요.', 'BLOCKCHAIN_NOT_CONFIGURED', 503);
  const provider = signer.provider;
  const { chainId } = await provider.getNetwork();
  const chain = assertAllowedChain(Number(chainId)); // 메인넷·미허용 체인이면 여기서 CHAIN_NOT_ALLOWED
  const network = chain.name;

  const settlement = new ethers.Contract(contractAddress, SETTLEMENT_ABI, signer);
  const pieCoin = new ethers.Contract(await settlement.pieCoin(), PIECOIN_ABI, provider);
  const explorer = (hash) => chain.explorerTx(hash);

  // 컨트랙트 revert → 우리 에러로 변환 (uidOf: 주소 → uid)
  function translate(err, uidOf = {}) {
    let parsed = err && err.revert ? err.revert : null;
    const data = err && (err.data || (err.info && err.info.error && err.info.error.data));
    if (!parsed && data) {
      try { parsed = settlement.interface.parseError(data); } catch { /* 해석 불가 */ }
    }
    if (parsed && parsed.name) {
      const a = parsed.args;
      switch (parsed.name) {
        case 'InsufficientBalance':
          // 에러 메시지에는 uid가 들어간다 — UI가 uid → 이름으로 바꿔 표시한다
          return new InsufficientBalanceError(uidOf[ethers.getAddress(a[0])] || a[0], Number(a[2]), Number(a[1]));
        case 'HoldNotElapsed':
          return new BlockchainError(`보류 기간이 아직 지나지 않았어요 (holdUntil: ${Number(a[0])}).`, 'HOLD_NOT_ELAPSED', 409, { holdUntil: Number(a[0]) });
        case 'InvalidStatus':
          return new BlockchainError(`현재 상태(${STATES[Number(a[0])] || a[0]})에서는 할 수 없는 동작이에요.`, 'INVALID_STATUS', 409, { state: STATES[Number(a[0])] });
        case 'InvalidVerdict':
          return new BlockchainError(`판정 코드 ${a[0]}는 허용되지 않아요 (0·1·2만).`, 'INVALID_VERDICT', 400);
        case 'NotLockedParticipant':
          return new BlockchainError(`${uidOf[ethers.getAddress(a[0])] || a[0]}은(는) 이 정산에 분담금을 잠근 적이 없어요.`, 'NOT_LOCKED_PARTICIPANT', 409);
        case 'AlreadyRefunded':
          return new BlockchainError(`${uidOf[ethers.getAddress(a[0])] || a[0]}은(는) 이미 환불됐어요.`, 'ALREADY_REFUNDED', 409);
        case 'SettlementNotOpened':
          return new BlockchainError('체인에 없는 정산 id예요.', 'SETTLEMENT_NOT_FOUND', 404);
        default:
          return new BlockchainError(`컨트랙트가 거부했어요: ${parsed.name}(${a.map(String).join(', ')})`, 'CONTRACT_REVERTED', 409);
      }
    }
    return new BlockchainError(`블록체인 호출 실패: ${err.shortMessage || err.message}`);
  }

  async function send(fnName, args, uidOf) {
    try {
      return await settlement[fnName](...args);
    } catch (err) {
      throw translate(err, uidOf);
    }
  }

  async function waitFor(tx, uidOf) {
    try {
      return await tx.wait(1, TX_TIMEOUT_MS);
    } catch (err) {
      throw translate(err, uidOf);
    }
  }

  const receiptInfo = (r) => ({ txHash: r.hash, block: formatBlock(r.blockNumber), blockNumber: r.blockNumber, explorerUrl: explorer(r.hash) });

  async function balanceOf(uid) {
    return Number(await pieCoin.balanceOf(addressOf(uid)));
  }

  // PieCoin 충전 (★ charge_token)
  async function chargeToken(uid, amount) {
    if (!Number.isSafeInteger(amount) || amount <= 0) throw new BlockchainError('충전 금액은 1 이상의 정수여야 해요.', 'INVALID_INPUT', 400);
    const address = addressOf(uid);
    const receipt = await waitFor(await send('charge_token', [address, amount]));
    return { uid, address, amount, ...receiptInfo(receipt) };
  }

  // 체인 상태 조회 → { state, holdUntil, verdict, lockedCount, participantCount, totalLocked, conditionsHash }
  async function getSettlementState({ settlementOnchainId }) {
    const s = await settlement.getSettlement(toBytes32(settlementOnchainId, 'settlementOnchainId'));
    return {
      state: STATES[Number(s.status)] || 'NONE',
      holdUntil: Number(s.holdUntil),
      holdSeconds: Number(s.holdSeconds),
      verdict: s.disputed ? VERDICT_NAMES[Number(s.verdict)] : null,
      lockedCount: Number(s.lockedCount),
      participantCount: Number(s.participantCount),
      totalLocked: Number(s.totalLocked),
      conditionsHash: s.conditionsHash,
    };
  }

  // /settlement/approve 에서 부르는 본체: 정산 등록 → 전원 잠금 (→ Locked, 보류 시작). 지급(release)은 보류 뒤 releaseSettlement로.
  // members·payer는 uid. 반환의 locks[].from / recipient 에도 uid가 들어간다.
  // conditionsHash: 승인 조건의 keccak256 (conditionsHash.js) — open_settlement에 함께 기록. 없으면 트랜잭션을 보내기 전에 거부
  // 반환: { mock:false, state:'LOCKED', recipient, viaEscrow, conditionsHash, holdSeconds, holdUntil, open, locks:[…], confirm:{txHash,block,holdUntil}, release:null }
  async function recordSettlement({ settlementId, members, shares, payer = null, conditionsHash, holdSeconds }) {
    if (!Array.isArray(members) || !Array.isArray(shares) || members.length !== shares.length) {
      throw new BlockchainError('members와 shares 길이가 달라요.', 'INVALID_INPUT', 400);
    }
    if (!isConditionsHash(conditionsHash)) {
      throw new BlockchainError('conditionsHash가 없어요. 승인 조건을 hashConditions()로 해시해서 넘겨 주세요.', 'MISSING_CONDITIONS_HASH', 400);
    }
    const hold = holdSeconds === undefined || holdSeconds === null ? holdSecondsFromEnv() : holdSeconds;
    if (!Number.isSafeInteger(hold) || hold < 0) throw new BlockchainError('holdSeconds는 0 이상의 정수여야 해요.', 'INVALID_INPUT', 400);

    const viaEscrow = !payer;
    const recipient = payer || ESCROW_RECIPIENT;
    let recipientAddress;
    if (payer) {
      recipientAddress = addressOf(payer);
    } else {
      if (!merchantAddress || !ethers.isAddress(merchantAddress)) {
        throw new BlockchainError('에스크로 지급처 MERCHANT_ADDRESS가 설정되지 않았어요 (backend/.env).', 'BLOCKCHAIN_NOT_CONFIGURED', 503);
      }
      recipientAddress = ethers.getAddress(merchantAddress);
    }

    // payer는 이미 결제했으므로 잠그지 않는다. 0원 멤버도 제외.
    const participants = members
      .map((uid, i) => ({ uid, address: addressOf(uid), amount: shares[i] }))
      .filter((p) => p.uid !== payer && p.amount > 0);
    if (!participants.length) throw new BlockchainError('잠글 분담금이 없어요.', 'INVALID_INPUT', 400);
    const uidOf = Object.fromEntries(participants.map((p) => [p.address, p.uid]));

    // 1) 잔액 선확인 — 한 명이라도 부족하면 트랜잭션을 하나도 보내지 않는다 (부분 잠금 방지)
    for (const p of participants) {
      const bal = Number(await pieCoin.balanceOf(p.address));
      if (bal < p.amount) throw new InsufficientBalanceError(p.uid, p.amount, bal);
    }

    // 같은 그룹을 여러 번 승인해도 충돌하지 않도록 매번 새 온체인 id
    const onchainId = ethers.keccak256(ethers.toUtf8Bytes(`${settlementId}:${Date.now()}:${Math.random()}`));

    // 2) 정산 등록
    const openReceipt = await waitFor(await send('open_settlement', [onchainId, participants.map((p) => p.address), participants.map((p) => p.amount), conditionsHash, hold], uidOf), uidOf);

    // 3) 잠금 — 트랜잭션을 연달아 보낸 뒤 한꺼번에 확정을 기다린다 (Sepolia 블록 대기 시간 절약)
    //    마지막 잠금이 확정되는 순간 컨트랙트가 Locked로 바꾸고 보류를 시작한다 → 그 영수증이 인증서 TxHash
    const sent = [];
    for (const p of participants) sent.push({ p, tx: await send('lock_for_settlement', [onchainId, p.address, p.amount], uidOf) });
    const lockReceipts = await Promise.all(sent.map(({ tx }) => waitFor(tx, uidOf)));
    const last = lockReceipts[lockReceipts.length - 1];
    const holdUntil = Number(await settlement.holdUntilOf(onchainId));

    return {
      mock: false,
      network,
      chainId: Number(chainId),
      contractAddress: await settlement.getAddress(),
      settlementOnchainId: onchainId,
      state: 'LOCKED',
      recipient,
      recipientAddress,
      viaEscrow,
      conditionsHash,
      holdSeconds: hold,
      holdUntil,
      open: { txHash: openReceipt.hash, block: formatBlock(openReceipt.blockNumber) },
      locks: sent.map(({ p }, i) => ({
        from: p.uid,
        to: recipient,
        amount: p.amount,
        txHash: lockReceipts[i].hash,
        fromAddress: p.address,
        block: formatBlock(lockReceipts[i].blockNumber),
      })),
      confirm: { txHash: last.hash, block: formatBlock(last.blockNumber), blockNumber: last.blockNumber, holdUntil, explorerUrl: explorer(last.hash) },
      release: null, // 보류 기간이 지난 뒤 releaseSettlement() 로 지급
    };
  }

  // 보류가 끝난 정산을 결제처(또는 payer)에게 지급 (★ release_to_recipient)
  async function releaseSettlement({ settlementOnchainId, recipientAddress = null, recipientUid = null }) {
    const sid = toBytes32(settlementOnchainId, 'settlementOnchainId');
    let to = recipientAddress;
    if (recipientUid) to = addressOf(recipientUid);
    if (!to) {
      if (!merchantAddress || !ethers.isAddress(merchantAddress)) {
        throw new BlockchainError('에스크로 지급처 MERCHANT_ADDRESS가 설정되지 않았어요 (backend/.env).', 'BLOCKCHAIN_NOT_CONFIGURED', 503);
      }
      to = merchantAddress;
    }
    to = ethers.getAddress(to);
    const amount = Number((await settlement.getSettlement(sid)).totalLocked);
    const receipt = await waitFor(await send('release_to_recipient', [sid, to]));
    return { ...receiptInfo(receipt), amount, recipientAddress: to, state: 'RELEASED' };
  }

  // 이의제기 접수 (raise_dispute) — Locked → Disputed (동결)
  async function raiseDispute({ settlementOnchainId, reason }) {
    const sid = toBytes32(settlementOnchainId, 'settlementOnchainId');
    if (typeof reason !== 'string' || !reason.trim()) throw new BlockchainError('이의제기 사유(reason)가 필요해요.', 'INVALID_INPUT', 400);
    const receipt = await waitFor(await send('raise_dispute', [sid, reason]));
    return { ...receiptInfo(receipt), reasonHash: ethers.keccak256(ethers.toUtf8Bytes(reason)), state: 'DISPUTED' };
  }

  // 판정 실행 (resolve_dispute) — verdict 문자열(CLAUDE.md 7번 3개) → 0/1/2
  async function resolveDispute({ settlementOnchainId, verdict }) {
    const sid = toBytes32(settlementOnchainId, 'settlementOnchainId');
    const code = verdictCodeOf(verdict); // 3개 밖이면 INVALID_VERDICT (전송 전 거부)
    const receipt = await waitFor(await send('resolve_dispute', [sid, code]));
    return { ...receiptInfo(receipt), verdict, verdictCode: code, state: code === VERDICT_CODES.GENUINE_ERROR ? 'CANCELLED' : 'LOCKED' };
  }

  // 착오 판정(Cancelled) 후 참여자 한 명에게 잠근 금액 환불 (refund_participant)
  async function refundParticipant({ settlementOnchainId, uid }) {
    const sid = toBytes32(settlementOnchainId, 'settlementOnchainId');
    const address = addressOf(uid);
    const amount = Number(await settlement.expectedOf(sid, address));
    const receipt = await waitFor(await send('refund_participant', [sid, address], { [address]: uid }), { [address]: uid });
    return { uid, address, amount, ...receiptInfo(receipt) };
  }

  return { network, chainId: Number(chainId), chain, contractAddress: ethers.getAddress(contractAddress), recordSettlement, chargeToken, balanceOf, releaseSettlement, raiseDispute, resolveDispute, refundParticipant, getSettlementState };
}

module.exports = { createOnchainClient, InsufficientBalanceError, BlockchainError, ESCROW_RECIPIENT, allowedChains };
