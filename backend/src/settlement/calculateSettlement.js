'use strict';

// Stage 2 — 정산 금액 계산 (순수 코드, AI 미사용, token 0)
// CLAUDE.md 0번 원칙 2: 금액 계산은 절대 AI가 하지 않는다.
//
// 입력 모양 = UI(Share_Pie_dc.html) 확인 카드의 confirmData + 그룹 members
//   { members, mode, itemName, total, participants, ratios, adjustments, items, totalBudget, payer }
//
// 정산 방식 4가지 (UI와 동일)
//   EQUAL  균등    — total을 participants가 똑같이
//   RATIO  비율    — ratios {이름: %}. 비율을 말하지 않은 참여자는 (100 - 말한 비율 합)을 똑같이 나눠 가짐
//   ADJUST 차등    — adjustments {이름: ±원}. n·X + Σdelta = total 이 되는 공통값 X에 각자 delta를 더함
//                    예) 35,900원 4명, 진주 -5,000 → X = 10,225 → 진주 5,225 / 나머지 10,225
//   ITEM   항목별  — items [{ name, price, participants }] 품목마다 그 참여자끼리 나눈 뒤 합산
//
// 원 단위: 1원 단위 + 최대잉여법(Largest Remainder Method) — UI의 distributeRemainder와 한 줄 한 줄 같은 방식.
//   각자 내림한 뒤 모자란 원을 소수점이 큰 사람부터 1원씩(동점이면 members 순서). 합계는 항상 total과 정확히 일치.
//   → UI 확인 카드에서 본 금액 = 서버가 승인 때 다시 계산한 금액.

const { logCodeOnlyStage } = require('../logger');
const { won } = require('../utils/format');

const MODES = ['EQUAL', 'RATIO', 'ADJUST', 'ITEM'];
const MODE_LABELS = { EQUAL: '균등 분배', RATIO: '비율 분배', ADJUST: '차등 분배', ITEM: '항목별 분배' };

class SettlementInputError extends Error {
  constructor(message) {
    super(message);
    this.name = 'SettlementInputError';
    this.code = 'INVALID_SETTLEMENT_INPUT';
    this.status = 400;
  }
}

function isPositiveInt(v) {
  return Number.isSafeInteger(v) && v > 0;
}

function isNameList(v) {
  return Array.isArray(v) && v.length > 0 && v.every((n) => typeof n === 'string' && n.trim()) && new Set(v).size === v.length;
}

// UI distributeRemainder(rawShares, total, 1)과 동일
function distributeRemainder(rawShares, total) {
  const floored = rawShares.map((s) => {
    const base = Math.floor(s.raw);
    return { name: s.name, base, remainder: s.raw - base };
  });
  let leftover = Math.round(total - floored.reduce((a, s) => a + s.base, 0));
  const sorted = [...floored].sort((a, b) => b.remainder - a.remainder); // 안정 정렬 → 동점이면 members 순서
  const map = new Map(floored.map((s) => [s.name, s.base]));
  for (let i = 0; i < sorted.length && leftover > 0; i++) { map.set(sorted[i].name, map.get(sorted[i].name) + 1); leftover--; }
  let i = 0;
  while (leftover < 0 && i < sorted.length) {
    const name = sorted[sorted.length - 1 - i].name;
    if (map.get(name) - 1 >= 0) { map.set(name, map.get(name) - 1); leftover++; }
    i++;
  }
  return rawShares.map((s) => ({ name: s.name, amount: map.get(s.name) }));
}

function subsetOf(list, members, label) {
  const unknown = list.filter((n) => !members.includes(n));
  if (unknown.length) throw new SettlementInputError(`${label}에 멤버가 아닌 이름이 있어요: ${unknown.join(', ')}`);
}

