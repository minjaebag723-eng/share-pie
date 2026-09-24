'use strict';

// Stage 1 — 자연어 비용분담 조건 → JSON 구조화 (AI, stage 태그: settlement.analyze)
// AI는 "이해"만 한다. shares(1인 금액)는 AI가 아니라 calculateSettlement(코드)가 채운다.
// 출력 = UI 확인 카드의 confirmData 모양 { mode, itemName, total, participants, ratios, adjustments, items }
//   → UI의 parseSettlementText(규칙 기반 임시 해석)를 이 API로 바꾸면 된다.
// 다턴 처리: previousState(직전 응답 또는 그룹의 {members})를 받아 최신 상태 전체를 다시 구조화.

const { callKilnJson } = require('../kilnClient');
const { calculateSettlement, SettlementInputError, MODES } = require('../settlement/calculateSettlement');
const { logEvent } = require('../logger');
const { InputError } = require('../errors');

const SYSTEM_PROMPT = `너는 정산 서비스 SharePie의 "조건 구조화" 담당이다.
사용자의 자연어 비용분담 조건을 아래 JSON 형식으로만 변환한다.

[출력 규칙 — 반드시 지킬 것]
- 반드시 JSON 객체 하나만 출력한다. 설명, 인사말, 마크다운, 코드펜스를 절대 붙이지 않는다.
- 형식:
{
  "needsClarification": false,
  "clarificationQuestion": null,
  "mode": "EQUAL",
  "itemName": "삼겹살",
  "total": 35900,
  "participants": "all",
  "ratios": null,
  "adjustments": null,
  "items": null,
  "members": ["진주","진우","민재","지현"],
  "totalBudget": null,
  "payer": null
}

[mode — 아래 4개 중 하나만]
- "EQUAL"  균등: "다같이 나눠", "N빵"                     → total 필수
- "RATIO"  비율: "진주 40%, 나머지 균등"                   → total 필수, ratios에 말한 사람의 %만 { "진주": 40 }
- "ADJUST" 차등: "진주는 5천원 적게", "진우는 3천원 더"    → total 필수, adjustments에 { "진주": -5000, "진우": 3000 }
                 (적게/덜/빼줘 = 음수, 더/많이 = 양수)
- "ITEM"   항목별: 품목이 2개 이상이고 품목마다 금액이 있을 때
           → items: [ { "name": "삼겹살", "price": 35900, "participants": "all" }, { "name": "술", "price": 12000, "participants": ["진우","민재"] } ]
           → total은 null (합계는 코드가 계산한다)
- 여러 방식을 한 번에 섞은 조건(예: 항목별 + 특정인 감면)은 지원하지 않으므로 needsClarification을 true로 하고 한 가지 방식으로 정리해 달라고 묻는다.

[필드 규칙]
- 금액은 모두 원 단위 정수로 쓴다 ("3만 5천원" → 35000, "35,900원" → 35900).
- 너는 계산을 하지 않는다. 문장에 적힌 숫자만 그대로 옮겨 적는다.
  합계·차액·1인당 금액·나머지 사람의 비율을 계산하지 않는다. "shares" 같은 1인 금액 필드를 만들지 않는다.
  금액을 알려면 계산이 필요한 경우(예: "총액의 절반")에는 needsClarification을 true로 한다.
- itemName: 무엇에 대한 비용인지 짧게 ("삼겹살", "숙소비"). ITEM이면 "여러 품목".
- participants: 전원이면 "all". "OO 빼고", "OO 제외"면 그 사람을 뺀 이름 배열.
- members: [현재 멤버]가 주어지면 그 이름과 순서를 그대로 쓴다. 목록에 없는 사람이 언급되면 needsClarification을 true로 한다.
  "나", "내가", "저"는 members의 첫 번째 사람이다.
- ratios / adjustments / items: 해당 mode가 아니면 null.
- totalBudget: "40만원 넘으면 안 돼"처럼 전체 상한이 명시된 경우만 쓰고, 없으면 null.
- payer: "진우가 결제했어"처럼 먼저 돈을 낸 사람이 명시된 경우만 쓰고, 없으면 null. 추측하지 않는다.

[모호한 조건]
- 금액이 없는 경우, "조금 더", "적당히"처럼 해석이 갈리는 표현이 있으면 임의로 정하지 않는다.
  "needsClarification": true, "clarificationQuestion": "한 문장 질문" 으로 답하고 나머지 필드는 알 수 있는 만큼만 채운다.
  예) "'조금 더'가 정확히 몇 원인가요?"

[대화 중 조건 변경]
- [이전 상태]가 주어지면 그 상태를 유지한 채 이번 발언의 변경 사항만 반영해서, 최신 상태 전체를 다시 출력한다.
  (예: 이전 EQUAL 35900 + "진주는 5천원 적게 내자" → mode ADJUST, total 35900 유지, adjustments { "진주": -5000 })`;

