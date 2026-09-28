'use strict';

// Kiln API 공용 클라이언트 (CLAUDE.md 4번 스펙 그대로)
// - OpenAI SDK + baseURL만 Kiln으로 변경, /chat/completions 사용
// - 모든 호출에 stage 태그 필수, 호출마다 input/output 토큰 로깅
// - Kiln은 response_format(json_object/json_schema)을 지원하지 않는다 (보내면 빈 응답이 옴 — 공식 문서
//   Known limitations). 그래서 절대 보내지 않고, "JSON만 출력" 프롬프트 + 파싱/검증 + 재요청으로 방어한다.

const OpenAI = require('openai');
const { logTokenUsage, logEvent } = require('./logger');

const DEFAULT_BASE_URL = 'https://api.bricksum.com/v1';
// 모델명은 코드에 두지 않는다 (CLAUDE.md 11번) — KILN_MODEL 환경변수로만 참조. 비어 있으면 호출 자체를 거부한다.
const MAX_RETRIES = 3; // 파싱/검증 실패 시 재요청 횟수 (최초 1회 + 재요청 3회)
const STAGES = new Set(['settlement.analyze', 'settlement.explain', 'dispute.investigate', 'shopping.search']);

class KilnConfigError extends Error {
  constructor(message = 'KILN_API_KEY가 설정되지 않았어요. backend/.env 파일을 확인하세요.') {
    super(message);
    this.name = 'KilnConfigError';
    this.code = 'KILN_NOT_CONFIGURED';
    this.status = 503;
  }
}

class AgentOutputError extends Error {
  constructor(stage, errors) {
    super(`[${stage}] AI 응답이 ${MAX_RETRIES + 1}회 연속 형식 검증에 실패했어요: ${errors.join(' / ')}`);
    this.name = 'AgentOutputError';
    this.code = 'AI_OUTPUT_INVALID';
    this.status = 502;
    this.stage = stage;
    this.errors = errors;
  }
}

let client = null;

function getClient() {
  if (!process.env.KILN_API_KEY) throw new KilnConfigError();
  if (!client) {
    client = new OpenAI({
      apiKey: process.env.KILN_API_KEY,
      baseURL: process.env.KILN_BASE_URL || DEFAULT_BASE_URL,
      timeout: 60_000,
      maxRetries: 2, // 네트워크/429/5xx 재시도 (SDK 기본 동작)
    });
  }
  return client;
}

async function chatCompletion({ stage, messages, attempt = 1 }) {
  if (!STAGES.has(stage)) throw new Error(`알 수 없는 stage 태그: ${stage}`);
  const model = (process.env.KILN_MODEL || '').trim();
  if (!model) throw new KilnConfigError('KILN_MODEL이 설정되지 않았어요. backend/.env에 사용할 Kiln 모델 ID를 넣어 주세요 (CLAUDE.md 4번 참고).');
  const params = { model, messages, temperature: 0 };

  const started = Date.now();
  let res;
  try {
    res = await getClient().chat.completions.create(params);
  } catch (err) {
    logTokenUsage({ stage, attempt, model, promptTokens: null, completionTokens: null, totalTokens: null, cost: null, ok: false, error: err.message, latencyMs: Date.now() - started });
    throw err;
  }

  const usage = res.usage || {};
  logTokenUsage({
    stage,
    attempt,
    model: res.model || model,
    promptTokens: usage.prompt_tokens ?? null,
    completionTokens: usage.completion_tokens ?? null,
    totalTokens: usage.total_tokens ?? null,
    cost: usage.cost ?? null,
    latencyMs: Date.now() - started,
    ok: true,
  });
  return { content: res.choices?.[0]?.message?.content ?? '', usage };
}

// 모델 응답 문자열에서 JSON 객체 하나를 꺼낸다.
// <think> 블록, ```json 코드펜스, 앞뒤 잡담이 섞여 있어도 처리.
function extractJson(text) {
  if (typeof text !== 'string' || !text.trim()) throw new Error('빈 응답');
  let s = text.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
  const fence = s.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) s = fence[1].trim();

  const asObject = (v) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) throw new Error('JSON 객체가 아님');
    return v;
  };
  try {
    return asObject(JSON.parse(s));
  } catch {
    const start = s.indexOf('{');
    const end = s.lastIndexOf('}');
    if (start === -1 || end <= start) throw new Error('JSON 객체를 찾을 수 없음');
    return asObject(JSON.parse(s.slice(start, end + 1)));
  }
}

// JSON을 받아야 하는 모든 AI 호출의 공통 루틴:
// 호출 → JSON 추출 → validate → 실패 시 에러 로그 + 문제점을 알려주며 재요청
async function callKilnJson({ stage, system, user, validate, maxRetries = MAX_RETRIES }) {
  const messages = [
    { role: 'system', content: system },
    { role: 'user', content: user },
  ];
  let lastErrors = [];

  for (let attempt = 1; attempt <= maxRetries + 1; attempt++) {
    const { content } = await module.exports.chatCompletion({ stage, messages, attempt });

    let parsed = null;
    try {
      parsed = extractJson(content);
    } catch (err) {
      lastErrors = [`JSON 파싱 실패 (${err.message})`];
      console.error(`[kiln] ${stage} #${attempt} JSON 파싱 실패: ${err.message}`);
      logEvent('ai.parse_error', { stage, attempt, error: err.message, raw: String(content).slice(0, 2000) });
    }

    if (parsed) {
      const result = validate(parsed);
      if (result.ok) return result.value;
      lastErrors = result.errors;
      console.error(`[kiln] ${stage} #${attempt} 형식 검증 실패: ${result.errors.join(' / ')}`);
      logEvent('ai.validation_error', { stage, attempt, errors: result.errors, raw: parsed });
    }

    messages.push({ role: 'assistant', content: content || '(빈 응답)' });
    messages.push({
      role: 'user',
      content: `직전 응답에 문제가 있습니다:\n- ${lastErrors.join('\n- ')}\n설명 없이 규칙에 맞는 JSON 객체 하나만 다시 출력하세요.`,
    });
  }
  throw new AgentOutputError(stage, lastErrors);
}

module.exports = { chatCompletion, callKilnJson, extractJson, KilnConfigError, AgentOutputError, MAX_RETRIES };
