// 데모 일괄 실행 + 증거 묶음 — preflight → Run 1 → Run 1.5 → Run 2 → (보류 지났으면) release(Run 1)
// 사용법: cd contracts && npm run demo:all
//   결과: backend/logs/demo-<timestamp>/ 에 summary.md + 각 Run 의 원본 json
//   한 Run 이 실패해도 다음으로 넘어가고 summary 에 실패 원인을 남긴다. MOCK 모드에서도 끝까지 돈다 (탐색기 링크 대신 "MOCK").
// ⚠️ 테스트넷 전용. 배포는 하지 않는다 (CONTRACT_ADDRESS 가 있어야 실제 체인, 없으면 MOCK).
const fs = require('fs');
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const blockchain = require(path.join(BACKEND, 'src', 'blockchain', 'blockchainClient'));
const { summarizeTokenUsage } = require(path.join(BACKEND, 'src', 'logger'));
const { hashConditions } = require(path.join(BACKEND, 'src', 'blockchain', 'conditionsHash'));
const { configuredChainId, describeChain } = require(path.join(BACKEND, 'src', 'blockchain', 'chains'));
const { preflight } = require('./preflight');
const run1 = require('./run1-settlement');
const run15 = require('./run1_5-over-budget');
const run2 = require('./run2-dispute');
const { runRelease } = require('./release-settlement');

function readEvents() {
  const dir = process.env.LOG_DIR || path.join(BACKEND, 'logs');
  const f = path.join(dir, 'events.jsonl');
  if (!fs.existsSync(f)) return [];
  return fs.readFileSync(f, 'utf8').trim().split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
}

// 본체 — 테스트도 부른다. 반환: { outDir, summaryPath, results }
async function runDemoAll({ quiet = false, outRoot = path.join(BACKEND, 'logs'), holdSeconds, investigate } = {}) {
  const say = (m) => { if (!quiet) console.log(m); };
  const isMock = blockchain.IS_MOCK;
  const chain = isMock ? null : describeChain(configuredChainId());
  const link = (hash) => (isMock || !chain ? 'MOCK' : chain.explorerTx(hash) || '-');
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outDir = path.join(outRoot, `demo-${stamp}`);
  fs.mkdirSync(outDir, { recursive: true });
  const results = { mode: isMock ? 'mock' : 'testnet', network: isMock ? 'mock' : chain ? chain.name : 'unknown', startedAt: new Date().toISOString() };
  const eventsBefore = readEvents().length;

  const stage = async (key, fn) => {
    say(`\n══════ ${key} ══════`);
    try { results[key] = { ok: true, data: await fn() }; }
    catch (err) { results[key] = { ok: false, error: { code: err.code || null, message: err.message } }; say(`❌ ${key} 실패: ${err.message}`); }
  };

  await stage('preflight', () => preflight({ quiet }));
  await stage('run1', async () => { const log = await run1.runRun1({ allowMock: true, quiet, holdSeconds }); fs.writeFileSync(path.join(outDir, 'run1.json'), JSON.stringify(log, null, 2)); return log; });
  await stage('run1_5', async () => { const log = await run15.runRun15({ allowMock: true, quiet }); fs.writeFileSync(path.join(outDir, 'run1_5.json'), JSON.stringify(log, null, 2)); return log; });
  await stage('run2', async () => { const log = await run2.runRun2({ allowMock: true, quiet, holdSeconds, ...(investigate ? { investigate } : {}) }); fs.writeFileSync(path.join(outDir, 'run2.json'), JSON.stringify(log, null, 2)); return log; });
  await stage('release', async () => {
    const r1 = results.run1;
    if (!r1 || !r1.ok) return { skipped: true, reason: 'Run 1 실패' };
    const r = await runRelease({ settlementOnchainId: r1.data.settlementOnchainId, allowMock: true, quiet });
    fs.writeFileSync(path.join(outDir, 'release.json'), JSON.stringify(r, null, 2));
    return r;
  });

  // 제3자 검증 (조건 해시): 실제 체인이면 verify-conditions 로 대조, MOCK 이면 로컬 해시만
  await stage('verify', async () => {
    const r1 = results.run1;
    if (!r1 || !r1.ok) return { skipped: true, reason: 'Run 1 실패' };
    const localHash = hashConditions(r1.data.conditions);
    if (isMock) return { mock: true, match: localHash === r1.data.conditionsHash, localHash, onchainHash: r1.data.conditionsHash, note: 'MOCK: 체인 대조 불가 — 로컬 재해시가 기록값과 같은지만 확인' };
    const { ethers } = require(path.join(BACKEND, 'node_modules', 'ethers'));
    const { verifyConditions } = require('./verify-conditions');
    const provider = new ethers.JsonRpcProvider(process.env.BLOCKCHAIN_RPC_URL);
    return verifyConditions({ conditions: r1.data.conditions, ref: r1.data.settlementOnchainId, provider, contractAddress: process.env.CONTRACT_ADDRESS });
  });

  results.finishedAt = new Date().toISOString();
  const events = readEvents().slice(eventsBefore);
  const tokens = summarizeTokenUsage();
  const summaryPath = path.join(outDir, 'summary.md');
  fs.writeFileSync(summaryPath, buildSummary({ results, events, tokens, link, isMock }));
  fs.writeFileSync(path.join(outDir, 'results.json'), JSON.stringify(results, null, 2));
  say(`\n📦 증거 묶음: ${outDir}\n   summary.md 를 확인하세요.`);
  return { outDir, summaryPath, results };
}

