'use strict';

// 승인된 정산 "조건"의 정규화·해시 — 온체인 open_settlement(…, conditionsHash)에 기록되는 값
// ⚠️ ethers를 절대 require하지 않는다 (MOCK 모드에서 ethers 미로드 보장). keccak256은 @noble/hashes 사용.
//
// 해시 대상 형식 (= /settlement/approve가 재계산에 쓴 입력 그대로, calculateSettlement에 넣은 값)
//   { members, mode, itemName, total, participants, ratios, adjustments, items, totalBudget, payer }
//   - members/participants: uid 배열 (표시 이름 아님)
//   - shares 같은 "계산 결과"는 넣지 않는다 — 결과는 이미 amounts로 체인에 있고, 해시는 "입력 조건"을 고정하는 용도
//   - members/shares 직접 경로(UI 정산 폼)는 { members, mode: 'DIRECT', shares, payer, rule } 를 그대로 해시
//
// 검증 방법: 제출 로그의 conditions 원문을 canonicalize → keccak256 → 체인의 conditionsHashOf(id)와 대조
//   (contracts/scripts/verify-conditions.js)

const { keccak_256 } = require('@noble/hashes/sha3');

class ConditionsError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConditionsError';
    this.code = 'INVALID_CONDITIONS';
    this.status = 400;
  }
}

// 객체 키를 재귀적으로 정렬한, 공백 없는 JSON 문자열.
// - 배열 순서는 유지, undefined는 제거(객체 키·배열 원소 모두), null은 유지
// - 숫자는 정수만 허용 (금액은 원 단위 정수 — CLAUDE.md 6-1). 소수·NaN·Infinity면 에러
function canonicalize(value, path = '$') {
  if (value === undefined) return undefined;
  if (value === null) return 'null';
  const t = typeof value;
  if (t === 'number') {
    if (!Number.isSafeInteger(value)) throw new ConditionsError(`${path}: 정산 조건의 숫자는 원 단위 정수여야 해요 (받은 값: ${String(value)})`);
    return String(value);
  }
  if (t === 'boolean') return value ? 'true' : 'false';
  if (t === 'string') return JSON.stringify(value);
  if (t === 'bigint') return value.toString();
  if (Array.isArray(value)) {
    const parts = [];
    value.forEach((v, i) => { const c = canonicalize(v, `${path}[${i}]`); if (c !== undefined) parts.push(c); });
    return '[' + parts.join(',') + ']';
  }
  if (t === 'object') {
    const keys = Object.keys(value).sort();
    const parts = [];
    for (const k of keys) {
      const c = canonicalize(value[k], `${path}.${k}`);
      if (c !== undefined) parts.push(JSON.stringify(k) + ':' + c);
    }
    return '{' + parts.join(',') + '}';
  }
  throw new ConditionsError(`${path}: 정산 조건에 쓸 수 없는 값 (${t})`);
}

function hashConditions(obj) {
  if (obj === null || obj === undefined || typeof obj !== 'object') throw new ConditionsError('정산 조건은 객체여야 해요.');
  const canonical = canonicalize(obj);
  const digest = keccak_256(new TextEncoder().encode(canonical));
  return '0x' + Buffer.from(digest).toString('hex');
}

function isConditionsHash(v) {
  return typeof v === 'string' && /^0x[0-9a-f]{64}$/i.test(v) && !/^0x0{64}$/.test(v);
}

module.exports = { canonicalize, hashConditions, isConditionsHash, ConditionsError };