function isPositiveInt(v) {
  return Number.isSafeInteger(v) && v > 0;
}

function isNameList(v) {
  return Array.isArray(v) && v.length > 0 && v.every((n) => typeof n === 'string' && n.trim()) && new Set(v).size === v.length;
}

const EMPTY_CONFIRM = { mode: null, itemName: null, total: null, participants: [], ratios: null, adjustments: null, items: null };

// 프론트가 넘긴 previousState 정리 (직전 analyze 응답 또는 그룹 데이터 {members, shares})
function normalizePreviousState(previousState) {
  if (previousState === null || previousState === undefined) {
    return { members: [], confirmData: null, totalBudget: null, payer: null, shares: null };
  }
  if (typeof previousState !== 'object' || Array.isArray(previousState)) throw new InputError('previousState는 객체여야 해요.');
  const { members = [], confirmData = null, totalBudget = null, payer = null, shares = null } = previousState;
  if (members.length && !isNameList(members)) throw new InputError('previousState.members는 중복 없는 이름 배열이어야 해요.');
  if (confirmData !== null && (typeof confirmData !== 'object' || Array.isArray(confirmData))) throw new InputError('previousState.confirmData는 객체여야 해요.');
  const validShares = Array.isArray(shares) && shares.length === members.length && shares.every((v) => Number.isSafeInteger(v) && v >= 0);
  return { members, confirmData: confirmData && confirmData.mode ? confirmData : null, totalBudget, payer, shares: validShares ? shares : null };
}

function checkNames(list, allowed, label, errors) {
  list.filter((n) => !allowed.has(n)).forEach((n) => errors.push(`${label}의 "${n}"은(는) members에 없습니다`));
}

// AI 응답 형식 검증 → { ok, value } 또는 { ok:false, errors }
function validateInterpretation(raw, knownMembers) {
  const errors = [];
  if (typeof raw.needsClarification !== 'boolean') errors.push('needsClarification은 true 또는 false여야 합니다');

  if (raw.needsClarification === true) {
    if (typeof raw.clarificationQuestion !== 'string' || !raw.clarificationQuestion.trim()) {
      errors.push('needsClarification이 true이면 clarificationQuestion에 질문 문장이 있어야 합니다');
    }
    return errors.length ? { ok: false, errors } : { ok: true, value: { needsClarification: true, clarificationQuestion: raw.clarificationQuestion.trim() } };
  }

  let members = raw.members;
  if (knownMembers.length) {
    if (members != null && !(isNameList(members) && members.length === knownMembers.length && members.every((m) => knownMembers.includes(m)))) {
      errors.push(`members는 현재 멤버 [${knownMembers.join(', ')}]와 정확히 같아야 합니다. 목록에 없는 사람이 있으면 needsClarification을 true로 하세요`);
    }
    members = [...knownMembers]; // UI의 approvals 배열과 인덱스가 맞도록 순서 고정
  } else if (!isNameList(members)) {
    errors.push('members는 중복 없는 이름 배열이어야 합니다');
  }
  const memberSet = new Set(isNameList(members) ? members : []);

  if (!MODES.includes(raw.mode)) errors.push(`mode는 ${MODES.join(' / ')} 중 하나여야 합니다`);

  let participants = raw.participants ?? 'all';
  if (participants !== 'all') {
    if (!isNameList(participants)) errors.push('participants는 "all" 또는 중복 없는 이름 배열이어야 합니다');
    else checkNames(participants, memberSet, 'participants', errors);
  }
  const partSet = participants === 'all' || !isNameList(participants) ? memberSet : new Set(participants);

  const value = { needsClarification: false, clarificationQuestion: null, ...EMPTY_CONFIRM, mode: raw.mode, members };

  if (raw.mode === 'ITEM') {
    if (!Array.isArray(raw.items) || raw.items.length < 1) {
      errors.push('ITEM이면 items는 1개 이상인 배열이어야 합니다');
    } else {
      raw.items.forEach((it, i) => {
        if (!it || typeof it.name !== 'string' || !it.name.trim()) errors.push(`items[${i}].name이 비어 있습니다`);
        if (!it || !isPositiveInt(it.price)) errors.push(`items[${i}].price는 원 단위 양의 정수여야 합니다`);
        if (it && it.participants != null && it.participants !== 'all') {
          if (!isNameList(it.participants)) errors.push(`items[${i}].participants는 "all" 또는 중복 없는 이름 배열이어야 합니다`);
          else checkNames(it.participants, partSet, `items[${i}].participants`, errors);
        }
      });
    }
  } else if (MODES.includes(raw.mode)) {
    if (!isPositiveInt(raw.total)) errors.push(`${raw.mode}이면 total은 원 단위 양의 정수여야 합니다. 금액을 모르면 needsClarification을 true로 하세요`);
  }

  if (raw.mode === 'RATIO') {
    const r = raw.ratios;
    if (!r || typeof r !== 'object' || Array.isArray(r) || !Object.keys(r).length) errors.push('RATIO면 ratios는 { "이름": 퍼센트 } 객체여야 합니다');
    else {
      checkNames(Object.keys(r), partSet, 'ratios', errors);
      Object.entries(r).forEach(([n, v]) => { if (typeof v !== 'number' || !(v > 0)) errors.push(`ratios.${n}는 0보다 큰 숫자여야 합니다`); });
    }
  }
  if (raw.mode === 'ADJUST') {
    const a = raw.adjustments;
    if (!a || typeof a !== 'object' || Array.isArray(a) || !Object.keys(a).length) errors.push('ADJUST면 adjustments는 { "이름": ±원 } 객체여야 합니다');
    else {
      checkNames(Object.keys(a), partSet, 'adjustments', errors);
      Object.entries(a).forEach(([n, v]) => { if (!Number.isSafeInteger(v) || v === 0) errors.push(`adjustments.${n}는 0이 아닌 정수여야 합니다 (적게 = 음수, 더 = 양수)`); });
    }
  }

  const totalBudget = raw.totalBudget ?? null;
  if (totalBudget !== null && !isPositiveInt(totalBudget)) errors.push('totalBudget은 null 또는 원 단위 양의 정수여야 합니다');
  const payer = raw.payer ?? null;
  if (payer !== null && !memberSet.has(payer)) errors.push('payer는 null 또는 members 중 한 명이어야 합니다');

  if (errors.length) return { ok: false, errors };

  const allOf = (p) => (p == null || p === 'all' ? [...partSet] : [...p]);
  value.participants = participants === 'all' ? [...members] : members.filter((m) => participants.includes(m));
  value.itemName = typeof raw.itemName === 'string' && raw.itemName.trim() ? raw.itemName.trim() : null;
  if (raw.mode === 'ITEM') value.items = raw.items.map((it) => ({ name: it.name.trim(), price: it.price, participants: allOf(it.participants) }));
  else value.total = raw.total;
  if (raw.mode === 'RATIO') value.ratios = { ...raw.ratios };
  if (raw.mode === 'ADJUST') value.adjustments = { ...raw.adjustments };
  value.totalBudget = totalBudget;
  value.payer = payer;
  return { ok: true, value };
}

