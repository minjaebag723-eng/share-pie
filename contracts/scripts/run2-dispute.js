// CLAUDE.md 9번 Run 2 (이의제기 → AI 재조사 → 판정 → 자동 실행) — Sepolia 테스트넷
// 사용법: cd contracts && npm run run2:sepolia -- <run1 로그 파일 경로> [이의제기 사유] [제기자 uid]
//   1) run1-*.json 에서 settlementOnchainId·조건·잠금 기록을 읽는다
//   2) raise_dispute  — 체인 동결 (LOCKED → DISPUTED)
//   3) AI 재조사     — 백엔드 investigateDispute (Kiln, dispute.investigate 태그로 AI 토큰 로깅) → verdict
//   4) resolve_dispute(verdict) — GENUINE_ERROR 면 refund_participant × N (에스크로 → 각자), 그 밖은 LOCKED 복귀
//   5) 각 TxHash·Etherscan 링크·전후 PieCoin 잔액을 backend/logs/run2-*.json 에 저장 (CLAUDE.md 12번: verdict → 행동 → TxHash)
// ⚠️ 테스트넷 전용. 판정은 AI(dispute.investigate)가 내리고 실행은 코드가 한다 — 3개 판정 밖의 값은 거부된다.
// ⚠️ 주의: AI 판정 규칙상 승인·송금 기록이 서로 일치하면 GENUINE_ERROR 가 나오지 않는다. 그 경우 환불 없이 LOCKED 로 복귀한다 (로그에 그대로 남김).
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { investigateDispute } = require(path.join(BACKEND, 'src', 'agents', 'investigateDispute'));
const { raiseDispute, resolveDispute } = require(path.join(BACKEND, 'src', 'settlement', 'settlementActions'));
const { findSettlement, saveSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'settlementStore'));

const DEFAULT_REASON = '지현은 그날 참석하지 않았는데 포함됨';

// run1 로그 → 저장소 기록이 없으면(다른 PC에서 run1 실행 등) 로그로 복원해 둔다 — raise/resolve 가 참여자를 찾을 수 있게
function ensureStoreRecord(run1) {
  const id = run1.settlementOnchainId;
  if (findSettlement(id)) return;
  const onchain = run1.steps.find((s) => s.name && s.name.startsWith('3.')) || {};
  saveSettlement({
    settlementOnchainId: id,
    settlementId: 'run1-demo',
    title: run1.conditions.itemName || 'Run 1',
    members: run1.conditions.members,
    shares: run1.shares,
    payer: run1.conditions.payer,
    recipient: onchain.recipient || 'SharePie 정산 에스크로',
    conditions: run1.conditions,
    conditionsHash: run1.conditionsHash,
    conditionsCanonical: run1.conditionsCanonical,
    txs: { open: onchain.open || null, locks: onchain.locks || [], confirm: onchain.confirm || null, release: null, dispute: null, resolve: null, refunds: [] },
    state: 'LOCKED',
    holdUntil: run1.holdUntil,
    verdict: null,
    mock: false,
  });
}

