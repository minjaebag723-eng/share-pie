// CLAUDE.md 9번 Run 2 (이의제기 → AI 재조사 → 판정 → 자동 실행) — 확정 시나리오 A안 "계산 단계 착오 시뮬레이션"
// 사용법: cd contracts && npm run run2:sepolia
//
// 원칙: AI 판정 규칙(기록이 일치하면 GENUINE_ERROR 금지)은 바꾸지 않는다. 대신 "조건과 다른 금액이 잠긴" 정산을 이 스크립트가 만든다.
//   합의 조건 = 삼겹살 35,900원, 진주(u0) 5,000원 감면, 4명  → 올바른 분담 [5225, 10225, 10225, 10225]
//   주입      = 감면이 누락된 균등 분담 [8975, 8975, 8975, 8975] 으로 잠금  (INJECTED_ERROR)
//   온체인 conditionsHash 는 올바른 합의 조건(ADJUST)의 해시 → "합의는 이거였다"를 제3자가 검증할 수 있다. 잠긴 금액만 주입값.
//   /settlement/approve 는 재계산하므로 이런 상태를 만들 수 없다(그게 정상). 주입은 recordSettlementOnchain 을 직접 부르며 shares 만 바꿔 넣는다.
//
// 흐름
//   0) 올바른 조건 계산(코드) + 조건 해시  1) 주입 정산 잠금(LOCKED)  2) raise_dispute (u0: "5,000원 적게 내기로 했는데 같은 금액이 잠겼어요")
//   3) AI 재조사 dispute.investigate — compareRecords 가 계산 단계 불일치를 찾고 AI 가 GENUINE_ERROR
//   4) resolve_dispute (코드가 불일치 확인을 다시 강제) → refund_participant × 4 → 잔액 복구
//   5) 정정: 올바른 조건으로 새 정산을 열어 LOCKED 까지 (환불받은 PIE 로 다시 잠금)
//   6) 로그 backend/logs/run2-*.json (verdict → 행동 → TxHash, 전후 잔액, Etherscan 링크)
// ⚠️ 테스트넷 전용. 판정은 AI 가 내리고 실행은 코드가 한다 — 3개 판정 밖의 값은 거부된다.
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { computeSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'calculateSettlement'));
const { hashConditions, canonicalize } = require(path.join(BACKEND, 'src', 'blockchain', 'conditionsHash'));
const { investigateDispute } = require(path.join(BACKEND, 'src', 'agents', 'investigateDispute'));
const { raiseDispute, resolveDispute } = require(path.join(BACKEND, 'src', 'settlement', 'settlementActions'));
const { saveSettlement } = require(path.join(BACKEND, 'src', 'settlement', 'settlementStore'));
const { logEvent } = require(path.join(BACKEND, 'src', 'logger'));

const NAME_OF = { u0: '진주', u1: '진우', u2: '민재', u3: '지현' };
const MEMBERS = ['u0', 'u1', 'u2', 'u3'];
// 합의 조건 (올바른 것) — approve 가 해시하는 것과 같은 형식
const CONDITIONS = { members: MEMBERS, mode: 'ADJUST', itemName: '삼겹살 1.2kg', total: 35900, participants: MEMBERS, ratios: null, adjustments: { u0: -5000 }, items: null, totalBudget: 40000, payer: null };
// 주입: 감면 누락 균등 분담
const INJECTED_SHARES = [8975, 8975, 8975, 8975];
const REASON = '진주(u0)가 5,000원 적게 내기로 했는데 같은 금액이 잠겼어요';
const RAISED_BY = 'u0';
const REQUEST_TEXT = '삼겹살 1.2kg 35,900원, 진주는 5천원 적게 내고 나머지가 똑같이 나눠줘. 예산 4만원.';

