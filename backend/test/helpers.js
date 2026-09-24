'use strict';

// 테스트 공통: 로그는 임시 폴더로, Kiln 호출은 가짜 응답으로 대체
const fs = require('fs');
const os = require('os');
const path = require('path');

process.env.NODE_ENV = 'test';
process.env.LOG_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'sharepie-test-'));

const kiln = require('../src/kilnClient');
const realChatCompletion = kiln.chatCompletion;

// responses: 문자열 배열 — 호출될 때마다 순서대로 돌려줌. 호출 기록은 calls에 쌓임
function fakeKiln(responses) {
  const calls = [];
  kiln.chatCompletion = async ({ stage, messages, attempt }) => {
    calls.push({ stage, attempt, messages: messages.map((m) => ({ ...m })) });
    const content = responses[Math.min(calls.length - 1, responses.length - 1)];
    return { content, usage: { prompt_tokens: 10, completion_tokens: 5 } };
  };
  return calls;
}

function restoreKiln() {
  kiln.chatCompletion = realChatCompletion;
}

function readLog(file) {
  const p = path.join(process.env.LOG_DIR, file);
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
}

module.exports = { fakeKiln, restoreKiln, readLog };
