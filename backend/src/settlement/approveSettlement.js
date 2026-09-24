'use strict';

// POST /settlement/approve 의 본체
// 전원 승인 확인 → (서버에서 금액 재계산) → 블록체인 잠금·지급 → 정산 인증서 객체 생성
// UI는 이 API 하나만 부르면 { group, cert } 를 받아 그대로 화면에 반영할 수 있다.

const { calculateSettlement } = require('./calculateSettlement');
const blockchain = require('../blockchain/blockchainClient');
const { logEvent } = require('../logger');
const { InputError } = require('../errors');
const { won } = require('../utils/format');

// 인증서 날짜: UI 샘플과 같은 "2026.09.21 19:42" (한국 시간)
function certDate(now = new Date()) {
  const p = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
      .formatToParts(now)
      .map((x) => [x.type, x.value]),
  );
  return `${p.year}.${p.month}.${p.day} ${p.hour}:${p.minute}`;
}

// UI 코드 계산 엔진으로 이미 계산된 금액: 형식만 검증
function fromDirectShares({ members, shares, payer = null, rule = null }) {
  const namesOk = Array.isArray(members) && members.length > 0 && members.every((m) => typeof m === 'string' && m.trim()) && new Set(members).size === members.length;
  if (!namesOk) throw new InputError('members는 중복 없는 이름 배열이어야 해요.');
  if (!Array.isArray(shares) || shares.length !== members.length || !shares.every((v) => Number.isSafeInteger(v) && v >= 0)) {
    throw new InputError('shares는 members와 같은 길이의 0 이상 정수 배열이어야 해요.');
  }
  if (shares.reduce((a, b) => a + b, 0) <= 0) throw new InputError('정산 금액이 0원이에요.');
  if (payer !== null && !members.includes(payer)) throw new InputError(`payer '${payer}'이(가) 멤버가 아니에요.`);
  return { members: [...members], shares: [...shares], payer, withinBudget: true, overBudgetBy: 0, rule: typeof rule === 'string' && rule.trim() ? rule.trim() : `${members.length}인 분담` };
}

// body 두 가지 방식
// (1) { settlement: { members, ...confirmData, totalBudget, payer } } — 확인 카드 조건 → 서버가 다시 계산 (프론트 금액을 믿지 않음)
//     confirmData = { mode, itemName, total, participants, ratios, adjustments, items } (/settlement/analyze 응답의 confirmData)
// (2) { members, shares, payer, rule } — UI 정산 폼에서 코드로 계산된 금액 → 형식 검증 후 그대로 사용
async function approveSettlement({ settlementId, title, settlement, approvals, members, shares, payer, rule }) {
  if (typeof settlementId !== 'string' || !settlementId.trim()) throw new InputError('settlementId(그룹 id)가 필요해요.');
  if (typeof title !== 'string' || !title.trim()) throw new InputError('title(그룹 이름)이 필요해요.');

  const calc = settlement ? calculateSettlement(settlement) : fromDirectShares({ members, shares, payer, rule });

  if (!Array.isArray(approvals) || approvals.length !== calc.members.length) {
    throw new InputError('approvals는 members와 같은 길이의 true/false 배열이어야 해요.');
  }
  if (!approvals.every((a) => a === true)) {
    throw new InputError('아직 승인하지 않은 멤버가 있어요.', 'NOT_ALL_APPROVED', 409);
  }
  if (!calc.withinBudget) {
    throw new InputError(`예산을 ${won(calc.overBudgetBy)} 초과해서 정산을 진행할 수 없어요.`, 'OVER_BUDGET', 409);
  }
  // 돈을 받는 곳
  // - 기본: Pie(AI 정산 에이전트)가 전원의 분담금을 에스크로에 모아 결제까지 처리 → 전원 잠금
  // - payer 명시("진우가 먼저 결제했어"): payer는 자기 몫을 이미 냈으므로 나머지 멤버만 잠그고 payer에게 지급
  const recipient = calc.payer || blockchain.ESCROW_RECIPIENT;
  // TODO(블록체인 연동): 중간에 한 명이라도 잠금이 실패하면 앞서 잠근 금액을 되돌리는 처리 필요
  //   (컨트랙트가 한 트랜잭션에서 전원 잠금을 지원하면 그쪽을 쓰는 게 가장 안전)
  const locks = [];
  for (let i = 0; i < calc.members.length; i++) {
    const participant = calc.members[i];
    if (participant === calc.payer || calc.shares[i] === 0) continue; // payer가 null이면 아무도 건너뛰지 않음
    const tx = await blockchain.lockForSettlement({ settlementId, participant, amount: calc.shares[i] });
    locks.push({ from: participant, to: recipient, amount: calc.shares[i], txHash: tx.txHash });
  }
  const release = await blockchain.releaseToRecipient({ settlementId, recipient });

  const cert = {
    id: 'd' + Date.now(),
    kind: 'cert',
    title: title.trim(),
    date: certDate(),
    rows: calc.members.map((m, i) => [m, calc.shares[i]]),
    hash: release.txHash,
    block: release.block,
    rule: calc.rule,
  };
  const group = {
    members: calc.members,
    shares: calc.shares,
    approvals: calc.members.map(() => true),
    status: '정산 완료',
    cert: cert.id,
  };

  const onchain = { mock: Boolean(blockchain.IS_MOCK), recipient, viaEscrow: !calc.payer, locks, release };
  logEvent('settlement.approve', { settlementId, source: settlement ? 'analyze' : 'ui-form', calculation: calc, cert, onchain });
  return { group, cert, onchain };
}

module.exports = { approveSettlement, certDate };
