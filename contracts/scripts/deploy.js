// SharePieSettlement(+ PieCoin) 배포 — 테스트넷 전용 (Sepolia 또는 env 로 추가한 대회 테스트넷)
// 실행: cd contracts && npm run deploy:sepolia   (커스텀 체인: npx hardhat run scripts/deploy.js --network custom)
// ⚠️ 허용 목록(backend/src/blockchain/chains.js)에 없는 chainId·메인넷이면 배포를 거부한다.
const fs = require('fs');
const path = require('path');
const hre = require('hardhat');
const { assertAllowedChain } = require(path.join(__dirname, '..', '..', 'backend', 'src', 'blockchain', 'chains'));

async function main() {
  const isLocal = hre.network.name === 'hardhat';
  // 네트워크에 연결하기 전에 설정부터 확인 (비어 있으면 알아보기 힘든 DNS 에러가 먼저 나기 때문)
  if (!isLocal && (!process.env.BLOCKCHAIN_RPC_URL || !process.env.DEPLOYER_PRIVATE_KEY)) {
    throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL과 DEPLOYER_PRIVATE_KEY를 먼저 넣어 주세요.');
  }
  const { chainId } = await hre.ethers.provider.getNetwork();
  const chain = assertAllowedChain(Number(chainId)); // 메인넷·미허용 체인이면 throw (테스트넷 전용)

  const [deployer] = await hre.ethers.getSigners();
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log(`네트워크   : ${chain.name} (hardhat: ${hre.network.name}, chainId ${chainId})`);
  console.log(`배포 지갑  : ${deployer.address}`);
  console.log(`가스용 ETH : ${hre.ethers.formatEther(balance)} ETH (테스트넷 ETH)`);
  if (balance === 0n) throw new Error('배포 지갑에 Sepolia 테스트 ETH가 없어요. faucet에서 먼저 받아 주세요.');

  const Factory = await hre.ethers.getContractFactory('SharePieSettlement');
  const contract = await Factory.deploy();
  const deployTx = contract.deploymentTransaction();
  console.log(`배포 트랜잭션: ${deployTx.hash} (확정 대기 중…)`);
  await contract.waitForDeployment();

  const address = await contract.getAddress();
  const pieCoin = await contract.pieCoin();
  const record = { network: chain.name, hardhatNetwork: hre.network.name, chainId: Number(chainId), settlement: address, pieCoin, deployer: deployer.address, txHash: deployTx.hash, explorerUrl: chain.explorerAddress(address), deployedAt: new Date().toISOString() };

  const outDir = path.join(__dirname, '..', 'deployments');
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, `${hre.network.name}.json`), JSON.stringify(record, null, 2) + '\n');

  console.log('\n✅ 배포 완료');
  console.log(`   SharePieSettlement : ${address}`);
  console.log(`   PieCoin (PIE)      : ${pieCoin}`);
  if (!isLocal) {
    if (record.explorerUrl) console.log(`   탐색기             : ${record.explorerUrl}`);
    console.log('\n👉 backend/.env 에 아래 한 줄을 넣고 백엔드를 다시 시작하세요:');
    console.log(`   CONTRACT_ADDRESS=${address}`);
  }
}

main().catch((err) => {
  console.error('❌', err.message);
  process.exitCode = 1;
});
