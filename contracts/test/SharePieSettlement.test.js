// 로컬 Hardhat 체인에서 컨트랙트 + 백엔드 연동 코드(onchainClient) 검증 — 가스·테스트 ETH 불필요
const path = require('path');
const { expect } = require('chai');
const { ethers } = require('hardhat');

const BACKEND = path.join(__dirname, '..', '..', 'backend');
process.env.NODE_ENV = 'test';
const { createOnchainClient, InsufficientBalanceError } = require(path.join(BACKEND, 'src', 'blockchain', 'onchainClient'));
const { addressOf } = require(path.join(BACKEND, 'src', 'blockchain', 'members'));

const id = (s) => ethers.id(s);

async function deploy() {
  const [owner, alice, bob, carol, merchant, stranger] = await ethers.getSigners();
  const settlement = await (await ethers.getContractFactory('SharePieSettlement')).deploy();
  const pie = await ethers.getContractAt('PieCoin', await settlement.pieCoin());
  return { settlement, pie, owner, alice, bob, carol, merchant, stranger };
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
    await settlement.open_settlement(id('s1'), [alice.address], [5000]);
    await expect(settlement.lock_for_settlement(id('s1'), alice.address, 5000))
      .to.be.revertedWithCustomError(settlement, 'InsufficientBalance').withArgs(alice.address, 4000, 5000);
    expect(await pie.balanceOf(alice.address)).to.equal(4000);
    expect(await settlement.isLocked(id('s1'), alice.address)).to.equal(false);
    expect((await settlement.getSettlement(id('s1'))).lockedCount).to.equal(0);
  });

  it('lock_for_settlement: 등록 안 된 정산 / 등록 금액과 다름 / 중복 잠금 거부', async () => {
    const { settlement, alice, bob } = await deploy();
    await settlement.charge_token(alice.address, 50000);
    await expect(settlement.lock_for_settlement(id('none'), alice.address, 100)).to.be.revertedWithCustomError(settlement, 'SettlementNotOpened');
    await settlement.open_settlement(id('s2'), [alice.address], [10000]);
    await expect(settlement.lock_for_settlement(id('s2'), alice.address, 9999)).to.be.revertedWithCustomError(settlement, 'UnexpectedAmount');
    await expect(settlement.lock_for_settlement(id('s2'), bob.address, 10000)).to.be.revertedWithCustomError(settlement, 'UnexpectedAmount');
    await settlement.lock_for_settlement(id('s2'), alice.address, 10000);
    await expect(settlement.lock_for_settlement(id('s2'), alice.address, 10000)).to.be.revertedWithCustomError(settlement, 'AlreadyLocked');
  });

  it('release_to_recipient: 전원 잠금 전에는 거부 → 전원 잠금 후 총액 지급, 두 번 지급 불가', async () => {
    const { settlement, pie, alice, bob, carol, merchant } = await deploy();
    for (const s of [alice, bob, carol]) await settlement.charge_token(s.address, 20000);
    await settlement.open_settlement(id('s3'), [alice.address, bob.address, carol.address], [5225, 10225, 10225]);
    await settlement.lock_for_settlement(id('s3'), alice.address, 5225);
    await settlement.lock_for_settlement(id('s3'), bob.address, 10225);
    await expect(settlement.release_to_recipient(id('s3'), merchant.address)).to.be.revertedWithCustomError(settlement, 'NotAllLocked').withArgs(2, 3);

    await settlement.lock_for_settlement(id('s3'), carol.address, 10225);
    await expect(settlement.release_to_recipient(id('s3'), merchant.address)).to.emit(settlement, 'SettlementReleased').withArgs(id('s3'), merchant.address, 25675);
    expect(await pie.balanceOf(merchant.address)).to.equal(25675);
    expect(await pie.balanceOf(await settlement.getAddress())).to.equal(0);
    await expect(settlement.release_to_recipient(id('s3'), merchant.address)).to.be.revertedWithCustomError(settlement, 'SettlementAlreadyReleased');
  });

  it('open_settlement: 같은 id 재등록·0원·중복 참여자·빈 목록 거부', async () => {
    const { settlement, alice, bob } = await deploy();
    await settlement.open_settlement(id('s4'), [alice.address], [1]);
    await expect(settlement.open_settlement(id('s4'), [bob.address], [1])).to.be.revertedWithCustomError(settlement, 'SettlementAlreadyOpened');
    await expect(settlement.open_settlement(id('s5'), [alice.address], [0])).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
    await expect(settlement.open_settlement(id('s6'), [alice.address, alice.address], [1, 1])).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
    await expect(settlement.open_settlement(id('s7'), [], [])).to.be.revertedWithCustomError(settlement, 'InvalidParticipants');
  });
});

describe('백엔드 연동 (backend/src/blockchain/onchainClient.js)', () => {
  const MEMBERS = ['u0', 'u1', 'u2', 'u3']; // uid — 표시 이름은 체인에 넘기지 않는다
  const SHARES = [5225, 10225, 10225, 10225];

  it('에스크로 정산: 전원 잠금 → 결제처 지급, /settlement/approve 응답 형식', async () => {
    const { settlement, pie, owner, merchant } = await deploy();
    const client = await createOnchainClient({ signer: owner, contractAddress: await settlement.getAddress(), merchantAddress: merchant.address });
    for (let i = 0; i < MEMBERS.length; i++) await client.chargeToken(MEMBERS[i], SHARES[i]);

    const r = await client.recordSettlement({ settlementId: 'g1', members: MEMBERS, shares: SHARES, payer: null });
    expect(r.mock).to.equal(false);
    expect(r.viaEscrow).to.equal(true);
    expect(r.recipient).to.equal('SharePie 정산 에스크로');
    expect(r.locks.map((l) => [l.from, l.amount])).to.deep.equal(MEMBERS.map((m, i) => [m, SHARES[i]]));
    r.locks.forEach((l) => expect(l.txHash).to.match(/^0x[0-9a-f]{64}$/));
    expect(r.release.txHash).to.match(/^0x[0-9a-f]{64}$/);
    expect(r.release.block).to.match(/^#[\d,]+$/);
    expect(await pie.balanceOf(merchant.address)).to.equal(35900);
    for (const m of MEMBERS) expect(await client.balanceOf(m)).to.equal(0);
  });

  it('payer 명시: payer는 잠그지 않고 나머지 분담금을 payer에게 지급 (viaEscrow false)', async () => {
    const { settlement, owner } = await deploy();
    const client = await createOnchainClient({ signer: owner, contractAddress: await settlement.getAddress() });
    for (let i = 1; i < MEMBERS.length; i++) await client.chargeToken(MEMBERS[i], SHARES[i]);
    const r = await client.recordSettlement({ settlementId: 'g2', members: MEMBERS, shares: SHARES, payer: 'u0' });
    expect(r.viaEscrow).to.equal(false);
    expect(r.recipient).to.equal('u0');
    expect(r.locks.map((l) => l.from)).to.deep.equal(['u1', 'u2', 'u3']);
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
    try { await client.recordSettlement({ settlementId: 'g3', members: MEMBERS, shares: SHARES }); } catch (e) { caught = e; }
    expect(caught).to.be.instanceOf(InsufficientBalanceError);
    expect(caught.code).to.equal('INSUFFICIENT_BALANCE');
    expect(caught.message).to.contain('u3'); // 메시지에는 uid — UI가 이름으로 바꿔 표시
    expect(await owner.getNonce()).to.equal(nonceBefore);
    expect(await client.balanceOf('u0')).to.equal(5225);
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
