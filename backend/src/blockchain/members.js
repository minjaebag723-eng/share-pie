'use strict';

// 멤버 이름 → 테스트넷 지갑 주소
// 데모는 서버 운영자 지갑 하나가 모든 트랜잭션에 서명하는 수탁 구조라서, 멤버 주소에는 비밀키가 필요 없다.
// - members.json 에 { "진주": "0x..." } 로 적어 두면 그 주소를 사용
// - 없으면 이름에서 항상 같은 주소를 만들어 사용 (같은 이름 = 같은 주소 → 잔액이 유지됨)
// ⚠️ 테스트넷 전용. 실제 자산이 있는 주소를 넣지 않는다.

const fs = require('fs');
const path = require('path');
const { ethers } = require('ethers');

const MEMBERS_FILE = path.join(__dirname, 'members.json');

function loadOverrides() {
  if (!fs.existsSync(MEMBERS_FILE)) return {};
  const raw = JSON.parse(fs.readFileSync(MEMBERS_FILE, 'utf8'));
  const out = {};
  for (const [name, addr] of Object.entries(raw)) {
    if (name.startsWith('_')) continue; // "_comment" 등
    out[name] = ethers.getAddress(addr); // 주소 형식이 틀리면 여기서 바로 에러
  }
  return out;
}

const overrides = loadOverrides();

function addressOf(name) {
  if (typeof name !== 'string' || !name.trim()) throw new Error('멤버 이름이 비어 있어요.');
  if (overrides[name]) return overrides[name];
  const hash = ethers.keccak256(ethers.toUtf8Bytes(`sharepie-demo-member:${name}`));
  return ethers.getAddress('0x' + hash.slice(-40));
}

module.exports = { addressOf };
