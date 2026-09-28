'use strict';
// 실제 테스트넷 증거 실행 — Python 백엔드(:8000, CHAIN_MODE=bsc) + 참여자 지갑 서명(ethers)으로 Run 1 / 1.5 / 2 를 끝까지 돌린다.
// 참여자 예치는 프론트(sp-bridge.js payShare)와 같은 순서: PIE.approve(ledger, 몫) → ShareLedger.lockForSettlement(chainId) → /api/settlement/approve
// 결과: docs/evidence/<network>-<시각>/{summary.md, run1.json, run1_5.json, run2.json, usage-report.md, members.json}
// 실행: cd hardhat && npm run evidence      (서버가 먼저 떠 있어야 함. 비밀키는 출력·저장하지 않음 — members-*.json 은 hardhat/deployments/ 에만)
const fs = require('fs');
const path = require('path');
const { ethers } = require('ethers');

const ROOT = path.join(__dirname, '..', '..');
const BASE = process.env.SP_BASE || 'http://127.0.0.1:8000';
const env = readEnv(path.join(ROOT, '.env'));
const RPC = process.env.BSC_RPC_URL || env.BSC_RPC_URL;
const FUND_WEI = ethers.parseEther(process.env.MEMBER_GAS_ETH || '0.0025');
const MIN_WEI = ethers.parseEther('0.0012');
const LABELS = ['진주', '진우', '민재', '지현'];
const PASSWORD = 'evidence1234x';

function readEnv(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return out;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 네트워크 순단(fetch failed / ECONNRESET / ETIMEDOUT)만 재시도. 트랜잭션 전송은 중복 위험이 있어 여기 태우지 않는다.
const isNetErr = (e) => /fetch failed|ECONNRESET|ETIMEDOUT|ENOTFOUND|socket hang up|network error|could not detect network/i.test(String(e && (e.message || e)));
async function retryNet(label, fn, tries = 4) {
  for (let i = 1; ; i++) {
    try { return await fn(); } catch (e) {
      if (!isNetErr(e) || i >= tries) throw e;
      log(`  네트워크 순단(${label}) → ${i * 5}초 후 재시도`); await sleep(i * 5000);
    }
  }
}
const short = (h) => (h ? h.slice(0, 10) + '…' + h.slice(-6) : '-');
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a);

async function apiRaw(p, body, token, method = body === undefined ? 'GET' : 'POST') {
  const res = await fetch(BASE + p, {
    method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), 'X-SP-Device': 'evidence-runner' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await res.json().catch(() => ({}));
  // 체인 트랜잭션 실패(가스 지연 등)는 20초 뒤 한 번 더 시도 (충전·등록·판정 실행 모두 서버가 멱등하게 처리하지는 않으므로 1회만)
  if ((j.error && j.error.code === 'CHAIN_TX_FAILED') && !api._retried) {
    api._retried = true; log('  체인 지연 → 20초 후 재시도: ' + p); await sleep(20000);
    try { return await apiRaw(p, body, token, method); } finally { api._retried = false; }
  }
  if (!res.ok || j.ok === false) {
    const e = j.error || {};
    throw Object.assign(new Error(`${p} → ${res.status} ${e.code || ''} ${e.message || ''}`), { code: e.code, details: e.details, status: res.status });
  }
  return j.data;
}
const api = (p, body, token, method) => retryNet('API ' + p, () => apiRaw(p, body, token, method));
api._retried = false;

// ── 참여자 지갑 (재실행 시 같은 지갑 재사용 · 파일은 git 제외 폴더) ──
function loadMembers(chainId) {
  const file = path.join(__dirname, '..', 'deployments', `members-${chainId}.json`);
  if (fs.existsSync(file)) return { file, members: JSON.parse(fs.readFileSync(file, 'utf8')) };
  const members = LABELS.map((label) => { const w = ethers.Wallet.createRandom(); return { label, address: w.address, privateKey: w.privateKey }; });
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(members, null, 2) + '\n');
  return { file, members };
}

