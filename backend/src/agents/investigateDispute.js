'use strict';

// Dispute 모듈 — 오송금 분쟁 조사·판정 (AI, stage 태그: dispute.investigate)
// 역할 분담
// - 코드(compareRecords): 4가지 기록 비교 → 불일치 여부·지점·금액·차액 계산
// - AI: 코드가 찾은 사실을 근거로 3가지 판정 중 하나 선택 + 자연어 설명
// 판정은 CLAUDE.md 7번의 3개만 허용. GENUINE_ERROR는 자동 환불로 이어지므로
// 코드가 찾은 사실과 모순되는 판정은 받아들이지 않는다.

const { callKilnJson } = require('../kilnClient');
const { compareRecords } = require('../dispute/compareRecords');
const { logEvent } = require('../logger');
const { findUnverifiedNumbers } = require('../utils/format');

const VERDICTS = ['NORMAL_APPROVAL', 'GENUINE_ERROR', 'BAD_FAITH_DISPUTE'];

const SYSTEM_PROMPT = `너는 정산 서비스 SharePie의 "분쟁 조사" 담당이다.
코드가 최초요청·정산안·승인기록·실제송금을 비교해 찾은 사실(facts)과 원본 기록, 이의제기 내용을 받는다.
이를 근거로 판정을 내리고 멤버들이 이해할 수 있게 설명한다.

[출력 규칙 — 반드시 지킬 것]
- 반드시 JSON 객체 하나만 출력한다: { "verdict": "...", "explanation": "..." }
- 설명, 인사말, 마크다운, 코드펜스를 JSON 밖에 절대 붙이지 않는다.

[판정 — 아래 3개 중 하나만 사용]
- "GENUINE_ERROR": facts.mismatchDetected가 true (기록끼리 금액이 실제로 다름) → 진짜 착오·오류.
- "NORMAL_APPROVAL": facts.mismatchDetected가 false이고, 이의제기가 착각·오해로 보임 → 정상 승인, 정산 유지.
- "BAD_FAITH_DISPUTE": facts.mismatchDetected가 false인데, 이의제기 내용이 기록(승인 txHash, 송금 내역)과
  명백히 모순되어 고의로 보임 (예: 승인 기록이 있는데 승인한 적 없다고 주장) → 악의적 이의제기.
- mismatchDetected가 true면 반드시 GENUINE_ERROR, false면 GENUINE_ERROR를 쓰지 않는다.

[설명 규칙]
- 2~3문장, 친근한 존댓말. 어느 단계(facts.mismatchPoint)에서 누구(facts.mismatchMember)의 금액이 얼마나 달랐는지 설명한다.
- 너는 계산을 하지 않는다. facts에 있는 숫자(expectedAmount, actualAmount, difference 등)만 그대로 쓴다.
- 금액은 "45,000원"처럼 숫자와 쉼표로 쓴다. "4만 5천원" 같은 표기는 쓰지 않는다.
- 불일치가 없으면 기록상 문제가 없는 이유와 판정 근거를 설명한다.`;

function allowedNumbers(facts, records) {
  return [
    facts.expectedAmount,
    facts.actualAmount,
    facts.difference,
    ...facts.mismatches.flatMap((x) => [x.expectedAmount, x.actualAmount, x.difference, Math.abs(x.difference)]),
    ...facts.perMember.flatMap((r) => [r.planned, r.approved, r.transferred]),
    ...records.flatMap((r) => r.map((x) => x.amount)),
    Math.abs(facts.difference ?? 0),
  ].filter((v) => typeof v === 'number');
}

function validateVerdict(raw, facts, allowed) {
  const errors = [];
  if (!VERDICTS.includes(raw.verdict)) errors.push(`verdict는 ${VERDICTS.join(' / ')} 중 하나여야 합니다`);
  else if (facts.mismatchDetected && raw.verdict !== 'GENUINE_ERROR') errors.push('facts.mismatchDetected가 true이므로 verdict는 GENUINE_ERROR여야 합니다');
  else if (!facts.mismatchDetected && raw.verdict === 'GENUINE_ERROR') errors.push('facts.mismatchDetected가 false이므로 GENUINE_ERROR를 쓸 수 없습니다');
  if (typeof raw.explanation !== 'string' || !raw.explanation.trim()) errors.push('explanation 문자열이 필요합니다');
  else errors.push(...findUnverifiedNumbers(raw.explanation, allowed));
  return errors.length ? { ok: false, errors } : { ok: true, value: { verdict: raw.verdict, explanation: raw.explanation.trim() } };
}

// dispute(선택): { raisedBy, reason } — 누가 무슨 이유로 이의제기했는지 (악의 여부 판단 근거)
async function investigateDispute(originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute = null) {
  const facts = compareRecords({ originalRequest, settlementPlan, approvalRecord, actualTransfer, dispute });
  const allowed = allowedNumbers(facts, [approvalRecord, actualTransfer]);

  const ai = await callKilnJson({
    stage: 'dispute.investigate',
    system: SYSTEM_PROMPT,
    user: JSON.stringify({
      facts,
      dispute: dispute || { raisedBy: null, reason: null },
      records: { originalRequest: originalRequest ?? null, settlementPlan, approvalRecord, actualTransfer },
    }),
    validate: (raw) => validateVerdict(raw, facts, allowed),
  });

  const result = {
    verdict: ai.verdict,
    mismatchDetected: facts.mismatchDetected,
    mismatchPoint: facts.mismatchPoint,
    expectedAmount: facts.expectedAmount,
    actualAmount: facts.actualAmount,
    explanation: ai.explanation,
  };
  logEvent('dispute.investigate', { dispute, facts, result, records: { originalRequest, settlementPlan, approvalRecord, actualTransfer } });
  return result;
}

module.exports = { investigateDispute, validateVerdict, VERDICTS, SYSTEM_PROMPT };
