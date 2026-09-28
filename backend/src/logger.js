'use strict';

// 토큰 사용량 로그 + 이벤트 로그 (CLAUDE.md 0번 원칙 3, 9번 제출용 로그)
// - logs/token-usage.jsonl : Kiln 호출 1회당 1줄 (stage 태그, input/output 토큰, cost)
// - logs/events.jsonl      : AI 응답, 계산 결과, 판정 근거, TxHash 등 데모 증빙

const fs = require('fs');
const path = require('path');

const STAGE_ORDER = ['settlement.analyze', 'settlement.calculate', 'settlement.explain', 'dispute.investigate', 'shopping.search'];

function logDir() {
  return process.env.LOG_DIR || path.join(__dirname, '..', 'logs');
}

function append(file, record) {
  try {
    fs.mkdirSync(logDir(), { recursive: true });
    fs.appendFileSync(path.join(logDir(), file), JSON.stringify({ ts: new Date().toISOString(), ...record }) + '\n');
  } catch (err) {
    console.error(`[logger] ${file} 기록 실패:`, err.message);
  }
}

function logTokenUsage(record) {
  append('token-usage.jsonl', record);
  if (process.env.NODE_ENV !== 'test') {
    console.log(`[tokens] ${record.stage} #${record.attempt ?? 1}: in=${record.promptTokens ?? '?'} out=${record.completionTokens ?? '?'} cost=${record.cost ?? '?'}${record.ok === false ? ' (FAILED)' : ''}`);
  }
}

function logCodeOnlyStage(stage) {
  append('token-usage.jsonl', { stage, promptTokens: 0, completionTokens: 0, totalTokens: 0, cost: 0, ok: true, note: 'code-only' });
  if (process.env.NODE_ENV !== 'test') console.log(`[tokens] ${stage}: 0 tokens (code-only)`);
}

function logEvent(type, data) {
  append('events.jsonl', { type, ...data });
}

// 흐름(stage)별 토큰 합계 — 챌린지 A "흐름별 토큰 사용량 보고"용
function summarizeTokenUsage() {
  const file = path.join(logDir(), 'token-usage.jsonl');
  const summary = {};
  STAGE_ORDER.forEach((s) => { summary[s] = { calls: 0, promptTokens: 0, completionTokens: 0, totalTokens: 0, cost: 0 }; });
  if (!fs.existsSync(file)) return summary;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let r;
    try { r = JSON.parse(line); } catch { continue; }
    const s = (summary[r.stage] ??= { calls: 0, promptTokens: 0, completionTokens: 0, totalTokens: 0, cost: 0 });
    if (r.ok === false) {
      s.failedCalls = (s.failedCalls || 0) + 1; // 네트워크/인증 실패 등 — 토큰 미사용
      continue;
    }
    s.calls += 1;
    s.promptTokens += r.promptTokens || 0;
    s.completionTokens += r.completionTokens || 0;
    s.totalTokens += r.totalTokens || 0;
    s.cost += r.cost || 0;
  }
  return summary;
}

module.exports = { logTokenUsage, logCodeOnlyStage, logEvent, summarizeTokenUsage, STAGE_ORDER };
