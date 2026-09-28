// SharePie 컨트랙트 — Hardhat 설정
// ⚠️ 테스트넷 전용: 로컬(hardhat), Sepolia(11155111), 그리고 env 로 추가한 대회 테스트넷(custom)만 정의한다.
//    메인넷 chainId 는 backend/src/blockchain/chains.js 의 거부 목록에 걸려 설정 단계에서 throw 된다.
// 비밀값은 backend/.env 하나에서 읽는다 (BLOCKCHAIN_RPC_URL, DEPLOYER_PRIVATE_KEY, CHAIN_ID).
require('@nomicfoundation/hardhat-toolbox');
require('dotenv').config({ path: require('path').join(__dirname, '..', 'backend', '.env'), quiet: true });
const { customChainFromEnv, parseChainId } = require(require('path').join(__dirname, '..', 'backend', 'src', 'blockchain', 'chains'));

const { BLOCKCHAIN_RPC_URL, DEPLOYER_PRIVATE_KEY } = process.env;
const pk = DEPLOYER_PRIVATE_KEY ? (DEPLOYER_PRIVATE_KEY.startsWith('0x') ? DEPLOYER_PRIVATE_KEY : '0x' + DEPLOYER_PRIVATE_KEY) : null;

// 대회 테스트넷 등 커스텀 체인: CHAIN_ID(+CHAIN_NAME, EXPLORER_TX_URL). 메인넷 id 면 customChainFromEnv 가 throw
const custom = customChainFromEnv();
const customNetwork = custom && parseChainId(process.env.CHAIN_ID) !== 11155111
  ? { custom: { url: BLOCKCHAIN_RPC_URL || 'https://rpc.custom.invalid', chainId: parseChainId(process.env.CHAIN_ID), accounts: pk ? [pk] : [] } }
  : {};

module.exports = {
  solidity: {
    version: '0.8.24',
    settings: { optimizer: { enabled: true, runs: 200 } },
  },
  networks: {
    hardhat: {},
    sepolia: {
      url: BLOCKCHAIN_RPC_URL || 'https://rpc.sepolia.invalid', // 비어 있으면 연결 단계에서 실패 (배포 스크립트가 안내)
      chainId: 11155111,
      accounts: pk ? [pk] : [],
    },
    ...customNetwork,
  },
};
