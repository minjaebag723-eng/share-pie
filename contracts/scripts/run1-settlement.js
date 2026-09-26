// CLAUDE.md 9번 Run 1 (정상 정산) — Sepolia 테스트넷에서 실제로 실행해 TxHash 확보
// 실행: cd contracts && npm run run1:sepolia
//
// 백엔드가 /settlement/approve 에서 쓰는 코드(계산 + blockchainClient)를 그대로 사용한다.
//   1) 정산 계산 (코드, 0 tokens)  삼겹살 35,900원 · 진주 5,000원 적게 · 4명
//   2) 잔액이 모자란 멤버만 charge_token 으로 충전
//   3) open_settlement → lock_for_settlement × 4 → release_to_recipient (Pie 에스크로 → 결제처)
//   4) TxHash · Etherscan 링크 출력 + backend/logs/run1-*.json 저장 (제출 자료용)
// ⚠️ 테스트넷 전용. PieCoin은 실화폐 가치가 없다.
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const { computeSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'calculateSettlement'));
const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { addressOf } = require(path.join(BACKEND, 'src', 'blockchain', 'members'));

async function main() {
  if (blockchain.IS_MOCK) {
    throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드).');
  }
  if (!process.env.MERCHANT_ADDRESS) throw new Error('backend/.env에 MERCHANT_ADDRESS(테스트 결제처 주소)를 넣어 주세요.');

  const log = { run: 'Run 1 (정상 정산)', startedAt: new Date().toISOString(), steps: [] };
  const step = (name, data) => { log.steps.push({ name, ...data }); console.log(`\n▶ ${name}\n${JSON.stringify(data, null, 2)}`); };

  // 1) 정산 계산 — 정산 코어 Stage 2 (코드 전용)
  const members = ['진주', '진우', '민재', '지현'];
  const calc = computeSettlement({
    members, mode: 'ADJUST', itemName: '삼겹살 1.2kg', total: 35900,
    participants: members, adjustments: { 진주: -5000 }, ratios: null, items: null, totalBudget: 40000, payer: null,
  });
  step('1. 정산 계산 (settlement.calculate: 0 tokens, code-only)', { members: calc.members, shares: calc.shares, total: calc.total, withinBudget: calc.withinBudget, rule: calc.rule });
  if (!calc.withinBudget) throw new Error('예산 초과 — Run 1은 예산 내 정산이어야 해요.');

  // 2) 잔액 확인 → 모자란 멤버만 충전
  const charges = [];
  for (let i = 0; i < members.length; i++) {
    const bal = await blockchain.getBalance(members[i]);
    if (bal < calc.shares[i]) charges.push(await blockchain.chargeToken(members[i], calc.shares[i] - bal));
  }
  step('2. PieCoin 충전 (charge_token)', {
    addresses: Object.fromEntries(members.map((m) => [m, addressOf(m)])),
    charges: charges.map((c) => ({ name: c.name, amount: c.amount, txHash: c.txHash, explorerUrl: c.explorerUrl })),
  });

  // 3) 전원 승인 → 온체인 기록 (백엔드 /settlement/approve 와 같은 함수)
  console.log('\n… Sepolia에 정산 등록·잠금·지급 트랜잭션을 보내는 중 (약 1분)');
  const onchain = await blockchain.recordSettlementOnchain({ settlementId: 'run1-demo', members: calc.members, shares: calc.shares, payer: calc.payer });
  step('3. 온체인 기록 (open → lock × N → release)', onchain);

  // 4) 잔액 재확인 (전원 잠금 → 결제처로 지급됐는지)
  const after = {};
  for (const m of members) after[m] = await blockchain.getBalance(m);
  step('4. 정산 후 멤버 잔액 (PIE)', after);

  log.finishedAt = new Date().toISOString();
  log.txHash = onchain.release.txHash;
  const outDir = path.join(BACKEND, 'logs');
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, `run1-${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify(log, null, 2) + '\n');

  console.log('\n✅ Run 1 완료');
  console.log(`   지급(release) TxHash : ${onchain.release.txHash}`);
  if (onchain.release.explorerUrl) console.log(`   Etherscan            : ${onchain.release.explorerUrl}`);
  console.log(`   로그 파일            : ${file}`);
}

main().catch((err) => {
  console.error('❌', err.code ? `[${err.code}]` : '', err.message);
  process.exitCode = 1;
});