// 본체 — 테스트에서도 부를 수 있게 함수로 분리 (investigate 는 주입 가능: 기본은 Kiln AI)
async function runDispute({ run1, reason = DEFAULT_REASON, raisedBy = 'u1', investigate = investigateDispute, nameOf = {} }) {
  const settlementOnchainId = run1.settlementOnchainId;
  const members = run1.conditions.members;
  const who = (uid) => ({ uid, name: nameOf[uid] || uid });
  const log = { run: 'Run 2 (이의제기 재조사)', startedAt: new Date().toISOString(), settlementOnchainId, reason, raisedBy, steps: [] };
  const step = (name, data) => { log.steps.push({ name, ...data }); console.log(`\n▶ ${name}\n${JSON.stringify(data, null, 2)}`); };

  ensureStoreRecord(run1);
  const before = {};
  for (const uid of members) before[uid] = await blockchain.getBalance(uid);
  step('0. 이의제기 전 상태', { state: await blockchain.getSettlementState({ settlementOnchainId }), balancesPIE: members.map((u) => ({ ...who(u), balance: before[u] })) });

  // 1) 이의제기 접수 → 체인 동결
  const raised = await raiseDispute({ settlementOnchainId, raisedBy, reason });
  step('1. raise_dispute (체인 동결)', { state: raised.state, txHash: raised.txHash, reasonHash: raised.dispute.reasonHash });

  // 2) AI 재조사 — 최초요청·정산안·승인기록(잠금)·실제송금(잠금) 4종을 넘긴다 (CLAUDE.md 7번)
  const onchainStep = run1.steps.find((s) => s.name && s.name.startsWith('3.')) || {};
  const locks = (onchainStep.locks || []).map((l) => ({ from: l.from, to: l.to, amount: l.amount, txHash: l.txHash }));
  const settlementPlan = { members, shares: run1.shares, payer: run1.conditions.payer };
  const investigation = await investigate(
    { text: run1.requestText || `${run1.conditions.itemName} 정산`, structured: run1.conditions },
    settlementPlan,
    locks,
    locks,
    { raisedBy, reason },
  );
  step('2. AI 재조사 (dispute.investigate — Kiln 호출, AI 토큰 로깅)', { verdict: investigation.verdict, mismatchDetected: investigation.mismatchDetected, mismatchPoint: investigation.mismatchPoint, explanation: investigation.explanation });

  // 3) 판정 실행 (코드 전용) — GENUINE_ERROR 면 환불 × N
  const resolved = await resolveDispute({ settlementOnchainId, verdict: investigation.verdict, investigation });
  step('3. resolve_dispute → 행동 실행', {
    responseKey: `verdict=${resolved.verdict}`,
    action: resolved.verdict === 'GENUINE_ERROR' ? `refund_participant × ${resolved.refunds.filter((r) => r.ok).length}/${resolved.refunds.length}` : '정산 유지 (LOCKED 복귀)',
    state: resolved.state,
    resolveTxHash: resolved.resolve.txHash,
    resolveExplorerUrl: resolved.resolve.explorerUrl || null,
    refunds: resolved.refunds.map((r) => ({ ...who(r.uid), amount: r.amount, ok: r.ok, txHash: r.txHash || null, error: r.error || null })),
  });

  const after = {};
  for (const uid of members) after[uid] = await blockchain.getBalance(uid);
  step('4. 이의제기 후 상태', { state: await blockchain.getSettlementState({ settlementOnchainId }), balancesPIE: members.map((u) => ({ ...who(u), before: before[u], after: after[u] })) });

  log.finishedAt = new Date().toISOString();
  log.verdict = resolved.verdict;
  log.state = resolved.state;
  log.txHashes = { raise: raised.txHash, resolve: resolved.resolve.txHash, refunds: resolved.refunds.filter((r) => r.ok).map((r) => r.txHash) };
  return log;
}

async function main() {
  const [file, reasonArg, raisedByArg] = process.argv.slice(2);
  if (!file) throw new Error('사용법: npm run run2:sepolia -- <run1 로그 파일 경로> [이의제기 사유] [제기자 uid]');
  if (blockchain.IS_MOCK) throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드).');
  const run1 = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (!run1.settlementOnchainId || !run1.conditions || !run1.shares) throw new Error('run1 로그에 settlementOnchainId·conditions·shares 가 없어요. 최신 run1 스크립트로 다시 실행해 주세요.');

  const log = await runDispute({ run1, reason: reasonArg || DEFAULT_REASON, raisedBy: raisedByArg || 'u1', nameOf: run1.nameOf || {} });

  const outDir = path.join(BACKEND, 'logs');
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, `run2-${Date.now()}.json`);
  fs.writeFileSync(out, JSON.stringify(log, null, 2) + '\n');
  console.log('\n✅ Run 2 완료');
  console.log(`   판정             : ${log.verdict} → 상태 ${log.state}`);
  console.log(`   raise TxHash     : ${log.txHashes.raise}`);
  console.log(`   resolve TxHash   : ${log.txHashes.resolve}`);
  log.txHashes.refunds.forEach((h, i) => console.log(`   refund #${i + 1} TxHash : ${h}`));
  console.log(`   로그 파일        : ${out}`);
}

module.exports = { runDispute, ensureStoreRecord, DEFAULT_REASON };

if (require.main === module) {
  main().catch((err) => { console.error('❌', err.code ? `[${err.code}]` : '', err.message); process.exitCode = 1; });
}
