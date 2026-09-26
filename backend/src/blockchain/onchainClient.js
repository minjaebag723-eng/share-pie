'use strict';

// 실제 체인(Sepolia 또는 로컬 Hardhat) 호출 — SharePieSettlement 컨트랙트
// ⚠️ 테스트넷 전용. chainId가 Sepolia(11155111) / 로컬 Hardhat(31337)이 아니면 아무 트랜잭션도 보내지 않는다.

const { ethers } = require('ethers');
const { SETTLEMENT_ABI, PIECOIN_ABI } = require('./abi');
const { addressOf } = require('./members');
const { ESCROW_RECIPIENT, InsufficientBalanceError, BlockchainError } = require('./errors');

const ALLOWED_CHAINS = { 11155111: 'sepolia', 31337: 'hardhat-local' };
const TX_TIMEOUT_MS = 180_000;

function formatBlock(n) {
  return '#' + Number(n).toLocaleString('en-US');
}

// signer: ethers Signer (서버는 NonceManager(Wallet), 테스트는 Hardhat signer)
async function createOnchainClient({ signer, contractAddress, merchantAddress = null }) {
  if (!ethers.isAddress(contractAddress)) throw new BlockchainError('CONTRACT_ADDRESS가 올바른 주소가 아니에요.', 'BLOCKCHAIN_NOT_CONFIGURED', 503);
  const provider = signer.provider;
  const { chainId } = await provider.getNetwork();
  const network = ALLOWED_CHAINS[Number(chainId)];
  if (!network) {
    throw new BlockchainError(`chainId ${chainId}는 허용되지 않아요. SharePie는 Sepolia(11155111) 테스트넷에서만 동작해요.`, 'CHAIN_NOT_ALLOWED', 503);
  }

  const settlement = new ethers.Contract(contractAddress, SETTLEMENT_ABI, signer);
  const pieCoin = new ethers.Contract(await settlement.pieCoin(), PIECOIN_ABI, provider);
  const explorer = (hash) => (network === 'sepolia' ? `https://sepolia.etherscan.io/tx/${hash}` : null);

  // 컨트랙트 revert → 우리 에러로 변환
  function translate(err, nameOf = {}) {
    let parsed = err && err.revert ? err.revert : null;
    const data = err && (err.data || (err.info && err.info.error && err.info.error.data));
    if (!parsed && data) {
      try { parsed = settlement.interface.parseError(data); } catch { /* 해석 불가 */ }
    }
    if (parsed && parsed.name === 'InsufficientBalance') {
      const [addr, balance, required] = parsed.args;
      return new InsufficientBalanceError(nameOf[ethers.getAddress(addr)] || addr, Number(required), Number(balance));
    }
    if (parsed && parsed.name) return new BlockchainError(`컨트랙트가 거부했어요: ${parsed.name}(${parsed.args.map(String).join(', ')})`, 'CONTRACT_REVERTED', 409);
    return new BlockchainError(`블록체인 호출 실패: ${err.shortMessage || err.message}`);
  }

  async function send(fnName, args, nameOf) {
    try {
      const tx = await settlement[fnName](...args);
      return tx;
    } catch (err) {
      throw translate(err, nameOf);
    }
  }

  async function waitFor(tx, nameOf) {
    try {
      const receipt = await tx.wait(1, TX_TIMEOUT_MS);
      return receipt;
    } catch (err) {
      throw translate(err, nameOf);
    }
  }

  async function balanceOf(name) {
    return Number(await pieCoin.balanceOf(addressOf(name)));
  }

  // PieCoin 충전 (★ charge_token)
  async function chargeToken(name, amount) {
    if (!Number.isSafeInteger(amount) || amount <= 0) throw new BlockchainError('충전 금액은 1 이상의 정수여야 해요.', 'INVALID_INPUT', 400);
    const address = addressOf(name);
    const receipt = await waitFor(await send('charge_token', [address, amount]));
    return { name, address, amount, txHash: receipt.hash, block: formatBlock(receipt.blockNumber), explorerUrl: explorer(receipt.hash) };
  }

  // /settlement/approve 에서 부르는 본체: 정산 등록 → 전원 잠금 → 지급
  // 반환: { mock:false, recipient, viaEscrow, locks:[{from,to,amount,txHash}], release:{...} } (CLAUDE.md 6-1)
  async function recordSettlement({ settlementId, members, shares, payer = null }) {
    if (!Array.isArray(members) || !Array.isArray(shares) || members.length !== shares.length) {
      throw new BlockchainError('members와 shares 길이가 달라요.', 'INVALID_INPUT', 400);
    }
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
      .map((name, i) => ({ name, address: addressOf(name), amount: shares[i] }))
      .filter((p) => p.name !== payer && p.amount > 0);
    if (!participants.length) throw new BlockchainError('잠글 분담금이 없어요.', 'INVALID_INPUT', 400);
    const nameOf = Object.fromEntries(participants.map((p) => [p.address, p.name]));

    // 1) 잔액 선확인 — 한 명이라도 부족하면 트랜잭션을 하나도 보내지 않는다 (부분 잠금 방지)
    for (const p of participants) {
      const bal = Number(await pieCoin.balanceOf(p.address));
      if (bal < p.amount) throw new InsufficientBalanceError(p.name, p.amount, bal);
    }

    // 같은 그룹을 여러 번 승인해도 충돌하지 않도록 매번 새 온체인 id
    const onchainId = ethers.keccak256(ethers.toUtf8Bytes(`${settlementId}:${Date.now()}:${Math.random()}`));

    // 2) 정산 등록
    const openReceipt = await waitFor(await send('open_settlement', [onchainId, participants.map((p) => p.address), participants.map((p) => p.amount)], nameOf), nameOf);

    // 3) 잠금 — 트랜잭션을 연달아 보낸 뒤 한꺼번에 확정을 기다린다 (Sepolia 블록 대기 시간 절약)
    const sent = [];
    for (const p of participants) sent.push({ p, tx: await send('lock_for_settlement', [onchainId, p.address, p.amount], nameOf) });
    const lockReceipts = await Promise.all(sent.map(({ tx }) => waitFor(tx, nameOf)));

    // 4) 지급 — 컨트랙트가 "전원 잠금 완료"가 아니면 거부
    const releaseReceipt = await waitFor(await send('release_to_recipient', [onchainId, recipientAddress], nameOf), nameOf);

    return {
      mock: false,
      network,
      chainId: Number(chainId),
      contractAddress: await settlement.getAddress(),
      settlementOnchainId: onchainId,
      recipient,
      recipientAddress,
      viaEscrow,
      open: { txHash: openReceipt.hash, block: formatBlock(openReceipt.blockNumber) },
      locks: sent.map(({ p }, i) => ({
        from: p.name,
        to: recipient,
        amount: p.amount,
        txHash: lockReceipts[i].hash,
        fromAddress: p.address,
        block: formatBlock(lockReceipts[i].blockNumber),
      })),
      release: {
        txHash: releaseReceipt.hash,
        block: formatBlock(releaseReceipt.blockNumber),
        blockNumber: releaseReceipt.blockNumber,
        amount: participants.reduce((a, p) => a + p.amount, 0),
        explorerUrl: explorer(releaseReceipt.hash),
      },
    };
  }

  return { network, chainId: Number(chainId), recordSettlement, chargeToken, balanceOf };
}

module.exports = { createOnchainClient, InsufficientBalanceError, BlockchainError, ESCROW_RECIPIENT, ALLOWED_CHAINS };
