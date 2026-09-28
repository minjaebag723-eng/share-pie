'use strict';
// PieToken + ShareLedger 스크립트 배포 (Remix 수동 배포 대체). 테스트넷 전용 — 메인넷 chainId 는 거부.
// 실행:  cd hardhat && npm run deploy -- --network sepolia   (또는 bsctest)
// 결과:  hardhat/deployments/<network>.json, contracts/abi/{ShareLedger,PieToken}.json (web3.py 가 우선 사용),
//        그리고 backend .env 에 넣을 줄을 출력한다. 비밀키는 절대 출력하지 않는다.
const hre = require('hardhat');
const fs = require('fs');
const path = require('path');

const MAINNET_CHAIN_IDS = new Set([1, 56, 137, 42161, 10, 8453, 43114, 250, 25, 100]);
const EXPLORERS = { 11155111: 'https://sepolia.etherscan.io', 97: 'https://testnet.bscscan.com' };
const ROOT = path.join(__dirname, '..', '..');

async function main() {
  const { chainId } = await hre.ethers.provider.getNetwork();
  const cid = Number(chainId);
  if (MAINNET_CHAIN_IDS.has(cid)) throw new Error(`chainId ${cid} 는 메인넷이에요. 테스트넷에만 배포합니다.`);
  const [deployer] = await hre.ethers.getSigners();
  const bal = await hre.ethers.provider.getBalance(deployer.address);
  const windowSec = Number(process.env.DISPUTE_WINDOW_SEC || hre.userConfig.sharePie?.disputeWindowSec || 180);

  console.log(`네트워크  : ${hre.network.name} (chainId ${cid})`);
  console.log(`에이전트  : ${deployer.address}  잔액 ${hre.ethers.formatEther(bal)} (테스트넷 가스)`);
  if (bal === 0n && cid !== 31337) throw new Error('가스용 테스트 ETH/BNB 가 없어요. faucet 에서 받은 뒤 다시 실행하세요.');

  // 공개 RPC 는 pending nonce 가 늦게 갱신될 때가 있어 "nonce too low" 가 나면 잠깐 기다렸다 다시 보낸다
  async function withRetry(label, fn) {
    for (let i = 1; i <= 4; i++) {
      try { return await fn(); } catch (e) {
        if (!/nonce too low|replacement transaction underpriced|already known/i.test(e.message) || i === 4) throw e;
        console.log(`  ${label}: nonce 지연 → ${i * 4}초 후 재시도`);
        await new Promise((r) => setTimeout(r, i * 4000));
      }
    }
  }

  // 이미 배포된 PieToken 을 재사용하려면 TOKEN_ADDRESS_REUSE=0x... (이전 실행이 중간에 끊겼을 때)
  let token, tokenTx;
  if (process.env.TOKEN_ADDRESS_REUSE) {
    token = await hre.ethers.getContractAt('PieToken', process.env.TOKEN_ADDRESS_REUSE);
    tokenTx = { hash: '(재사용)' };
    console.log(`PieToken     : ${await token.getAddress()}  (기존 배포 재사용)`);
  } else {
    token = await withRetry('PieToken', async () => { const t = await (await hre.ethers.getContractFactory('PieToken')).deploy(); await t.waitForDeployment(); return t; });
    tokenTx = token.deploymentTransaction();
    console.log(`PieToken     : ${await token.getAddress()}  (tx ${tokenTx.hash})`);
  }

  const ledger = await withRetry('ShareLedger', async () => { const l = await (await hre.ethers.getContractFactory('ShareLedger')).deploy(); await l.waitForDeployment(); return l; });
  const ledgerTx = ledger.deploymentTransaction();
  const ledgerReceipt = await ledgerTx.wait();
  console.log(`ShareLedger  : ${await ledger.getAddress()}  (tx ${ledgerTx.hash}, block ${ledgerReceipt.blockNumber})`);

  if (windowSec !== 180) {
    const tx = await withRetry('setDisputeWindow', () => ledger.setDisputeWindow(windowSec));
    await tx.wait();
    console.log(`disputeWindow: ${windowSec}s (tx ${tx.hash})`);
  } else {
    console.log('disputeWindow: 180s (컨트랙트 기본값)');
  }

  // ABI 저장 → agent/abi.py 가 contracts/abi/*.json 을 우선 사용
  const abiDir = path.join(ROOT, 'contracts', 'abi');
  fs.mkdirSync(abiDir, { recursive: true });
  for (const name of ['ShareLedger', 'PieToken']) {
    const art = await hre.artifacts.readArtifact(name);
    fs.writeFileSync(path.join(abiDir, `${name}.json`), JSON.stringify(art.abi, null, 2) + '\n');
  }

  const record = {
    network: hre.network.name, chainId: cid, deployedAt: new Date().toISOString(),
    agent: deployer.address,
    token: await token.getAddress(), tokenTx: tokenTx.hash,
    ledger: await ledger.getAddress(), ledgerTx: ledgerTx.hash, ledgerDeployBlock: ledgerReceipt.blockNumber,
    disputeWindowSec: windowSec, explorer: EXPLORERS[cid] || null,
  };
  const outDir = path.join(__dirname, '..', 'deployments');
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, `${hre.network.name}.json`), JSON.stringify(record, null, 2) + '\n');

  console.log('\n✅ 배포 완료. backend .env 에 넣을 값:');
  console.log(`CHAIN_MODE=bsc`);
  console.log(`BSC_CHAIN_ID=${cid}`);
  console.log(`LEDGER_ADDRESS=${record.ledger}`);
  console.log(`TOKEN_ADDRESS=${record.token}`);
  console.log(`LEDGER_DEPLOY_BLOCK=${record.ledgerDeployBlock}`);
  if (record.explorer) {
    console.log(`BSC_EXPLORER=${record.explorer}`);
    console.log(`\n탐색기: ${record.explorer}/address/${record.ledger}`);
  }
  console.log('(AGENT_PRIVATE_KEY 는 배포에 쓴 지갑의 비밀키 — .env 에만, 출력하지 않음)');
}

main().catch((e) => { console.error('❌ 배포 실패:', e.message); process.exit(1); });