function clarificationResponse(question, prev) {
  return {
    needsClarification: true,
    clarificationQuestion: question,
    confirmData: prev.confirmData,
    members: prev.members,
    // 되묻는 동안 UI 표시가 깨지지 않도록 직전 금액(없으면 0) 유지
    shares: prev.shares ?? prev.members.map(() => 0),
    totalBudget: prev.totalBudget,
    payer: prev.payer,
    calculation: null,
  };
}

async function interpretConditions(text, previousState = null) {
  if (typeof text !== 'string' || !text.trim()) throw new InputError('text(자연어 조건)가 비어 있어요.');
  if (text.length > 2000) throw new InputError('text는 2,000자 이하로 보내 주세요.');
  const prev = normalizePreviousState(previousState);

  const user = JSON.stringify({
    '현재 멤버': prev.members.length ? prev.members : '(아직 없음 — 문장에서 파악)',
    '이전 상태': prev.confirmData ? { ...prev.confirmData, totalBudget: prev.totalBudget, payer: prev.payer } : null,
    '이번 발언': text.trim(),
  });

  const ai = await callKilnJson({
    stage: 'settlement.analyze',
    system: SYSTEM_PROMPT,
    user,
    validate: (raw) => validateInterpretation(raw, prev.members),
  });

  if (ai.needsClarification) {
    logEvent('settlement.analyze', { text, previousState: prev, ai });
    return clarificationResponse(ai.clarificationQuestion, prev);
  }

  let calculation;
  try {
    calculation = calculateSettlement(ai);
  } catch (err) {
    if (!(err instanceof SettlementInputError)) throw err;
    logEvent('settlement.analyze', { text, previousState: prev, ai, calculationError: err.message });
    return clarificationResponse(`${err.message} 조건을 다시 알려주세요.`, prev);
  }

  logEvent('settlement.analyze', { text, previousState: prev, ai, calculation });
  return {
    needsClarification: false,
    clarificationQuestion: null,
    // UI 확인 카드에 그대로 넣는 값 (ITEM의 total은 코드가 합산한 값)
    confirmData: {
      mode: calculation.mode,
      itemName: calculation.itemName,
      total: calculation.total,
      participants: calculation.participants,
      ratios: calculation.ratios,
      adjustments: calculation.adjustments,
      items: calculation.items && calculation.items.map(({ name, price, participants }) => ({ name, price, participants })),
    },
    members: calculation.members,
    shares: calculation.shares,
    totalBudget: calculation.totalBudget,
    payer: calculation.payer,
    calculation,
  };
}

module.exports = { interpretConditions, validateInterpretation, normalizePreviousState, SYSTEM_PROMPT };
