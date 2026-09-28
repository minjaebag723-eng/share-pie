// CLAUDE.md 9번 Run 1 (정상 정산) — 테스트넷에서 실제로 실행해 TxHash 확보
// 실행: cd contracts && npm run run1:sepolia   (MOCK 모드에서는 demo-all 이 allowMock 으로 부른다)
//
// 백엔드가 /settlement/approve 에서 쓰는 코드(계산 + blockchainClient)를 그대로 사용한다.
//   1) 정산 계산 (코드, AI 토큰 0)  삼겹살 35,900원 · 진주 5,000원 적게 · 4명 · 예산 40,000
//   2) 잔액이 모자란 멤버만 charge_token 으로 충전
//   3) open_settlement → lock_for_settlement × 4 → Locked(보류 시작). 인증서 TxHash = confirm(마지막 lock)
//   4) 로그 backend/logs/run1-*.json (제출 자료용). 지급(release)은 보류 기간 뒤 release-settlement.js
// ⚠️ 테스트넷 전용. PieCoin은 실화폐 가치가 없다.
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const { computeSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'calculateSettlement'));
const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { hashConditions, canonicalize } = require(path.join(BACKEND, 'src', 'blockchain', 'conditionsHash'));
const { saveSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'settlementStore'));

// 멤버는 uid로만 다룬다 (체인·계산 입력). 표시 이름은 아래 맵으로 로그·콘솔에만 붙인다 — 체인에는 절대 넘기지 않는다.
const NAME_OF = { u0: '진주', u1: '진우', u2: '민재', u3: '지현' };
const MEMBERS = ['u0', 'u1', 'u2', 'u3'];
// 승인된 조건(계산 입력) 그대로. 이 객체를 해시해 open_settlement에 기록한다 (제3자 검증용)
const CONDITIONS = { members: MEMBERS, mode: 'ADJUST', itemName: '삼겹살 1.2kg', total: 35900, participants: MEMBERS, adjustments: { u0: -5000 }, ratios: null, items: null, totalBudget: 40000, payer: null };
const REQUEST_TEXT = '삼겹살 1.2kg 35,900원, 진주는 5천원 적게 내고 나머지가 똑같이 나눠줘. 예산 4만원.';

function addressOfSafe(uid) {
  if (blockchain.IS_MOCK) return null; // MOCK 에서는 ethers 를 불러오지 않는다
  return require(path.join(BACKEND, 'src', 'blockchain', 'members')).addressOf(uid);
}

