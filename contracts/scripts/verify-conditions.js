// 제3자 검증: 정산 조건 JSON을 다시 해시해서 체인에 기록된 conditionsHash와 대조한다
// 사용법: node scripts/verify-conditions.js <conditions.json 경로> <settlementOnchainId(bytes32) 또는 open 트랜잭션 해시>
//   - backend/.env 의 BLOCKCHAIN_RPC_URL · CONTRACT_ADDRESS 를 읽는다 (없으면 안내 후 종료)
//   - 백엔드와 같은 canonicalize/hashConditions 를 쓰므로, 로그의 conditions 원문이 그대로면 반드시 MATCH
// ⚠️ 테스트넷 전용. 읽기만 하며 트랜잭션을 보내지 않는다.
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
const { ethers } = require(path.join(BACKEND, 'node_modules', 'ethers'));
const { hashConditions, canonicalize } = require(path.join(BACKEND, 'src', 'blockchain', 'conditionsHash'));
const { SETTLEMENT_ABI } = require(path.join(BACKEND, 'src', 'blockchain', 'abi'));

// 체인에서 조건 해시를 읽는다. ref 가 settlementOnchainId 면 conditionsHashOf, 트랜잭션 해시면 영수증의 SettlementOpened 이벤트.
async function readOnchainConditionsHash({ provider, contractAddress, ref }) {
  const contract = new ethers.Contract(contractAddress, SETTLEMENT_ABI, provider);
  const direct = await contract.conditionsHashOf(ref);
  if (direct && !/^0x0{64}$/.test(direct)) return { onchainHash: direct, settlementOnchainId: ref, source: 'conditionsHashOf' };

  const receipt = await provider.getTransactionReceipt(ref);
  if (!receipt) throw new Error(`체인에서 찾을 수 없어요: ${ref} (settlementOnchainId도 아니고 트랜잭션 해시도 아님)`);
  for (const log of receipt.logs) {
    if (log.address.toLowerCase() !== contractAddress.toLowerCase()) continue;
    let parsed;
    try { parsed = contract.interface.parseLog(log); } catch { continue; }
    if (parsed && parsed.name === 'SettlementOpened') {
      return { onchainHash: parsed.args.conditionsHash, settlementOnchainId: parsed.args.settlementId, source: 'SettlementOpened 이벤트' };
    }
  }
  throw new Error(`트랜잭션 ${ref} 에 SettlementOpened 이벤트가 없어요.`);
}

// 대조 로직 (테스트에서도 직접 호출) → { match, localHash, onchainHash, canonical, settlementOnchainId, source }
async function verifyConditions({ conditions, ref, provider, contractAddress }) {
  const canonical = canonicalize(conditions);
  const localHash = hashConditions(conditions);
  const onchain = await readOnchainConditionsHash({ provider, contractAddress, ref });
  return { match: localHash.toLowerCase() === String(onchain.onchainHash).toLowerCase(), localHash, canonical, ...onchain };
}

async function main() {
  const [file, ref] = process.argv.slice(2);
  if (!file || !ref) {
    console.error('사용법: node scripts/verify-conditions.js <conditions.json> <settlementOnchainId 또는 open 트랜잭션 해시>');
    process.exitCode = 2;
    return;
  }
  require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });
  const { BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS } = process.env;
  if (!BLOCKCHAIN_RPC_URL || !CONTRACT_ADDRESS) {
    console.error('backend/.env 에 BLOCKCHAIN_RPC_URL 과 CONTRACT_ADDRESS 가 있어야 체인과 대조할 수 있어요 (컨트랙트 배포 후 실행).');
    process.exitCode = 2;
    return;
  }
  const conditions = JSON.parse(fs.readFileSync(file, 'utf8'));
  const provider = new ethers.JsonRpcProvider(BLOCKCHAIN_RPC_URL);
  const r = await verifyConditions({ conditions, ref, provider, contractAddress: CONTRACT_ADDRESS });
  console.log(`정산 id      : ${r.settlementOnchainId}  (${r.source})`);
  console.log(`정규화 조건  : ${r.canonical}`);
  console.log(`로컬 해시    : ${r.localHash}`);
  console.log(`체인 해시    : ${r.onchainHash}`);
  console.log(r.match ? '✅ MATCH — 체인에 기록된 조건과 일치해요' : '❌ MISMATCH — 조건 원문이 체인 기록과 달라요');
  process.exitCode = r.match ? 0 : 1;
}

module.exports = { verifyConditions, readOnchainConditionsHash };

if (require.main === module) {
  main().catch((err) => { console.error('❌', err.message); process.exitCode = 1; });
}
