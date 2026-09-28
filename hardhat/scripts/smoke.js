'use strict';
// [blockchain 담당] 체인 스모크 테스트 — 새 백엔드를 붙인 직후(또는 프롬프트가 바뀔 때마다) 10분 안에 "체인에 잘못된 값이 가지 않는지" 자동 판정.
// 실행: 서버(:8000, CHAIN_MODE=bsc) 켠 뒤  cd hardhat && npm run smoke      (가스 절약: SMOKE_SKIP_CHAIN_WRITE=1 npm run smoke)
// 검사: ① 서버·.env·코드 패치 ② 온체인 권한·잔액 ③ 해석 문장 6개(감면·비율·모호·접미사 이름·한글 금액 2개)
//       ④ 가드 A(오파싱 금액 등록 거부, tx 0건) ⑤ 체인 쓰기: 한도 초과 → Blocked, 정상 등록 → 취소(참여자 지갑 파일이 있을 때만, tx 3건)
// 결과: 표 + 종료 코드(🔴 하나라도 있으면 1). ⚠️ 는 알려진 코드 버그(⑥ 한글 금액)라 실패로 치지 않는다.
const fs = require('fs');
const path = require('path');
const { ethers } = require('ethers');

const ROOT = path.join(__dirname, '..', '..');
const BASE = process.env.SP_BASE || 'http://127.0.0.1:8000';
const PASSWORD = 'evidence1234x';
const rows = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const short = (h) => (h ? h.slice(0, 10) + '…' : '-');
function add(level, area, name, detail) { rows.push({ level, area, name, detail: String(detail || '') }); console.log(`${level} [${area}] ${name}${detail ? ' — ' + detail : ''}`); }
const ok = (a, n, d) => add('✅', a, n, d), warn = (a, n, d) => add('⚠️', a, n, d), bad = (a, n, d) => add('🔴', a, n, d);

function readEnv(file) {
  const out = {};
  if (!fs.existsSync(file)) return out;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !line.trim().startsWith('#')) out[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
  return out;
}
const env = readEnv(path.join(ROOT, '.env'));

