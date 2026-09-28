// 로컬 Hardhat 체인에서 컨트랙트 + 백엔드 연동 코드(onchainClient) 검증 — 가스·테스트 ETH 불필요
const path = require('path');
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
process.env.NODE_ENV = 'test';
const { createOnchainClient, InsufficientBalanceError } = require(path.join(BACKEND, 'src', 'blockchain', 'onchainClient'));
const { addressOf } = require(path.join(BACKEND, 'src', 'blockchain', 'members'));
const { hashConditions } = require(path.join(BACKEND, 'src', 'blockchain', 'conditionsHash'));
const { verifyConditions } = require(path.join(__dirname, '..', 'scripts', 'verify-conditions'));

const id = (s) => ethers.id(s);
const COND = id('cond-1'); // 테스트용 조건 해시 (bytes32)
const HOLD = 600; // 테스트용 보류 기간(초)
// 상태 enum (컨트랙트와 같은 순서)
const S = { None: 0, Opened: 1, Locked: 2, Disputed: 3, Released: 4, Cancelled: 5 };
// 판정 코드 (CLAUDE.md 7번)
const V = { NORMAL_APPROVAL: 0, GENUINE_ERROR: 1, BAD_FAITH_DISPUTE: 2 };

async function deploy() {
  const [owner, alice, bob, carol, merchant, stranger] = await ethers.getSigners();
  const settlement = await (await ethers.getContractFactory('SharePieSettlement')).deploy();
  const pie = await ethers.getContractAt('PieCoin', await settlement.pieCoin());
  return { settlement, pie, owner, alice, bob, carol, merchant, stranger };
}

// 3명 충전 + 등록 + 전원 잠금 → Locked 상태의 정산 하나
async function lockedSettlement(sid = 's-locked', hold = HOLD) {
  const d = await deploy();
  const { settlement, alice, bob, carol } = d;
  const ps = [alice, bob, carol];
  const amounts = [5225, 10225, 10225];
  for (let i = 0; i < ps.length; i++) await settlement.charge_token(ps[i].address, amounts[i]);
  await settlement.open_settlement(id(sid), ps.map((p) => p.address), amounts, COND, hold);
  for (let i = 0; i < ps.length; i++) await settlement.lock_for_settlement(id(sid), ps[i].address, amounts[i]);
  return { ...d, sid: id(sid), ps, amounts, total: 25675 };
}

describe('PieCoin', () => {
  it('테스트넷 토큰: decimals 0 (1 PIE = 1원), 이름에 Testnet 표기', async () => {
    const { pie } = await deploy();
    expect(await pie.decimals()).to.equal(0);
    expect(await pie.symbol()).to.equal('PIE');
    expect(await pie.name()).to.contain('Testnet');
  });

  it('정산 컨트랙트만 발행·이동 가능 (운영자 지갑이 직접 mint 불가)', async () => {
    const { pie, owner, alice } = await deploy();
    await expect(pie.connect(owner).mint(alice.address, 1)).to.be.revertedWithCustomError(pie, 'OwnableUnauthorizedAccount');
    await expect(pie.connect(owner).settlementTransfer(alice.address, owner.address, 1)).to.be.revertedWithCustomError(pie, 'OwnableUnauthorizedAccount');
  });
});