function validateInput(input) {
  if (!input || typeof input !== 'object') throw new SettlementInputError('정산 입력이 비어 있어요.');
  const { members, mode, itemName = null, totalBudget = null, payer = null } = input;

  if (!Array.isArray(members) || members.length === 0) throw new SettlementInputError('members가 비어 있어요.');
  if (members.some((m) => typeof m !== 'string' || !m.trim())) throw new SettlementInputError('members에 빈 이름이 있어요.');
  if (new Set(members).size !== members.length) throw new SettlementInputError('members에 중복된 이름이 있어요.');
  if (!MODES.includes(mode)) throw new SettlementInputError(`mode는 ${MODES.join(' / ')} 중 하나여야 해요.`);

  const participants = input.participants == null ? [...members] : input.participants;
  if (!isNameList(participants)) throw new SettlementInputError('participants는 중복 없는 이름 배열(1명 이상)이어야 해요.');
  subsetOf(participants, members, 'participants');

  if (totalBudget !== null && !isPositiveInt(totalBudget)) throw new SettlementInputError('totalBudget은 null 또는 1원 이상의 정수여야 해요.');
  if (payer !== null && !members.includes(payer)) throw new SettlementInputError(`payer '${payer}'이(가) 멤버가 아니에요.`);

  const base = { members: [...members], mode, itemName: typeof itemName === 'string' && itemName.trim() ? itemName.trim() : null, participants: members.filter((m) => participants.includes(m)), totalBudget, payer };

  if (mode === 'ITEM') {
    const { items } = input;
    if (!Array.isArray(items) || items.length === 0) throw new SettlementInputError('항목별 분배에는 items가 1개 이상 필요해요.');
    base.items = items.map((it, i) => {
      if (!it || typeof it.name !== 'string' || !it.name.trim()) throw new SettlementInputError(`items[${i}]의 name이 없어요.`);
      if (!isPositiveInt(it.price)) throw new SettlementInputError(`'${it.name}'의 금액(price)은 1원 이상의 정수여야 해요.`);
      const parts = it.participants == null ? base.participants : it.participants;
      if (!isNameList(parts)) throw new SettlementInputError(`'${it.name}'의 participants는 중복 없는 이름 배열이어야 해요.`);
      subsetOf(parts, base.participants, `'${it.name}'의 participants`);
      return { name: it.name.trim(), price: it.price, participants: members.filter((m) => parts.includes(m)) };
    });
    return base;
  }

  if (!isPositiveInt(input.total)) throw new SettlementInputError('total(총 금액)은 1원 이상의 정수여야 해요.');
  base.total = input.total;

  if (mode === 'RATIO') {
    const ratios = input.ratios;
    if (!ratios || typeof ratios !== 'object' || Array.isArray(ratios) || !Object.keys(ratios).length) throw new SettlementInputError('비율 분배에는 ratios({이름: %})가 필요해요.');
    subsetOf(Object.keys(ratios), base.participants, 'ratios');
    Object.entries(ratios).forEach(([n, v]) => {
      if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0) throw new SettlementInputError(`'${n}'의 비율은 0보다 큰 숫자여야 해요.`);
    });
    base.ratios = { ...ratios };
  }

  if (mode === 'ADJUST') {
    const adj = input.adjustments;
    if (!adj || typeof adj !== 'object' || Array.isArray(adj) || !Object.keys(adj).length) throw new SettlementInputError('차등 분배에는 adjustments({이름: ±원})가 필요해요.');
    subsetOf(Object.keys(adj), base.participants, 'adjustments');
    Object.entries(adj).forEach(([n, v]) => {
      if (!Number.isSafeInteger(v) || v === 0) throw new SettlementInputError(`'${n}'의 조정 금액은 0이 아닌 정수여야 해요 (적게 내면 음수, 더 내면 양수).`);
    });
    base.adjustments = { ...adj };
  }
  return base;
}

// 비율을 말하지 않은 참여자에게 (100 - 말한 비율 합)을 똑같이 배분 (UI parseSettlementText와 같은 규칙)
function resolveRatios(participants, ratios) {
  const named = participants.filter((p) => ratios[p] !== undefined);
  const rest = participants.filter((p) => ratios[p] === undefined);
  const namedSum = named.reduce((a, p) => a + ratios[p], 0);
  const resolved = {};
  named.forEach((p) => { resolved[p] = ratios[p]; });
  if (rest.length) {
    const each = (100 - namedSum) / rest.length;
    if (each <= 0) throw new SettlementInputError(`말한 비율 합이 ${namedSum}%라서 ${rest.join(', ')}의 몫이 없어요. 나머지 사람 비율도 알려주세요.`);
    rest.forEach((p) => { resolved[p] = each; });
  }
  return resolved;
}

