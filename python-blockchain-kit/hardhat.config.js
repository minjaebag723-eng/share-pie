'use strict';
// Hardhat 설정 (컨트랙트 테스트·스크립트 배포용). 소스 = ./contracts (수정하지 않음).
// 의존성·테스트·산출물은 전부 ./hardhat 안에 둔다:  cd hardhat && npm install && npm test
// 네트워크 값은 이 폴더의 .env 에서 읽는다 (BSC_RPC_URL, BSC_CHAIN_ID, AGENT_PRIVATE_KEY, DISPUTE_WINDOW_SEC).
// ⚠️ 테스트넷 전용. 메인넷 chainId 는 설정 단계에서 거부한다.
const fs = require('fs');
const path = require('path');
require(path.join(__dirname, 'hardhat', 'node_modules', '@nomicfoundation', 'hardhat-toolbox'));

// .env 를 의존성 없이 읽는다 (KEY=value, # 주석, 따옴표 제거). process.env 가 우선.
function readEnv(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return out;
}
const env = { ...readEnv(path.join(__dirname, '.env')), ...process.env };
const pk = env.AGENT_PRIVATE_KEY ? [env.AGENT_PRIVATE_KEY.startsWith('0x') ? env.AGENT_PRIVATE_KEY : '0x' + env.AGENT_PRIVATE_KEY] : [];
const MAINNET = new Set([1, 56, 137, 42161, 10, 8453, 43114]);
const cid = Number(env.BSC_CHAIN_ID || 97);
if (MAINNET.has(cid)) throw new Error(`BSC_CHAIN_ID=${cid} 는 메인넷이에요. 테스트넷만 허용합니다.`);

module.exports = {
  solidity: { version: '0.8.24', settings: { optimizer: { enabled: true, runs: 200 } } },
  paths: {
    sources: './contracts',
    tests: './hardhat/test',
    cache: './hardhat/cache',
    artifacts: './hardhat/artifacts',
  },
  networks: {
    hardhat: { chainId: 31337 },
    // .env 의 BSC_RPC_URL / BSC_CHAIN_ID 가 가리키는 테스트넷 (이름은 호환용. Sepolia 등 EVM 테스트넷이면 뭐든 됨)
    testnet: { url: env.BSC_RPC_URL || 'https://data-seed-prebsc-1-s1.bnbchain.org:8545', chainId: cid, accounts: pk },
    sepolia: { url: env.SEPOLIA_RPC_URL || 'https://ethereum-sepolia-rpc.publicnode.com', chainId: 11155111, accounts: pk },
    bsctest: { url: 'https://data-seed-prebsc-1-s1.bnbchain.org:8545', chainId: 97, accounts: pk },
  },
  sharePie: { disputeWindowSec: Number(env.DISPUTE_WINDOW_SEC || 180) },
};