// 본체 — CLI·demo-all 이 같이 쓴다
async function runRun1({ allowMock = false, quiet = false, holdSeconds } = {}) {
  if (!allowMock && blockchain.IS_MOCK) throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드). MOCK으로 돌리려면 allowMock 옵션을 쓰세요.');
  if (!blockchain.IS_MOCK && !process.env.MERCHANT_ADDRESS) throw new Error('backend/.env에 MERCHANT_ADDRESS(테스트 결제처 주소)를 넣어 주세요.');
  const say = (m) => { if (!quiet) console.log(m); };
  const log = { run: 'Run 1 (정상 정산)', mock: blockchain.IS_MOCK, startedAt: new Date().toISOString(), steps: [] };
  const step = (name, data) => { log.steps.push({ name, ...data }); say(`\n▶ ${name}\n${JSON.stringify(data, null, 2)}`); };
  const who = (uid) => ({ uid, name: NAME_OF[uid] || uid, address: addressOfSafe(uid) });

  // 1) 정산 계산 — 정산 코어 Stage 2 (코드 전용, AI 토큰 0)
  const calc = computeSettlement(CONDITIONS);
  const conditionsCanonical = canonicalize(CONDITIONS);
  const conditionsHash = hashConditions(CONDITIONS);
  log.conditions = CONDITIONS; log.conditionsCanonical = conditionsCanonical; log.conditionsHash = conditionsHash;
  step('1. 정산 계산 (settlement.calculate: AI 토큰 0, code-only)', {
    members: calc.members.map((uid, i) => ({ ...who(uid), share: calc.shares[i] })),
    total: calc.total, withinBudget: calc.withinBudget, rule: calc.rule, conditionsHash,
  });
  if (!calc.withinBudget) throw new Error('예산 초과 — Run 1은 예산 내 정산이어야 해요.');

  // 2) 잔액 확인 → 모자란 멤버만 충전 (MOCK: 충전한 uid 만 잔액 추적)
  const charges = [];
  for (let i = 0; i < MEMBERS.length; i++) {
    const bal = await blockchain.getBalance(MEMBERS[i]);
    if (bal === null || bal < calc.shares[i]) charges.push(await blockchain.chargeToken(MEMBERS[i], calc.shares[i] - (bal || 0)));
  }
  step('2. PieCoin 충전 (charge_token)', {
    members: MEMBERS.map(who),
    charges: charges.map((c) => ({ ...who(c.uid), amount: c.amount, txHash: c.txHash, explorerUrl: c.explorerUrl || null })),
  });

  // 3) 전원 승인 → 온체인 등록·전원 잠금 (백엔드 /settlement/approve 와 같은 함수). 지급(release)은 보류 기간 뒤 따로.
  say(`\n… ${blockchain.IS_MOCK ? 'MOCK' : '테스트넷'}에 정산 등록·잠금 트랜잭션을 보내는 중${blockchain.IS_MOCK ? '' : ' (약 1분)'}`);
  const onchain = await blockchain.recordSettlementOnchain({ settlementId: 'run1-demo', members: calc.members, shares: calc.shares, payer: calc.payer, conditionsHash, holdSeconds });
  log.openTxHash = onchain.open && onchain.open.txHash;
  log.settlementOnchainId = onchain.settlementOnchainId;
  log.holdSeconds = onchain.holdSeconds;
  log.holdUntil = onchain.holdUntil;
  log.shares = calc.shares;
  log.nameOf = NAME_OF;
  log.requestText = REQUEST_TEXT;
  step('3. 온체인 기록 (open → lock × N → Locked, 보류 시작) — 인증서 TxHash = confirm', {
    ...onchain,
    locks: onchain.locks.map((l) => ({ ...l, fromName: NAME_OF[l.from] || l.from })),
  });

  // 저장소 기록 — release / raise·resolve·refund 가 참여자·payer 를 여기서 찾는다 (/settlement/approve 와 동일)
  saveSettlement({
    settlementOnchainId: onchain.settlementOnchainId, settlementId: 'run1-demo', title: CONDITIONS.itemName,
    members: calc.members, shares: calc.shares, payer: calc.payer, recipient: onchain.recipient,
    conditions: CONDITIONS, conditionsHash, conditionsCanonical,
    txs: { open: onchain.open, locks: onchain.locks, confirm: onchain.confirm, release: null, dispute: null, resolve: null, refunds: [] },
    state: onchain.state, holdUntil: onchain.holdUntil, holdSeconds: onchain.holdSeconds, verdict: null, mock: Boolean(onchain.mock),
  });

  // 4) 잔액 재확인 (전원 잠금 → 에스크로 보관 중이므로 멤버 잔액은 0)
  const after = [];
  for (const uid of MEMBERS) after.push({ ...who(uid), balancePIE: await blockchain.getBalance(uid) });
  step('4. 잠금 후 멤버 PieCoin 잔액 (에스크로 보관 중)', after);

  log.finishedAt = new Date().toISOString();
  log.txHash = onchain.confirm.txHash; // 인증서 TxHash (전원 잠금 확정)
  log.txHashes = { open: onchain.open.txHash, locks: onchain.locks.map((l) => l.txHash), confirm: onchain.confirm.txHash };
  return log;
}

function writeLog(log, outDir = path.join(BACKEND, 'logs')) {
  fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, `run1-${Date.now()}.json`);
  fs.writeFileSync(file, JSON.stringify(log, null, 2) + '\n');
  return file;
}

async function main() {
  const log = await runRun1({});
  const file = writeLog(log);
  const holdAt = new Date(log.holdUntil * 1000).toLocaleString('ko-KR');
  console.log('\n✅ Run 1 완료 (전원 잠금 확정 → 보류 중)');
  console.log(`   정산 id(settlementOnchainId): ${log.settlementOnchainId}`);
  console.log(`   조건 해시(conditionsHash)   : ${log.conditionsHash}`);
  console.log(`   등록(open) TxHash          : ${log.openTxHash}`);
  console.log(`   인증서(confirm) TxHash     : ${log.txHash}`);
  const confirm = log.steps.find((s) => s.name.startsWith('3.')).confirm;
  if (confirm && confirm.explorerUrl) console.log(`   탐색기                     : ${confirm.explorerUrl}`);
  console.log(`   보류 종료(holdUntil)        : ${holdAt} (${log.holdSeconds}초)`);
  console.log(`   지급: 보류가 끝난 뒤  npm run release:sepolia -- ${log.settlementOnchainId}`);
  console.log(`   Run 1.5(중단 사례): npm run run1.5:sepolia   /   Run 2(이의제기): npm run run2:sepolia`);
  console.log(`   제3자 검증: node scripts/verify-conditions.js <조건 JSON> ${log.settlementOnchainId}`);
  console.log(`   로그 파일                  : ${file}`);
}

module.exports = { runRun1, writeLog, CONDITIONS, MEMBERS, NAME_OF, REQUEST_TEXT };

if (require.main === module) {
  main().catch((err) => { console.error('❌', err.code ? `[${err.code}]` : '', err.message); process.exitCode = 1; });
}