async function apiRaw(p, body, token, method = body === undefined ? 'GET' : 'POST') {
  const res = await fetch(BASE + p, { method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), 'X-SP-Device': 'smoke' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const j = await res.json().catch(() => ({}));
  if (!res.ok || j.ok === false) { const e = j.error || {}; throw Object.assign(new Error(`${e.code || res.status} ${e.message || ''}`), { code: e.code, status: res.status, details: e.details }); }
  return j.data;
}
async function api(p, body, token, method) {
  for (let i = 1; ; i++) {
    try { return await apiRaw(p, body, token, method); } catch (e) {
      if (!/fetch failed|ECONNRESET|ETIMEDOUT/i.test(e.message) || i >= 4) throw e;
      await sleep(i * 4000);
    }
  }
}

async function main() {
  // ── ① 서버 · .env · 코드 패치 ─────────────────────────────────────
  let cfg, health;
  try { health = await api('/api/health'); cfg = await api('/api/config'); } catch (e) { bad('서버', '응답 없음', `${BASE} — ${e.message}`); return finish(); }
  const c = cfg.chain;
  (c.mode === 'bsc' ? ok : bad)('서버', '실제 체인 모드', `chain.mode=${c.mode}`);
  (String(c.chain_id) === String(env.BSC_CHAIN_ID) ? ok : bad)('서버', 'chainId 일치', `서버 ${c.chain_id} / .env ${env.BSC_CHAIN_ID}`);
  (c.ledger && c.ledger.toLowerCase() === (env.LEDGER_ADDRESS || '').toLowerCase() ? ok : bad)('서버', 'ShareLedger 주소 일치', c.ledger);
  (c.token && c.token.toLowerCase() === (env.TOKEN_ADDRESS || '').toLowerCase() ? ok : bad)('서버', 'PieToken 주소 일치', c.token);
  (health.llm_mode === 'live' ? ok : warn)('서버', 'AI 모드', `llm_mode=${health.llm_mode} model=${health.model}`);
  ((env.KILN_TOOL_MODE || '').toLowerCase() === 'json' ? ok : bad)('.env', 'KILN_TOOL_MODE=json', `현재 ${env.KILN_TOOL_MODE || '(없음)'} — auto/tools 면 감면 무시·판정 기본값 재발`);
  (Number(env.GAS_DRIP_ETH || 0.002) > 0 ? ok : warn)('.env', '가스 자동 지급 켜짐', `GAS_DRIP_ETH=${env.GAS_DRIP_ETH || '(기본 0.002)'}`);
  (String(c.dispute_window) === String(env.DISPUTE_WINDOW_SEC || 180) ? ok : warn)('체인', '이의제기 기간 일치', `컨트랙트 ${c.dispute_window}s / .env ${env.DISPUTE_WINDOW_SEC || '(기본 180)'} — 다르면 setDisputeWindow 필요`);
  const chainPy = fs.readFileSync(path.join(ROOT, 'agent', 'chain.py'), 'utf8');
  const svcPy = fs.readFileSync(path.join(ROOT, 'agent', 'service.py'), 'utf8');
  for (const [file, src, marker, name] of [[
    'chain.py', chainPy, 'def _gas_price', '가스 가격 v2 (배수·대기 300초)'], ['chain.py', chainPy, 'def send_gas', '가스 자동 지급'], ['chain.py', chainPy, 'PURPOSE_MAX', '가드 C purpose 제한'],
    ['service.py', svcPy, 'AMOUNT_SUSPECT', '가드 A 금액 오파싱 방어'], ['service.py', svcPy, 'REFUND_GUARD', '가드 B 판정-환불 일관성']]) {
    (src.includes(marker) ? ok : bad)('코드', name, src.includes(marker) ? file : `${file}에 없음 → py tools/apply_blockchain_patches.py`);
  }

  // ── ② 온체인 권한 · 잔액 ────────────────────────────────────────
  const provider = new ethers.JsonRpcProvider(env.BSC_RPC_URL);
  const ledger = new ethers.Contract(c.ledger, cfg.abi.ledger, provider);
  const token = new ethers.Contract(c.token, cfg.abi.token, provider);
  try {
    const net = await provider.getNetwork();
    (Number(net.chainId) === Number(c.chain_id) ? ok : bad)('체인', 'RPC 체인 일치', `RPC chainId ${net.chainId}`);
    const bal = Number(ethers.formatEther(await provider.getBalance(c.agent)));
    (bal >= 0.05 ? ok : bal >= 0.01 ? warn : bad)('체인', '에이전트 가스 잔액', `${bal.toFixed(4)} ETH (베타: 참가자 수 × 0.003 이상 권장)`);
    (await ledger.isAgent(c.agent) ? ok : bad)('체인', 'ShareLedger isAgent', c.agent);
    let minter = true; try { minter = await token.isMinter(c.agent); } catch { try { minter = (await token.minter()).toLowerCase() === c.agent.toLowerCase(); } catch { minter = null; } }
    (minter === null ? warn : minter ? ok : bad)('체인', 'PieToken 발급 권한', minter === null ? '확인 함수 없음' : String(minter));
  } catch (e) { bad('체인', 'RPC 조회 실패', e.message); }

  // ── 사용자 준비 (참여자 지갑 파일이 있으면 재사용) ─────────────────
  const membersFile = path.join(__dirname, '..', 'deployments', `members-${c.chain_id}.json`);
  let members = fs.existsSync(membersFile) ? JSON.parse(fs.readFileSync(membersFile, 'utf8')) : [];
  let me = null;
  for (const m of members) {
    if (!m.email) continue;
    try { const u = await api('/api/auth/login', { email: m.email, password: PASSWORD }); m.token = u.token; m.short = u.short || u.name; m.walletOk = !!u.wallet; } catch { m.token = null; }
  }
  const ready = members.filter((m) => m.token && m.walletOk);
  if (ready.length) { me = ready[0]; ok('사용자', '참여자 로그인', `${ready.length}명 (${ready.map((m) => m.short).join(', ')})`); }
  else {
    const ts = Date.now(); const email = `smoke.${ts}@evidence.test`;
    const code = (await api('/api/auth/email-code', { email, purpose: 'signup' })).dev_code;
    if (!code) { bad('사용자', '개발 모드 인증번호 없음', 'SMTP 서버에서는 자동 가입 불가'); return finish(); }
    const u = await api('/api/auth/signup', { name: '스모크', email, password: PASSWORD, code, pie_id: `smoke${String(ts).slice(-7)}` });
    me = { short: u.short || u.name, token: u.token, walletOk: false };
    warn('사용자', '참여자 지갑 파일 없음', '해석·가드 검사만 실행. 체인 쓰기 검사는 npm run evidence 가 지갑을 만들며 수행');
  }
  const names = ready.length >= 4 ? ready.slice(0, 4).map((m) => m.short) : [me.short, '진우2', '민재2', '지현2'];

  // ── ③ 해석 문장 (Stage 1 AI + Stage 2 코드) ──────────────────────
  const N = names;
  const cases = [
    { name: '감면(접미사 이름)', text: `${N[0]}는 5천원 적게 내고 나머지 세 명이 나눠줘`, total: 35900, expect: (d) => d.status === 'ok' && sh(d)[N[0]] === 5225 && sh(d)[N[1]] === 10225, want: `${N[0]} 5,225 / 나머지 10,225` },
    { name: '비율', text: `${N[1]}가 40% 내고 나머지 셋이 똑같이 나눠`, total: 40000, expect: (d) => d.status === 'ok' && sh(d)[N[1]] === 16000 && sh(d)[N[0]] === 8000, want: `${N[1]} 16,000 / 나머지 8,000` },
    { name: '모호 → 되묻기', text: `${N[0]}는 조금 더 내`, total: 30000, expect: (d) => d.status === 'need_info', want: 'need_info' },
    { name: '빼기', text: `${N[3]} 빼고 셋이 똑같이`, total: 30000, expect: (d) => d.status === 'ok' && (sh(d)[N[3]] || 0) === 0 && sh(d)[N[0]] === 10000, want: `${N[3]} 0 / 나머지 10,000` },
    { name: '한글 금액 "만2천원" (⑥ 알려진 버그)', text: `택시비 만2천원 나랑 ${N[1]} 반띵`, total: null, membersOverride: [N[0], N[1]], expect: (d) => d.status === 'ok' && d.total === 12000, want: 'total 12,000', known: true },
    { name: '한글 금액 "만오천원씩" (⑥ 알려진 버그)', text: `한 명당 만오천원씩 걷자`, total: null, expect: (d) => d.status === 'ok' && d.total === 60000, want: 'total 60,000', known: true },
  ];
  function sh(d) { return Object.fromEntries((d.shares || []).map(([n, a]) => [n, a])); }
  let analyzeTokens = 0;
  for (const cs of cases) {
    try {
      const body = { text: cs.text, members: cs.membersOverride || N, payer: N[0], subject: '스모크', flow: 'smoke' };
      if (cs.total !== null) body.total = cs.total;
      const d = await api('/api/settlement/analyze', body, me.token);
      const usage = d.usage || {}; analyzeTokens += usage.total_tokens || 0;
      const got = d.status === 'ok' ? `total ${d.total} · ${JSON.stringify(d.shares)}` : `${d.status} · ${d.question || ''}`;
      const pass = cs.expect(d);
      (pass ? ok : cs.known ? warn : bad)('해석', cs.name, pass ? got : `기대 ${cs.want} / 실제 ${got}`);
    } catch (e) { (cs.known ? warn : bad)('해석', cs.name, e.message); }
  }

  // ── ④ 가드 A: 오파싱 금액 등록 거부 (tx 0건) ─────────────────────
  const canWrite = ready.length >= 4 && ready.every((m) => m.walletOk) && !process.env.SMOKE_SKIP_CHAIN_WRITE;
  try {
    await api('/api/settlement/request', { group_name: '스모크 가드A', members: N.slice(0, 2), shares: [[N[0], 1000], [N[1], 1000]], total: 2000, payer: N[0], rule_text: `택시비 만2천원 나랑 ${N[1]} 반띵`, purpose: '스모크', merchant: 'Share Pie 공동구매', mode: 'EQUAL' }, me.token);
    bad('가드A', '오파싱 금액이 등록됨', '총액 2,000 + 문장 "만2천원" 이 거부되지 않음 → 온체인에 잘못된 총액이 갈 수 있음');
  } catch (e) {
    (e.code === 'AMOUNT_SUSPECT' ? ok : e.code === 'MEMBER_WALLET_MISSING' || e.code === 'BAD_REQUEST' ? warn : bad)('가드A', '오파싱 금액 등록 거부', `${e.code}: ${e.message.slice(0, 80)}`);
  }

  // ── ⑤ 체인 쓰기: 한도 초과 Blocked → 정상 등록 → 취소 ─────────────
  if (!canWrite) warn('체인쓰기', '건너뜀', process.env.SMOKE_SKIP_CHAIN_WRITE ? 'SMOKE_SKIP_CHAIN_WRITE=1 (가스 절약)' : '참여자 4명 지갑 파일 필요 (npm run evidence 가 생성)');
  else {
    const shares = [[N[0], 5225], [N[1], 10225], [N[2], 10225], [N[3], 10225]];
    const base = { members: N, shares, total: 35900, payer: N[0], rule_text: `${N[0]}는 5천원 적게 내고 나머지 세 명이 나눠줘`, purpose: '스모크 검사 (x'.padEnd(120, '~') + ')', merchant: 'Share Pie 공동구매', mode: 'ADJUST' };
    try {
      const r = await api('/api/settlement/request', { ...base, group_name: '스모크 한도초과', total_cap: 30000 }, me.token);
      (r.status === 'blocked' && r.blocked && r.blocked.tx_hash ? ok : bad)('체인쓰기', '한도 초과 → Blocked 온체인', r.status === 'blocked' ? `${r.blocked.code} tx ${short(r.blocked.tx_hash)}` : `상태 ${r.status}`);
    } catch (e) { bad('체인쓰기', '한도 초과 요청 실패', e.message); }
    try {
      const r = await api('/api/settlement/request', { ...base, group_name: '스모크 정상등록', total_cap: 40000 }, me.token);
      (r.status === 'open' ? ok : bad)('체인쓰기', '정상 등록 (createSettlement)', `상태 ${r.status} · ${r.txs.map((t) => t.kind + ':' + short(t.tx_hash)).join(' ')}`);
      if (r.status === 'open') {
        const onchain = await ledger.getSettlement(r.chainId).catch(() => null);
        const purposeLen = onchain ? String(onchain[onchain.length - 1] ?? '').length : null;
        try {
          const s = await ledger.getSettlement(r.chainId);
          const pStr = Array.from(s).find((v) => typeof v === 'string' && !v.startsWith('0x')) || '';
          (pStr.length <= 60 ? ok : bad)('가드C', '온체인 purpose 길이', `${pStr.length}자 (≤60)`);
        } catch { warn('가드C', '온체인 purpose 확인 불가', 'getSettlement 파싱 실패'); }
        const cx = await api('/api/settlement/cancel', { settlement_id: r.id, name: N[0] }, me.token);
        (cx.status === 'blocked' || cx.status === 'cancelled' ? ok : bad)('체인쓰기', '결제자 취소 (blockSettlement)', `상태 ${cx.status}${cx.blocked && cx.blocked.tx_hash ? ' tx ' + short(cx.blocked.tx_hash) : ''}`);
      }
    } catch (e) { bad('체인쓰기', '정상 등록 실패', e.message); }
  }
  ok('AI', '해석 토큰 합계', `${analyzeTokens} 토큰 / ${cases.length}문장 (문장당 ${Math.round(analyzeTokens / cases.length)}) — 3,000 넘게 뛰면 지식·예시가 통째로 들어간 것`);
  return finish();
}

function finish() {
  const n = { '✅': 0, '⚠️': 0, '🔴': 0 };
  for (const r of rows) n[r.level]++;
  console.log('\n| 결과 | 영역 | 검사 | 내용 |\n|---|---|---|---|');
  for (const r of rows) console.log(`| ${r.level} | ${r.area} | ${r.name} | ${r.detail.replace(/\|/g, '/')} |`);
  console.log(`\n합계: ✅ ${n['✅']} · ⚠️ ${n['⚠️']} · 🔴 ${n['🔴']}  →  ${n['🔴'] ? '🔴 베타 불가 — 빨간 항목부터 고치세요' : n['⚠️'] ? '⚠️ 진행 가능 (경고 확인)' : '✅ 통과'}`);
  const outDir = path.join(ROOT, 'docs', 'evidence'); fs.mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, `smoke-${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}.md`);
  fs.writeFileSync(file, `# 체인 스모크 테스트 ${new Date().toISOString()}\n\n| 결과 | 영역 | 검사 | 내용 |\n|---|---|---|---|\n${rows.map((r) => `| ${r.level} | ${r.area} | ${r.name} | ${r.detail.replace(/\|/g, '/')} |`).join('\n')}\n\n합계: ✅ ${n['✅']} · ⚠️ ${n['⚠️']} · 🔴 ${n['🔴']}\n`);
  console.log(`기록: ${file}`);
  process.exit(n['🔴'] ? 1 : 0);
}

main().catch((e) => { bad('실행', '예외', e.message); finish(); });