describe('SharePieSettlement ★ 함수', () => {
  it('charge_token: 운영자만 호출 가능', async () => {
    const { settlement, pie, alice, stranger } = await deploy();
    await expect(settlement.charge_token(alice.address, 10000)).to.emit(settlement, 'TokenCharged').withArgs(alice.address, 10000);
    expect(await pie.balanceOf(alice.address)).to.equal(10000);
    await expect(settlement.connect(stranger).charge_token(stranger.address, 1)).to.be.revertedWithCustomError(settlement, 'OwnableUnauthorizedAccount');
  });

  it('lock_for_settlement: 잔액 부족이면 InsufficientBalance로 거부하고 한 푼도 움직이지 않음', async () => {
    const { settlement, pie, alice } = await deploy();
    await settlement.charge_token(alice.address, 4000);
    await settlement.open_settlement(id('s1'), [alice.address], [5000], COND, HOLD);
    await expect(settlement.lock_for_settlement(id('s1'), alice.address, 5000))
      .to.be.revertedWithCustomError(settlement, 'InsufficientBalance').withArgs(alice.address, 4000, 5000);
    expect(await pie.balanceOf(alice.address)).to.equal(4000);
    expect(await settlement.isLocked(id('s1'), alice.address)).to.equal(false);
    expect((await settlement.getSettlement(id('s1'))).lockedCount).to.equal(0);
    expect(await settlement.statusOf(id('s1'))).to.equal(S.Opened);
  });

  it('lock_for_settlement: 등록 안 된 정산 / 등록 금액과 다름 / 중복 잠금 거부', async () => {
    const { settlement, alice, bob } = await deploy();
    await settlement.charge_token(alice.address, 50000);
    await expect(settlement.lock_for_settlement(id('none'), alice.address, 100)).to.be.revertedWithCustomError(settlement, 'SettlementNotOpened');
    await settlement.open_settlement(id('s2'), [alice.address, bob.address], [10000, 1], COND, HOLD);
    await expect(settlement.lock_for_settlement(id('s2'), alice.address, 9999)).to.be.revertedWithCustomError(settlement, 'UnexpectedAmount');
    await settlement.lock_for_settlement(id('s2'), alice.address, 10000);
    await expect(settlement.lock_for_settlement(id('s2'), alice.address, 10000)).to.be.revertedWithCustomError(settlement, 'AlreadyLocked');
  });

  it('open_settlement: 같은 id 재등록·0원·중복 참여자·빈 목록 거부', async () => {
    const { settlement, alice, bob } = await deploy();
    await settlement.open_settlement(id('s4'), [alice.address], [1], COND, HOLD);
    await expect(settlement.open_settlement(id('s4'), [bob.address], [1], COND, HOLD)).to.be.revertedWithCustomError(settlement, 'SettlementAlreadyOpened');
    await expect(settlement.open_settlement(id('s5'), [alice.address], [0], COND, HOLD)).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
    await expect(settlement.open_settlement(id('s6'), [alice.address, alice.address], [1, 1], COND, HOLD)).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
    await expect(settlement.open_settlement(id('s7'), [], [], COND, HOLD)).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
  });

  it('open_settlement: 조건 해시가 저장되고 conditionsHashOf·SettlementOpened 이벤트로 확인, bytes32(0)이면 거부, holdSeconds 0 허용', async () => {
    const { settlement, alice } = await deploy();
    await expect(settlement.open_settlement(id('s8'), [alice.address], [100], COND, 0))
      .to.emit(settlement, 'SettlementOpened').withArgs(id('s8'), 1, 100, COND);
    expect(await settlement.conditionsHashOf(id('s8'))).to.equal(COND);
    const s = await settlement.getSettlement(id('s8'));
    expect(s.conditionsHash).to.equal(COND);
    expect(s.status).to.equal(S.Opened);
    expect(s.holdSeconds).to.equal(0);
    expect(await settlement.conditionsHashOf(id('never'))).to.equal(ethers.ZeroHash);
    await expect(settlement.open_settlement(id('s9'), [alice.address], [100], ethers.ZeroHash, HOLD))
      .to.be.revertedWithCustomError(settlement, 'MissingConditionsHash');
  });
});

