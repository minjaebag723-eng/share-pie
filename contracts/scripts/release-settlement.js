// 보류가 끝난 정산을 지급 (★ release_to_recipient) — Sepolia 테스트넷
// 사용법: cd contracts && npm run release:sepolia -- <settlementOnchainId>
//   - 보류 기간(holdUntil)이 지났으면 release 하고 TxHash 출력
//   - 아직이면 남은 시간만 출력하고 아무 트랜잭션도 보내지 않는다
//   - 분쟁 중(DISPUTED)·취소(CANCELLED)·이미 지급(RELEASED)이면 체인이 거부한다 (INVALID_STATUS)
// ⚠️ 테스트넷 전용. PieCoin은 실화폐 가치가 없다.
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { releaseSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'settlementActions'));
const { findSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'settlementStore'));

function fmt(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? `${m}분 ${s}초` : `${s}초`;
}

async function main() {
  const [settlementOnchainId] = process.argv.slice(2);
  if (!settlementOnchainId) throw new Error('사용법: npm run release:sepolia -- <settlementOnchainId>');
  if (blockchain.IS_MOCK) throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드).');

  const state = await blockchain.getSettlementState({ settlementOnchainId });
  console.log(`정산 상태 : ${state.state}  (잠금 ${state.lockedCount}/${state.participantCount}, 보관 ${state.totalLocked} PIE)`);
  if (state.state !== 'LOCKED') throw new Error(`LOCKED 상태에서만 지급할 수 있어요 (현재 ${state.state}).`);

  const now = Math.floor(Date.now() / 1000);
  if (now < state.holdUntil) {
    console.log(`⏳ 보류 중 — ${fmt(state.holdUntil - now)} 뒤(${new Date(state.holdUntil * 1000).toLocaleString('ko-KR')})부터 지급할 수 있어요. 트랜잭션을 보내지 않았어요.`);
    return;
  }
  if (!findSettlement(settlementOnchainId)) {
    throw new Error('backend/data/settlements.json 에 이 정산 기록이 없어요 (run1 스크립트나 /settlement/approve 로 만든 정산만 지급할 수 있어요).');
  }
  const r = await releaseSettlement({ settlementOnchainId });
  console.log('✅ 지급 완료');
  console.log(`   받는 곳          : ${r.recipient}`);
  console.log(`   금액             : ${r.release.amount} PIE`);
  console.log(`   release TxHash   : ${r.release.txHash}`);
  if (r.release.explorerUrl) console.log(`   Etherscan        : ${r.release.explorerUrl}`);
}

main().catch((err) => {
  console.error('❌', err.code ? `[${err.code}]` : '', err.message);
  process.exitCode = 1;
});
