'use strict';

// 허용 체인 목록 — Sepolia 고정을 풀고 대회 테스트넷(EVM 호환)도 env 로 추가할 수 있게 한다.
// ⚠️ 테스트넷/데브넷 전용 (CLAUDE.md 0번 원칙 4). 메인넷 chainId 는 명시적으로 거부한다.
// ethers 를 require 하지 않는다 (MOCK 모드에서도 /health·preflight 가 쓴다).
//
// env (선택, 기본 Sepolia):
//   CHAIN_ID          예: 11155111
//   CHAIN_NAME        예: sepolia
//   EXPLORER_TX_URL   예: https://sepolia.etherscan.io/tx/{hash}   ({hash} 자리에 트랜잭션 해시. {address} 는 주소용)

const BUILTIN = {
  11155111: { name: 'sepolia', explorerTx: 'https://sepolia.etherscan.io/tx/{hash}', explorerAddress: 'https://sepolia.etherscan.io/address/{address}', testnet: true },
  31337: { name: 'hardhat-local', explorerTx: null, explorerAddress: null, testnet: true },
};

// 메인넷(실제 자산) — 어떤 설정으로도 허용하지 않는다
const MAINNET_CHAIN_IDS = {
  1: 'Ethereum Mainnet', 10: 'OP Mainnet', 56: 'BNB Smart Chain', 100: 'Gnosis', 137: 'Polygon Mainnet',
  250: 'Fantom Opera', 324: 'zkSync Era Mainnet', 1101: 'Polygon zkEVM', 5000: 'Mantle', 8453: 'Base Mainnet',
  42161: 'Arbitrum One', 42220: 'Celo Mainnet', 43114: 'Avalanche C-Chain', 59144: 'Linea Mainnet', 81457: 'Blast', 534352: 'Scroll',
};

class ChainNotAllowedError extends Error {
  constructor(chainId, reason) {
    super(reason);
    this.name = 'ChainNotAllowedError';
    this.code = 'CHAIN_NOT_ALLOWED';
    this.status = 503;
    this.chainId = chainId;
  }
}

function parseChainId(v) {
  const n = Number(v);
  return Number.isSafeInteger(n) && n > 0 ? n : null;
}

// env 로 추가한 커스텀 체인 (대회 테스트넷). 메인넷 id 면 설정 단계에서 바로 실패.
function customChainFromEnv(env = process.env) {
  const id = parseChainId(env.CHAIN_ID);
  if (!id) return null;
  if (MAINNET_CHAIN_IDS[id]) throw new ChainNotAllowedError(id, `CHAIN_ID ${id}(${MAINNET_CHAIN_IDS[id]})는 메인넷이라 허용되지 않아요. SharePie는 테스트넷 전용이에요.`);
  const tx = env.EXPLORER_TX_URL && env.EXPLORER_TX_URL.includes('{hash}') ? env.EXPLORER_TX_URL : null;
  return { name: env.CHAIN_NAME || `chain-${id}`, explorerTx: tx, explorerAddress: env.EXPLORER_ADDRESS_URL && env.EXPLORER_ADDRESS_URL.includes('{address}') ? env.EXPLORER_ADDRESS_URL : null, testnet: true, custom: true };
}

// chainId → { name, explorerTx(hash), explorerAddress(addr) } 또는 null(허용 안 됨)
function allowedChains(env = process.env) {
  const map = { ...BUILTIN };
  const custom = customChainFromEnv(env);
  if (custom) map[parseChainId(env.CHAIN_ID)] = custom;
  return map;
}

function describeChain(chainId, env = process.env) {
  const id = parseChainId(chainId);
  if (id === null) return null;
  if (MAINNET_CHAIN_IDS[id]) return null;
  const c = allowedChains(env)[id];
  if (!c) return null;
  return {
    chainId: id,
    name: c.name,
    testnet: true,
    custom: Boolean(c.custom),
    explorerTx: (hash) => (c.explorerTx ? c.explorerTx.replace('{hash}', hash) : null),
    explorerAddress: (addr) => (c.explorerAddress ? c.explorerAddress.replace('{address}', addr) : null),
  };
}

// 허용 여부 검사 — 통과하면 describeChain 결과, 아니면 ChainNotAllowedError
function assertAllowedChain(chainId, env = process.env) {
  const id = parseChainId(chainId);
  if (id !== null && MAINNET_CHAIN_IDS[id]) throw new ChainNotAllowedError(id, `chainId ${id}(${MAINNET_CHAIN_IDS[id]})는 메인넷이라 허용되지 않아요. SharePie는 테스트넷 전용이에요.`);
  const d = describeChain(chainId, env);
  if (!d) throw new ChainNotAllowedError(id, `chainId ${chainId}는 허용 목록에 없어요. 기본 허용: Sepolia(11155111), 로컬 Hardhat(31337). 대회 테스트넷은 backend/.env의 CHAIN_ID·CHAIN_NAME·EXPLORER_TX_URL로 추가하세요.`);
  return d;
}

// 설정상의 "목표 체인" (env CHAIN_ID 없으면 Sepolia)
function configuredChainId(env = process.env) {
  return parseChainId(env.CHAIN_ID) || 11155111;
}

module.exports = { BUILTIN, MAINNET_CHAIN_IDS, ChainNotAllowedError, allowedChains, describeChain, assertAllowedChain, configuredChainId, customChainFromEnv, parseChainId };
