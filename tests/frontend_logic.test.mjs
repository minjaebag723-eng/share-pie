// 프론트 Component 로직을 브라우저 없이 실행해 백엔드와 E2E 검증 (폰 4대 시뮬레이션)
// 실행: DISPUTE_WINDOW_SEC=3 CHARGE_COOLDOWN_SEC=0 으로 백엔드를 켠 뒤  node tests/frontend_logic.test.mjs
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8');
const bridge = fs.readFileSync(path.join(ROOT, 'frontend/sp-bridge.js'), 'utf8');
const src = html.split('<script type="text/x-dc" data-dc-script>')[1].split('</script>')[0];
const tpl = html.split('<x-dc>')[1].split('</x-dc>')[0];
const BASE = process.env.API || 'http://127.0.0.1:8000';
const RUN = Date.now().toString(36).slice(-4);

let failures = 0;
const ok = (cond, msg) => { console.log((cond ? '  ✓ ' : '  ✗ ') + msg); if (!cond) failures++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

function makePhone(opts = {}) {
  const store = opts.store || {};
  const loc = { protocol: 'http:', host: 'localhost:8000', pathname: '/', href: '', origin: 'http://localhost:8000', search: '' };
  const win = { SP_API_BASE: BASE, location: loc, localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } },
    addEventListener() {}, removeEventListener() {}, isSecureContext: true, innerHeight: 900, innerWidth: 420, open() {} };
  const ctx = vm.createContext({ window: win, fetch, console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
    navigator: { userAgent: 'node', ...(opts.geo ? { geolocation: opts.geo } : {}) }, location: loc, localStorage: win.localStorage, URLSearchParams, JSON, Date, Math, Promise, BigInt, Proxy, Set, Map });
  ctx.window.window = ctx.window;
  vm.runInContext(bridge.replace('(function () {', '(function () { var location = window.location;'), ctx);
  ctx.SP = ctx.window.SP;
  class StreamableLogic {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(u, cb) { const p = typeof u === 'function' ? u(this.state) : u; this.state = { ...this.state, ...(p || {}) }; cb && cb(); }
  }
  const Component = vm.runInContext(`(function(DCLogic, StreamableLogic, React){ ${src}\n; return Component; })`, ctx)(StreamableLogic, StreamableLogic, { createRef: () => ({ current: null }) });
  const c = new Component({});
  c.toasts = []; c.showToast = t => { c.toasts.push(t); };
  c._store = store; c._loc = loc;
  return c;
}

function templateKeys() {
  const keys = new Set();
  const loopVars = new Set([...tpl.matchAll(/as="(\w+)"/g)].map(m => m[1]));
  for (const m of tpl.matchAll(/\{\{\s*([\w.]+)\s*\}\}/g)) {
    const root = m[1].split('.')[0];
    if (!loopVars.has(root) && !['true', 'false'].includes(root)) keys.add(root);
  }
  return keys;
}
const waitTyping = async p => { for (let i = 0; i < 80 && p.state.typing; i++) await sleep(50); };
const lastBot = p => p.state.chats[0].msgs.filter(m => m.from === 'bot');
const card = (p, pred) => p.renderVals().groupList.find(pred);

async function befriend(p, others) {   // 친구 요청 → 상대가 수락해야 서로 친구 (서버 저장)
  for (const o of others) {
    await p.loadFriends();
    if (p.state.friends.some(f => f.id === o.state.userId)) continue;
    p.openFriendAdd(null); p.state.friendAddQ = '@' + o.state.userId;
    await p.lookupFriendId(); await p.sendFriendRequest();
    await o.loadFriends(); await o.acceptFriend(p.state.userId);
    await p.loadFriends();
  }
}

async function pickFriends(p, names) {
  for (const n of names) {
    p.state.friendSearchQ = n;
    const f = p.renderVals().friendSearchList.find(x => x.name === n);
    if (!f) throw new Error('친구 목록에 없음: ' + n);
    if (!f.on) f.toggle();
  }
  p.state.friendSearchQ = '';
}

async function payAll(phones, sid) {
  for (const p of phones) {
    await p.refreshServer();
    const c = card(p, x => x.sid === sid);
    if (c && /결제하기|인출 승인/.test(c.actionLabel)) await c.remind();
  }
}

// 분담표 승인: 확인 카드를 누른 사람 말고도 정산 대상 전원이 각자 폰에서 ‘승인하기’를 눌러야 온체인 정산이 시작된다
const ALL = [];
async function approveSplitAll(gid) {
  for (const p of ALL) {
    await p.refreshServer();
    const g = p.state.groups.find(x => x.id === gid), sa = g && g.splitApproval;
    if (sa && sa.targets.includes(p.me) && !sa.approved.includes(p.me)) { await p.approveSplit(gid); await sleep(100); }
  }
  for (const p of ALL) await p.refreshServer();
}

async function splitByChat(ph, gid, text) {   // 새 UI: 그룹 채팅 → 확인 카드 → 확인(코드 계산 + 온체인 요청)
  ph.state.gchatId = gid; ph.state.gchatInput = text; ph.sendGchat(); await sleep(500);
  const cm = ph.state.groups.find(x => x.id === gid).msgs.filter(m => m.kind === 'confirm').at(-1);
  if (cm) { await ph.confirmSettlement(gid, cm.id); await sleep(300); await approveSplitAll(gid); }
  await ph.refreshServer();
}

