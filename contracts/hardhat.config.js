// SharePie 컨트랙트 — Hardhat 설정
// ⚠️ 테스트넷 전용: 네트워크는 로컬(hardhat)과 Sepolia(chainId 11155111)만 정의한다. 메인넷 설정을 추가하지 않는다.
// 비밀값은 backend/.env 하나에서 읽는다 (BLOCKCHAIN_RPC_URL, DEPLOYER_PRIVATE_KEY).
require('@nomicfoundation/hardhat-toolbox');
require('dotenv').config({ path: require('path').join(__dirname, '..', 'backend', '.env'), quiet: true });

const { BLOCKCHAIN_RPC_URL, DEPLOYER_PRIVATE_KEY } = process.env;
const pk = DEPLOYER_PRIVATE_KEY ? (DEPLOYER_PRIVATE_KEY.startsWith('0x') ? DEPLOYER_PRIVATE_KEY : '0x' + DEPLOYER_PRIVATE_KEY) : null;

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
  },
};