async function main() {
  const started = Date.now();
  const health = await api('/api/health');
  const cfg = await api('/api/config');
  const chain = cfg.chain;
  if (chain.mode !== 'bsc') throw new Error(`서버가 실제 체인 모드가 아니에요 (chain.mode=${chain.mode}). CHAIN_MODE=bsc 로 켜 주세요.`);
  log(`서버 OK · llm=${health.llm_mode}/${health.model} · chain=${chain.chain_id} ledger=${chain.ledger} token=${chain.token} window=${chain.dispute_window}s`);

  const provider = new ethers.JsonRpcProvider(RPC);
  const net = await retryNet('getNetwork', () => provider.getNetwork());
  if (Number(net.chainId) !== Number(chain.chain_id)) throw new Error(`RPC chainId ${net.chainId} ≠ 서버 chain_id ${chain.chain_id}`);
  const agent = new ethers.NonceManager(new ethers.Wallet(env.AGENT_PRIVATE_KEY.startsWith('0x') ? env.AGENT_PRIVATE_KEY : '0x' + env.AGENT_PRIVATE_KEY, provider));
  const agentAddr = await agent.getAddress();
  log(`에이전트 ${agentAddr} 잔액 ${ethers.formatEther(await retryNet('agentBalance', () => provider.getBalance(agentAddr)))} ETH`);

  const token = new ethers.Contract(chain.token, cfg.abi.token, provider);
  const ledgerAbi = cfg.abi.ledger;

  // 1) 참여자 지갑 준비 + 가스비
  const { file: membersFile, members } = loadMembers(chain.chain_id);
  for (const m of members) {
    m.signer = new ethers.Wallet(m.privateKey, provider);
    const bal = await retryNet('getBalance', () => provider.getBalance(m.address));
    if (bal < MIN_WEI) {
      const tx = await agent.sendTransaction({ to: m.address, value: FUND_WEI });
      await tx.wait();
      log(`가스 전송 → ${m.label} ${m.address} (${ethers.formatEther(FUND_WEI)} ETH) ${short(tx.hash)}`);
    }
  }

  // 2) 가입 (개발 모드 인증번호) · 지갑 등록 · PIE 충전 (에이전트 chargeToken 온체인)
  const ts = Date.now();
  const charges = [];
  for (let i = 0; i < members.length; i++) {
    const m = members[i];
    // 재실행 시 같은 사용자로 로그인 (가입 정보는 members-*.json 에 저장) — 지갑이 이미 등록돼 있으면 건너뜀
    let u = null;
    if (m.email) {
      try { u = await api('/api/auth/login', { email: m.email, password: PASSWORD }); } catch (e) { log(`  ${m.label} 로그인 실패(${e.code}) → 새로 가입`); }
    }
    if (!u) {
      const email = `ev${i}.${ts}@evidence.test`;
      const code = (await api('/api/auth/email-code', { email, purpose: 'signup' })).dev_code;
      if (!code) throw new Error('개발 모드 인증번호(dev_code)가 없어요. SMTP 가 설정된 서버에서는 자동 가입을 못 해요.');
      u = await api('/api/auth/signup', { name: m.label, email, password: PASSWORD, code, pie_id: `ev${i}x${String(ts).slice(-6)}` });
      m.email = email;
    }
    m.token = u.token; m.short = u.short || u.name;
    fs.writeFileSync(membersFile, JSON.stringify(members.map(({ label, address, privateKey, email, short }) => ({ label, address, privateKey, email, short })), null, 2) + '\n');
    const registered = (u.wallet || '').toLowerCase();
    if (registered && registered !== m.address.toLowerCase()) throw new Error(`${m.short} 에 다른 지갑(${u.wallet})이 등록돼 있어요. members-*.json 을 지우고 새 지갑으로 다시 실행하세요.`);
    if (!registered) await api('/api/members/register', { name: m.short, wallet: m.address }, m.token);
    const c = await api('/api/wallet/charge', { name: m.short }, m.token);
    charges.push({ member: m.short, amount: c.amount, tx_hash: c.tx_hash, url: c.url });
    log(`가입 ${m.label}→${m.short} · 지갑 등록 · 충전 ${c.amount} PIE ${short(c.tx_hash)}`);
  }
  const names = members.map((m) => m.short);
  const byShort = Object.fromEntries(members.map((m) => [m.short, m]));

  // 참여자 예치: 프론트 payShare 와 같은 순서
  async function lockAll(rec, who = names) {
    const out = [];
    for (const m of rec.members) {
      if (m.state !== 'wait' || !who.includes(m.name)) continue;
      const w = byShort[m.name];
      const t = token.connect(w.signer);
      const l = new ethers.Contract(chain.ledger, ledgerAbi, w.signer);
      const allowed = await retryNet('allowance', () => t.allowance(w.address, chain.ledger));
      if (allowed < BigInt(m.share)) await (await t.approve(chain.ledger, BigInt(m.share))).wait();
      const r = await (await l.lockForSettlement(rec.chainId)).wait();
      const updated = await api('/api/settlement/approve', { settlement_id: rec.id, name: m.name, tx_hash: r.hash }, w.token);
      out.push({ member: m.name, share: m.share, tx_hash: r.hash, block: r.blockNumber, url: `${chain.explorer}/tx/${r.hash}` });
      log(`  예치 ${m.name} ${m.share} PIE ${short(r.hash)} → 상태 ${updated.status}`);
      rec = updated;
    }
    return { rec, locks: out };
  }

  const balances = async () => Object.fromEntries(await Promise.all(members.map(async (m) => [m.short, Number(await retryNet('balanceOf', () => token.balanceOf(m.address)))])));

  // ── Run 1 ─────────────────────────────────────────────────────────────
  log('▶ Run 1: 정상 정산 (삼겹살 35,900 · 진주 5,000 감면 · 예산 40,000)');
  const payer = members[0];
  const an = await api('/api/settlement/analyze', {
    text: `${names[0]}는 5천원 적게 내고 나머지 세 명이 나눠줘`, members: names, total: 35900, payer: names[0], subject: '삼겹살 1.2kg 공동구매', flow: 'run1',
  }, payer.token);
  if (an.status !== 'ok') throw new Error(`analyze: ${an.status} ${an.question || ''}`);
  log(`  Stage1/2: ${JSON.stringify(an.shares)} · ${an.ruleText}`);
  let r1 = await api('/api/settlement/request', {
    group_name: '삼겹살 1.2kg 공동구매', members: names, shares: an.shares, total: 35900, payer: names[0],
    rule_text: an.ruleText, purpose: an.purpose, per_person_cap: null, total_cap: 40000, merchant: 'Share Pie 공동구매', mode: an.mode || 'EQUAL',
  }, payer.token);
  log(`  등록 → 상태 ${r1.status} · chainId ${short(r1.chainId)} · txs ${r1.txs.map((t) => t.kind).join(',')}`);
  if (r1.status !== 'open') throw new Error(`Run 1 등록 상태가 open 이 아니에요: ${r1.status} ${JSON.stringify(r1.blocked || r1.violations)}`);
  const l1 = await lockAll(r1); r1 = l1.rec;
  if (r1.status !== 'locked') throw new Error(`Run 1: 전원 예치 후 상태 ${r1.status}`);
  const waitS = Math.max(0, Math.ceil(r1.releaseAt - Date.now() / 1000)) + 8;
  log(`  전원 예치(LOCKED) · 인증서(예치 확정) ${short(r1.cert && r1.cert.txHash)} · 보류 ${waitS}초 대기 후 지급`);
  await sleep(waitS * 1000);
  r1 = await api(`/api/settlement/${r1.id}/sync`, {}, payer.token);
  for (let i = 0; i < 6 && r1.status !== 'paid'; i++) { await sleep(10000); r1 = await api(`/api/settlement/${r1.id}/sync`, {}, payer.token); }
  log(`  sync → 상태 ${r1.status} · 지급 tx ${short(r1.cert && r1.cert.txHash)}`);
  const run1 = { analyze: { shares: an.shares, ruleText: an.ruleText, purpose: an.purpose, meta: an.meta }, settlement: r1, locks: l1.locks, balancesAfter: await balances() };

  // ── Run 1.5 ───────────────────────────────────────────────────────────
  log('▶ Run 1.5: 조건 변경 → 지출 통제 중단 (1인 한도 9,000 / 총 한도 30,000)');
  const run15 = { cases: [] };
  for (const [label, caps] of [['1인 한도 9,000원', { per_person_cap: 9000, total_cap: null }], ['총 한도 30,000원', { per_person_cap: null, total_cap: 30000 }]]) {
    let rec, error = null;
    try {
      rec = await api('/api/settlement/request', {
        group_name: `중단 시나리오 (${label})`, members: names, shares: an.shares, total: 35900, payer: names[0],
        rule_text: an.ruleText, purpose: an.purpose, merchant: 'Share Pie 공동구매', mode: an.mode || 'EQUAL', ...caps,
      }, payer.token);
    } catch (e) { error = { code: e.code, message: e.message, details: e.details }; }
    const row = { label, caps, status: rec ? rec.status : 'refused', blocked: rec ? rec.blocked : null, violations: rec ? rec.violations : null, error, txs: rec ? rec.txs : [] };
    run15.cases.push(row);
    log(`  ${label} → ${row.status}${rec && rec.blocked ? ` · Blocked tx ${short(rec.blocked.tx_hash)}` : ''}${error ? ` · ${error.code}` : ''}`);
  }
  run15.balancesAfter = await balances();

  // ── Run 2 ─────────────────────────────────────────────────────────────
  log('▶ Run 2: 예치 → 이의제기(품절 취소) → AI 판정 → 환불');
  let r2 = await api('/api/settlement/request', {
    group_name: '삼겹살 공동구매 (2차)', members: names, shares: an.shares, total: 35900, payer: names[0],
    rule_text: an.ruleText, purpose: an.purpose, per_person_cap: null, total_cap: 40000, merchant: 'Share Pie 공동구매', mode: an.mode || 'EQUAL',
  }, payer.token);
  if (r2.status !== 'open') throw new Error(`Run 2 등록 상태 ${r2.status}`);
  const l2 = await lockAll(r2); r2 = l2.rec;
  const balBefore = await balances();
  const disputer = members[1];
  const reason = '판매자가 품절로 주문을 취소했어요. 예치금을 전원 돌려받아야 해요';
  const raised = await api('/api/dispute/raise', { settlement_id: r2.id, by: disputer.short, reason }, disputer.token);
  log(`  이의제기 ${disputer.short} → 상태 ${raised.status || (raised.settlement && raised.settlement.status) || '?'}`);
  const inv = await api('/api/dispute/investigate', { settlement_id: r2.id }, disputer.token);
  log(`  AI 판정: ${inv.verdict} (${inv.verdict_ko}) · refund=${inv.refund}${inv.guard ? ` · guard: ${inv.guard}` : ''}`);
  const res = await api('/api/dispute/resolve', { settlement_id: r2.id }, disputer.token);
  r2 = await api(`/api/settlement/${r2.id}`, undefined, disputer.token);
  const balAfter = await balances();
  log(`  실행 → 상태 ${r2.status} · txs ${r2.txs.map((t) => `${t.kind}:${short(t.tx_hash)}`).join(' ')}`);
  const run2 = { settlement: r2, locks: l2.locks, dispute: { by: disputer.short, reason, raise: raised, investigate: inv, resolve: res }, balancesBefore: balBefore, balancesAfter: balAfter };

  // ── 증거 묶음 ─────────────────────────────────────────────────────────
  const usageMd = await (await fetch(BASE + '/api/usage/report.md')).text();
  const usage = await api('/api/usage');
  const wallets = {};
  for (const m of members) wallets[m.short] = await api(`/api/wallet/${m.address}`);
  const dir = path.join(ROOT, 'docs', 'evidence', `${(chain.explorer || '').includes('sepolia') ? 'sepolia' : 'chain' + chain.chain_id}-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}`);
  fs.mkdirSync(dir, { recursive: true });
  const w = (n, d) => fs.writeFileSync(path.join(dir, n), typeof d === 'string' ? d : JSON.stringify(d, null, 2) + '\n');
  w('run1.json', run1); w('run1_5.json', run15); w('run2.json', run2); w('usage-report.md', usageMd); w('usage.json', usage); w('wallets.json', wallets);
  w('members.json', members.map((m) => ({ label: m.label, short: m.short, address: m.address, explorer: `${chain.explorer}/address/${m.address}` })));
  w('charges.json', charges);

  const tx = (run, kind, t) => `| ${run} | ${kind} | \`${t.tx_hash || t.txHash}\` | ${t.url || (chain.explorer + '/tx/' + (t.tx_hash || t.txHash))} |`;
  const L = [];
  L.push('# SharePie 실제 테스트넷 증거 묶음 (Python 백엔드 + ShareLedger)');
  L.push('');
  L.push(`- 네트워크: **${chain.explorer && chain.explorer.includes('sepolia') ? 'Sepolia' : chain.network}** (chainId ${chain.chain_id}) · 실행 ${new Date(started).toISOString()} → ${new Date().toISOString()}`);
  L.push(`- ShareLedger \`${chain.ledger}\` · PieToken \`${chain.token}\` · 에이전트 \`${agentAddr}\` · 이의제기 기간 ${chain.dispute_window}s`);
  L.push(`- 컨트랙트: ${chain.explorer}/address/${chain.ledger}`);
  L.push(`- AI: Kiln ${health.model} (llm_mode=${health.llm_mode}) · 서명 모델: 등록·차단·환불·판정 = 에이전트, 예치 = 참여자 지갑(스크립트가 MetaMask 대신 서명)`);
  L.push('');
  L.push('## 참여자 지갑 (테스트 전용)');
  for (const m of members) L.push(`- ${m.label}(${m.short}) \`${m.address}\` — ${chain.explorer}/address/${m.address}`);
  L.push('');
  L.push('## 트랜잭션');
  L.push('| Run | 종류 | TxHash | 탐색기 |'); L.push('|---|---|---|---|');
  for (const c of charges) L.push(tx('준비', `charge_token (${c.member}, ${c.amount} PIE)`, c));
  for (const t of run1.settlement.txs) L.push(tx('Run 1', t.kind + (t.member ? ` (${t.member})` : ''), t));
  for (const c of run15.cases) { if (c.blocked && c.blocked.tx_hash) L.push(tx('Run 1.5', `blockSettlement (${c.label})`, c.blocked)); for (const t of c.txs || []) L.push(tx('Run 1.5', t.kind, t)); }
  for (const t of run2.settlement.txs) L.push(tx('Run 2', t.kind + (t.member ? ` (${t.member})` : ''), t));
  L.push('');
  L.push('## Run 1 — 정상 정산');
  L.push(`- 조건: "${names[0]}는 5천원 적게 내고 나머지 세 명이 나눠줘" (총 35,900 · 예산 40,000) → Stage1(AI)+Stage2(코드): ${JSON.stringify(an.shares)}`);
  L.push(`- 규칙: ${an.ruleText} · 목적: ${an.purpose}`);
  L.push(`- 정산 id \`${run1.settlement.id}\` · chainId \`${run1.settlement.chainId}\` · 최종 상태 **${run1.settlement.status}**`);
  L.push(`- 인증서 TxHash: \`${run1.settlement.cert ? run1.settlement.cert.txHash : '-'}\` (${run1.settlement.cert ? run1.settlement.cert.url : ''})`);
  L.push(`- 지급 후 PIE 잔액: ${JSON.stringify(run1.balancesAfter)}`);
  L.push('');
  L.push('## Run 1.5 — 조건 변경 → 지출 통제 중단');
  for (const c of run15.cases) L.push(`- ${c.label}: 상태 **${c.status}**${c.blocked ? ` · reason_code ${c.blocked.reason_code} · ${c.blocked.message || c.blocked.code || ''} · tx \`${c.blocked.tx_hash}\`` : ''}${c.error ? ` · ${c.error.code}: ${c.error.message}` : ''}`);
  L.push('- 예치·지급 트랜잭션 없음. 중단 판단은 코드(지출 통제)이며 체인에 Blocked 이벤트로 기록됨.');
  L.push('');
  L.push('## Run 2 — 이의제기 → AI 판정 → 자동 실행');
  L.push(`- 정산 id \`${run2.settlement.id}\` · 이의제기: ${disputer.short} — "${reason}"`);
  L.push(`- AI 판정(dispute.investigate): **${inv.verdict}** (${inv.verdict_ko}) · refund=${inv.refund}${inv.guard ? ` · 코드 가드: ${inv.guard}` : ''}`);
  L.push(`- 설명: ${inv.explanation || ''}`);
  L.push(`- 실행 후 상태 **${run2.settlement.status}** · PIE 잔액 전/후: ${JSON.stringify(balBefore)} → ${JSON.stringify(balAfter)}`);
  L.push('');
  L.push('## AI 토큰 사용량 (서버 /api/usage/report.md)');
  L.push(usageMd.trim());
  L.push('');
  L.push('> 한계: 참여자 예치 서명은 실사용에서 MetaMask 가 하지만 이 증거 실행에서는 스크립트가 참여자 지갑으로 서명했다(동일한 컨트랙트 호출). 등록·차단·환불·판정은 에이전트 지갑 하나가 서명하는 데모용 구조. Run 2 의 이의 사유는 시연용 시나리오다.');
  w('summary.md', L.join('\n') + '\n');
  log(`📦 증거 묶음: ${dir}`);
  console.log(`\nSUMMARY_PATH=${dir}`);
}

main().catch((e) => { console.error('❌ 실패:', e.message, e.details ? JSON.stringify(e.details) : ''); process.exit(1); });