function buildRule(c) {
  const excluded = c.members.filter((m) => !c.participants.includes(m));
  const exText = excluded.length ? ` (${excluded.join('·')} 제외)` : '';
  const n = c.participants.length;
  if (c.mode === 'EQUAL') return `${n}인 균등 분담${exText}`;
  if (c.mode === 'RATIO') return `비율 분배: ${c.participants.map((p) => `${p} ${Math.round(c.ratios[p] * 10) / 10}%`).join(', ')}${exText}`;
  if (c.mode === 'ADJUST') {
    const adj = Object.entries(c.adjustments).map(([p, d]) => `${p} ${won(Math.abs(d))} ${d < 0 ? '감면' : '추가'}`).join(', ');
    return `${adj} 후 ${n}인 분담${exText}`;
  }
  return '항목별 분담 (' + c.items.map((it) => `${it.name}: ${it.participants.length === c.members.length ? '전원' : it.participants.join('·')}`).join(', ') + ')';
}

// 로그 없이 계산만 하는 순수 함수 (테스트·재계산 검증·Shopping 비교용)
function computeSettlement(input) {
  const c = validateInput(input);
  let results;
  let total;

  if (c.mode === 'EQUAL') {
    total = c.total;
    results = distributeRemainder(c.participants.map((name) => ({ name, raw: total / c.participants.length })), total);
  } else if (c.mode === 'RATIO') {
    total = c.total;
    c.ratios = resolveRatios(c.participants, c.ratios);
    const sum = c.participants.reduce((a, p) => a + c.ratios[p], 0);
    results = distributeRemainder(c.participants.map((name) => ({ name, raw: (total * c.ratios[name]) / sum })), total);
  } else if (c.mode === 'ADJUST') {
    total = c.total;
    const deltaOf = (p) => c.adjustments[p] || 0;
    const X = (total - c.participants.reduce((a, p) => a + deltaOf(p), 0)) / c.participants.length;
    const raw = c.participants.map((name) => ({ name, raw: X + deltaOf(name) }));
    const negative = raw.filter((r) => r.raw < 0).map((r) => r.name);
    if (negative.length) throw new SettlementInputError(`조정 금액이 너무 커서 ${negative.join(', ')}의 분담액이 0원보다 작아져요.`);
    results = distributeRemainder(raw, total);
  } else {
    const totals = new Map(c.members.map((m) => [m, 0]));
    c.items = c.items.map((it) => {
      const dist = distributeRemainder(it.participants.map((name) => ({ name, raw: it.price / it.participants.length })), it.price);
      dist.forEach((d) => totals.set(d.name, totals.get(d.name) + d.amount));
      return { ...it, shares: dist.map((d) => d.amount) };
    });
    total = c.items.reduce((a, it) => a + it.price, 0);
    results = c.members.map((name) => ({ name, amount: totals.get(name) }));
  }

  // 참여하지 않은 멤버는 0원 — UI의 members[i] ↔ shares[i] ↔ approvals[i] 평행 배열 유지
  const shares = c.members.map((m) => { const r = results.find((x) => x.name === m); return r ? r.amount : 0; });
  if (shares.reduce((a, b) => a + b, 0) !== total) throw new Error(`계산 합계가 총액(${total})과 일치하지 않아요.`); // 절대 일어나면 안 됨

  const withinBudget = c.totalBudget === null ? true : total <= c.totalBudget;
  return {
    members: c.members,
    shares,
    total,
    mode: c.mode,
    modeLabel: MODE_LABELS[c.mode],
    itemName: c.itemName || (c.mode === 'ITEM' ? '여러 품목' : '정산'),
    participants: c.participants,
    ratios: c.ratios ?? null,
    adjustments: c.adjustments ?? null,
    items: c.items ?? null,
    totalBudget: c.totalBudget,
    withinBudget,
    overBudgetBy: withinBudget ? 0 : total - c.totalBudget,
    payer: c.payer,
    roundingUnit: 1,
    rule: buildRule(c),
  };
}

// 정산 코어 Stage 2 진입점 — 토큰 로그에 "settlement.calculate: 0 tokens (code-only)" 기록
function calculateSettlement(input) {
  const result = computeSettlement(input);
  logCodeOnlyStage('settlement.calculate');
  return result;
}

module.exports = { calculateSettlement, computeSettlement, distributeRemainder, SettlementInputError, MODES, MODE_LABELS };