async function main() {
  console.log('▶ 백엔드', BASE);
  const people = [['김진주', 'jinju'], ['박진우', 'jinwoo'], ['이민재', 'minjae'], ['최지현', 'jihyun']].map(([n, e]) => [n, `${e}@test.com`]);
  const phones = people.map(() => makePhone());
  const [jin, woo, min, hyun] = phones; ALL.push(...phones);
  for (const p of phones) await p.boot();
  ok(phones.every(p => p.state.online), '4대 모두 백엔드 연결');

  // 예시 데이터가 없는지
  ok(jin.state.chats.length === 0 && jin.state.groups.filter(g => !g.sid).length === 0 && jin.state.docs.length === 0 && jin.state.notifs.length === 0,
     '예시 데이터 없음 (대화·그룹·인증서·알림 0개)');
  const rv0 = jin.renderVals();
  ok(rv0.nearList.length === 0 && rv0.nearEmpty && !('hotList' in rv0), '공동구매 탭: 예시 상품 없음 (실제 모집글만)');
  ok(!rv0.hasRec, '추천 섹션은 대화 전에는 숨김');

  // 회원가입 (서버 계정)
  const PW = 'abc12345';
  {   // 인증번호 없이/틀리게 가입 시도 → 차단
    const t = makePhone(); await t.boot();
    Object.assign(t.state, { authMode: 'signup', name: '테스트' + RUN, email: `nocode.${RUN}@test.com`, pw: PW, signupId: 'nocode' + RUN });
    await t.submitAuth();
    ok(t.state.screen !== 'main' && /인증번호/.test(t.state.authErr), '인증번호 받기 전 가입 차단: ' + t.state.authErr);
    await t.sendSignupCode();
    ok(t.state.codeSent && /^\d{6}$/.test(t.state.code), '인증번호 발송 (개발 모드: 화면 표시) · ' + t.state.codeHint.slice(0, 30));
    t.state.code = t.state.code === '000000' ? '111111' : '000000'; await t.submitAuth();
    ok(t.state.screen !== 'main' && /맞지 않아요/.test(t.state.authErr), '틀린 인증번호 거부: ' + t.state.authErr);
    Object.assign(t.state, { pw: '123456' }); await t.sendSignupCode().catch(() => {});
  }
  for (let i = 0; i < 4; i++) {
    const p = phones[i];
    Object.assign(p.state, { authMode: 'signup', name: people[i][0], email: people[i][1], pw: PW, signupId: people[i][1].split('@')[0] + '.pie' });
    await p.sendSignupCode();
    await p.submitAuth();
    if (p.state.screen !== 'main') { Object.assign(p.state, { authMode: 'login', email: people[i][1], pw: PW }); await p.submitAuth(); } // 재실행 시
  }
  ok(phones.every(p => p.state.screen === 'main'), '4명 서버 회원가입 → 메인 진입');
  ok(phones.every(p => /\.pie$/.test(p.state.userId)), 'Pie ID 가입: ' + phones.map(p => '@' + p.state.userId).join(' '));
  {   // Pie ID 중복 확인 · 형식 검사 · 없는 ID
    const t = makePhone(); await t.boot();
    t.state.authMode = 'signup'; t.renderVals().onSignupId({ target: { value: jin.state.userId } }); await sleep(600);
    ok(/이미 사용 중/.test(t.renderVals().signupIdHelp), '가입 화면: 이미 쓰는 Pie ID 알림 → ' + t.renderVals().signupIdHelp);
    t.renderVals().onSignupId({ target: { value: '1abc' } });
    ok(/소문자로 시작/.test(t.renderVals().signupIdHelp), 'Pie ID 형식 검사: ' + t.renderVals().signupIdHelp);
    jin.openFriendAdd(null); jin.state.friendAddQ = 'nobody.here'; await jin.lookupFriendId();
    ok(/없어요/.test(jin.state.friendAddErr), '없는 Pie ID: ' + jin.state.friendAddErr);
    jin.state.friendAddQ = jin.state.userId; await jin.lookupFriendId();
    ok(/내 Pie ID/.test(jin.state.friendAddErr), '내 ID로는 친구 추가 불가');
  }
  // ── 친구 요청 흐름: 요청 → 알림 → 수락/거절/취소 ──
  jin.openFriendAdd(null); jin.state.friendAddQ = '@' + woo.state.userId; await jin.lookupFriendId();
  ok(jin.renderVals().friendAddResult.btnLabel === '친구 요청', '친구 찾기 결과: ‘친구 요청’ 버튼');
  await jin.sendFriendRequest();
  ok(jin.toasts.some(t => /친구 요청을 보냈어요/.test(t)) && jin.state.friendReqOut.some(f => f.id === woo.state.userId) && !jin.state.friends.length,
     '요청만으로는 친구가 아님 (보낸 요청 목록에 표시)');
  await woo.loadNotifs(); await woo.loadFriends();
  const wn = woo.renderVals().notifList.find(n => n.req && n.req.type === 'friend');
  ok(wn && wn.hasActions && /친구 요청을 보냈어요/.test(wn.text) && woo.renderVals().reqInCount === 1 && woo.renderVals().tabs.find(t => t.label === 'MY').hasBadge,
     '받는 사람: 알림함에 수락/거절 버튼 + 친구 탭 배지 + MY 탭 배지');
  await wn.onDecline(); await jin.loadFriends();
  ok(!woo.state.friendReqIn.length && !jin.state.friendReqOut.length && !jin.state.friends.length, '거절 → 요청 사라짐 (친구 아님)');
  jin.openFriendAdd(null); jin.state.friendAddQ = '@' + woo.state.userId; await jin.lookupFriendId(); await jin.sendFriendRequest();
  await jin.cancelFriendRequest(woo.state.userId); await woo.loadFriends(); await woo.loadNotifs();
  ok(!woo.state.friendReqIn.length && !woo.state.notifs.some(n => n.req && n.req.status === 'pending'), '요청 취소 → 상대 알림함에서도 사라짐');
  jin.openFriendAdd(null); jin.state.friendAddQ = '@' + woo.state.userId; await jin.lookupFriendId(); await jin.sendFriendRequest();
  await woo.loadNotifs(); await woo.renderVals().notifList.find(n => n.hasActions).onAccept(); await jin.loadFriends(); await jin.loadNotifs();
  ok(jin.state.friends.some(f => f.id === woo.state.userId) && woo.state.friends.some(f => f.id === jin.state.userId)
     && jin.state.notifs.some(n => /수락했어요/.test(n.text)), '수락 → 서로 친구 + 요청한 사람에게 ‘수락했어요’ 알림');
  for (const p of phones) await befriend(p, phones.filter(x => x !== p));
  ok(jin.state.friends.length === 3 && jin.state.friends.every(f => f.id && f.name), 'Pie ID로 친구 3명 추가: ' + jin.state.friends.map(f => `${f.name}(@${f.id})`).join(', '));
  { const other = makePhone(); await other.boot(); Object.assign(other.state, { authMode: 'login', email: people[0][1], pw: PW }); await other.submitAuth(); await sleep(200);
    ok(other.state.friends.length === 3, '다른 기기 로그인해도 친구 목록 유지 (서버 저장)'); }
  jin.openAddressSheet(); jin.state.draftAddress = '서울 성동구 성수동'; await jin.saveAddress();
  ok(jin.state.userAddress === '서울 성동구 성수동' && jin.renderVals().userAddress === '서울 성동구 성수동', '우리 동네 저장 (서버 프로필)');
  ok(jin.me === '진주' && min.me === '민재', `me = 가입 이름 기준 (${jin.me}/${min.me})`);
  const dup = makePhone(); await dup.boot();
  Object.assign(dup.state, { authMode: 'signup', name: '강진주', email: `dup.${RUN}@test.com`, pw: PW, signupId: 'dup' + RUN }); await dup.sendSignupCode(); await dup.submitAuth();
  ok(dup.state.screen === 'main' && dup.me === '강진주', '같은 이름도 가입 가능 → 정산에서는 ‘강진주’로 구분: ' + dup.me);
  { const d2 = makePhone(); await d2.boot();
    Object.assign(d2.state, { authMode: 'signup', name: '김진주', email: `dup2.${RUN}@test.com`, pw: PW, signupId: 'dupb' + RUN });
    await d2.sendSignupCode();
    const cv = d2.renderVals();
    ok(/5분 안에 입력해주세요\. 메일이 오지 않으면 한번 재요청을 해주세요\./.test(cv.codeHint) && /남은 시간 [45]:\d\d/.test(cv.codeHint) && cv.codeBtnLabel === '재요청',
       '인증번호: 5분 안내 문구 + 남은 시간 타이머: ' + cv.codeHint.replace(/^.*?5분/, '5분'));
    await d2.sendSignupCode(); await d2.sendSignupCode();
    const cv2 = d2.renderVals();
    ok(!d2.state.authErr && /^재요청 [01]:\d\d$/.test(cv2.codeBtnLabel), '재요청 2번까지는 바로 → 그다음부터 1분 대기 표시: ' + cv2.codeBtnLabel);
    await d2.sendSignupCode();
    ok(/초 뒤에/.test(d2.state.authErr), '1분 안에 4번째 요청 → 막힘: ' + d2.state.authErr);
    d2.state.codeExpAt = Date.now() - 1000;
    ok(d2.renderVals().codeHintColor === '#B8401A' && /시간이 지났어요/.test(d2.renderVals().codeHint), '5분 지나면 만료 안내');
    await d2.submitAuth();
    ok(/5분\)이 지났어요/.test(d2.state.authErr), '만료된 인증번호로는 가입 버튼이 막힘');
    d2.state.codeExpAt = Date.now() + 200000; await d2.submitAuth();
    ok(d2.state.screen === 'main' && d2.me === '김진주', '이름이 완전히 같아도 가입 → 정산 이름은 ‘김진주’: ' + d2.me); }
  const again = makePhone(); await again.boot();
  Object.assign(again.state, { authMode: 'login', email: people[2][1], pw: PW }); await again.submitAuth();
  ok(again.state.userName === '이민재', '다른 기기에서 로그인 → 이름 복원: ' + again.state.userName);

  const need = templateKeys(); const v = jin.renderVals();
  const missing = [...need].filter(k => !(k in v));
  ok(missing.length === 0, '템플릿 {{ }} 바인딩 키가 모두 존재' + (missing.length ? ' — 누락: ' + missing.join(',') : ''));

  for (const p of phones) { await p.connectWallet(); await p.chargePie(); }
  ok(phones.every(p => p.state.wallet && p.state.fund && p.state.fund.balance >= 100000), '지갑 연결 + PIE 충전 (에이전트 chargeToken)');

  // ── Shopping: 배달 메뉴 ──
  jin.startChat('4명 예산 15만원 배달 메뉴 추천'); await waitTyping(jin);
  let b = lastBot(jin);
  ok(!b[0].compare && /예시 가격으로 만들지 않아요/.test(b[0].text) && /1인 37,500원/.test(b[0].text),
     '예시 메뉴표 없음 → 가짜 조합 대신 솔직하게 (예산·1인 계산은 코드): ' + b[0].text.slice(0, 80));
  ok(!jin.renderVals().hasRec, '가짜 추천 카드 없음');
  jin.startChat('4명 예산 20만원 캠핑 장비 추천해줘'); await waitTyping(jin);
  b = lastBot(jin);
  ok(!b[0].compare && /못했|없/.test(b[0].text), '못 찾은 품목은 엉뚱한 상품 대신 솔직하게: ' + b[0].text.slice(0, 60));

  // ── Run 1: 공동구매 → 정산방(친구 선택) → 조건 → 온체인 → 예치 → 에스크로 → 지급 ──
  jin.openCreate('삼겹살 1.2kg 공동구매', null, { total: 38900, subject: '삼겹살 1.2kg' });
  ok(jin.state.sheet === 'create' && jin.state.newTotalInput === '38900' && !jin.state.listingOn, '정산방 만들기 시트 (총 38,900원 자동 입력)');
  await pickFriends(jin, ['진우', '민재', '지현']);
  jin.state.prefillMeta = { ...jin.state.prefillMeta, fromProduct: false };   // Run 1은 '결제자가 먼저 산 비용 정산'(에스크로→결제자 지급) 흐름
  jin.createGroup();
  const gid = jin.state.openGroup; let g = jin.state.groups.find(x => x.id === gid);
  ok(g && g.members.join() === '진주,진우,민재,지현' && g.total === 38900, '정산방 생성 (서버 가입자 중 친구 선택)');
  jin.state.gchatId = gid; jin.state.gchatInput = '진주는 주문하는 사람이니까 5천원 적게 내고 나머지 세 명이 나눠줘.'; jin.sendGchat(); await sleep(500);
  g = jin.state.groups.find(x => x.id === gid);
  ok(g.msgs[0].guide, '새 정산방: Pie mate 안내 카드');
  let cm = g.msgs.find(m => m.kind === 'confirm');
  ok(cm && cm.confirmData.lines.join() .includes('진주 5,975원') && g.shares.every(a => a === 0), '확인 카드 (계산 결과 미리보기 · 아직 반영 안 됨): ' + (cm && cm.confirmData.lines.join(' / ')));
  jin.state.gchatId = gid;
  const gm = jin.renderVals().gcMsgs.find(m => m.isConfirm);
  ok(gm && gm.confirmPending && gm.confirmModeLabel === '차등 분배', '확인 카드 렌더: ' + (gm && gm.confirmModeLabel));
  await jin.confirmSettlement(gid, cm.id); await sleep(300);
  g = jin.state.groups.find(x => x.id === gid);
  ok(g.shares.join() === '5975,10975,10975,10975', '확인 → Stage2 결과 반영: ' + g.shares.join());
  // ── 분담표 승인: 정산 대상 4명 모두 승인해야 온체인 정산 시작 ──
  ok(!g.sid && g.splitApproval && g.splitApproval.targets.length === 4 && g.splitApproval.approved.join() === '진주' && g.status === '승인 대기',
     '확인 → 바로 온체인이 아니라 분담표 승인 요청 (요청한 진주만 승인 1/4)');
  let c1 = card(jin, x => x.id === gid);
  ok(!c1.needMyApproval && c1.approvedStr === '1/4 승인' && /분담표 승인 1\/4/.test(c1.note) && /승인 요청 취소/.test(c1.actionLabel), '진주 카드: 1/4명 승인 · 승인 대기 명단 · 요청 취소 버튼');
  await woo.refreshServer(); woo.setState({ banner: null });
  const wc1 = card(woo, x => x.id === gid);
  ok(wc1 && wc1.needMyApproval && wc1.approveLabel === '분담표 승인하기 · 내 몫 10,975원', '진우 그룹 카드: ‘분담표 승인하기 · 내 몫 10,975원’ 버튼');
  ok(woo.state.notifs.some(n => n.cat === '승인 요청' && n.action && /분담표 승인/.test(n.text)), '진우 알림함: 분담표 승인 요청');
  woo.state.gchatId = gid;
  let sq = woo.renderVals().gcMsgs.find(m => m.isSplitReq);
  ok(sq && sq.splitPending && sq.splitMine === '10,975원' && sq.splitProgress === '1/4명 승인' && sq.splitRows.length === 4, '진우 채팅방: 분담표 승인 카드 (승인하기 / 금액이 이상해요)');
  await sq.onSplitApprove(); await sleep(100);
  woo.state.gchatId = gid; sq = woo.renderVals().gcMsgs.find(m => m.isSplitReq);
  ok(sq.splitWaiting && sq.splitProgress === '2/4명 승인' && !woo.state.groups.find(x => x.id === gid).sid, '진우 승인 → 2/4 · 아직 온체인 전');
  await approveSplitAll(gid);
  g = jin.state.groups.find(x => x.id === gid);
  jin.state.gchatId = gid; const sqDone = jin.renderVals().gcMsgs.find(m => m.isSplitReq);
  ok(g.sid && g.status === '결제 대기' && sqDone.splitDone && /전원 승인/.test(sqDone.splitDoneText), '4명 모두 승인 → 서버가 온체인 정산 요청 sid=' + g.sid);
  ok(g.msgs.some(m => /모두 분담표를 승인/.test(m.text || '')), '승인 기록이 방에 남음');
  c1 = card(woo, x => x.id === gid);
  ok(c1.needMyApproval && c1.approveLabel === '내 몫 10,975원 결제하기', '온체인 시작 후 진우 카드: ‘내 몫 10,975원 결제하기’');
  await payAll([woo, min, hyun], g.sid);
  await jin.refreshServer(); g = jin.state.groups.find(x => x.id === gid);
  ok(g.status === '지급 대기', '전원 예치 → 에스크로 보관 (지급 대기)');
  c1 = card(jin, x => x.id === gid);
  ok(/에스크로/.test(c1.note) && /이의제기/.test(c1.actionLabel), '이의제기 가능 안내: ' + c1.note.slice(0, 50));
  await sleep(3300); await jin.refreshServer(); g = jin.state.groups.find(x => x.id === gid);
  ok(g.status === '정산 완료', '이의제기 기간 종료 → 결제자에게 자동 지급');
  const cert = jin.state.docs.find(d => d.sid === g.sid && d.kind === 'cert');
  const rcpt = jin.state.docs.find(d => d.sid === g.sid && d.kind === 'rcpt');
  ok(cert && cert.badge === '검증 완료' && cert.hash.startsWith('0x'), '정산 인증서 확정 hash=' + (cert && cert.hash.slice(0, 12)));
  ok(!!rcpt, '영수증 문서 생성 (가맹점: ' + (rcpt && rcpt.store) + ')');
  await woo.refreshFund();
  ok(woo.state.fund.spent >= 10975 && woo.state.fund.history.some(h => h.t === '정산 송금' && h.s), `진우 실사용 ${woo.state.fund.spent} · 목적 “${woo.state.fund.history[0].s}”`);

  // ── 정산 캘린더: 실제 날짜(서버 시계 · KST)에 정산이 작게 표시 ──
  jin.renderVals().tabs.find(t => t.label === '정산').go(); await sleep(500);
  const kstToday = new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
  ok(jin.state.cal && jin.state.cal.today === kstToday, `캘린더 오늘 = 서버 실제 날짜(KST): ${jin.state.cal && jin.state.cal.today}`);
  let rvCal = jin.renderVals();
  ok(rvCal.hasCal && rvCal.calTitle === `${+kstToday.slice(0, 4)}년 ${+kstToday.slice(5, 7)}월`, '캘린더가 실제 연·월로 열림: ' + rvCal.calTitle);
  const todayCell = rvCal.calWeeks.flatMap(w => w.days).find(d => String(d.n) === String(+kstToday.slice(8, 10)));
  ok(todayCell && todayCell.dots.length >= 1, '오늘 날짜 칸에 정산 점 표시');
  ok(rvCal.calDayList.some(e => /삼겹살/.test(e.name) && e.pillLabel === '완료' && e.mineStr === '5,975원'), '오늘 목록: 삼겹살 정산 · 완료 · 내 몫 5,975원');
  const calT0 = rvCal.calTitle; rvCal.calPrev();
  rvCal = jin.renderVals();
  ok(rvCal.calTitle !== calT0 && rvCal.calNotThisMonth && rvCal.calWeeks.flatMap(w => w.days).every(d => !d.dots.length), '이전 달로 이동 (기록 없음 · ‘오늘’ 버튼 표시)');
  rvCal.calGoToday();
  ok(jin.renderVals().calTitle === calT0, '‘오늘’ 버튼 → 이번 달·오늘로 복귀');
  jin.setState({ tab: 'home' });

  // ── Run 2: 조건 변경 (1인 한도) → 지출 통제 중단 ──
  jin.openCreate('목살 공동구매'); await pickFriends(jin, ['진우', '민재', '지현']);
  jin.state.newTotalInput = '39900'; jin.createGroup();
  const gid2 = jin.state.openGroup;
  jin.state.gchatId = gid2; jin.state.gchatInput = '1인 9천원 넘으면 안 돼. 똑같이 나눠줘'; jin.sendGchat(); await sleep(500);
  let cm2 = jin.state.groups.find(x => x.id === gid2).msgs.find(m => m.kind === 'confirm');
  ok(cm2 && cm2.confirmData.lines.some(l => /⚠️/.test(l) && /중단/.test(l)), '확인 카드에 사전 경고: ' + (cm2 && cm2.confirmData.lines.at(-1)));
  await jin.confirmSettlement(gid2, cm2.id); await sleep(300); await approveSplitAll(gid2); let g2 = jin.state.groups.find(x => x.id === gid2);
  ok(g2.status === '중단됨' && g2.srv.blocked.tx_hash, '지출 통제 중단 + 체인 기록 tx=' + (g2.srv.blocked.tx_hash || '').slice(0, 12));

  // ── Run 3: 비율 분배 → 예치 → 이의제기(취소) → GENUINE_ERROR → 전원 환불 ──
  jin.openCreate('딸기 공동구매'); await pickFriends(jin, ['진우', '민재', '지현']);
  jin.state.newTotalInput = '40000'; jin.createGroup();
  const gid3 = jin.state.openGroup;
  jin.state.gchatId = gid3; jin.state.gchatInput = '진주 40%, 진우 20%, 민재 20%, 지현 20%로 나눠줘'; jin.sendGchat(); await sleep(500);
  const cm3 = jin.state.groups.find(x => x.id === gid3).msgs.find(m => m.kind === 'confirm');
  ok(cm3 && cm3.confirmData.modeLabel === '비율 분배', '비율 조건 → 확인 카드: ' + (cm3 ? cm3.confirmData.lines.join(' / ') : jin.state.groups.find(x => x.id === gid3).msgs.at(-1).text));
  await jin.confirmSettlement(gid3, cm3.id); await sleep(300); await approveSplitAll(gid3);
  let g3 = jin.state.groups.find(x => x.id === gid3);
  ok(g3.shares.join() === '16000,8000,8000,8000' && g3.sid, '비율 분배 (코드 계산) + 확인 시 온체인 등록: ' + g3.shares.join());
  const before = (await (await fetch(`${BASE}/api/wallet/${min.state.wallet}`)).json()).data.balance;
  await payAll([woo, min, hyun], g3.sid);
  await min.refreshServer();
  const mc = card(min, x => x.sid === g3.sid);
  ok(/이의제기/.test(mc.actionLabel), '민재 화면: ' + mc.actionLabel);
  mc.remind(); await sleep(150); await waitTyping(min);
  ok(/어떤 문제/.test(lastBot(min).at(-1).text), 'Dispute Agent가 사유를 되물음');
  min.state.chatInput = '딸기 공동구매가 품절로 취소됐어요. 환불해 주세요'; min.sendChat(); await waitTyping(min);
  const dmsg = lastBot(min).at(-1).text;
  ok(/GENUINE_ERROR/.test(dmsg) && /환불/.test(dmsg), '판정: ' + dmsg.split('\n')[0]);
  const after = (await (await fetch(`${BASE}/api/wallet/${min.state.wallet}`)).json()).data.balance;
  ok(after === before, `민재 잔액 원상복구 (${before} → 예치 → ${after})`);
  await jin.refreshServer(); g3 = jin.state.groups.find(x => x.id === gid3);
  ok(g3.status === '환불 완료', '정산 상태: 환불 완료');

  // ── Run 4: 항목별 분배 → 예치 → "승인 안 했다" 이의제기 → BAD_FAITH_DISPUTE ──
  jin.openCreate('MT 장보기'); await pickFriends(jin, ['진우', '민재']);
  jin.state.newTotalInput = '36000'; jin.createGroup(); const gid4 = jin.state.openGroup;
  jin.state.gchatId = gid4; jin.state.gchatInput = '셋이 똑같이 나눠줘'; jin.sendGchat(); await sleep(500);
  const cm4 = jin.state.groups.find(x => x.id === gid4).msgs.find(m => m.kind === 'confirm');
  await jin.confirmSettlement(gid4, cm4.id); await sleep(300);
  await min.refreshServer(); min.state.gchatId = gid4;
  const msq = min.renderVals().gcMsgs.find(m => m.isSplitReq);
  msq.onSplitReject(); await min.state.confirm.fn(); min.setState({ confirm: null });
  await jin.refreshServer(); let g4r = jin.state.groups.find(x => x.id === gid4); jin.state.gchatId = gid4;
  const jsq = jin.renderVals().gcMsgs.find(m => m.isSplitReq);
  ok(!g4r.splitApproval && !g4r.sid && jsq.splitDone && /민재님이 동의하지 않아/.test(jsq.splitDoneText) && jin.state.notifs.some(n => /동의하지 않았어요/.test(n.text)),
     '민재 ‘금액이 이상해요’ → 승인 요청 취소 · 진주에게 알림: ' + jsq.splitDoneText);
  ok(card(jin, x => x.id === gid4).status === '비용 입력 대기', '거절되면 정산 상태가 다시 조건 입력 대기로');
  jin.state.gchatId = gid4; jin.state.gchatInput = '셋이 똑같이 나눠줘'; jin.sendGchat(); await sleep(500);
  const cm4b = jin.state.groups.find(x => x.id === gid4).msgs.filter(m => m.kind === 'confirm' && !m.resolved).at(-1);
  await jin.confirmSettlement(gid4, cm4b.id); await sleep(300); await approveSplitAll(gid4);
  let g4 = jin.state.groups.find(x => x.id === gid4);
  ok(g4.shares.join() === '12000,12000,12000' && g4.sid, '확인 카드 → 균등 분배 (코드 계산): ' + g4.shares.join());
  await card(jin, x => x.id === gid4).remind(); g4 = jin.state.groups.find(x => x.id === gid4);
  await payAll([woo, min], g4.sid);
  await woo.refreshServer(); card(woo, x => x.sid === g4.sid).remind(); await sleep(150); await waitTyping(woo);
  woo.state.chatInput = '저는 이 정산 승인한 적 없어요'; woo.sendChat(); await waitTyping(woo);
  const d4 = lastBot(woo).at(-1).text;
  ok(/BAD_FAITH_DISPUTE/.test(d4), '판정: ' + d4.split('\n')[0]);
  await jin.refreshServer();
  ok(jin.state.groups.find(x => x.id === gid4).status === '정산 완료', '기각 → 결제자에게 지급');

  // ── Shopping(인터넷 여러 사이트): WEB_TEST=1 일 때 (tests/fake_web.py 필요) ──
  if (process.env.WEB_TEST) {
    {   // GPS 자동 위치: 권한 허용 → 좌표 → 서버 역지오코딩 → 동네 저장 · 이동하면 자동 변경
      let cb = null; const geo = { watchPosition(ok) { cb = ok; ok({ coords: { latitude: 37.5446, longitude: 127.0557, accuracy: 25 } }); return 7; },
        clearWatch() { cb = null; }, getCurrentPosition(ok) { ok({ coords: { latitude: 37.5446, longitude: 127.0557, accuracy: 10 } }); } };
      const g = makePhone({ geo }); await g.boot();
      Object.assign(g.state, { authMode: 'login', email: people[1][1], pw: PW }); await g.submitAuth(); await sleep(400);
      ok(g.state.confirm && /GPS/.test(g.state.confirm.title), '로그인 후 GPS 자동 설정 여부를 한 번 물어봄');
      g.state.confirm.fn(); g.setState({ confirm: null }); await sleep(400);
      ok(g.state.geoOn && g.state.userAddress === '서울 성동구 성수동', 'GPS 좌표 → 동네 자동 설정: ' + g.state.userAddress + ' · ' + g.state.geoStatus);
      g._geoLast.t -= 31000; cb({ coords: { latitude: 37.5006, longitude: 127.0364, accuracy: 30 } }); await sleep(1600);   // OpenStreetMap 초당 1회 제한 대기
      ok(g.state.userAddress === '서울 강남구 역삼동' && g.toasts.some(t => /역삼동/.test(t)), '이동하면 자동으로 동네 변경: ' + g.state.userAddress);
      g.toggleGeo(); ok(!g.state.geoOn, '자동 추적 끄기');
    }
    jin.startChat('한정선 공동구매 20만원'); await waitTyping(jin);
    b = lastBot(jin);
    ok(b[0].compare && b[0].compare.length >= 3, `여러 사이트 후보 ${b[0].compare && b[0].compare.length}개`);
    const versions = b[0].compareData.map(c => c.version);
    ok(new Set(versions).size >= 3, '성격이 다른 버전: ' + versions.join(' / '));
    const ci = jin.renderVals().chatMsgs.find(m => m.hasCompare && m.compareItems[0].col2Label === '판매처').compareItems;
    ok(ci.every(c => c.deadline), '카드에 판매처 표시: ' + ci.map(c => c.deadline).join(', '));
    jin.openProduct(b[0].compare[0]); const spv = jin.renderVals().sp;
    ok(spv.hasUrl && /정산방/.test(spv.cta), '상품 시트: 판매 링크 + “' + spv.cta + '”');
    await jin.joinProduct();
    ok(jin.state.sheet === 'create' && Number(jin.state.newTotalInput) > 0, '예산 구매분으로 정산방 시트: ' + jin.state.newTotalInput + '원');
    await pickFriends(jin, ['진우', '민재']); jin.createGroup(); const gw = jin.state.openGroup;
    ok(/채팅에 나누는 방법/.test(card(jin, x => x.id === gw).note), '분담 전 안내 문구');
    await splitByChat(jin, gw, '똑같이 나눠줘'); const gwg = jin.state.groups.find(x => x.id === gw);
    ok(gwg.sid && /구매 승인 0\/3/.test(gwg.status) && gwg.srv.purchase && /^SP-\d{4}-\d{4}-\d{4}$/.test(gwg.srv.purchase.va),
       `외부 쇼핑몰(${gwg.srv && gwg.srv.purchase && gwg.srv.purchase.merchant}) 상품 → AI 구매 대행 등록 · 가상계좌 ${gwg.srv && gwg.srv.purchase && gwg.srv.purchase.va} · ${gwg.status}`);
    {   // AI 구매 대행: 각자 인출 승인 → 전원 승인 즉시 AI가 인출·가맹점 결제
      const before = {}; for (const p of [jin, woo, min]) before[p.me] = (await (await fetch(`${BASE}/api/wallet/${p.state.wallet}`)).json()).data.balance;
      await jin.refreshServer(); await card(jin, x => x.sid === gwg.sid).remind();
      const mid = (await (await fetch(`${BASE}/api/wallet/${jin.state.wallet}`)).json()).data.balance;
      ok(mid === before[jin.me], '인출 승인만으로는 돈이 빠져나가지 않음 (전원 승인 전)');
      await payAll([woo, min], gwg.sid);
      await jin.refreshServer(); const done = jin.state.groups.find(x => x.sid === gwg.sid);
      ok(done.status === '구매 완료' && done.srv.purchase.orderNo, `전원 승인 → AI 자동 인출·결제: ${done.status} · 주문번호 ${done.srv.purchase.orderNo}`);
      const after = {}; for (const p of [jin, woo, min]) after[p.me] = (await (await fetch(`${BASE}/api/wallet/${p.state.wallet}`)).json()).data.balance;
      const ok3 = [jin, woo, min].every((p, i) => before[p.me] - after[p.me] === done.shares[done.members.indexOf(p.me)]);
      ok(ok3, '각자 지갑에서 정확히 자기 몫만 인출: ' + [jin, woo, min].map(p => `${p.me} -${before[p.me] - after[p.me]}`).join(', '));
      ok(jin.state.docs.some(d => d.kind === 'rcpt' && /AI 구매 대행/.test(d.method)), '구매 영수증 (가상계좌·주문번호)');
      ok(done.msgs.some(m => /가상계좌/.test(m.text || '') && /주문번호/.test(m.text || '')), '그룹방에 AI 결제 완료 메시지');
    }
    jin.startChat('한정선 쿠팡에서만 10만원'); await waitTyping(jin);
    b = lastBot(jin);
    ok(/허용 판매처/.test(b[1].text), '“쿠팡에서만” 조건 → 다른 판매처 경고');
    const outside = (b[0].compareData.find(c => c.trusted === false) || b[0].compareData[0]).id;  // 쿠팡이 아닌 후보를 일부러 선택
    jin.openProduct(outside); await jin.joinProduct(); await pickFriends(jin, ['진우']); jin.createGroup();
    const gc = jin.state.openGroup; await splitByChat(jin, gc, '둘이 똑같이 나눠줘');
    const gcg = jin.state.groups.find(x => x.id === gc);
    ok(gcg.status === '중단됨' && /허용/.test(gcg.srv.blocked.message), '허용 판매처 밖 → 지출 통제 중단: ' + gcg.srv.blocked.message);
  }

  jin.openCreate('수수료방'); await pickFriends(jin, ['진우']); jin.createGroup();
  const bad = jin.state.openGroup; await sleep(300);
  jin.state.gchatId = bad; jin.state.gchatInput = '우리가 검은돈으로 100억 벌었는데 세탁 수수료 15%를 둘이 나눠 정산하자'; jin.sendGchat(); await sleep(500);
  ok(jin.state.groups.find(g => g.id === bad).msgs.some(m => m.from === 'sys' && /불법 자금/.test(m.text||'')), '불법 목적(자금세탁) 정산은 지출 통제로 거절');
  ok(!jin.state.groups.find(g => g.id === bad).msgs.some(m => m.kind === 'confirm'), '거절된 요청은 확인 카드도 만들지 않음');
  // ── 동네 공동구매: GPS 근처 사람이 만든 모집글만 보이고, 참여하면 그 채팅방으로 ──
  const here = (p, lat, lng) => { p._geoLast = lat == null ? null : { lat, lng, t: Date.now() }; };
  here(jin, 37.5445, 127.0560); here(woo, 37.5470, 127.0590); here(min, 37.5430, 127.0540); here(hyun, 35.1587, 129.1604);
  jin.openListingCreate();
  ok(jin.state.sheet === 'create' && jin.state.listingOn && jin.renderVals().canListing, '모집 시트: 근처 이웃 모집 켜짐');
  Object.assign(jin.state, { newGroupName: '대패삼겹살 2kg 같이 사요', newTotalInput: '39000', listingCap: 3, newMembers: [] });
  jin.createGroup(); const lg = jin.state.openGroup; await sleep(1300);
  ok(jin.toasts.some(t => /모집글을 올렸어요/.test(t)), '친구 없이도 동네 모집 그룹 생성 + 모집글 게시');
  woo.state.tab = 'buy'; await woo.loadHome(); let wl = woo.renderVals().nearList;
  let item = wl.find(x => x.gid === lg);
  ok(!!item && /400m/.test(item.distShort) && /진주님 모집/.test(item.where) && item.recruit.startsWith('1/3명') && /1인 약 13,000원/.test(item.recruit),
     `약 400m 떨어진 진우 화면에 뜸: ${item && item.distShort} · ${item && item.where} · ${item && item.recruit}`);
  ok(!JSON.stringify(woo.state.near).includes('37.54'), '다른 사람에게 모집 좌표는 보내지 않음 (거리·동 이름만)');
  await hyun.loadHome();
  ok(!hyun.state.near.items.some(x => x.id === lg), '부산(약 325km)에 있는 지현 화면에는 안 뜸');
  woo.state.nearRadius = 1; await woo.loadHome();
  ok(woo.state.near.items.some(x => x.id === lg) && woo.state.near.radiusKm === 1, '반경 1km로 줄여도 400m라 보임');
  here(woo, 37.5445 + 0.02, 127.0560); await woo.loadHome();
  ok(!woo.state.near.items.some(x => x.id === lg), '2km 멀어지면 반경 1km 목록에서 빠짐');
  here(woo, 37.5470, 127.0590); woo.state.nearRadius = 3; await woo.loadHome();
  woo.openProduct('gb_' + lg); ok(/참여하고 채팅방/.test(woo.renderVals().sp.cta), '모집글 상세: 참여 버튼');
  await woo.joinProduct(); await sleep(200);
  let wg2 = woo.state.groups.find(g => g.id === lg);
  ok(wg2 && wg2.members.join() === '진주,진우' && woo.state.overlay === 'gchat', '참여 → 진우가 모집 채팅방 멤버로 들어감');
  await jin.refreshServer(); let jg = jin.state.groups.find(g => g.id === lg);
  ok(jg.members.join() === '진주,진우' && jg.msgs.some(m => /진우님이 동네 공동구매에 참여/.test(m.text || '')), '진주 폰: 멤버 추가 + 참여 알림 메시지');
  const far = await hyun.joinListing({ gid: lg }).then(() => hyun.toasts.at(-1));
  ok(/km 떨어져/.test(far || ''), '멀리 있는 사람은 id를 알아도 참여 불가: ' + far);
  await min.loadHome(); min.openProduct('gb_' + lg); await min.joinProduct(); await sleep(200);
  await woo.loadHome(); item = woo.state.near.items.find(x => x.id === lg);
  ok(item && item.status === 'full' && item.joined === 3, '3명 모이면 모집 마감 (참여자에게는 계속 보임)');
  here(hyun, 37.5446, 127.0561); await hyun.loadHome();
  ok(!hyun.state.near.items.some(x => x.id === lg), '마감된 모집은 새 사람에게 안 보임');
  jin.state.gchatId = lg; jin.state.gchatInput = '똑같이 나눠줘'; await jin.sendGchat(); await sleep(300);
  jg = jin.state.groups.find(g => g.id === lg); const lcm = jg.msgs.find(m => m.kind === 'confirm');
  ok(lcm && lcm.confirmData.lines.join().includes('13,000원'), '모인 3명이 Pie로 나누기: ' + (lcm && lcm.confirmData.lines.join(' / ')));
  for (const p of [jin, woo, min]) await p.chargePie();   // 앞 시나리오에서 쓴 PIE 보충 (잔액 부족이면 지출 통제로 중단돼 모집이 계속 열려 있음)
  await jin.confirmSettlement(lg, lcm.id); await sleep(300); await approveSplitAll(lg);
  await woo.loadHome();
  jg = jin.state.groups.find(g => g.id === lg);
  ok(jg.sid && !woo.state.near.items.some(x => x.id === lg), `정산이 시작되면 모집글 자동 마감 (정산 상태: ${jg.status})`);

  // ── 회원 기능 · 공유 그룹방 · 대화 기록 ──
  const noAuth = await (await fetch(`${BASE}/api/settlements?member=진주`)).json();
  ok(!noAuth.ok && noAuth.error.code === 'UNAUTHORIZED', '로그인 없이 정산 조회 차단 (토큰 필요)');
  jin.openCreate('공유 테스트방'); await pickFriends(jin, ['진우']); jin.state.newTotalInput = '20000'; jin.createGroup();
  const shared = jin.state.openGroup; await sleep(300);
  const sys0 = jin.state.groups.find(g => g.id === shared).msgs.filter(m => m.from === 'sys').length;
  jin.state.gchatId = shared; jin.state.gchatInput = '안녕 진우야'; jin.sendGchat(); await sleep(300);
  ok(jin.state.groups.find(g => g.id === shared).msgs.filter(m => m.from === 'sys').length === sys0, '잡담(안녕 진우야)에는 Pie가 끼어들지 않음');
  jin.state.gchatId = shared; jin.state.gchatInput = '파메야 뭐해?'; jin.sendGchat(); await sleep(500);
  const pieHi = jin.state.groups.find(g => g.id === shared).msgs.find(m => m.pie);
  ok(!!pieHi && /진주/.test(pieHi.text), '이름(파메)을 부르면 Pie mate가 부른 사람에게 답함: ' + (pieHi||{}).text);
  await woo.refreshServer();
  woo.state.gchatId = shared; woo.state.gchatInput = '애플파이 맛있겠다 ㅋㅋ'; woo.sendGchat(); await sleep(400);
  ok(woo.state.groups.find(g => g.id === shared).msgs.filter(m => m.pie).length === 1, '‘애플파이’ 잡담은 이름 부름이 아님 → 무시');
  await woo.refreshServer();
  const wg = woo.state.groups.find(g => g.id === shared);
  ok(wg && wg.msgs.some(m => m.text === '안녕 진우야' && m.from === '진주'), '그룹 채팅: 진주가 만든 방과 메시지가 진우 폰에도 보임');
  ok(wg && wg.msgs.some(m => m.pie && m.replyTo), '진우 폰에도 Pie mate 답이 실시간으로 보임');
  woo.state.gchatId = shared; woo.state.gchatInput = '둘이 똑같이 나눠줘'; woo.sendGchat(); await sleep(600);
  await jin.refreshServer();
  const jcard = jin.state.groups.find(g => g.id === shared).msgs.find(m => m.kind === 'confirm');
  ok(!!jcard && jin.state.groups.find(g => g.id === shared).msgs.some(m => m.text === '둘이 똑같이 나눠줘'), '진우가 보낸 조건과 Pie 확인 카드가 진주 폰에도 보임');
  const wcard = woo.state.groups.find(g => g.id === shared).msgs.find(m => m.kind === 'confirm');
  await woo.confirmSettlement(shared, wcard.id); await sleep(300);
  await jin.confirmSettlement(shared, jcard.id);
  ok(jin.toasts.some(t => /이미 처리한/.test(t)), '같은 확인 카드를 두 사람이 누르면 한 번만 처리');
  await approveSplitAll(shared);
  await jin.refreshServer(); await woo.refreshServer();
  ok(woo.state.groups.find(g => g.id === shared).sid && woo.state.groups.find(g => g.id === shared).sid === jin.state.groups.find(g => g.id === shared).sid,
     '확정된 정산이 두 폰에서 같은 온체인 정산으로 연결');
  const other = makePhone(); await other.boot();
  Object.assign(other.state, { authMode: 'login', email: people[0][1], pw: PW }); await other.submitAuth(); await sleep(300);
  ok(other.state.chats.length > 0 && other.state.groups.some(g => g.id === shared), `다른 기기 로그인 → Pie 대화 ${other.state.chats.length}개·그룹방 복원`);
  other.openAccount('pw'); Object.assign(other.state, { acc1: PW, acc2: 'xyz98765', acc3: 'xyz98765' }); await other.submitAccount();
  ok(other.toasts.some(t => /비밀번호를 바꿨어요/.test(t)), '비밀번호 변경');
  other.openAccount('pw'); Object.assign(other.state, { acc1: 'xyz98765', acc2: PW, acc3: PW }); await other.submitAccount();
  const f = makePhone(); await f.boot(); f.setAuthMode('find'); f.state.findName = '진주'; await f.submitFindId();
  ok(/@test\.com/.test(f.state.findResult) && /\*/.test(f.state.findResult), '아이디 찾기 (가린 이메일): ' + f.state.findResult);
  f.setAuthMode('reset'); f.state.email = people[3][1]; await f.sendResetCode();
  Object.assign(f.state, { pw: PW }); await f.submitReset();
  ok(f.state.authMode === 'login' && f.toasts.some(t => /비밀번호를 바꿨어요/.test(t)), '비밀번호 재설정 (메일 인증번호)');
  await hyun.refreshServer();
  ok(hyun.state.screen !== 'main' || hyun.toasts.some(t => /만료/.test(t)), '재설정하면 기존 기기 로그인 해제');
  Object.assign(hyun.state, { authMode: 'login', email: people[3][1], pw: PW }); await hyun.submitAuth();
  const w = makePhone(); await w.boot();
  const wm = `bye.${RUN}@test.com`; Object.assign(w.state, { authMode: 'signup', name: '탈퇴' + RUN, email: wm, pw: PW, signupId: 'bye' + RUN }); await w.sendSignupCode(); await w.submitAuth();
  w.openAccount('withdraw'); w.state.acc1 = PW; await w.submitAccount();
  ok(w.state.screen === 'auth' && w.toasts.some(t => /탈퇴/.test(t)), '회원 탈퇴 → 로그아웃');

  // ── 로그인 화면 이메일 자동 채우기 (서버가 기기별로 기억) · 소셜 버튼 ──
  const r1 = makePhone(); await r1.boot();
  const rm = `remember.${RUN}@test.com`;
  Object.assign(r1.state, { authMode: 'signup', name: '기억' + RUN, email: rm, pw: PW, signupId: 'remem' + RUN }); await r1.sendSignupCode(); await r1.submitAuth();
  ok(r1.state.screen === 'main', '이메일 가입');
  r1.signOut('');
  const r2 = makePhone({ store: r1._store }); await r2.boot(); await sleep(200);
  ok(r2.state.email === rm, '같은 기기에서 앱을 다시 열면 가입한 이메일이 로그인 칸에 채워짐: ' + r2.state.email);
  const r3 = makePhone(); await r3.boot(); await sleep(200);
  ok(!r3.state.email, '다른 기기에는 채워지지 않음');
  const rv = r2.renderVals();
  ok(rv.showSocial && rv.socialProviders.length === 4 && rv.socialProviders.map(x => x.name).join() === '카카오톡,네이버,구글,애플', '소셜 버튼 4개 (카카오·네이버·구글·애플)');
  rv.socialProviders[2].go();
  ok(r2.toasts.some(t => /Google 로그인은 아직 준비 중/.test(t)), '키 없는 회사 버튼 → 준비 중 안내 (가짜 로그인 안 함)');
  r2._loc.hash = '#sp_social_error=' + encodeURIComponent('카카오 로그인이 취소됐어요.'); await r2.handleSocialReturn();
  ok(r2.state.authErr === '카카오 로그인이 취소됐어요.', '소셜 로그인 취소 → 로그인 화면에 이유 표시');

  // ── 그룹 초대 · 안 읽은 메시지 · 배너 · 알림 끔 · 방 이름 · 방 초대 · 승인 요청 카드 · 나가기 · 환불 요청 ──
  for (const p of [jin, woo, min]) { await p.chargePie(); await p.refreshServer(); }
  jin.openCreate('주말 캠핑'); await pickFriends(jin, ['진우', '민재']); jin.createGroup();
  const cg = jin.state.openGroup; await sleep(400);
  await woo.refreshServer(); await min.refreshServer();
  const inv = woo.renderVals().notifList.find(n => n.req && n.req.type === 'invite' && n.req.key === cg);
  ok(inv && inv.hasActions && inv.acceptLabel === '참여' && /주말 캠핑/.test(inv.text), '그룹 초대 알림 (참여/거절 버튼)');
  await inv.onAccept(); await jin.refreshServer();
  ok(woo.state.overlay === 'gchat' && jin.state.groups.find(g => g.id === cg).msgs.some(m => /진우님이 들어왔어요/.test(m.text || '')), '초대 참여 → 방으로 이동 + ‘들어왔어요’');
  await min.renderVals().notifList.find(n => n.req && n.req.key === cg).onDecline(); await jin.refreshServer();
  ok(!min.state.groups.some(g => g.id === cg) && jin.state.groups.find(g => g.id === cg).members.join() === '진주,진우', '초대 거절 → 방에서 빠짐');
  woo.setState({ overlay: null, gchatId: null, banner: null });
  const badge = p => Number(p.renderVals().tabs.find(t => t.label === '그룹').badge || 0);
  const b0 = badge(woo);
  jin.state.gchatId = cg; jin.state.gchatInput = '내일 몇 시에 모여?'; await jin.sendGchat(); await sleep(200);
  await woo.refreshServer();
  let wg3 = woo.state.groups.find(g => g.id === cg), wl3 = woo.renderVals().groupList.find(g => g.id === cg);
  ok(wg3.unread === 1 && wl3.hasNew && wl3.newStr === '1' && /안 읽은 메시지 1개/.test(wl3.chatAria) && woo.state.banner && /내일 몇 시에/.test(woo.state.banner.text)
     && badge(woo) === b0 + 1, `새 메시지: 카드 채팅 아이콘 배지 1 · 배너 · 그룹 탭 배지 (unread=${wg3.unread}, banner=${JSON.stringify(woo.state.banner)}, badge=${woo.renderVals().tabs.find(t => t.label === '그룹').badge})`);
  woo.openGroupChat(cg); await sleep(200); await woo.refreshServer();
  ok(woo.state.groups.find(g => g.id === cg).unread === 0, '방을 열면 읽음 처리 (서버에도 저장)');
  woo.setState({ overlay: null, gchatId: null, banner: null });
  await woo.toggleRoomMute(cg); const b1 = badge(woo);
  jin.state.gchatInput = '텐트는 내가 챙길게'; await jin.sendGchat(); await sleep(200); await woo.refreshServer();
  ok(woo.renderVals().groupList.find(g => g.id === cg).isMuted && !woo.state.banner && badge(woo) === b1 && woo.state.groups.find(g => g.id === cg).unread === 1,
     '알림 끈 방: 배너·탭 배지 없음 (목록 안 읽음 수만) ' + JSON.stringify(woo.state.banner) + ' ' + woo.renderVals().tabs.find(t => t.label === '그룹').badge);
  await woo.toggleRoomMute(cg);
  jin.openRoomRename(); jin.state.roomNameDraft = '캠핑 1박 2일'; await jin.saveRoomName(); await woo.refreshServer();
  ok(woo.state.groups.find(g => g.id === cg).name === '캠핑 1박 2일', '방 이름 변경 → 다른 멤버 폰에도 반영');
  jin.openRoomInvite(); jin.toggleRoomInvite(min.state.userId); await jin.confirmRoomInvite(); await min.refreshServer();
  ok(min.state.groups.some(g => g.id === cg) && min.state.notifs.some(n => n.req && n.req.key === cg && n.req.status === 'pending'), '방 설정 → 친구 초대 (초대 알림 도착)');
  await min.acceptInvite(cg); await jin.refreshServer();
  jin.state.gchatId = cg; jin.state.gchatInput = '총 6만원 똑같이 나눠줘'; await jin.sendGchat(); await sleep(300);
  const ccard = jin.state.groups.find(g => g.id === cg).msgs.find(m => m.kind === 'confirm' && !m.resolved);
  await jin.confirmSettlement(cg, ccard.id); await sleep(300); await approveSplitAll(cg);
  await woo.refreshServer(); woo.setState({ banner: null });
  woo.state.gchatId = cg;
  const rq = woo.renderVals().gcMsgs.find(m => m.isApproveReq);
  ok(rq && rq.reqPending && rq.reqMine === '20,000원' && /진주님이 정산 결제를 요청/.test(rq.reqBy) && rq.reqBtn === '결제하기', '방에 ‘결제 요청’ 카드 (내 몫 20,000원)');
  ok(woo.state.notifs.some(n => n.cat === '결제 요청' && n.action && /내 몫 20,000원/.test(n.text)), '알림함: 결제 요청 (주황 강조)');
  const wcard2 = woo.renderVals().groupList.find(g => g.id === cg);
  ok(wcard2.needMyApproval && /20,000원 결제하기/.test(wcard2.approveLabel), '그룹 카드: ‘내 몫 20,000원 결제하기’ 버튼');
  woo.leaveGroup(cg); await woo.state.confirm.fn(); await sleep(100);
  ok(woo.state.groups.some(g => g.id === cg) && woo.state.confirm && /정산이 진행 중/.test(woo.state.confirm.body || ''), '정산 진행 중에는 방을 나갈 수 없음');
  woo.setState({ confirm: null });
  await wcard2.approveMine(); await min.refreshServer(); await min.approveMine(cg); await sleep(200);
  await woo.refreshServer(); woo.state.gchatId = cg;
  const rq2 = woo.renderVals().gcMsgs.find(m => m.isApproveReq);
  ok(rq2 && rq2.reqDone && rq2.reqDoneText === '결제 완료', '결제하면 카드가 ‘결제 완료’로 바뀜');
  await woo.refreshFund();
  const rf = woo.renderVals().payList.find(h => h.canRefund && h.sid === woo.state.groups.find(g => g.id === cg).sid);
  ok(!!rf, 'MY 결제 내역: 지급 전(에스크로) 결제에 ‘환불 요청’ 버튼');
  rf.onRefund(); woo.state.refundReason = '금액 착오'; await woo.confirmRefund();
  ok(woo.state.confirm && /환불/.test(woo.state.confirm.title) && /판정/.test(woo.state.confirm.body || ''), '환불 요청 → AI 이의제기 판정 결과: ' + (woo.state.confirm && woo.state.confirm.title));
  woo.setState({ confirm: null });
  await jin.refreshServer();
  ok(jin.state.groups.find(g => g.id === cg).msgs.some(m => /환불을 요청했어요/.test(m.text || '')), '방 멤버에게도 환불 요청 기록 공유');

  // ── 지갑 안 연결한 멤버가 있을 때: 확인 후 보관 → 지갑 연결·충전하면 서버가 자동으로 정산 시작 ──
  const nw = makePhone(); await nw.boot();
  Object.assign(nw.state, { authMode: 'signup', name: '오새봄', email: `nowallet.${RUN}@test.com`, pw: PW, signupId: 'saebom' + RUN });
  await nw.sendSignupCode(); await nw.submitAuth();
  await befriend(jin, [nw]); ALL.push(nw);
  jin.openCreate('회식비'); await pickFriends(jin, ['새봄']); jin.createGroup(); const hg = jin.state.openGroup; await sleep(300);
  jin.state.gchatId = hg; jin.state.gchatInput = '총 39000원 똑같이 나눠줘'; await jin.sendGchat(); await sleep(300);
  const hc = jin.state.groups.find(g => g.id === hg).msgs.find(m => m.kind === 'confirm');
  await jin.confirmSettlement(hg, hc.id); await sleep(300); await approveSplitAll(hg); await jin.refreshServer();
  let hgj = jin.state.groups.find(g => g.id === hg); jin.state.gchatId = hg;
  const hcv = jin.renderVals().gcMsgs.find(m => m.isConfirm);
  ok(!hgj.sid && hgj.pendingPropose && /새봄 지갑 연결/.test(hcv.confirmStatusText) && hgj.msgs.some(m => /정산 준비 중/.test(m.text || '')),
     '지갑 미연결 멤버 → ‘시작했어요’가 아니라 준비 대기 표시: ' + hcv.confirmStatusText);
  ok(/지갑 연결 필요/.test(jin.renderVals().groupList.find(g => g.id === hg).note || ''), '그룹 카드에도 무엇이 남았는지 표시');
  await nw.refreshServer();
  ok(nw.state.notifs.some(n => /지갑 연결이 필요/.test(n.text)), '준비 안 된 사람에게 알림');
  await nw.connectWallet(); await jin.refreshServer(); hgj = jin.state.groups.find(g => g.id === hg);
  ok(!hgj.sid && hgj.pendingPropose && (hgj.pendingPropose.short || []).includes('새봄'), '지갑만 연결(잔액 0) → 이번엔 PIE 충전 대기');
  await nw.chargePie(); await sleep(200); await jin.refreshServer(); hgj = jin.state.groups.find(g => g.id === hg);
  ok(hgj.sid && !hgj.pendingPropose && hgj.msgs.some(m => /자동으로 온체인 정산을 시작/.test(m.text || '')), '충전하는 순간 서버가 자동으로 정산 시작 (다시 누를 필요 없음)');
  await nw.refreshServer();
  ok(/결제하기/.test(nw.renderVals().groupList.find(g => g.id === hg).approveLabel), '새봄 화면: ‘내 몫 결제하기’ 버튼');

  // ── 방 나가기 (정산 끝난 방) · AI 전용 페이 화면 ──
  await jin.refreshServer();
  const gl = jin.renderVals().groupList, g4c = gl.find(g => g.id === gid4), hgc = gl.find(g => g.id === hg);
  ok(g4c && g4c.status === '정산 완료' && typeof g4c.leave === 'function' && typeof hgc.leave === 'function', '나가기 아이콘은 모든 방 카드에 표시 (fixed31 v2)');
  const firstDone = gl.findIndex(g => g.status === '정산 완료');
  ok(firstDone >= 0 && gl.slice(firstDone).every(g => g.status === '정산 완료'), '정산 끝난 방은 목록 맨 아래로');
  hgc.leave(); ok(/나가시겠습니까/.test(jin.state.confirm.title), '나가기 = 항상 확인창 먼저: ' + jin.state.confirm.title);
  await jin.state.confirm.fn(); await sleep(100);
  ok(jin.state.confirm && /나갈 수 없어요/.test(jin.state.confirm.title) && jin.state.confirm.alert && jin.state.groups.some(g => g.id === hg),
     '진행 중인 방은 확인 후 차단 (취소 없는 알림창)');
  jin.setState({ confirm: null });
  g4c.leave(); await jin.state.confirm.fn(); await sleep(150); await jin.refreshServer();
  ok(!jin.state.groups.some(g => g.id === gid4) && jin.toasts.some(t => /채팅방에서 나왔어요/.test(t)), '정산 끝난 방은 나가짐');
  await woo.refreshServer(); const w4 = woo.state.groups.find(g => g.id === gid4);
  ok(w4 && w4.msgs.some(m => /방에서 나갔어요/.test(m.text || '')), '남은 멤버 방에 ‘나갔어요’ 안내');
  jin.state.tab = 'my'; await jin.loadUsage(); const mv = jin.renderVals();
  ok(mv.myMenu[0].label === 'AI 토큰 세부내용' && mv.myMenu[0].hasValue && /토큰$/.test(mv.myMenu[0].value), 'MY 메뉴: AI 토큰 세부내용 + 요금제·누적 토큰: ' + mv.myMenu[0].value);
  ok(jin.state.aiSrv && typeof jin.state.aiSrv.tokens === 'number' && mv.usageBadge && /토큰/.test(mv.usageNote), `서버 AI 사용량 연결 (${mv.usageBadge} · ${mv.usageTotal} 토큰 · ${mv.usageCalls})`);
  ok(mv.hasQuota && /%$/.test(mv.sessionPctStr) && /토큰/.test(mv.sessionSub) && /토큰/.test(mv.weekSub) && mv.aiPlanLabel === 'Free',
     `MY AI 카드: ${mv.aiPlanLabel} · 세션 ${mv.sessionPctStr} (${mv.sessionSub}) · 이번 주 ${mv.weekPctStr}`);
  mv.openAiTokens(); await sleep(100); const uv = jin.renderVals();
  ok(uv.isUsage && uv.usageStages.length === 6 && uv.usageStages[1].isCode && uv.usageChips.length === 3, 'AI 토큰 세부내용 화면 (단계별 · 정산 코어 먼저)');
  ok(uv.usageDays.some(d => d.items.some(i => i.title === '정산 송금' || i.title === '정산 입금')), '결제·정산은 ‘AI 미사용’ 기록으로 함께 표시');
  const csv = jin.downloadUsageCsv();
  ok(/^\ufeff일시,구분,단계 태그/.test(csv) && /지연\(ms\),에너지 상한\(Wh\),한도 포함,요금제,흐름,응답 반영/.test(csv), 'CSV 명세서 (BOM + 지연·에너지·한도·흐름·응답 반영 열)');
  if (jin.state.aiSrv.measured) ok(uv.usageDays.some(d => d.items.some(i => /토큰$/.test(i.tokStr) && i.tokStr !== '0 토큰')) && uv.usageBadge === 'Kiln 실측', `실측 AI 사용 기록 ${uv.usageCalls}`);
  ok(typeof jin.openAiPay === 'undefined' && !('isAiPaySheet' in uv) && !('aiUnpaidStr' in uv), '쓴 만큼 송금하는 화면 없음 (구독 방식)');
  jin.downloadReport(); ok(/보고서/.test(jin.toasts.at(-1)), '심사용 보고서 열기');
  const rep = await (await fetch(BASE + '/api/usage/report.md')).text();
  ok(/## 1\. 워크플로 단계별 토큰/.test(rep) && /## 6\. 구독 요금제/.test(rep), '보고서(.md) 서버 응답');

  // ── AI 요금제 (Claude 벤치마킹: Free → Pro → Max 5x → Max 20x · 5시간 세션·주간 한도) ──
  await jin.loadUsage(); let sv = jin.renderVals();
  ok(!sv.hasAiSub && sv.subRowTitle === 'Free 요금제' && sv.subRowBtn === '요금제 ›', 'MY AI 카드: Free 요금제 행');
  await jin.openAiSub(); sv = jin.renderVals();
  ok(sv.isAiSubSheet && sv.subPlanCards.length === 4 && sv.subPlanCards[0].current && sv.subPlanCards[1].label === 'Pie Pro' && sv.subPlanCards[1].priceStr === '월 4,900 PIE'
     && sv.subPlanCards[2].priceStr === '월 24,500 PIE' && sv.subPlanCards[3].priceStr === '월 49,000 PIE', 'AI 요금제 시트: Free·Pro·Max 5x·Max 20x 카드');
  ok(/5시간마다/.test(sv.subPlanCards[1].allowStr) && sv.subInfo.sessionStr && sv.subInfo.weekStr, '카드마다 5시간·주간 한도 · 사용량 막대 두 개');
  const subBal0 = jin.state.fund.balance, freeLimit = jin.state.aiSrv.quota.session.limit;
  jin.subscribeTo('pro'); await jin.state.confirm.fn(); jin.setState({ confirm: null }); await sleep(150);
  let subNow = jin.state.aiSrv.sub;
  ok(subNow && subNow.plan === 'pro' && jin.state.fund.balance === subBal0 - 4900 && jin.state.aiSrv.quota.session.limit === freeLimit * 5, 'Pro 구독 → 4,900 PIE 결제 · 세션 한도 5배');
  sv = jin.renderVals();
  ok(sv.hasAiSub && sv.subRowTitle === 'Pie Pro 요금제' && /이번 주 \d+% 사용/.test(sv.subRowSub), 'MY 카드: 요금제·이번 주 사용량');
  jin.startChat('구독 테스트로 뭐 하나 물어볼게'); await waitTyping(jin); await jin.loadUsage();
  if (jin.state.aiSrv.measured) ok(jin.state.aiSrv.quota.session.used > 0, `구독 중 AI 사용 → 세션 사용량 ${jin.state.aiSrv.quota.session.used} 토큰`);
  jin.cancelAiSub(); await jin.state.confirm.fn(); jin.setState({ confirm: null }); await sleep(150);
  ok(jin.state.aiSrv.sub.cancelAt && jin.state.aiSrv.sub.plan === 'pro', '해지 예약 · 남은 기간은 유지');
  const subBal1 = jin.state.fund.balance;
  jin.subscribeTo('pro'); await jin.state.confirm.fn(); jin.setState({ confirm: null }); await sleep(150);
  ok(!jin.state.aiSrv.sub.cancelAt && jin.state.fund.balance === subBal1, '예약 취소 · 추가 결제 없음');
  jin.subscribeTo('max'); await jin.state.confirm.fn(); jin.setState({ confirm: null }); await sleep(150);
  ok(jin.state.aiSrv.sub.plan === 'max' && jin.state.fund.balance === subBal1 - 24500, 'Max 5x로 올림 → 바로 결제');
  const subBal2 = jin.state.fund.balance;
  jin.subscribeTo('pro'); await jin.state.confirm.fn(); jin.setState({ confirm: null }); await sleep(150);
  ok(jin.state.aiSrv.sub.plan === 'max' && jin.state.aiSrv.sub.nextPlan === 'pro' && jin.state.fund.balance === subBal2, 'Pro로 내림 → 결제 없이 다음 결제일부터');
  jin.setState({ sheet: null });
  jin.setState({ overlay: null });

  // ── 베타: 기능 예시(미션) · 대화 제공 동의 · 답 평가 ──
  await jin.loadBeta(); let bV = jin.renderVals();
  ok(bV.betaOn && bV.betaAsk && bV.betaNext.length === 3 && /\/13/.test(bV.betaProgress), `홈 베타 카드: 동의 배너 · 다음 미션 3개 (${bV.betaProgress})`);
  bV.betaAgree(); await sleep(150); bV = jin.renderVals();
  ok(jin.state.beta.consent === true && !bV.betaAsk, '동의하고 참여');
  ok(bV.myMenu.some(x => x.label === '베타 테스트 참여' && x.value === '대화 제공 중'), 'MY 메뉴: 베타 테스트 참여 (대화 제공 중)');
  await jin.openBetaMissions(); bV = jin.renderVals();
  ok(bV.isBetaSheet && bV.betaGroups.length === 5 && bV.betaGroups.reduce((a, g) => a + g.items.length, 0) === 13, '미션 시트: 5개 분류 · 13개');
  jin.setState({ sheet: null });
  const bS01 = jin.state.beta.scenarios.find(x => x.id === 'S01');
  jin.tryScenario(bS01);
  ok(jin.state.overlay === 'chat' && jin.state.chatInput === bS01.text && jin.state.betaDraft.id === 'S01', '미션 누르면 새 대화 + 예시 문장이 입력창에');
  jin.sendChat(); await waitTyping(jin); await sleep(250);
  const bChat = jin.state.chats.find(c => c.id === jin.state.chatId);
  const bBot = bChat.msgs.find(m => m.from === 'bot' && m.turn);
  ok(bBot && jin.state.beta.scenarios.find(x => x.id === 'S01').done, `보내면 미션 완료 · 답에 turn (${bBot && bBot.turn})`);
  const bRate = jin.renderVals().chatMsgs.find(m => m.canRate);
  ok(bRate && typeof bRate.rateUp === 'function', '답 아래 ‘도움 됐어요 · 아쉬워요’');
  bRate.rateDown(); ok(jin.state.sheet === 'betaReason', '아쉬워요 → 이유 고르기');
  jin.renderVals().betaReasons[0].pick(); await jin.sendBetaReason(); await sleep(100);
  ok(jin.state.betaRated[bBot.turn] === 'down' && jin.state.sheet === null, '이유와 함께 보냄');
  const bS04 = jin.state.beta.scenarios.find(x => x.id === 'S04');
  jin.tryScenario(bS04); jin.sendChat(); await waitTyping(jin);
  ok(jin.state.chatInput === bS04.follow && jin.state.betaDraft && jin.state.betaDraft.isFollow, '조건 바꾸기 미션: 이어 보낼 문장이 입력창에');
  jin.setState({ chatInput: '', betaDraft: null, overlay: null, sheet: null });
  const bRep = await (await fetch(BASE + '/api/beta/report')).json();
  ok(bRep.data.scenarios.some(x => x.scenario === 'S01' && x.turns >= 1 && x.down >= 1), `베타 보고서: S01 턴 · 👎 기록`);

  // ── 화면 스모크 ──
  for (const tab of ['home', 'buy', 'group', 'settle', 'my']) { jin.state.tab = tab; jin.state.overlay = null; jin.renderVals(); }
  jin.state.overlay = 'doc'; jin.state.docId = cert.id; const dv = jin.renderVals();
  ok(dv.doc.hasPurpose && dv.doc.badge, `인증서 화면 (${dv.doc.network}) · 목적 “${dv.doc.purpose}”`);
  const my = woo.renderVals();
  ok(my.hasFund && /PIE/.test(my.balanceStr) && my.payList.length > 0, `MY: ${my.balanceStr} · ${my.fundRows.map(f => f.k + ' ' + f.v).join(', ')}`);
  ok(jin.state.notifs.length > 0, `알림 ${jin.state.notifs.length}개 (전부 실제 이벤트)`);

  const usage = await (await fetch(BASE + '/api/usage')).json();
  console.log('\n' + usage.data.markdown);
  console.log(failures ? `\n✗ 실패 ${failures}건` : '\n✓ 전체 통과');
  process.exit(failures ? 1 : 0);
}
main().catch(e => { console.error(e); process.exit(1); });
