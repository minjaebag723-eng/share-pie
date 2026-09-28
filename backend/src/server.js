'use strict';

require('dotenv').config({ path: require('path').join(__dirname, '..', '.env'), quiet: true });

const fs = require('fs');
const path = require('path');
const express = require('express');
const cors = require('cors');
const { APIError, APIConnectionError } = require('openai');
const settlementRouter = require('./routes/settlement');
const disputeRouter = require('./routes/dispute');
const shoppingRouter = require('./routes/shopping');
const { summarizeTokenUsage } = require('./logger');
const { configuredChainId, describeChain } = require('./blockchain/chains'); // ethers 없이 동작

const app = express();
app.use(cors());
app.use(express.json({ limit: '200kb' }));

// ── UI 화면 (저장소 루트의 UI 담당 파일을 그대로 보여줌) ─────────────────────
// ⚠️ 루트 폴더 전체를 static으로 열면 backend/.env(API 키)까지 노출되므로,
//    화면에 필요한 파일(HTML, support.js, assets/)만 명시적으로 연다.
const REPO_ROOT = path.join(__dirname, '..', '..');

function findUiFile() {
  if (process.env.UI_FILE) return path.join(REPO_ROOT, process.env.UI_FILE);
  // UI 파일 이름이 바뀌어도 동작하도록 루트의 Share*.html 중 가장 최근 파일 사용
  const candidates = fs.readdirSync(REPO_ROOT)
    .filter((f) => /^share.*\.html$/i.test(f))
    .map((f) => ({ f, t: fs.statSync(path.join(REPO_ROOT, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  return candidates.length ? path.join(REPO_ROOT, candidates[0].f) : null;
}

app.get('/', (req, res) => {
  const file = findUiFile();
  if (!file || !fs.existsSync(file)) {
    return res.status(404).json({ error: { code: 'UI_NOT_FOUND', message: '저장소 루트에 Share*.html UI 파일이 없어요.' } });
  }
  res.sendFile(file);
});
app.get('/support.js', (req, res) => res.sendFile(path.join(REPO_ROOT, 'support.js')));
app.use('/assets', express.static(path.join(REPO_ROOT, 'assets'), { dotfiles: 'deny' }));

app.get('/health', (req, res) => {
  const model = (process.env.KILN_MODEL || '').trim() || null;
  // 블록체인 모드: 설정 3개가 모두 있으면 testnet, 아니면 mock (blockchainClient.IS_MOCK 과 같은 기준)
  const chainConfigured = Boolean(process.env.BLOCKCHAIN_RPC_URL && process.env.CONTRACT_ADDRESS && process.env.DEPLOYER_PRIVATE_KEY);
  let chainInfo = null;
  try { chainInfo = describeChain(configuredChainId()); } catch { chainInfo = null; }
  const contractAddress = process.env.CONTRACT_ADDRESS ? `${process.env.CONTRACT_ADDRESS.slice(0, 10)}…` : null;
  res.json({ ok: true, kilnConfigured: Boolean(process.env.KILN_API_KEY), kilnModelConfigured: Boolean(model), model,
    mode: chainConfigured ? 'testnet' : 'mock', network: chainConfigured ? (chainInfo ? chainInfo.name : 'unknown') : 'mock', chainId: chainConfigured && chainInfo ? chainInfo.chainId : null, contractAddress,
    shoppingProvider: process.env.SHOPPING_PROVIDER === 'mock' || !process.env.SHOPPING_API_KEY ? 'mock' : 'serpapi' });
});

app.use('/settlement', settlementRouter);
app.use('/dispute', disputeRouter);
app.use('/shopping', shoppingRouter); // 선택적 모듈 (3순위)

// 흐름별 토큰 사용량 합계 (기술 로그 화면 / 제출 자료용)
app.get('/logs/tokens', (req, res) => {
  res.json(summarizeTokenUsage());
});

app.use((req, res) => {
  res.status(404).json({ error: { code: 'NOT_FOUND', message: `${req.method} ${req.path} 는 없는 API예요.` } });
});

// 모든 에러를 { error: { code, message } } 한 가지 모양으로 응답
// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  if (err.type === 'entity.parse.failed') {
    return res.status(400).json({ error: { code: 'INVALID_JSON', message: '요청 body가 올바른 JSON이 아니에요.' } });
  }
  // Kiln(OpenAI SDK) 에러를 먼저 처리 — SDK 에러도 code/status를 갖고 있어서 순서가 중요
  if (err instanceof APIConnectionError) {
    console.error('[kiln] 연결 실패:', err.message);
    return res.status(502).json({ error: { code: 'KILN_UNREACHABLE', message: 'Kiln API 서버에 연결하지 못했어요. 네트워크를 확인해 주세요.' } });
  }
  if (err instanceof APIError) {
    console.error('[kiln] API 에러:', err.status, err.message);
    return res.status(502).json({ error: { code: 'KILN_API_ERROR', message: `Kiln API 에러 (${err.status}): ${err.message}` } });
  }
  // 우리 코드가 던진 에러 (InputError, SettlementInputError, KilnConfigError, AgentOutputError 등)
  if (err.code && err.status) {
    return res.status(err.status).json({ error: { code: err.code, message: err.message } });
  }
  console.error(err);
  res.status(500).json({ error: { code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했어요.' } });
});

if (require.main === module) {
  const port = Number(process.env.PORT) || 3000;
  app.listen(port, (err) => {
    if (err) {
      // Express 5는 포트 충돌 등의 에러를 여기로 넘긴다 — 무시하면 "성공"처럼 보이고 조용히 꺼짐
      if (err.code === 'EADDRINUSE') {
        console.error(`❌ ${port}번 포트를 이미 다른 프로그램이 쓰고 있어요.`);
        console.error('   → 다른 터미널에서 켜 둔 서버를 Ctrl+C로 끄거나, backend/.env의 PORT를 다른 번호로 바꾸세요.');
      } else {
        console.error('❌ 서버를 시작하지 못했어요:', err.message);
      }
      process.exit(1);
    }
    console.log(`SharePie → http://localhost:${port}  (화면)`);
    console.log(`          http://localhost:${port}/health  (서버 상태)`);
    if (!process.env.KILN_API_KEY) console.warn('⚠️  KILN_API_KEY가 없어요. backend/.env를 만들어 주세요 (.env.example 참고).');
    if (!(process.env.KILN_MODEL || '').trim()) console.warn('⚠️  KILN_MODEL이 없어요. AI 호출(analyze/explain/investigate/search)은 503으로 거부돼요. backend/.env에 모델 ID를 넣어 주세요.');
  });
}

module.exports = app;