describe('SharePieSettlement 상태 머신 (보류 · 분쟁 · 환불)', () => {
  it('전원 잠금 시 Locked 전환·holdUntil 저장·SettlementConfirmed 이벤트 (마지막 lock 트랜잭션)', async () => {
    const { settlement, alice, bob } = await deploy();
    await settlement.charge_token(alice.address, 100);
    await settlement.charge_token(bob.address, 200);
    await settlement.open_settlement(id('c1'), [alice.address, bob.address], [100, 200], COND, HOLD);
    await settlement.lock_for_settlement(id('c1'), alice.address, 100);
    expect(await settlement.statusOf(id('c1'))).to.equal(S.Opened);
    expect(await settlement.holdUntilOf(id('c1'))).to.equal(0);

    const tx = settlement.lock_for_settlement(id('c1'), bob.address, 200);
    await expect(tx).to.emit(settlement, 'SettlementConfirmed');
    const now = await time.latest();
    expect(await settlement.statusOf(id('c1'))).to.equal(S.Locked);
    expect(await settlement.holdUntilOf(id('c1'))).to.equal(now + HOLD);
    await expect(tx).to.emit(settlement, 'SettlementConfirmed').withArgs(id('c1'), 300, now + HOLD);
    // Locked 이후엔 추가 잠금 불가
    await expect(settlement.lock_for_settlement(id('c1'), alice.address, 100)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Locked);
  });

  it('release: 보류 전 HoldNotElapsed → 보류 후 성공(총액 지급, Released) → 두 번 지급·Opened 상태 지급 거부', async () => {
    const { settlement, pie, sid, merchant, total } = await lockedSettlement('r1');
    const holdUntil = await settlement.holdUntilOf(sid);
    await expect(settlement.release_to_recipient(sid, merchant.address)).to.be.revertedWithCustomError(settlement, 'HoldNotElapsed').withArgs(holdUntil);
    await time.increaseTo(holdUntil);
    await expect(settlement.release_to_recipient(sid, merchant.address)).to.emit(settlement, 'SettlementReleased').withArgs(sid, merchant.address, total);
    expect(await pie.balanceOf(merchant.address)).to.equal(total);
    expect(await pie.balanceOf(await settlement.getAddress())).to.equal(0);
    expect(await settlement.statusOf(sid)).to.equal(S.Released);
    await expect(settlement.release_to_recipient(sid, merchant.address)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Released);

    // 전원 잠금 전(Opened)에는 보류와 무관하게 거부
    const { alice } = await deploy();
    await settlement.open_settlement(id('r1-open'), [alice.address], [1], COND, 0);
    await expect(settlement.release_to_recipient(id('r1-open'), merchant.address)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Opened);
  });

  it('raise_dispute: Locked에서만 (Opened·Released 거부), Disputed 동결 → release 거부, DisputeRaised 이벤트에 사유 포함', async () => {
    const { settlement, sid, alice, merchant } = await lockedSettlement('d1');
    const reason = '지현은 그날 참석하지 않았는데 포함됨';
    await expect(settlement.raise_dispute(sid, reason)).to.emit(settlement, 'DisputeRaised').withArgs(sid, ethers.keccak256(ethers.toUtf8Bytes(reason)), reason);
    expect(await settlement.statusOf(sid)).to.equal(S.Disputed);
    expect((await settlement.getSettlement(sid)).disputed).to.equal(true);
    await expect(settlement.raise_dispute(sid, 'again')).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Disputed);
    await time.increase(HOLD + 1);
    await expect(settlement.release_to_recipient(sid, merchant.address)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Disputed);

    // Opened 에서 거부
    await settlement.open_settlement(id('d1-open'), [alice.address], [1], COND, 0);
    await expect(settlement.raise_dispute(id('d1-open'), 'x')).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Opened);
    // Released 에서 거부
    const r = await lockedSettlement('d1-rel', 0);
    await r.settlement.release_to_recipient(r.sid, r.merchant.address);
    await expect(r.settlement.raise_dispute(r.sid, 'x')).to.be.revertedWithCustomError(r.settlement, 'InvalidStatus').withArgs(S.Released);
    await expect(settlement.raise_dispute(id('nope'), 'x')).to.be.revertedWithCustomError(settlement, 'SettlementNotOpened');
  });

  it('resolve_dispute: Disputed에서만, verdict 3 이상 InvalidVerdict, 0·2 → Locked 복귀(holdUntil 유지) → 보류 지나면 release 가능', async () => {
    const { settlement, pie, sid, merchant, total } = await lockedSettlement('v1');
    await expect(settlement.resolve_dispute(sid, V.NORMAL_APPROVAL)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Locked);
    const holdUntil = await settlement.holdUntilOf(sid);
    await settlement.raise_dispute(sid, '이상해요');
    await expect(settlement.resolve_dispute(sid, 3)).to.be.revertedWithCustomError(settlement, 'InvalidVerdict').withArgs(3);
    await expect(settlement.resolve_dispute(sid, 255)).to.be.revertedWithCustomError(settlement, 'InvalidVerdict').withArgs(255);
    await expect(settlement.resolve_dispute(sid, V.BAD_FAITH_DISPUTE)).to.emit(settlement, 'DisputeResolved').withArgs(sid, V.BAD_FAITH_DISPUTE);
    expect(await settlement.statusOf(sid)).to.equal(S.Locked);
    expect(await settlement.holdUntilOf(sid)).to.equal(holdUntil);
    expect((await settlement.getSettlement(sid)).verdict).to.equal(V.BAD_FAITH_DISPUTE);

    // 다시 분쟁 → NORMAL_APPROVAL 도 Locked 복귀
    await settlement.raise_dispute(sid, '또 이상해요');
    await settlement.resolve_dispute(sid, V.NORMAL_APPROVAL);
    expect(await settlement.statusOf(sid)).to.equal(S.Locked);
    await time.increaseTo(holdUntil);
    await settlement.release_to_recipient(sid, merchant.address);
    expect(await pie.balanceOf(merchant.address)).to.equal(total);
  });

  it('GENUINE_ERROR → Cancelled → refund_participant 로 각자 잔액 복구, 에스크로 0, 두 번 환불·잠근 적 없는 주소·Cancelled 후 release 거부', async () => {
    const { settlement, pie, sid, ps, amounts, stranger, merchant } = await lockedSettlement('g1');
    const escrow = await settlement.getAddress();
    for (const p of ps) expect(await pie.balanceOf(p.address)).to.equal(0); // 잠금 후
    await settlement.raise_dispute(sid, '참여자 착오');
    // Disputed 에서는 환불 불가 (판정 전)
    await expect(settlement.refund_participant(sid, ps[0].address)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Disputed);

    const tx = settlement.resolve_dispute(sid, V.GENUINE_ERROR);
    await expect(tx).to.emit(settlement, 'DisputeResolved').withArgs(sid, V.GENUINE_ERROR);
    await expect(tx).to.emit(settlement, 'SettlementCancelled').withArgs(sid);
    expect(await settlement.statusOf(sid)).to.equal(S.Cancelled);

    for (let i = 0; i < ps.length; i++) {
      await expect(settlement.refund_participant(sid, ps[i].address)).to.emit(settlement, 'Refunded').withArgs(sid, ps[i].address, amounts[i]);
      expect(await pie.balanceOf(ps[i].address)).to.equal(amounts[i]); // 잠금 전으로 복구
      expect(await settlement.isRefunded(sid, ps[i].address)).to.equal(true);
    }
    expect(await pie.balanceOf(escrow)).to.equal(0);
    await expect(settlement.refund_participant(sid, ps[0].address)).to.be.revertedWithCustomError(settlement, 'AlreadyRefunded').withArgs(ps[0].address);
    await expect(settlement.refund_participant(sid, stranger.address)).to.be.revertedWithCustomError(settlement, 'NotLockedParticipant').withArgs(stranger.address);
    await time.increase(HOLD + 1);
    await expect(settlement.release_to_recipient(sid, merchant.address)).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Cancelled);
    await expect(settlement.raise_dispute(sid, 'x')).to.be.revertedWithCustomError(settlement, 'InvalidStatus').withArgs(S.Cancelled);

    // Cancelled 가 아닌 상태(Locked)에서 환불 거부
    const l = await lockedSettlement('g1-locked');
    await expect(l.settlement.refund_participant(l.sid, l.ps[0].address)).to.be.revertedWithCustomError(l.settlement, 'InvalidStatus').withArgs(S.Locked);
  });
});