function buildSummary({ results, events, tokens, link, isMock }) {
  const L = [];
  const okmark = (r) => (r && r.ok ? '✅' : '❌');
  const fail = (r) => (r && !r.ok ? ` — 실패: ${r.error.code ? `[${r.error.code}] ` : ''}${r.error.message}` : '');
  L.push(`# SharePie 데모 증거 묶음`);
  L.push(``);
  L.push(`- 모드: **${results.mode}**${isMock ? ' (블록체인 설정 없음 — 가짜 TxHash, 탐색기 링크 없음)' : ` (${results.network})`}`);
  L.push(`- 실행: ${results.startedAt} → ${results.finishedAt}`);
  L.push(`- 단계: preflight ${okmark(results.preflight)} · Run 1 ${okmark(results.run1)} · Run 1.5 ${okmark(results.run1_5)} · Run 2 ${okmark(results.run2)} · release ${okmark(results.release)} · verify ${okmark(results.verify)}`);
  for (const k of ['preflight', 'run1', 'run1_5', 'run2', 'release', 'verify']) if (results[k] && !results[k].ok) L.push(`  - ${k}${fail(results[k])}`);
  L.push(``);

  // 0) preflight
  if (results.preflight && results.preflight.ok) {
    L.push(`## 사전 점검 (preflight)`);
    for (const i of results.preflight.data.items) L.push(`- ${i.ok === true ? '✅' : i.ok === false ? '❌' : '⚠️'} ${i.name}: ${i.detail}`);
    L.push(``);
  }

  // 1) 트랜잭션 표
  const row = (run, fn, hash, extra = '') => `| ${run} | ${fn} | \`${hash}\` | ${link(hash)} |${extra}`;
  L.push(`## 트랜잭션 (함수 · TxHash · 탐색기)`);
  L.push(`| Run | 함수 | TxHash | 탐색기 |`);
  L.push(`|---|---|---|---|`);
  if (results.run1 && results.run1.ok) {
    const d = results.run1.data;
    L.push(row('Run 1', 'open_settlement', d.txHashes.open));
    d.txHashes.locks.forEach((h, i) => L.push(row('Run 1', `lock_for_settlement (${d.conditions.members[i]})`, h)));
    L.push(row('Run 1', 'confirm = 마지막 lock (SettlementConfirmed, 인증서)', d.txHashes.confirm));
  }
  if (results.release && results.release.ok && results.release.data.released) L.push(row('Run 1', 'release_to_recipient', results.release.data.release.txHash));
  if (results.run2 && results.run2.ok) {
    const d = results.run2.data;
    L.push(row('Run 2', 'open_settlement (주입 정산)', d.txHashes.open));
    L.push(row('Run 2', 'confirm (주입 정산 잠금 확정)', d.txHashes.confirm));
    L.push(row('Run 2', 'raise_dispute', d.txHashes.raise));
    L.push(row('Run 2', `resolve_dispute (${d.verdict})`, d.txHashes.resolve));
    d.txHashes.refunds.forEach((h, i) => L.push(row('Run 2', `refund_participant #${i + 1}`, h)));
    if (d.txHashes.corrected) L.push(row('Run 2', 'confirm (정정 정산 잠금 확정)', d.txHashes.corrected));
  }
  L.push(``);

  // 2) Run 별 요약
  L.push(`## Run 1 — 정상 정산${fail(results.run1)}`);
  if (results.run1 && results.run1.ok) {
    const d = results.run1.data;
    L.push(`- 정산 id: \`${d.settlementOnchainId}\``);
    L.push(`- 조건 해시(conditionsHash): \`${d.conditionsHash}\``);
    L.push(`- 분담: ${d.conditions.members.map((u, i) => `${d.nameOf[u]}(${u}) ${d.shares[i]}`).join(' · ')} = ${d.shares.reduce((a, b) => a + b, 0)} PIE (예산 ${d.conditions.totalBudget})`);
    L.push(`- 상태: LOCKED(보류) → holdUntil ${d.holdUntil} (${d.holdSeconds}초). 인증서 TxHash = \`${d.txHash}\``);
    if (results.release && results.release.ok) L.push(results.release.data.released ? `- release: ✅ 지급 완료 → \`${results.release.data.release.txHash}\` (${results.release.data.recipient})` : `- release: ⏳ 보류 중 (남은 ${results.release.data.remainingSeconds}초) — 보류 뒤 \`npm run release:sepolia -- ${d.settlementOnchainId}\``);
  }
  L.push(``);

  L.push(`## Run 1.5 — 조건 변경 → 코드 중단 (온체인 트랜잭션 0건)${fail(results.run1_5)}`);
  if (results.run1_5 && results.run1_5.ok) {
    for (const c of results.run1_5.data.cases) L.push(`- ${c.aborted ? '✅' : c.skipped ? '⚠️' : '❌'} ${c.name}${c.summary ? ` — ${c.summary}` : c.reason ? ` — ${c.reason}` : ''}`);
    L.push(`- ${results.run1_5.data.note}`);
  }
  L.push(``);

  L.push(`## Run 2 — 이의제기 재조사 (계산 단계 착오 시뮬레이션)${fail(results.run2)}`);
  if (results.run2 && results.run2.ok) {
    const d = results.run2.data;
    const inv = d.steps.find((s) => s.name.startsWith('3.')) || {};
    const act = d.steps.find((s) => s.name.startsWith('4.')) || {};
    L.push(`- 주입: 합의 분담 [${d.correctShares.join(', ')}] 대신 [${d.injectedShares.join(', ')}] 잠금 (INJECTED_ERROR: shares replaced). 조건 해시는 합의 조건 그대로 \`${d.conditionsHash}\``);
    L.push(`- 이의제기: ${run2.RAISED_BY} — "${run2.REASON}"`);
    L.push(`- AI 재조사(dispute.investigate): mismatchDetected=${inv.mismatchDetected}, mismatchPoint=${inv.mismatchPoint}, expected=${inv.expectedAmount}, actual=${inv.actualAmount} → verdict=**${d.verdict}**`);
    L.push(`- 실행: ${act.summary || '-'} → 상태 ${d.state}`);
    if (d.txHashes.corrected) L.push(`- 정정 정산: \`${d.correctedSettlementOnchainId}\` (LOCKED, 올바른 분담 [${d.correctShares.join(', ')}])`);
  }
  L.push(``);

  // 3) AI 응답 → 행동 로그 (12번)
  L.push(`## AI 응답 → 코드 판정 → 행동 (events.jsonl)`);
  const picked = events.filter((e) => ['settlement.abort', 'dispute.raise', 'dispute.action', 'settlement.release', 'run2.injected_error'].includes(e.type));
  if (!picked.length) L.push(`- (로그 없음)`);
  for (const e of picked) {
    if (e.type === 'settlement.abort') L.push(`- [${e.type}] ${e.summary}`);
    else if (e.type === 'dispute.action') L.push(`- [${e.type}] ${e.summary} · resolve \`${e.resolveTxHash}\`${e.txHashes.length ? ` · refunds ${e.txHashes.map((h) => `\`${h}\``).join(', ')}` : ''}`);
    else if (e.type === 'run2.injected_error') L.push(`- [${e.type}] ${e.note}`);
    else L.push(`- [${e.type}] ${e.action || ''} \`${e.txHash || ''}\``);
  }
  L.push(``);

  // 4) AI 토큰 표
  L.push(`## AI 토큰 사용량 (단계별, /logs/tokens 와 같은 집계 — 누적)`);
  L.push(`| stage | 호출 | 입력 AI 토큰 | 출력 AI 토큰 | cost(USD) |`);
  L.push(`|---|---:|---:|---:|---:|`);
  for (const [k, v] of Object.entries(tokens)) L.push(`| ${k} | ${v.calls}${k === 'settlement.calculate' ? ' (code-only)' : ''} | ${v.promptTokens} | ${v.completionTokens} | ${v.cost} |`);
  L.push(``);

  // 5) 제3자 검증
  L.push(`## 제3자 검증 (verify-conditions)${fail(results.verify)}`);
  if (results.verify && results.verify.ok) {
    const v = results.verify.data;
    if (v.skipped) L.push(`- 건너뜀: ${v.reason}`);
    else L.push(`- ${v.match ? '✅ MATCH' : '❌ MISMATCH'} — 로컬 \`${v.localHash}\` vs 체인 \`${v.onchainHash}\`${v.note ? ` (${v.note})` : ''}`);
  }
  L.push(``);
  L.push(`> 한계: 운영자 지갑 하나(DEPLOYER_PRIVATE_KEY)가 모든 트랜잭션에 서명하는 데모용 수탁 구조. Run 2 의 착오는 의도적으로 주입한 시뮬레이션이며, 온체인 금액이 아니라 "합의 조건 해시 ≠ 잠긴 금액"으로 만들어진다.`);
  return L.join('\n') + '\n';
}

module.exports = { runDemoAll, buildSummary };

if (require.main === module) {
  runDemoAll({}).then((r) => {
    const failed = Object.values(r.results).filter((x) => x && typeof x === 'object' && x.ok === false).length;
    process.exitCode = failed ? 1 : 0;
  }).catch((err) => { console.error('❌', err.message); process.exitCode = 1; });
}
