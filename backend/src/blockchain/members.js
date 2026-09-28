'use strict';

// 멤버 uid → 테스트넷 지갑 주소
// 데모는 서버 운영자 지갑 하나가 모든 트랜잭션에 서명하는 수탁 구조라서, 멤버 주소에는 비밀키가 필요 없다.
// - uid: UI가 붙이는 고정 사용자 번호('u0', 'u1', …). 이름·Pie ID를 바꿔도 uid는 그대로라 지갑이 유지된다.
// - 표시 이름('진주')은 동명이인이 있을 수 있어 절대 지갑 키로 쓰지 않는다 (한글·공백이 오면 즉시 에러).
// - members.json 에 { "u0": "0x..." } 로 적어 두면 그 주소를 사용
// - 없으면 uid에서 항상 같은 주소를 만들어 사용 (같은 uid = 같은 주소 → 잔액이 유지됨)
// ⚠️ 테스트넷 전용. 실제 자산이 있는 주소를 넣지 않는다.

const fs = require('fs');
const path = require('path');
const { ethers } = require('ethers');
const { UID_PATTERN, assertUid } = require('./errors');

const MEMBERS_FILE = path.join(__dirname, 'members.json');

function loadOverrides() {
  if (!fs.existsSync(MEMBERS_FILE)) return {};
  const raw = JSON.parse(fs.readFileSync(MEMBERS_FILE, 'utf8'));
  const out = {};
  for (const [uid, addr] of Object.entries(raw)) {
    if (uid.startsWith('_')) continue; // "_comment" 등
    assertUid(uid); // 키가 이름이면 여기서 바로 에러
    out[uid] = ethers.getAddress(addr); // 주소 형식이 틀리면 여기서 바로 에러
  }
  return out;
}

const overrides = loadOverrides();

function addressOf(uid) {
  assertUid(uid);
  if (overrides[uid]) return overrides[uid];
  const hash = ethers.keccak256(ethers.toUtf8Bytes(`sharepie-demo-uid:${uid}`));
  return ethers.getAddress('0x' + hash.slice(-40));
}

module.exports = { addressOf, UID_PATTERN };
