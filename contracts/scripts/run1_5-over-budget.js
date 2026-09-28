// CLAUDE.md 9번·12번 Run 1.5 — "조건을 변경해 2회 실행": 코드가 중단하는 사례 2건 (온체인 트랜잭션 0건)
// 사용법: cd contracts && npm run run1.5:sepolia   (MOCK 모드에서도 동작 — demo-all 이 allowMock 으로 부른다)
//   사례 1) 예산 변경: Run 1 과 같은 조건에서 totalBudget 만 40,000 → 30,000 으로 줄여 approve
//           → Stage 2(코드)가 예산 초과를 감지 → 409 OVER_BUDGET → 온체인 호출 0건
//   사례 2) 잔액 부족: 참여자 한 명(u3)의 PieCoin 잔액을 분담금보다 적게 둔 채 approve
//           → 잠금 전 잔액 선확인(코드/컨트랙트 규칙) → 409 INSUFFICIENT_BALANCE → 온체인 호출 0건
// AI 는 조건 해석(Stage 1)에만 쓰인다. 두 사례 모두 중단 판단은 코드가 한다 — 이 스크립트는 AI 를 호출하지 않는다 (조건은 이미 구조화된 입력).
// ⚠️ 테스트넷 전용. 이 스크립트는 정산을 만들지 않는다 — 실패(중단)만 기록한다.
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { approveSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'approveSettlement'));
const { computeSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'calculateSettlement'));

const MEMBERS = ['u0', 'u1', 'u2', 'u3'];
const NAME_OF = { u0: '진주', u1: '진우', u2: '민재', u3: '지현' };
// Run 1 과 같은 합의 조건
const BASE = { members: MEMBERS, mode: 'ADJUST', itemName: '삼겹살 1.2kg', total: 35900, participants: MEMBERS, ratios: null, adjustments: { u0: -5000 }, items: null, totalBudget: 40000, payer: null };
const APPROVALS = [true, true, true, true];

async function attempt(name, body, expectCode) {
  try {
    const r = await approveSettlement(body);
    return { name, aborted: false, unexpected: true, result: { state: r.onchain.state, settlementOnchainId: r.onchain.settlementOnchainId } };
  } catch (err) {
    return { name, aborted: true, code: err.code, status: err.status, message: err.message, expected: expectCode, ok: err.code === expectCode };
  }
}

// 본체 — demo-all·테스트가 같이 쓴다. 온체인 트랜잭션은 보내지 않는다 (중단만 확인)
async function runRun15({ allowMock = false, quiet = false } = {}) {
  if (!allowMock && blockchain.IS_MOCK) throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드). MOCK으로 돌리려면 allowMock 옵션을 쓰세요.');
  const say = (m) => { if (!quiet) console.log(m); };
  const log = { run: 'Run 1.5 (조건 변경 → 코드 중단)', mock: blockchain.IS_MOCK, startedAt: new Date().toISOString(), aiCalls: 0, note: 'AI는 조건 해석(Stage 1)에만 쓰인다. 중단 판단은 코드(Stage 2 예산 검증 / 잠금 전 잔액 선확인)가 한다. 이 스크립트는 AI를 호출하지 않는다.', cases: [] };
  const step = (c) => { log.cases.push(c); say(`\n▶ ${c.name}\n${JSON.stringify(c, null, 2)}`); };

  // 사례 1: 예산 40,000 → 30,000
  const calc = computeSettlement(BASE); // 35,900 (예산 40,000 안)
  const overBudget = { ...BASE, totalBudget: 30000 };
  const c1 = await attempt('1. 예산 변경 (40,000 → 30,000) → OVER_BUDGET', { settlementId: 'run1_5-budget', title: '삼겹살 (예산 초과)', settlement: overBudget, approvals: APPROVALS }, 'OVER_BUDGET');
  c1.detail = { total: calc.total, budgetBefore: BASE.totalBudget, budgetAfter: 30000, overBudgetBy: calc.total - 30000, onchainTx: 0, aiCalled: false };
  c1.summary = `예산 40,000→30,000 변경 → overBudgetBy ${calc.total - 30000} → 승인 거부(${c1.code}), 잠금 0건`;
  step(c1);

  // 사례 2: u3 잔액을 분담금(10,225)보다 적게(100) 둔 채 approve
  const u3Need = calc.shares[MEMBERS.indexOf('u3')];
  const u3Bal = await blockchain.getBalance('u3');
  // 잔액이 이미 충분하면(이전 Run 의 잔액) 이 사례를 만들 수 없다 — 그 경우 건너뛰고 이유를 남긴다
  let c2;
  if (u3Bal !== null && u3Bal >= u3Need) {
    c2 = { name: '2. 잔액 부족 (u3) → INSUFFICIENT_BALANCE', aborted: false, skipped: true, reason: `u3 잔액(${u3Bal} PIE)이 이미 분담금(${u3Need})보다 많아 시나리오를 만들 수 없음 — 새 지갑/새 배포에서 실행`, ok: false };
  } else {
    if (u3Bal === null || u3Bal < 100) await blockchain.chargeToken('u3', 100 - (u3Bal || 0)); // 일부러 100 PIE 만
    for (const uid of ['u0', 'u1', 'u2']) { // 나머지는 충분히 (그래야 u3 만 부족)
      const need = calc.shares[MEMBERS.indexOf(uid)]; const bal = await blockchain.getBalance(uid);
      if (bal === null || bal < need) await blockchain.chargeToken(uid, need - (bal || 0));
    }
    c2 = await attempt('2. 잔액 부족 (u3: 100 PIE < 10,225) → INSUFFICIENT_BALANCE', { settlementId: 'run1_5-balance', title: '삼겹살 (잔액 부족)', settlement: BASE, approvals: APPROVALS }, 'INSUFFICIENT_BALANCE');
    c2.detail = { participant: 'u3', participantName: NAME_OF.u3, balancePIE: await blockchain.getBalance('u3'), requiredPIE: u3Need, onchainTx: 0, aiCalled: false };
    c2.summary = `u3 잔액 ${c2.detail.balancePIE} PIE < 분담금 ${u3Need} → 잠금 전 잔액 선확인에서 거부(${c2.code}), 잠금 0건`;
  }
  step(c2);

  log.finishedAt = new Date().toISOString();
  log.allAborted = log.cases.every((c) => c.aborted && c.ok);
  return log;
}

function writeLog(log, outDir = path.join(BACKEND, 'logs')) {
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, `run1_5-${Date.now()}.json`);
  fs.writeFileSync(out, JSON.stringify(log, null, 2) + '\n');
  return out;
}

async function main() {
  const log = await runRun15({});
  const out = writeLog(log);
  console.log(`\n${log.allAborted ? '✅' : '⚠️'} Run 1.5 완료 — 중단 ${log.cases.filter((c) => c.aborted).length}/${log.cases.length}건, 온체인 트랜잭션 0건`);
  console.log(`   로그 파일 : ${out}`);
}

module.exports = { runRun15, writeLog, BASE };

if (require.main === module) {
  main().catch((err) => { console.error('❌', err.code ? `[${err.code}]` : '', err.message); process.exitCode = 1; });
}