describe('백엔드 연동 (backend/src/blockchain/onchainClient.js)', () => {
  const MEMBERS = ['u0', 'u1', 'u2', 'u3']; // uid — 표시 이름은 체인에 넘기지 않는다
  const SHARES = [5225, 10225, 10225, 10225];
  // 승인 조건(계산 입력) — 백엔드 approve가 해시하는 것과 같은 형식
  const CONDITIONS = { members: MEMBERS, mode: 'ADJUST', itemName: '삼겹살', total: 35900, participants: MEMBERS, ratios: null, adjustments: { u0: -5000 }, items: null, totalBudget: null, payer: null };
  const CHASH = hashConditions(CONDITIONS);

  async function clientWith(hold = HOLD) {
    const d = await deploy();
    const contractAddress = await d.settlement.getAddress();
    const client = await createOnchainClient({ signer: d.owner, contractAddress, merchantAddress: d.merchant.address });
    for (let i = 0; i < MEMBERS.length; i++) await client.chargeToken(MEMBERS[i], SHARES[i]);
    return { ...d, client, contractAddress, hold };
  }

  it('에스크로 정산: open → lock × N 까지만 (Locked·confirm·holdUntil), release는 null', async () => {
    const { settlement, pie, client } = await clientWith();
    const r = await client.recordSettlement({ settlementId: 'g1', members: MEMBERS, shares: SHARES, payer: null, conditionsHash: CHASH, holdSeconds: HOLD });
    expect(r.mock).to.equal(false);
    expect(r.viaEscrow).to.equal(true);
    expect(r.recipient).to.equal('SharePie 정산 에스크로');
    expect(r.state).to.equal('LOCKED');
    expect(r.release).to.equal(null);
    expect(r.conditionsHash).to.equal(CHASH);
    expect(r.holdSeconds).to.equal(HOLD);
    expect(r.locks.map((l) => [l.from, l.amount])).to.deep.equal(MEMBERS.map((m, i) => [m, SHARES[i]]));
    r.locks.forEach((l) => expect(l.txHash).to.match(/^0x[0-9a-f]{64}$/));
    expect(r.confirm.txHash).to.equal(r.locks[r.locks.length - 1].txHash); // 마지막 lock = 인증서 TxHash
    expect(r.confirm.block).to.match(/^#[\d,]+$/);
    expect(r.confirm.holdUntil).to.equal(Number(await settlement.holdUntilOf(r.settlementOnchainId)));
    expect(r.holdUntil).to.equal(r.confirm.holdUntil);
    expect(await settlement.conditionsHashOf(r.settlementOnchainId)).to.equal(CHASH);
    expect(await settlement.statusOf(r.settlementOnchainId)).to.equal(S.Locked);
    expect(await pie.balanceOf(await settlement.getAddress())).to.equal(35900); // 아직 에스크로에 보관
    for (const m of MEMBERS) expect(await client.balanceOf(m)).to.equal(0);
    const st = await client.getSettlementState({ settlementOnchainId: r.settlementOnchainId });
    expect(st).to.include({ state: 'LOCKED', verdict: null, lockedCount: 4, participantCount: 4, totalLocked: 35900 });
    expect(st.holdUntil).to.equal(r.holdUntil);
  });

  it('releaseSettlement: 보류 전 HOLD_NOT_ELAPSED → 보류 후 결제처 지급 (RELEASED)', async () => {
    const { pie, client, merchant } = await clientWith();
    const r = await client.recordSettlement({ settlementId: 'g1r', members: MEMBERS, shares: SHARES, conditionsHash: CHASH, holdSeconds: HOLD });
    let caught;
    try { await client.releaseSettlement({ settlementOnchainId: r.settlementOnchainId }); } catch (e) { caught = e; }
    expect(caught && caught.code).to.equal('HOLD_NOT_ELAPSED');
    expect(caught.status).to.equal(409);
    await time.increaseTo(r.holdUntil);
    const rel = await client.releaseSettlement({ settlementOnchainId: r.settlementOnchainId });
    expect(rel.txHash).to.match(/^0x[0-9a-f]{64}$/);
    expect(rel.amount).to.equal(35900);
    expect(rel.state).to.equal('RELEASED');
    expect(await pie.balanceOf(merchant.address)).to.equal(35900);
    // payer 명시 정산은 payer 에게 지급 (첫 정산에서 잔액이 잠겼으므로 다시 충전)
    for (let i = 1; i < MEMBERS.length; i++) await client.chargeToken(MEMBERS[i], SHARES[i]);
    const p = await client.recordSettlement({ settlementId: 'g1p', members: MEMBERS, shares: SHARES, payer: 'u0', conditionsHash: CHASH, holdSeconds: 0 });
    expect(p.viaEscrow).to.equal(false);
    expect(p.locks.map((l) => l.from)).to.deep.equal(['u1', 'u2', 'u3']);
    const rel2 = await client.releaseSettlement({ settlementOnchainId: p.settlementOnchainId, recipientUid: 'u0' });
    expect(rel2.recipientAddress).to.equal(addressOf('u0'));
    expect(await client.balanceOf('u0')).to.equal(30675);
  });

  it('한 명이라도 잔액 부족이면 InsufficientBalanceError, 트랜잭션을 하나도 보내지 않음 (부분 잠금 없음)', async () => {
    const { settlement, owner, merchant } = await deploy();
    const client = await createOnchainClient({ signer: owner, contractAddress: await settlement.getAddress(), merchantAddress: merchant.address });
    await client.chargeToken('u0', 5225);
    await client.chargeToken('u1', 10225);
    await client.chargeToken('u2', 10225);
    await client.chargeToken('u3', 100); // 부족
    const nonceBefore = await owner.getNonce();
    let caught;
    try { await client.recordSettlement({ settlementId: 'g3', members: MEMBERS, shares: SHARES, conditionsHash: CHASH }); } catch (e) { caught = e; }
    expect(caught).to.be.instanceOf(InsufficientBalanceError);
    expect(caught.code).to.equal('INSUFFICIENT_BALANCE');
    expect(caught.message).to.contain('u3'); // 메시지에는 uid — UI가 이름으로 바꿔 표시
    expect(await owner.getNonce()).to.equal(nonceBefore);
    expect(await client.balanceOf('u0')).to.equal(5225);
  });

  it('conditionsHash 없이 recordSettlement를 부르면 트랜잭션을 보내기 전에 MISSING_CONDITIONS_HASH', async () => {
    const { client, owner } = await clientWith();
    const nonceBefore = await owner.getNonce();
    for (const bad of [undefined, null, '', ethers.ZeroHash, '0x1234']) {
      let caught;
      try { await client.recordSettlement({ settlementId: 'g4', members: MEMBERS, shares: SHARES, conditionsHash: bad }); } catch (e) { caught = e; }
      expect(caught && caught.code, String(bad)).to.equal('MISSING_CONDITIONS_HASH');
    }
    expect(await owner.getNonce()).to.equal(nonceBefore);
  });

  it('제3자 검증: 백엔드 hashConditions로 넣은 해시를 verify-conditions가 MATCH, 조건을 한 글자 바꾸면 MISMATCH', async () => {
    const { client, contractAddress } = await clientWith();
    const r = await client.recordSettlement({ settlementId: 'g5', members: MEMBERS, shares: SHARES, conditionsHash: CHASH });

    // 키 순서를 바꿔도 같은 조건이면 MATCH (정규화)
    const reordered = { payer: null, totalBudget: null, items: null, adjustments: { u0: -5000 }, ratios: null, participants: MEMBERS, total: 35900, itemName: '삼겹살', mode: 'ADJUST', members: MEMBERS };
    const byId = await verifyConditions({ conditions: reordered, ref: r.settlementOnchainId, provider: ethers.provider, contractAddress });
    expect(byId.match).to.equal(true);
    expect(byId.onchainHash).to.equal(CHASH);
    // open 트랜잭션 해시로도 대조 가능 (SettlementOpened 이벤트)
    const byTx = await verifyConditions({ conditions: CONDITIONS, ref: r.open.txHash, provider: ethers.provider, contractAddress });
    expect(byTx.match).to.equal(true);
    expect(byTx.source).to.contain('SettlementOpened');
    // 조건을 한 글자라도 바꾸면 MISMATCH
    const tampered = { ...CONDITIONS, total: 35901 };
    const bad = await verifyConditions({ conditions: tampered, ref: r.settlementOnchainId, provider: ethers.provider, contractAddress });
    expect(bad.match).to.equal(false);
  });

  it('분쟁 통합(Run 2 흐름): recordSettlement → raiseDispute → resolveDispute(GENUINE_ERROR) → refundParticipant × N, 잔액 복구', async () => {
    const { pie, settlement, client } = await clientWith();
    const r = await client.recordSettlement({ settlementId: 'g6', members: MEMBERS, shares: SHARES, conditionsHash: CHASH, holdSeconds: HOLD });
    const sid = r.settlementOnchainId;

    const raised = await client.raiseDispute({ settlementOnchainId: sid, reason: '지현은 그날 참석하지 않았는데 포함됨' });
    expect(raised.txHash).to.match(/^0x[0-9a-f]{64}$/);
    expect(raised.reasonHash).to.equal(ethers.keccak256(ethers.toUtf8Bytes('지현은 그날 참석하지 않았는데 포함됨')));
    expect(raised.state).to.equal('DISPUTED');
    expect((await client.getSettlementState({ settlementOnchainId: sid })).state).to.equal('DISPUTED');
    // 동결: 지급 불가
    await time.increase(HOLD + 1);
    let caught;
    try { await client.releaseSettlement({ settlementOnchainId: sid }); } catch (e) { caught = e; }
    expect(caught && caught.code).to.equal('INVALID_STATUS');

    // 판정 3개 밖 문자열은 전송 전에 거부
    caught = null;
    try { await client.resolveDispute({ settlementOnchainId: sid, verdict: 'REFUND' }); } catch (e) { caught = e; }
    expect(caught && caught.code).to.equal('INVALID_VERDICT');

    const resolved = await client.resolveDispute({ settlementOnchainId: sid, verdict: 'GENUINE_ERROR' });
    expect(resolved).to.include({ verdict: 'GENUINE_ERROR', verdictCode: 1, state: 'CANCELLED' });
    expect(resolved.txHash).to.match(/^0x[0-9a-f]{64}$/);

    const refunds = [];
    for (const uid of MEMBERS) refunds.push(await client.refundParticipant({ settlementOnchainId: sid, uid }));
    expect(refunds.map((x) => [x.uid, x.amount])).to.deep.equal(MEMBERS.map((m, i) => [m, SHARES[i]]));
    refunds.forEach((x) => { expect(x.txHash).to.match(/^0x[0-9a-f]{64}$/); expect(x.address).to.equal(addressOf(x.uid)); });
    for (let i = 0; i < MEMBERS.length; i++) expect(await client.balanceOf(MEMBERS[i])).to.equal(SHARES[i]);
    expect(await pie.balanceOf(await settlement.getAddress())).to.equal(0);
    caught = null;
    try { await client.refundParticipant({ settlementOnchainId: sid, uid: 'u0' }); } catch (e) { caught = e; }
    expect(caught && caught.code).to.equal('ALREADY_REFUNDED');
    const st = await client.getSettlementState({ settlementOnchainId: sid });
    expect(st).to.include({ state: 'CANCELLED', verdict: 'GENUINE_ERROR' });

    // NORMAL_APPROVAL 은 Locked 복귀 → 환불 불가, 보류 후 지급 가능
    const r2 = await client.recordSettlement({ settlementId: 'g7', members: MEMBERS, shares: SHARES, conditionsHash: CHASH, holdSeconds: 0 });
    for (let i = 0; i < MEMBERS.length; i++) await client.chargeToken(MEMBERS[i], 0 + SHARES[i]).catch(() => {}); // (이미 환불받아 잔액 있음)
    await client.raiseDispute({ settlementOnchainId: r2.settlementOnchainId, reason: '계산이 틀린 것 같아요' });
    const ok = await client.resolveDispute({ settlementOnchainId: r2.settlementOnchainId, verdict: 'NORMAL_APPROVAL' });
    expect(ok).to.include({ verdictCode: 0, state: 'LOCKED' });
    caught = null;
    try { await client.refundParticipant({ settlementOnchainId: r2.settlementOnchainId, uid: 'u0' }); } catch (e) { caught = e; }
    expect(caught && caught.code).to.equal('INVALID_STATUS');
    const rel = await client.releaseSettlement({ settlementOnchainId: r2.settlementOnchainId });
    expect(rel.state).to.equal('RELEASED');
  });

  it('멤버 주소는 uid마다 고정: 같은 uid = 같은 주소, 다른 uid = 다른 주소', () => {
    expect(addressOf('u0')).to.equal(addressOf('u0'));
    expect(addressOf('u0')).to.not.equal(addressOf('u1'));
    expect(ethers.isAddress(addressOf('u0'))).to.equal(true);
  });

  it('이름이 같은 두 사용자(u1·u11 = 둘 다 "진우")는 서로 다른 지갑', () => {
    expect(addressOf('u1')).to.not.equal(addressOf('u11'));
  });

  it('표시 이름·공백 등 uid 형식이 아니면 에러 (이름으로 지갑을 만드는 실수 방지)', () => {
    for (const bad of ['진주', 'u 1', '', 'u1\n', 'x'.repeat(65)]) {
      expect(() => addressOf(bad), JSON.stringify(bad)).to.throw(/uid여야 해요/);
    }
    expect(() => addressOf('진주')).to.throw(/받은 값: "진주"/);
  });
});
