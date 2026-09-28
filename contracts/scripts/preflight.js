// 테스트넷 배포 전 사전 점검 — 항목별 ✅/❌. 트랜잭션·AI 호출은 하지 않는다 (읽기만).
// 사용법: cd contracts && npm run preflight
// 비밀값은 절대 출력하지 않는다 (키는 앞 6자리만).
const path = require('path');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
require(path.join(BACKEND, 'node_modules', 'dotenv')).config({ path: path.join(BACKEND, '.env'), quiet: true });

const { configuredChainId, describeChain, assertAllowedChain, MAINNET_CHAIN_IDS } = require(path.join(BACKEND, 'src', 'blockchain', 'chains'));

const MIN_GAS_ETH = 0.02; // Run 1 + 1.5 + 2 + release 를 돌리기에 넉넉한 최소치 (경고 기준)
const mask = (v) => (v ? `${String(v).slice(0, 6)}…(${String(v).length}자)` : '(비어 있음)');

// 결과 항목: { name, ok: true|false|null(경고/정보), detail, hint }
async function preflight({ env = process.env, quiet = false } = {}) {
  const items = [];
  const add = (name, ok, detail, hint) => { items.push({ name, ok, detail, hint: hint || null }); };
  const isAddr = (v) => /^0x[0-9a-fA-F]{40}$/.test(v || '');
  // ethers 는 RPC·키·주소 중 하나라도 있을 때만 불러온다 (MOCK 점검에서는 ethers 없이 동작)
  let ethers = null;
  if (env.BLOCKCHAIN_RPC_URL || env.DEPLOYER_PRIVATE_KEY || env.CONTRACT_ADDRESS) {
    try { ethers = require(path.join(BACKEND, 'node_modules', 'ethers')).ethers; } catch { /* backend npm install 전 */ }
  }

  // 1) 체인 설정 (env)
  let chain = null;
  try {
    const id = configuredChainId(env);
    chain = assertAllowedChain(id, env);
    add('체인 설정 (CHAIN_ID)', true, `${chain.name} (chainId ${chain.chainId}${chain.custom ? ', env 커스텀' : ', 기본 Sepolia'})`);
  } catch (err) {
    add('체인 설정 (CHAIN_ID)', false, err.message, '테스트넷 chainId 만 허용. 대회 테스트넷이면 CHAIN_ID·CHAIN_NAME·EXPLORER_TX_URL 을 backend/.env 에 넣기');
  }

  // 2) RPC 접속 + chainId 일치
  const rpc = env.BLOCKCHAIN_RPC_URL;
  let provider = null;
  if (!rpc) {
    add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, '비어 있음', 'Alchemy/Infura 등에서 테스트넷 RPC URL 발급 → backend/.env 의 BLOCKCHAIN_RPC_URL');
  } else if (!ethers) {
    add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, 'ethers 가 설치되지 않음', 'backend 폴더에서 npm install');
  } else {
    try {
      provider = new ethers.JsonRpcProvider(rpc, undefined, { staticNetwork: undefined });
      const net = await Promise.race([provider.getNetwork(), new Promise((_, rej) => setTimeout(() => rej(new Error('10초 안에 응답 없음')), 10_000))]);
      const id = Number(net.chainId);
      const d = describeChain(id, env);
      if (MAINNET_CHAIN_IDS[id]) add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, `연결됨 — 그런데 chainId ${id}(${MAINNET_CHAIN_IDS[id]})는 메인넷!`, 'RPC 가 테스트넷을 가리키는지 확인');
      else if (!d) add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, `연결됨 — chainId ${id}는 허용 목록에 없음`, 'CHAIN_ID 를 이 값으로 맞추고 CHAIN_NAME·EXPLORER_TX_URL 추가');
      else if (chain && id !== chain.chainId) add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, `연결됨 — RPC chainId ${id}(${d.name}) ≠ 설정 ${chain.chainId}`, 'CHAIN_ID 와 RPC 가 같은 체인을 가리키게 맞추기');
      else add('RPC 접속 (BLOCKCHAIN_RPC_URL)', true, `연결됨 — ${d.name} (chainId ${id})`);
    } catch (err) {
      add('RPC 접속 (BLOCKCHAIN_RPC_URL)', false, `연결 실패: ${err.message}`, 'URL 오타·키 만료·네트워크 확인');
      provider = null;
    }
  }

  // 3) 운영자(배포) 지갑
  const pkRaw = env.DEPLOYER_PRIVATE_KEY;
  if (!pkRaw) {
    add('운영자 지갑 (DEPLOYER_PRIVATE_KEY)', false, '비어 있음', '테스트 전용 새 지갑을 만들어 비밀키를 backend/.env 에 (실제 자산 지갑 금지)');
  } else if (!ethers) {
    add('운영자 지갑 (DEPLOYER_PRIVATE_KEY)', false, 'ethers 미설치로 확인 불가', 'backend 폴더에서 npm install');
  } else {
    try {
      const pk = pkRaw.startsWith('0x') ? pkRaw : '0x' + pkRaw;
      const wallet = new ethers.Wallet(pk);
      if (provider) {
        const bal = Number(ethers.formatEther(await provider.getBalance(wallet.address)));
        const ok = bal > 0;
        add('운영자 지갑 (DEPLOYER_PRIVATE_KEY)', ok ? (bal < MIN_GAS_ETH ? null : true) : false, `${wallet.address} — 잔액 ${bal} ETH (테스트넷)${bal > 0 && bal < MIN_GAS_ETH ? ` ⚠️ ${MIN_GAS_ETH} ETH 미만: 데모 전 faucet 권장` : ''}`, ok ? null : '해당 테스트넷 faucet 에서 가스용 ETH 받기');
      } else {
        add('운영자 지갑 (DEPLOYER_PRIVATE_KEY)', null, `${wallet.address} — 잔액은 RPC 연결 후 확인`, null);
      }
    } catch (err) {
      add('운영자 지갑 (DEPLOYER_PRIVATE_KEY)', false, `비밀키 형식 오류 (${mask(pkRaw)})`, '0x + 64자리 hex 인지 확인');
    }
  }

  // 4) 결제처 주소
  if (!env.MERCHANT_ADDRESS) add('결제처 주소 (MERCHANT_ADDRESS)', false, '비어 있음', 'payer 없는 정산의 release 수령처 — 아무 테스트 지갑 주소');
  else if (!isAddr(env.MERCHANT_ADDRESS)) add('결제처 주소 (MERCHANT_ADDRESS)', false, `형식 오류: ${env.MERCHANT_ADDRESS}`, '0x + 40자리 hex');
  else add('결제처 주소 (MERCHANT_ADDRESS)', true, env.MERCHANT_ADDRESS);

  // 5) 컨트랙트 주소 → 코드 배포 여부
  const ca = env.CONTRACT_ADDRESS;
  if (!ca) add('컨트랙트 (CONTRACT_ADDRESS)', null, '비어 있음 — 아직 배포 전', 'npm run deploy:sepolia (또는 --network custom) 후 출력 주소를 backend/.env 에');
  else if (!isAddr(ca)) add('컨트랙트 (CONTRACT_ADDRESS)', false, `형식 오류: ${ca}`, '0x + 40자리 hex');
  else if (!provider) add('컨트랙트 (CONTRACT_ADDRESS)', null, `${ca} — 배포 여부는 RPC 연결 후 확인`, null);
  else {
    try {
      const code = await provider.getCode(ca);
      add('컨트랙트 (CONTRACT_ADDRESS)', code && code !== '0x', code && code !== '0x' ? `${ca} — 코드 배포됨 (${(code.length - 2) / 2} bytes)` : `${ca} — 이 체인에 코드가 없음`, code && code !== '0x' ? null : '다른 체인에 배포했거나 주소 오타. deploy 다시 실행');
    } catch (err) {
      add('컨트랙트 (CONTRACT_ADDRESS)', false, `getCode 실패: ${err.message}`, null);
    }
  }

  // 6) Kiln (호출하지 않음)
  add('Kiln 키 (KILN_API_KEY)', Boolean(env.KILN_API_KEY), env.KILN_API_KEY ? `설정됨 (${mask(env.KILN_API_KEY)})` : '비어 있음', env.KILN_API_KEY ? null : 'kiln.bricksum.com 에서 발급 → backend/.env');
  add('Kiln 모델 (KILN_MODEL)', Boolean((env.KILN_MODEL || '').trim()), (env.KILN_MODEL || '').trim() || '비어 있음 — AI 호출이 503 으로 거부됨', (env.KILN_MODEL || '').trim() ? null : 'CLAUDE.md 4번: 주최측 공지 모델 ID (개발 중 qwen3-32b)');

  // 7) 보류 기간
  const hold = env.SETTLEMENT_HOLD_SECONDS;
  const holdN = hold === undefined || hold === '' ? 600 : Number(hold);
  add('보류 기간 (SETTLEMENT_HOLD_SECONDS)', Number.isSafeInteger(holdN) && holdN >= 0, `${holdN}초${hold === undefined || hold === '' ? ' (기본값)' : ''} — Run 1 release 는 이 시간 뒤에 가능`, Number.isSafeInteger(holdN) && holdN >= 0 ? null : '0 이상의 정수');

  const failed = items.filter((i) => i.ok === false).length;
  const warned = items.filter((i) => i.ok === null).length;
  if (!quiet) {
    console.log('=== SharePie 배포 사전 점검 (읽기만, 트랜잭션 없음) ===');
    for (const i of items) {
      console.log(`${i.ok === true ? '✅' : i.ok === false ? '❌' : '⚠️'} ${i.name}: ${i.detail}`);
      if (i.hint) console.log(`     → ${i.hint}`);
    }
    console.log(failed ? `\n❌ ${failed}개 항목을 채워야 해요${warned ? `, 경고 ${warned}개` : ''}.` : `\n✅ 필수 항목 통과${warned ? ` (경고 ${warned}개)` : ''}. 배포/데모를 진행할 수 있어요.`);
  }
  return { ok: failed === 0, failed, warned, items, mode: env.BLOCKCHAIN_RPC_URL && env.CONTRACT_ADDRESS && env.DEPLOYER_PRIVATE_KEY ? 'testnet' : 'mock' };
}

module.exports = { preflight };

if (require.main === module) {
  preflight().then((r) => { process.exitCode = r.ok ? 0 : 1; }).catch((err) => { console.error('❌', err.message); process.exitCode = 1; });
}
