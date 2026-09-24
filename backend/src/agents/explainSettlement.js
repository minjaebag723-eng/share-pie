'use strict';

// Stage 3 — 코드가 계산한 정산 결과를 자연어로 설명 (AI, stage 태그: settlement.explain)
// AI가 새 금액을 만들어내지 못하도록, 설명 속 숫자가 계산 결과에 있는 숫자인지 코드로 검사한다.
// AI가 끝내 규칙을 못 지키면 코드 템플릿 설명으로 대체한다 (정산 흐름이 멈추지 않도록).

const { callKilnJson } = require('../kilnClient');
const { logEvent } = require('../logger');
const { won, findUnverifiedNumbers } = require('../utils/format');
const { InputError } = require('../errors');

const SYSTEM_PROMPT = `너는 정산 서비스 SharePie의 "정산 결과 설명" 담당이다.
코드가 이미 정확히 계산한 결과(JSON)를 받아, 모임 멤버들이 읽을 짧은 한국어 설명을 쓴다.

[출력 규칙 — 반드시 지킬 것]
- 반드시 JSON 객체 하나만 출력한다: { "explanation": "설명 문장" }
- 설명, 인사말, 마크다운, 코드펜스를 JSON 밖에 절대 붙이지 않는다.

[설명 규칙]
- 2~4문장, 친근한 존댓말.
- 너는 계산을 하지 않는다. 입력 JSON에 있는 숫자만 그대로 쓰고, 합계·차액·1인당 금액을 새로 계산하지 않는다.
- 금액은 "45,000원"처럼 숫자와 쉼표로 쓴다. "4만 5천원" 같은 표기는 쓰지 않는다.
- 포함할 내용: 무엇에 대한 비용인지(itemName), 어떤 방식으로 나눴는지(modeLabel, rule),
  멤버별 금액(members와 shares는 같은 순서로 짝지어짐, 0원인 사람은 이번 정산에서 빠진 사람),
  예산(totalBudget)이 있으면 예산 안인지(withinBudget, 초과 시 overBudgetBy).
  totalBudget이 null이면 예산이 정해지지 않은 것이므로 "예산"이라는 말을 아예 쓰지 않는다.
- 1원 단위로 나누어떨어지지 않으면 몇 명이 1원씩 더 낼 수 있다. 이 차이를 굳이 계산해서 설명하지 않는다.`;

function validateCalculation(c) {
  if (!c || typeof c !== 'object') throw new InputError('calculatedResult가 비어 있어요.');
  if (!Array.isArray(c.members) || !Array.isArray(c.shares) || c.members.length !== c.shares.length || c.members.length === 0) {
    throw new InputError('calculatedResult.members와 shares는 길이가 같은 배열이어야 해요. /settlement/calculate 결과를 그대로 보내 주세요.');
  }
  if (!Number.isSafeInteger(c.total)) throw new InputError('calculatedResult.total이 없어요. /settlement/calculate 결과를 그대로 보내 주세요.');
}

function numbersIn(text) {
  return [...String(text ?? '').matchAll(/\d[\d,]*/g)].map((m) => Number(m[0].replace(/,/g, '')));
}

function allowedNumbers(c) {
  return [
    ...numbersIn(c.rule),
    ...numbersIn(c.itemName),
    ...(c.items || []).flatMap((it) => numbersIn(it.name)), // "2026 MT 회비" 같은 항목 이름 속 숫자
    ...c.shares,
    c.total,
    c.totalBudget,
    c.overBudgetBy,
    ...(c.items || []).flatMap((it) => [it.price, ...(it.shares || [])]),
    ...Object.values(c.adjustments || {}).flatMap((d) => [d, Math.abs(d)]),
    ...Object.values(c.ratios || {}).flatMap((p) => [p, Math.round(p), Math.round(p * 10) / 10]),
  ].filter((v) => typeof v === 'number');
}

function fallbackExplanation(c) {
  const list = c.members.map((m, i) => `${m} ${won(c.shares[i])}`).join(', ');
  let text = `${c.itemName ? c.itemName + ' ' : ''}총 ${won(c.total)}을 '${c.rule}' 규칙으로 나눴어요. ${list}입니다.`;
  if (c.totalBudget !== null && c.totalBudget !== undefined) {
    text += c.withinBudget ? ` 예산 ${won(c.totalBudget)} 안이에요.` : ` 예산 ${won(c.totalBudget)}을 ${won(c.overBudgetBy)} 초과했어요.`;
  }
  return text;
}

async function explainSettlement(calculatedResult) {
  validateCalculation(calculatedResult);
  const allowed = allowedNumbers(calculatedResult);

  try {
    const { explanation } = await callKilnJson({
      stage: 'settlement.explain',
      system: SYSTEM_PROMPT,
      user: JSON.stringify(calculatedResult),
      validate: (raw) => {
        if (typeof raw.explanation !== 'string' || !raw.explanation.trim()) return { ok: false, errors: ['explanation 문자열이 필요합니다'] };
        const problems = findUnverifiedNumbers(raw.explanation, allowed);
        return problems.length ? { ok: false, errors: problems } : { ok: true, value: { explanation: raw.explanation.trim() } };
      },
    });
    logEvent('settlement.explain', { calculatedResult, explanation, fallback: false });
    return { explanation, fallback: false };
  } catch (err) {
    if (err.code !== 'AI_OUTPUT_INVALID') throw err;
    const explanation = fallbackExplanation(calculatedResult);
    logEvent('settlement.explain', { calculatedResult, explanation, fallback: true, reason: err.message });
    return { explanation, fallback: true };
  }
}

module.exports = { explainSettlement, fallbackExplanation, SYSTEM_PROMPT };