function requireChain(chain) {
  if (chain === blockchain && blockchain.IS_MOCK) {
    throw new Error('backend/.env에 BLOCKCHAIN_RPC_URL, CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY가 모두 있어야 해요 (지금은 MOCK 모드). MOCK으로 돌리려면 allowMock 옵션을 쓰세요.');
  }
}

// 본체 — CLI·demo-all·Hardhat 통합 테스트가 같이 쓴다.
//   chain: blockchainClient(기본, env 로 실제/MOCK) 또는 onchainClient(테스트가 주입)
//   investigate: 기본 Kiln AI(dispute.investigate). 테스트는 가짜를 주입
async function runRun2({ chain = blockchain, investigate = investigateDispute, allowMock = false, holdSeconds, quiet = false } = {}) {
  if (!allowMock) requireChain(chain);
  const say = (m) => { if (!quiet) console.log(m); };
  const who = (uid) => ({ uid, name: NAME_OF[uid] || uid });
  const log = { run: 'Run 2 (이의제기 재조사 — 계산 단계 착오 시뮬레이션)', mock: Boolean(chain === blockchain ? blockchain.IS_MOCK : false), startedAt: new Date().toISOString(), scenario: 'A: calculation-stage error simulation', steps: [] };
  const step = (name, data) => { log.steps.push({ name, ...data }); say(`\n▶ ${name}\n${JSON.stringify(data, null, 2)}`); };

  // 0) 올바른 조건 계산 (코드, AI 토큰 0) + 조건 해시
  const correct = computeSettlement(CONDITIONS);
  const conditionsHash = hashConditions(CONDITIONS);
  const conditionsCanonical = canonicalize(CONDITIONS);
  log.conditions = CONDITIONS; log.conditionsCanonical = conditionsCanonical; log.conditionsHash = conditionsHash;
  log.correctShares = correct.shares; log.injectedShares = INJECTED_SHARES; log.nameOf = NAME_OF;
  step('0. 합의 조건 계산 (settlement.calculate: AI 토큰 0) + 조건 해시', { correctShares: correct.shares, injectedShares: INJECTED_SHARES, conditionsHash, rule: correct.rule });

  // 잔액 준비: 주입 금액만큼 충전 (실제 체인/MOCK 추적 잔액)
  for (let i = 0; i < MEMBERS.length; i++) {
    const bal = await chain.getBalance ? await chain.getBalance(MEMBERS[i]) : await chain.balanceOf(MEMBERS[i]);
    const need = INJECTED_SHARES[i] - (bal ?? 0);
    if (need > 0) await chain.chargeToken(MEMBERS[i], need);
  }

  // 1) 주입 정산 — 조건 해시는 올바른 조건, 잠기는 금액은 주입값 (approve 를 거치지 않고 직접 호출)
  const onchain = await (chain.recordSettlementOnchain || chain.recordSettlement).call(chain, { settlementId: 'run2-injected', members: MEMBERS, shares: INJECTED_SHARES, payer: null, conditionsHash, holdSeconds });
  const sid = onchain.settlementOnchainId;
  logEvent('run2.injected_error', { settlementOnchainId: sid, note: 'INJECTED_ERROR: shares replaced (calculation-stage error simulation)', correctShares: correct.shares, injectedShares: INJECTED_SHARES, conditionsHash });
  saveSettlement({
    settlementOnchainId: sid, settlementId: 'run2-injected', title: CONDITIONS.itemName,
    members: MEMBERS, shares: INJECTED_SHARES, payer: null, recipient: onchain.recipient,
    conditions: CONDITIONS, conditionsHash, conditionsCanonical,
    txs: { open: onchain.open, locks: onchain.locks, confirm: onchain.confirm, release: null, dispute: null, resolve: null, refunds: [] },
    state: onchain.state, holdUntil: onchain.holdUntil, holdSeconds: onchain.holdSeconds, verdict: null, mock: Boolean(onchain.mock),
    injectedError: 'INJECTED_ERROR: shares replaced (calculation-stage error simulation)',
  });
  const balBefore = {};
  for (const u of MEMBERS) balBefore[u] = await (chain.getBalance ? chain.getBalance(u) : chain.balanceOf(u));
  step('1. 주입 정산 잠금 — INJECTED_ERROR: shares replaced (calculation-stage error simulation)', {
    settlementOnchainId: sid, state: onchain.state, holdUntil: onchain.holdUntil, conditionsHash, lockedShares: INJECTED_SHARES,
    open: onchain.open, confirm: onchain.confirm, locks: onchain.locks.map((l) => ({ ...l, fromName: NAME_OF[l.from] || l.from })),
    balancesAfterLock: MEMBERS.map((u) => ({ ...who(u), balance: balBefore[u] })),
  });

  // 2) 이의제기 → 체인 동결
  const raised = await raiseDispute({ settlementOnchainId: sid, raisedBy: RAISED_BY, reason: REASON }, chain);
  step('2. raise_dispute (체인 동결)', { raisedBy: RAISED_BY, reason: REASON, state: raised.state, txHash: raised.txHash, reasonHash: raised.dispute.reasonHash });

  // 3) AI 재조사 — 최초요청(올바른 조건)·정산안(잠긴 주입 금액)·승인/송금 기록(온체인 locks)
  const locks = onchain.locks.map((l) => ({ from: l.from, to: l.to, amount: l.amount, txHash: l.txHash }));
  const investigateInput = {
    originalRequest: { text: REQUEST_TEXT, structured: CONDITIONS },
    settlementPlan: { members: MEMBERS, shares: INJECTED_SHARES, payer: null },
    approvalRecord: locks, actualTransfer: locks,
    dispute: { raisedBy: RAISED_BY, reason: REASON },
  };
  const investigation = await investigate(investigateInput.originalRequest, investigateInput.settlementPlan, investigateInput.approvalRecord, investigateInput.actualTransfer, investigateInput.dispute);
  step('3. AI 재조사 (dispute.investigate — Kiln 호출, AI 토큰 로깅)', { verdict: investigation.verdict, mismatchDetected: investigation.mismatchDetected, mismatchPoint: investigation.mismatchPoint, expectedAmount: investigation.expectedAmount, actualAmount: investigation.actualAmount, explanation: investigation.explanation });

  // 4) 판정 실행 — 코드가 불일치를 다시 확인한 뒤에만 온체인 실행 (GENUINE_ERROR 면 환불 × N)
  const resolved = await resolveDispute({ settlementOnchainId: sid, verdict: investigation.verdict, investigation }, chain);
  const balAfter = {};
  for (const u of MEMBERS) balAfter[u] = await (chain.getBalance ? chain.getBalance(u) : chain.balanceOf(u));
  step('4. resolve_dispute → 행동 실행', {
    summary: `mismatchDetected=${investigation.mismatchDetected}, mismatchPoint=${investigation.mismatchPoint} → verdict=${resolved.verdict} → ${resolved.verdict === 'GENUINE_ERROR' ? `refund_participant × ${resolved.refunds.filter((r) => r.ok).length}/${resolved.refunds.length}` : '정산 유지 (LOCKED 복귀)'}`,
    state: resolved.state, resolveTxHash: resolved.resolve.txHash, resolveExplorerUrl: resolved.resolve.explorerUrl || null,
    refunds: resolved.refunds.map((r) => ({ ...who(r.uid), amount: r.amount, ok: r.ok, txHash: r.txHash || null, error: r.error || null })),
    balances: MEMBERS.map((u) => ({ ...who(u), afterLock: balBefore[u], afterRefund: balAfter[u] })),
  });

  // 5) 정정 — 올바른 조건으로 새 정산 (환불받은 PIE 로 다시 잠금). 환불이 안 됐으면 건너뛴다
  let corrected = null;
  if (resolved.verdict === 'GENUINE_ERROR' && resolved.refunds.every((r) => r.ok)) {
    // 환불로 돌아온 금액(주입액)보다 올바른 분담이 큰 멤버는 부족분을 먼저 충전한다 (실제 서비스에서도 정정 정산 전 재충전이 필요)
    const topUps = [];
    for (let i = 0; i < MEMBERS.length; i++) {
      const bal = await (chain.getBalance ? chain.getBalance(MEMBERS[i]) : chain.balanceOf(MEMBERS[i]));
      const need = correct.shares[i] - (bal ?? 0);
      if (need > 0) { const c = await chain.chargeToken(MEMBERS[i], need); topUps.push({ ...who(MEMBERS[i]), amount: need, txHash: c.txHash }); }
    }
    log.correctionTopUps = topUps;
    corrected = await (chain.recordSettlementOnchain || chain.recordSettlement).call(chain, { settlementId: 'run2-corrected', members: MEMBERS, shares: correct.shares, payer: null, conditionsHash, holdSeconds });
    saveSettlement({
      settlementOnchainId: corrected.settlementOnchainId, settlementId: 'run2-corrected', title: CONDITIONS.itemName,
      members: MEMBERS, shares: correct.shares, payer: null, recipient: corrected.recipient,
      conditions: CONDITIONS, conditionsHash, conditionsCanonical,
      txs: { open: corrected.open, locks: corrected.locks, confirm: corrected.confirm, release: null, dispute: null, resolve: null, refunds: [] },
      state: corrected.state, holdUntil: corrected.holdUntil, holdSeconds: corrected.holdSeconds, verdict: null, mock: Boolean(corrected.mock),
    });
    step('5. 정정 — 부족분 충전 후 올바른 조건으로 새 정산 (LOCKED)', { topUps, settlementOnchainId: corrected.settlementOnchainId, shares: correct.shares, confirm: corrected.confirm, conditionsHash });
  } else {
    step('5. 정정 건너뜀', { reason: resolved.verdict !== 'GENUINE_ERROR' ? `verdict=${resolved.verdict}` : '환불 일부 실패' });
  }

  log.finishedAt = new Date().toISOString();
  log.settlementOnchainId = sid;
  log.verdict = resolved.verdict;
  log.state = resolved.state;
  log.txHashes = { open: onchain.open.txHash, confirm: onchain.confirm.txHash, raise: raised.txHash, resolve: resolved.resolve.txHash, refunds: resolved.refunds.filter((r) => r.ok).map((r) => r.txHash), corrected: corrected ? corrected.confirm.txHash : null };
  log.correctedSettlementOnchainId = corrected ? corrected.settlementOnchainId : null;
  return log;
}

function writeLog(log, outDir = path.join(BACKEND, 'logs')) {
  fs.mkdirSync(outDir, { recursive: true });
  const out = path.join(outDir, `run2-${Date.now()}.json`);
  fs.writeFileSync(out, JSON.stringify(log, null, 2) + '\n');
  return out;
}

async function main() {
  const log = await runRun2({});
  const out = writeLog(log);
  console.log('\n✅ Run 2 완료');
  console.log(`   판정             : ${log.verdict} → 상태 ${log.state}`);
  console.log(`   raise TxHash     : ${log.txHashes.raise}`);
  console.log(`   resolve TxHash   : ${log.txHashes.resolve}`);
  log.txHashes.refunds.forEach((h, i) => console.log(`   refund #${i + 1} TxHash : ${h}`));
  if (log.txHashes.corrected) console.log(`   정정 정산 confirm : ${log.txHashes.corrected}`);
  console.log(`   로그 파일        : ${out}`);
}

module.exports = { runRun2, writeLog, CONDITIONS, INJECTED_SHARES, REASON, RAISED_BY, MEMBERS, NAME_OF };

if (require.main === module) {
  main().catch((err) => { console.error('❌', err.code ? `[${err.code}]` : '', err.message); process.exitCode = 1; });
}
