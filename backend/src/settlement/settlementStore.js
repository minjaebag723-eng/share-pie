'use strict';

// 정산 기록 저장소 — settlementOnchainId → 승인된 정산 한 건
// 환불(refund_participant)·지급(release)·이의제기 때 참여자 목록·payer 를 다시 찾기 위해 필요하다.
// - 파일: backend/data/settlements.json (git 제외). 테스트는 SETTLEMENT_STORE_DIR 로 임시 폴더 지정
// - 한 건: { settlementOnchainId, settlementId, title, members(uid), shares, payer, recipient, conditionsHash, conditionsCanonical,
//           txs: { open, locks, confirm, release, dispute, resolve, refunds }, state, holdUntil, verdict, createdAt, updatedAt }
// - 비밀값(키·개인키)은 절대 넣지 않는다

const fs = require('fs');
const path = require('path');

const FILE_NAME = 'settlements.json';

function storeDir() {
  return process.env.SETTLEMENT_STORE_DIR || path.join(__dirname, '..', '..', 'data');
}
function storeFile() {
  return path.join(storeDir(), FILE_NAME);
}

function readAll() {
  const f = storeFile();
  if (!fs.existsSync(f)) return {};
  try {
    return JSON.parse(fs.readFileSync(f, 'utf8')) || {};
  } catch (err) {
    console.error(`[settlementStore] ${f} 읽기 실패 (빈 저장소로 진행):`, err.message);
    return {};
  }
}

function writeAll(all) {
  fs.mkdirSync(storeDir(), { recursive: true });
  const tmp = storeFile() + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(all, null, 2) + '\n');
  fs.renameSync(tmp, storeFile()); // 쓰다 말고 죽어도 파일이 깨지지 않게
}

class SettlementNotFoundError extends Error {
  constructor(id) {
    super(`저장소에 없는 정산이에요: ${id}`);
    this.name = 'SettlementNotFoundError';
    this.code = 'SETTLEMENT_NOT_FOUND';
    this.status = 404;
  }
}

function saveSettlement(record) {
  if (!record || typeof record.settlementOnchainId !== 'string') throw new Error('settlementOnchainId가 없는 기록은 저장할 수 없어요.');
  const all = readAll();
  const now = new Date().toISOString();
  all[record.settlementOnchainId] = { ...record, createdAt: record.createdAt || now, updatedAt: now };
  writeAll(all);
  return all[record.settlementOnchainId];
}

function getSettlement(settlementOnchainId) {
  const rec = readAll()[settlementOnchainId];
  if (!rec) throw new SettlementNotFoundError(settlementOnchainId);
  return rec;
}

function findSettlement(settlementOnchainId) {
  return readAll()[settlementOnchainId] || null;
}

// patch 의 최상위 필드는 덮어쓰고, txs 는 병합한다
function updateSettlement(settlementOnchainId, patch) {
  const all = readAll();
  const rec = all[settlementOnchainId];
  if (!rec) throw new SettlementNotFoundError(settlementOnchainId);
  const next = { ...rec, ...patch, txs: { ...(rec.txs || {}), ...(patch.txs || {}) }, updatedAt: new Date().toISOString() };
  all[settlementOnchainId] = next;
  writeAll(all);
  return next;
}

function listSettlements() {
  return Object.values(readAll());
}

module.exports = { saveSettlement, getSettlement, findSettlement, updateSettlement, listSettlements, storeFile, SettlementNotFoundError };
