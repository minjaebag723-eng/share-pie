/* Share Pie ↔ 백엔드 / MetaMask 연결 모듈 (window.SP)
 *  - SP.api(path, body?)      : 백엔드 호출. 성공 시 data 반환, 실패 시 Error{code,message,details} throw
 *  - SP.web3.connect()        : MetaMask 연결 + BNB Testnet(97) 전환 → 지갑 주소
 *  - (충전은 서버 /api/wallet/charge — 에이전트가 chargeToken으로 발급, 사용자 가스비 없음)
 *  - SP.web3.payShare(rec, me): 내 몫 approve → lockForSettlement (MetaMask 서명 2번) → tx hash
 *    구매 대행(rec.mode==='purchase')이면 approve(한도 추가) → approvePurchase(인출 승인). 전원 승인되면 AI가 인출·결제
 *  CHAIN_MODE=mock 이면 MetaMask 없이 서버의 /api/dev/* 로 같은 흐름을 흉내 냅니다.
 */
(function () {
  var BASE = window.SP_API_BASE || (location.protocol === 'file:' ? 'http://localhost:8000' : '');

  function err(code, message, extra) {
    var e = new Error(message); e.code = code; e.sp = true;
    if (extra) for (var k in extra) e[k] = extra[k];
    return e;
  }

  // 로그인 토큰 (서버가 발급 · 이 기기에만 저장) — 모든 API 요청에 Authorization 헤더로 붙인다
  var TOKEN_KEY = 'sp_token', unauthorized = [];
  function getToken() { try { return window.localStorage.getItem(TOKEN_KEY) || null; } catch (e) { return null; } }
  function setToken(t) { try { if (t) window.localStorage.setItem(TOKEN_KEY, t); else window.localStorage.setItem(TOKEN_KEY, ''); } catch (e) {} }

  // 기기 식별용 무작위 ID (이메일 자동 채우기용 · 개인정보 아님). 저장소를 못 쓰면 이 창에서만 유지
  var memDevice = null;
  function deviceId() {
    try {
      var d = localStorage.getItem('sp_device');
      if (!d) { d = rnd(); localStorage.setItem('sp_device', d); }
      return d;
    } catch (e) { return memDevice || (memDevice = rnd()); }
  }
  function rnd() {
    var a = new Uint8Array(18), cr = window.crypto || window.msCrypto;
    if (cr && cr.getRandomValues) cr.getRandomValues(a); else for (var i = 0; i < a.length; i++) a[i] = Math.floor(Math.random() * 256);
    return Array.prototype.map.call(a, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  async function api(path, body) {
    var headers = {}, tok = getToken(), dev = deviceId();
    if (tok) headers.Authorization = 'Bearer ' + tok;
    if (dev) headers['X-SP-Device'] = dev;   // 이 기기에서 쓴 이메일을 서버가 기억 → 로그인 화면 자동 채우기
    var opt = body === undefined ? { method: 'GET', headers: headers }
      : { method: 'POST', headers: Object.assign({ 'Content-Type': 'application/json' }, headers), body: JSON.stringify(body) };
    var res, j;
    try { res = await fetch(BASE + path, opt); } catch (e) { throw err('NETWORK', '서버에 연결할 수 없어요'); }
    try { j = await res.json(); } catch (e) {
      // JSON이 아닌 응답 = 앱 서버가 아니라 중간(터널·프록시)이 보낸 에러 페이지
      if ([502, 503, 504, 520, 521, 522, 523, 524, 530].indexOf(res.status) >= 0)
        throw err('SERVER_DOWN', '서버에 연결되지 않았어요 (HTTP ' + res.status + '). 서버 창(uvicorn)이 켜져 있는지, 터널 주소가 바뀌지 않았는지 확인해 주세요.');
      throw err('BAD_RESPONSE', '서버 응답을 읽을 수 없어요 (HTTP ' + res.status + ')');
    }
    if (!j.ok) {
      var x = j.error || {};
      if (x.code === 'UNAUTHORIZED' && tok) unauthorized.forEach(function (f) { try { f(); } catch (e) {} });
      throw err(x.code || 'ERROR', x.message || '오류가 발생했어요', { details: x.details, stage: x.stage });
    }
    return j.data;
  }

  var cfg = null;
  async function config() { if (!cfg) cfg = await api('/api/config'); return cfg; }

  function friendly(e) {
    var m = (e && (e.shortMessage || e.reason || e.message)) || '';
    if (e && (e.code === 4001 || e.code === 'ACTION_REJECTED' || /rejected|denied/i.test(m))) return err('USER_REJECTED', '서명을 취소했어요');
    if (/insufficient funds/i.test(m)) return err('NO_GAS', '가스비(tBNB)가 부족해요. BNB Testnet Faucet에서 tBNB를 받아 주세요');
    if (/cooldown/i.test(m)) return err('FAUCET_COOLDOWN', '충전은 1시간에 한 번만 할 수 있어요');
    if (/insufficient (PIE )?balance|exceeds balance/i.test(m)) return err('NO_PIE', 'PIE 잔액이 부족해요. MY 탭에서 충전해 주세요');
    if (/not open|already closed/i.test(m)) return err('NOT_OPEN', '이미 종료되었거나 중단된 정산이에요. 새로고침해 주세요');
    if (/window closed/i.test(m)) return err('WINDOW_CLOSED', '이의제기 가능 시간이 지났어요');
    if (/already locked|already approved/i.test(m)) return err('ALREADY_PAID', '이미 결제·승인한 정산이에요');
    if (/allowance too low/i.test(m)) return err('NO_ALLOWANCE', '인출 한도 승인이 필요해요. 다시 시도해 주세요');
    return err(e && e.code ? String(e.code) : 'WALLET_ERROR', m.slice(0, 160) || '지갑 오류');
  }

  async function ensureChain(c) {
    var want = c.chain_id_hex;
    var now = await window.ethereum.request({ method: 'eth_chainId' });
    if (now && now.toLowerCase() === want.toLowerCase()) return;
    try {
      await window.ethereum.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: want }] });
    } catch (e) {
      if (e && (e.code === 4902 || /Unrecognized chain/i.test(e.message || ''))) {
        await window.ethereum.request({ method: 'wallet_addEthereumChain', params: [{
          chainId: want, chainName: 'BNB Smart Chain Testnet',
          nativeCurrency: { name: 'tBNB', symbol: 'tBNB', decimals: 18 },
          rpcUrls: [c.rpc], blockExplorerUrls: [c.explorer] }] });
      } else throw e;
    }
  }

  async function signer() {
    var c = (await config()).chain;
    if (!window.ethereum) throw err('NO_WALLET', 'MetaMask가 필요해요');
    if (!window.ethers) throw err('NO_ETHERS', 'ethers 라이브러리를 불러오지 못했어요 (인터넷 연결 확인)');
    await window.ethereum.request({ method: 'eth_requestAccounts' });
    await ensureChain(c);
    var provider = new window.ethers.BrowserProvider(window.ethereum);
    return { c: c, provider: provider, signer: await provider.getSigner() };
  }

  var web3 = {
    isMobile: function () { return /Android|iPhone|iPad/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1); },
    hasWallet: function () { return !!window.ethereum; },
    metamaskLink: function () { return 'https://metamask.app.link/dapp/' + location.host + location.pathname + location.search; },
    faucetUrl: 'https://www.bnbchain.org/en/testnet-faucet',

    async mode() { return (await config()).chain.mode; },

    async connect() {
      var c = (await config()).chain;
      if (c.mode === 'mock') return null; // 서버가 이름으로 가짜 주소 발급
      try {
        var s = await signer();
        var addr = await s.signer.getAddress();
        try { // PIE 토큰을 MetaMask 자산 목록에 추가 (실패해도 무시)
          await window.ethereum.request({ method: 'wallet_watchAsset', params: { type: 'ERC20', options: {
            address: c.token, symbol: c.token_symbol || 'PIE', decimals: c.token_decimals || 0 } } });
        } catch (e) {}
        return addr;
      } catch (e) { throw e && e.sp ? e : friendly(e); }
    },

    /* rec: /api/settlements 가 준 정산, me: 내 이름, onStep: 진행 문구 콜백 */
    async payShare(rec, me, onStep) {
      var c = (await config()).chain;
      var mine = rec.members.find(function (m) { return m.name === me; });
      if (!mine) throw err('NOT_MEMBER', '이 정산의 참여자가 아니에요');
      if (c.mode === 'mock') { onStep && onStep('결제 중…'); return { rec: await api('/api/dev/mock-lock', { sid: rec.id, name: me }) }; }
      try {
        var s = await signer();
        var addr = await s.signer.getAddress();
        if (addr.toLowerCase() !== mine.wallet.toLowerCase())
          throw err('WRONG_ACCOUNT', 'MetaMask 계정이 등록한 지갑과 달라요 (' + mine.wallet.slice(0, 6) + '…' + mine.wallet.slice(-4) + ')');
        var gas = await s.provider.getBalance(addr);
        if (gas === 0n) throw err('NO_GAS', '가스비(tBNB)가 없어요. BNB Testnet Faucet에서 tBNB를 받아 주세요');
        var abi = (await config()).abi;
        var token = new window.ethers.Contract(c.token, abi.token, s.signer);
        var ledger = new window.ethers.Contract(c.ledger, abi.ledger, s.signer);
        var units = BigInt(mine.share) * (10n ** BigInt(c.token_decimals || 0));
        var bal = await token.balanceOf(addr);
        if (bal < units) throw err('NO_PIE', 'PIE 잔액이 부족해요. MY 탭에서 충전해 주세요');
        var allowed = await token.allowance(addr, c.ledger);
        if (rec.mode === 'purchase') {
          // AI 구매 대행: 내 몫만큼 '인출 한도'를 더해 주고(다른 진행 중 구매 한도는 유지) → 인출 승인. 돈은 전원 승인 후 AI가 한 번에 인출·결제
          onStep && onStep('1/2 · MetaMask에서 내 몫(' + mine.share.toLocaleString() + ' PIE) 인출 한도를 승인해 주세요');
          await (await token.approve(c.ledger, allowed + units)).wait();
          onStep && onStep('2/2 · MetaMask에서 구매 참여(인출 승인)를 확인해 주세요');
          var rp = await (await ledger.approvePurchase(rec.chainId)).wait();
          return { txHash: rp.hash };
        }
        if (allowed < units) {
          onStep && onStep('1/2 · MetaMask에서 PIE 사용을 승인해 주세요');
          await (await token.approve(c.ledger, units)).wait();
        }
        onStep && onStep('2/2 · MetaMask에서 예치(결제)를 확인해 주세요');
        var r = await (await ledger.lockForSettlement(rec.chainId)).wait();
        return { txHash: r.hash };
      } catch (e) { throw e && e.sp ? e : friendly(e); }
    },

    /* AI 구독 (Claude 요금제 벤치마킹): mock이면 서버가 대신 결제, 실제 체인이면 MetaMask로 구독료 송금 후 확인 */
    async paySub(plan, price, myWallet, onStep) {
      var cfgAll = await config(), c = cfgAll.chain;
      if (c.mode === 'mock') { onStep && onStep('구독 결제 중…'); return api('/api/ai/subscribe', { plan: plan }); }
      try {
        var s = await signer();
        var addr = await s.signer.getAddress();
        if (myWallet && addr.toLowerCase() !== myWallet.toLowerCase())
          throw err('WRONG_ACCOUNT', 'MetaMask 계정이 등록한 지갑과 달라요 (' + myWallet.slice(0, 6) + '…' + myWallet.slice(-4) + ')');
        if ((await s.provider.getBalance(addr)) === 0n) throw err('NO_GAS', '가스비(tBNB)가 없어요. BNB Testnet Faucet에서 tBNB를 받아 주세요');
        var token = new window.ethers.Contract(c.token, cfgAll.abi.token, s.signer);
        var units = BigInt(price) * (10n ** BigInt(c.token_decimals || 0));
        if ((await token.balanceOf(addr)) < units) throw err('NO_PIE', 'PIE 잔액이 부족해요. MY 탭에서 충전해 주세요');
        onStep && onStep('MetaMask에서 구독료 송금(' + Number(price).toLocaleString() + ' PIE)을 확인해 주세요');
        var r = await (await token.transfer(cfgAll.ai_pay.fee_wallet, units)).wait();
        onStep && onStep('송금 확인 중…');
        return api('/api/ai/subscribe', { plan: plan, tx_hash: r.hash });
      } catch (e) { throw e && e.sp ? e : friendly(e); }
    },

    /* AI 전용 페이: 누적 AI 사용량으로 송금 (Pie Pay → 사용료 지갑). myWallet: 내가 등록한 지갑 주소 */
    async payAiFee(amount, myWallet, onStep) {
      var cfgAll = await config(), c = cfgAll.chain;
      if (c.mode === 'mock') { onStep && onStep('송금 중…'); return api('/api/ai/pay', { amount: amount }); }
      try {
        var s = await signer();
        var addr = await s.signer.getAddress();
        if (myWallet && addr.toLowerCase() !== myWallet.toLowerCase())
          throw err('WRONG_ACCOUNT', 'MetaMask 계정이 등록한 지갑과 달라요 (' + myWallet.slice(0, 6) + '…' + myWallet.slice(-4) + ')');
        if ((await s.provider.getBalance(addr)) === 0n) throw err('NO_GAS', '가스비(tBNB)가 없어요. BNB Testnet Faucet에서 tBNB를 받아 주세요');
        var token = new window.ethers.Contract(c.token, cfgAll.abi.token, s.signer);
        var units = BigInt(amount) * (10n ** BigInt(c.token_decimals || 0));
        if ((await token.balanceOf(addr)) < units) throw err('NO_PIE', 'PIE 잔액이 부족해요. MY 탭에서 충전해 주세요');
        onStep && onStep('MetaMask에서 AI 사용료 송금(' + Number(amount).toLocaleString() + ' PIE)을 확인해 주세요');
        var r = await (await token.transfer(cfgAll.ai_pay.fee_wallet, units)).wait();
        onStep && onStep('송금 확인 중…');
        return api('/api/ai/pay', { tx_hash: r.hash });
      } catch (e) { throw e && e.sp ? e : friendly(e); }
    },
  };

  // 소셜 로그인: 페이지째 각 사 로그인 화면으로 이동 (돌아오면 /#sp_social=티켓)
  function socialStart(provider) { location.href = BASE + '/api/auth/social/' + encodeURIComponent(provider) + '/start'; }

  window.SP = { api: api, config: config, web3: web3, base: BASE, getToken: getToken, setToken: setToken, deviceId: deviceId, socialStart: socialStart,
    onUnauthorized: function (f) { unauthorized.push(f); } };
})();
