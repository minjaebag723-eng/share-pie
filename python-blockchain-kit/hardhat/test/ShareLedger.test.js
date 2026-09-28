'use strict';

// ShareLedger.sol · PieToken.sol 컨트랙트 검증 (로컬 Hardhat 체인)
// - 컨트랙트 소스는 ../contracts 그대로. 여기서는 규칙이 코드대로 강제되는지만 확인한다.
// - 서명 모델: createSettlement/markOfflinePayment/refund/resolve/block = 에이전트, lockForSettlement/approvePurchase = 참여자 본인
// - 판정 코드: 1 NORMAL_APPROVAL · 2 GENUINE_ERROR · 3 BAD_FAITH_DISPUTE (ShareLedger.sol 기준)
// - 참여자 상태: 0 대기 · 1 예치 · 2 현금 · 3 환불 · 4 결제자 · 5 구매 승인
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

const S = { None: 0, Open: 1, Locked: 2, Paid: 3, Blocked: 4, Disputed: 5, Refunded: 6 };
const M = { WAIT: 0, LOCKED: 1, OFFLINE: 2, REFUNDED: 3, PAYEE: 4, APPROVED: 5 };
const V = { NORMAL: 1, GENUINE: 2, BAD_FAITH: 3 };
const WINDOW = 180; // 초

const id = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));
const cond = (s) => ethers.keccak256(ethers.toUtf8Bytes(s));

// 삼겹살 35,900원 · 진주(결제자) 5,000원 감면 → [5225, 10225, 10225, 10225]
const SHARES = [5225n, 10225n, 10225n, 10225n];
const TOTAL = 35900n;

async function deploy() {
  const [agent, jinju, jinwoo, minjae, jihyun, stranger, merchant] = await ethers.getSigners();
  const token = await (await ethers.getContractFactory('PieToken')).deploy();
  const ledger = await (await ethers.getContractFactory('ShareLedger')).deploy();
  await ledger.setDisputeWindow(WINDOW);
  const members = [jinju, jinwoo, minjae, jihyun];
  for (const m of members) await token.chargeToken(m.address, 100000);
  return { agent, jinju, jinwoo, minjae, jihyun, stranger, merchant, token, ledger, members };
}

// 결제자 jinju 포함 4명 정산 등록 (jinju 몫은 M_PAYEE 로 즉시 확보)
async function open(c, sid = 's1', payee = c.jinju) {
  const addrs = c.members.map((m) => m.address);
  await c.ledger.createSettlement(id(sid), await c.token.getAddress(), payee.address, addrs, SHARES, cond('cond:' + sid), '삼겹살 분담금');
  return id(sid);
}

async function lockAs(c, sid, signer, amt) {
  await c.token.connect(signer).approve(await c.ledger.getAddress(), amt);
  return c.ledger.connect(signer).lockForSettlement(sid);
}

async function lockAll(c, sid) {
  // 결제자(jinju)는 예치하지 않음 → 나머지 3명
  await lockAs(c, sid, c.jinwoo, SHARES[1]);
  await lockAs(c, sid, c.minjae, SHARES[2]);
  return lockAs(c, sid, c.jihyun, SHARES[3]);
}

const status = async (c, sid) => Number((await c.ledger.getSettlement(sid)).status);
const mstate = async (c, sid, who) => Number(await c.ledger.memberState(sid, who.address));

// ───────────────────────────────────────────── PieToken
describe('PieToken (PIE)', () => {
  it('테스트넷 전용 토큰: decimals 0, 이름에 Testnet, 1 PIE = 1원', async () => {
    const c = await deploy();
    expect(await c.token.decimals()).to.equal(0);
    expect(await c.token.name()).to.include('Testnet');
    expect(await c.token.symbol()).to.equal('PIE');
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(100000);
  });

  it('chargeToken: minter만 · 0 또는 MAX_CHARGE 초과 거부 · Charged 이벤트', async () => {
    const c = await deploy();
    await expect(c.token.connect(c.stranger).chargeToken(c.stranger.address, 1)).to.be.revertedWith('PIE: not minter');
    await expect(c.token.chargeToken(c.jinju.address, 0)).to.be.revertedWith('PIE: bad amount');
    await expect(c.token.chargeToken(c.jinju.address, 1000001)).to.be.revertedWith('PIE: bad amount');
    await expect(c.token.chargeToken(c.jinju.address, 500)).to.emit(c.token, 'Charged').withArgs(c.jinju.address, 500, c.agent.address);
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(100500);
  });

  it('setMinter: owner만 · 새 minter 발급 가능', async () => {
    const c = await deploy();
    await expect(c.token.connect(c.stranger).setMinter(c.stranger.address, true)).to.be.revertedWith('PIE: not owner');
    await c.token.setMinter(c.stranger.address, true);
    await c.token.connect(c.stranger).chargeToken(c.stranger.address, 10);
    expect(await c.token.balanceOf(c.stranger.address)).to.equal(10);
  });

  it('claim: 1시간에 1회 100,000 PIE (에이전트 없을 때 대비)', async () => {
    const c = await deploy();
    await c.token.connect(c.stranger).claim();
    expect(await c.token.balanceOf(c.stranger.address)).to.equal(100000);
    await expect(c.token.connect(c.stranger).claim()).to.be.revertedWith('PIE: faucet cooldown');
    await time.increase(3600);
    await c.token.connect(c.stranger).claim();
    expect(await c.token.balanceOf(c.stranger.address)).to.equal(200000);
  });

  it('transfer / approve / transferFrom: 잔액·한도 부족 거부, 무제한 한도는 차감 안 함', async () => {
    const c = await deploy();
    await expect(c.token.connect(c.jinju).transfer(c.jinwoo.address, 100001)).to.be.revertedWith('PIE: insufficient balance');
    await expect(c.token.connect(c.jinju).transfer(ethers.ZeroAddress, 1)).to.be.revertedWith('PIE: transfer to zero');
    await expect(c.token.connect(c.stranger).transferFrom(c.jinju.address, c.stranger.address, 1)).to.be.revertedWith('PIE: insufficient allowance');
    await c.token.connect(c.jinju).approve(c.stranger.address, 300);
    await c.token.connect(c.stranger).transferFrom(c.jinju.address, c.stranger.address, 200);
    expect(await c.token.allowance(c.jinju.address, c.stranger.address)).to.equal(100);
    await c.token.connect(c.jinju).approve(c.stranger.address, ethers.MaxUint256);
    await c.token.connect(c.stranger).transferFrom(c.jinju.address, c.stranger.address, 100);
    expect(await c.token.allowance(c.jinju.address, c.stranger.address)).to.equal(ethers.MaxUint256);
  });
});

// ───────────────────────────────────────────── ShareLedger: 권한·등록
describe('ShareLedger — 권한 · 등록(createSettlement)', () => {
  it('배포자 = owner = agent · setAgent/setDisputeWindow 는 owner만', async () => {
    const c = await deploy();
    expect(await c.ledger.owner()).to.equal(c.agent.address);
    expect(await c.ledger.isAgent(c.agent.address)).to.equal(true);
    await expect(c.ledger.connect(c.stranger).setAgent(c.stranger.address, true)).to.be.revertedWith('Ledger: not owner');
    await expect(c.ledger.connect(c.stranger).setDisputeWindow(1)).to.be.revertedWith('Ledger: not owner');
    await expect(c.ledger.setAgent(c.stranger.address, true)).to.emit(c.ledger, 'AgentSet').withArgs(c.stranger.address, true);
  });

  it('createSettlement: 에이전트만 · 조건 해시·목적 저장 · 결제자 몫은 즉시 확보(M_PAYEE) · 이벤트', async () => {
    const c = await deploy();
    const addrs = c.members.map((m) => m.address);
    const tok = await c.token.getAddress();
    await expect(c.ledger.connect(c.stranger).createSettlement(id('x'), tok, c.jinju.address, addrs, SHARES, cond('c'), 'p'))
      .to.be.revertedWith('Ledger: not agent');
    await expect(c.ledger.createSettlement(id('s1'), tok, c.jinju.address, addrs, SHARES, cond('cond:s1'), '삼겹살 분담금'))
      .to.emit(c.ledger, 'SettlementCreated').withArgs(id('s1'), tok, c.jinju.address, TOTAL, cond('cond:s1'), '삼겹살 분담금')
      .and.to.emit(c.ledger, 'ShareAssigned').withArgs(id('s1'), c.jinwoo.address, SHARES[1]);
    const s = await c.ledger.getSettlement(id('s1'));
    expect(s.total).to.equal(TOTAL);
    expect(s.collected).to.equal(SHARES[0]); // 결제자 본인 몫
    expect(s.escrowed).to.equal(0);
    expect(s.conditionHash).to.equal(cond('cond:s1'));
    expect(Number(s.status)).to.equal(S.Open);
    expect(await mstate(c, id('s1'), c.jinju)).to.equal(M.PAYEE);
    expect(await mstate(c, id('s1'), c.jinwoo)).to.equal(M.WAIT);
    // 자금추적: 배정액은 committedOf 에
    expect(await c.ledger.committedOf(c.jinwoo.address)).to.equal(SHARES[1]);
    const gm = await c.ledger.getMembers(id('s1'));
    expect(gm.members).to.deep.equal(addrs);
    expect(gm.shares.map(Number)).to.deep.equal(SHARES.map(Number));
  });

  it('createSettlement: id 재사용 · 0 주소 · 길이 불일치 · 0명/21명 · 0원 몫 · 중복 멤버 거부', async () => {
    const c = await deploy();
    const tok = await c.token.getAddress();
    const addrs = c.members.map((m) => m.address);
    await open(c, 's1');
    await expect(c.ledger.createSettlement(id('s1'), tok, c.jinju.address, addrs, SHARES, cond('c'), 'p')).to.be.revertedWith('Ledger: id used');
    await expect(c.ledger.createSettlement(id('a'), ethers.ZeroAddress, c.jinju.address, addrs, SHARES, cond('c'), 'p')).to.be.revertedWith('Ledger: zero address');
    await expect(c.ledger.createSettlement(id('b'), tok, c.jinju.address, addrs, [1n, 2n], cond('c'), 'p')).to.be.revertedWith('Ledger: length mismatch');
    await expect(c.ledger.createSettlement(id('c'), tok, c.jinju.address, [], [], cond('c'), 'p')).to.be.revertedWith('Ledger: bad member count');
    const many = Array.from({ length: 21 }, (_, i) => ethers.Wallet.createRandom().address);
    await expect(c.ledger.createSettlement(id('d'), tok, c.jinju.address, many, many.map(() => 1n), cond('c'), 'p')).to.be.revertedWith('Ledger: bad member count');
    await expect(c.ledger.createSettlement(id('e'), tok, c.jinju.address, addrs, [0n, 1n, 1n, 1n], cond('c'), 'p')).to.be.revertedWith('Ledger: zero share');
    await expect(c.ledger.createSettlement(id('f'), tok, c.jinju.address, [addrs[1], addrs[1]], [1n, 1n], cond('c'), 'p')).to.be.revertedWith('Ledger: duplicate member');
  });

  it('결제자 혼자인 정산은 등록 즉시 Locked (확보액 = 총액)', async () => {
    const c = await deploy();
    await c.ledger.createSettlement(id('solo'), await c.token.getAddress(), c.jinju.address, [c.jinju.address], [1000n], cond('c'), 'p');
    expect(await status(c, id('solo'))).to.equal(S.Locked);
  });
});

// ───────────────────────────────────────────── 예치 · 현금 · 지급
describe('ShareLedger — 예치(lockForSettlement) · 현금(markOfflinePayment) · 지급(releaseToRecipient)', () => {
  it('lockForSettlement: 참여자 본인 서명 · approve 필요 · 잔액 부족이면 거부하고 한 푼도 안 움직임', async () => {
    const c = await deploy();
    const sid = await open(c);
    const ledgerAddr = await c.ledger.getAddress();
    // approve 없이 → transferFrom 실패 (PIE 한도)
    await expect(c.ledger.connect(c.jinwoo).lockForSettlement(sid)).to.be.revertedWith('PIE: insufficient allowance');
    // 멤버 아님
    await expect(c.ledger.connect(c.stranger).lockForSettlement(sid)).to.be.revertedWith('Ledger: not a member');
    // 잔액 부족: 지현 잔액을 100 PIE 로
    await c.token.connect(c.jihyun).transfer(c.stranger.address, 99900);
    await c.token.connect(c.jihyun).approve(ledgerAddr, SHARES[3]);
    await expect(c.ledger.connect(c.jihyun).lockForSettlement(sid)).to.be.revertedWith('Ledger: insufficient PIE balance');
    expect(await c.token.balanceOf(ledgerAddr)).to.equal(0);
    expect(await c.ledger.escrowOf(c.jihyun.address)).to.equal(0);
    // 정상 예치
    await expect(lockAs(c, sid, c.jinwoo, SHARES[1])).to.emit(c.ledger, 'Locked').withArgs(sid, c.jinwoo.address, SHARES[1]);
    expect(await c.token.balanceOf(ledgerAddr)).to.equal(SHARES[1]);
    expect(await c.ledger.escrowOf(c.jinwoo.address)).to.equal(SHARES[1]);
    expect(await mstate(c, sid, c.jinwoo)).to.equal(M.LOCKED);
    // 중복 예치 거부
    await c.token.connect(c.jinwoo).approve(ledgerAddr, SHARES[1]);
    await expect(c.ledger.connect(c.jinwoo).lockForSettlement(sid)).to.be.revertedWith('Ledger: already locked');
  });

  it('전원 확보 → Locked · FullyLocked(releaseAfter = now + window) · 보류 전 지급 거부 · 보류 후 결제자 지급', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAs(c, sid, c.jinwoo, SHARES[1]);
    await lockAs(c, sid, c.minjae, SHARES[2]);
    const tx = await lockAs(c, sid, c.jihyun, SHARES[3]);
    const blk = await ethers.provider.getBlock((await tx.wait()).blockNumber);
    await expect(tx).to.emit(c.ledger, 'FullyLocked').withArgs(sid, TOTAL, BigInt(blk.timestamp + WINDOW));
    expect(await status(c, sid)).to.equal(S.Locked);
    expect(await c.ledger.releaseAt(sid)).to.equal(BigInt(blk.timestamp + WINDOW));

    await expect(c.ledger.releaseToRecipient(sid)).to.be.revertedWith('Ledger: dispute window open');
    await time.increase(WINDOW + 1);
    const before = await c.token.balanceOf(c.jinju.address);
    // 누구나 호출 가능
    await expect(c.ledger.connect(c.stranger).releaseToRecipient(sid))
      .to.emit(c.ledger, 'Paid').withArgs(sid, c.jinwoo.address, c.jinju.address, SHARES[1], '삼겹살 분담금');
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(before + SHARES[1] + SHARES[2] + SHARES[3]);
    expect(await status(c, sid)).to.equal(S.Paid);
    expect((await c.ledger.getSettlement(sid)).escrowed).to.equal(0);
    // 자금추적 정리
    expect(await c.ledger.escrowOf(c.jinwoo.address)).to.equal(0);
    expect(await c.ledger.committedOf(c.jinwoo.address)).to.equal(0);
    expect(await c.ledger.spentOf(c.jinwoo.address)).to.equal(SHARES[1]);
    expect(await c.ledger.spentOf(c.jinju.address)).to.equal(SHARES[0]); // 결제자 본인 몫도 실사용으로
    await expect(c.ledger.releaseToRecipient(sid)).to.be.revertedWith('Ledger: not locked');
  });

  it('markOfflinePayment: 에이전트만 · 토큰 이동 없이 확보액에 포함 · 현금 멤버가 마지막이면 Locked', async () => {
    const c = await deploy();
    const sid = await open(c);
    await expect(c.ledger.connect(c.jinwoo).markOfflinePayment(sid, c.jinwoo.address)).to.be.revertedWith('Ledger: not agent');
    await lockAs(c, sid, c.jinwoo, SHARES[1]);
    await lockAs(c, sid, c.minjae, SHARES[2]);
    await expect(c.ledger.markOfflinePayment(sid, c.jihyun.address))
      .to.emit(c.ledger, 'OfflinePaid').withArgs(sid, c.jihyun.address, SHARES[3], c.jinju.address)
      .and.to.emit(c.ledger, 'FullyLocked');
    expect(await mstate(c, sid, c.jihyun)).to.equal(M.OFFLINE);
    expect(await status(c, sid)).to.equal(S.Locked);
    expect((await c.ledger.getSettlement(sid)).escrowed).to.equal(SHARES[1] + SHARES[2]); // 현금분은 에스크로에 없음
    await expect(c.ledger.markOfflinePayment(sid, c.jihyun.address)).to.be.revertedWith('Ledger: not open');
  });

  it('disputeWindow = 0 이면 전원 확보 즉시 지급', async () => {
    const c = await deploy();
    await c.ledger.setDisputeWindow(0);
    const sid = await open(c);
    const before = await c.token.balanceOf(c.jinju.address);
    await lockAll(c, sid);
    expect(await status(c, sid)).to.equal(S.Paid);
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(before + SHARES[1] + SHARES[2] + SHARES[3]);
  });
});

// ───────────────────────────────────────────── 이의제기 · 환불 · 판정
describe('ShareLedger — 이의제기(raiseDispute) · 환불(refundParticipant) · 판정(resolveDispute)', () => {
  it('raiseDispute: Locked + 보류 중에만 · 멤버 본인 또는 에이전트만 · Disputed 동안 지급 거부', async () => {
    const c = await deploy();
    const sid = await open(c);
    await expect(c.ledger.connect(c.jinwoo).raiseDispute(sid, c.jinwoo.address, 'r')).to.be.revertedWith('Ledger: not disputable');
    await lockAll(c, sid);
    await expect(c.ledger.connect(c.stranger).raiseDispute(sid, c.stranger.address, 'r')).to.be.revertedWith('Ledger: not a member');
    await expect(c.ledger.connect(c.stranger).raiseDispute(sid, c.jinwoo.address, 'r')).to.be.revertedWith('Ledger: not allowed');
    await expect(c.ledger.connect(c.jinwoo).raiseDispute(sid, c.jinwoo.address, '5천원 감면이 빠졌어요'))
      .to.emit(c.ledger, 'DisputeRaised').withArgs(sid, c.jinwoo.address, '5천원 감면이 빠졌어요');
    expect(await status(c, sid)).to.equal(S.Disputed);
    await time.increase(WINDOW + 1);
    await expect(c.ledger.releaseToRecipient(sid)).to.be.revertedWith('Ledger: not locked');
    // 보류 기간이 끝난 뒤에는 이의제기 불가
    const sid2 = await open(c, 's2');
    await lockAll(c, sid2);
    await time.increase(WINDOW + 1);
    await expect(c.ledger.raiseDispute(sid2, c.jinwoo.address, 'late')).to.be.revertedWith('Ledger: window closed');
  });

  it('에이전트가 앱에서 대신 접수 가능 (by = 멤버)', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAll(c, sid);
    await c.ledger.raiseDispute(sid, c.minjae.address, '대신 접수');
    expect(await status(c, sid)).to.equal(S.Disputed);
  });

  it('refundParticipant: 에이전트만 · Disputed에서만 · 예치(M_LOCKED)한 사람만 · 두 번 환불 불가', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAll(c, sid);
    await expect(c.ledger.refundParticipant(sid, c.jinwoo.address)).to.be.revertedWith('Ledger: not disputed');
    await c.ledger.raiseDispute(sid, c.jinwoo.address, 'r');
    await expect(c.ledger.connect(c.jinwoo).refundParticipant(sid, c.jinwoo.address)).to.be.revertedWith('Ledger: not agent');
    await expect(c.ledger.refundParticipant(sid, c.jinju.address)).to.be.revertedWith('Ledger: nothing to refund'); // 결제자
    const before = await c.token.balanceOf(c.jinwoo.address);
    await expect(c.ledger.refundParticipant(sid, c.jinwoo.address)).to.emit(c.ledger, 'Refunded').withArgs(sid, c.jinwoo.address, SHARES[1]);
    expect(await c.token.balanceOf(c.jinwoo.address)).to.equal(before + SHARES[1]);
    expect(await mstate(c, sid, c.jinwoo)).to.equal(M.REFUNDED);
    expect(await c.ledger.escrowOf(c.jinwoo.address)).to.equal(0);
    expect(await c.ledger.committedOf(c.jinwoo.address)).to.equal(0);
    await expect(c.ledger.refundParticipant(sid, c.jinwoo.address)).to.be.revertedWith('Ledger: nothing to refund');
  });

  it('resolveDispute: 에이전트만 · Disputed에서만 · 판정 0·4 거부 (1/2/3만)', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAll(c, sid);
    await expect(c.ledger.resolveDispute(sid, V.NORMAL, 'n')).to.be.revertedWith('Ledger: not disputed');
    await c.ledger.raiseDispute(sid, c.jinwoo.address, 'r');
    await expect(c.ledger.connect(c.jinwoo).resolveDispute(sid, V.NORMAL, 'n')).to.be.revertedWith('Ledger: not agent');
    await expect(c.ledger.resolveDispute(sid, 0, 'n')).to.be.revertedWith('Ledger: bad verdict');
    await expect(c.ledger.resolveDispute(sid, 4, 'n')).to.be.revertedWith('Ledger: bad verdict');
  });

  it('NORMAL_APPROVAL(1) · BAD_FAITH_DISPUTE(3): 정산 유지 → 결제자에게 지급 (보류 기간과 무관하게 즉시)', async () => {
    for (const verdict of [V.NORMAL, V.BAD_FAITH]) {
      const c = await deploy();
      const sid = await open(c);
      await lockAll(c, sid);
      await c.ledger.raiseDispute(sid, c.jinwoo.address, 'r');
      const before = await c.token.balanceOf(c.jinju.address);
      await expect(c.ledger.resolveDispute(sid, verdict, '기록 일치'))
        .to.emit(c.ledger, 'DisputeResolved').withArgs(sid, verdict, '기록 일치');
      expect(await status(c, sid)).to.equal(S.Paid);
      expect(await c.token.balanceOf(c.jinju.address)).to.equal(before + SHARES[1] + SHARES[2] + SHARES[3]);
    }
  });

  it('GENUINE_ERROR(2) + 전원 환불 → Refunded 종료 · 결제자 committedOf 정리 · 에스크로 0', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAll(c, sid);
    await c.ledger.raiseDispute(sid, c.jinwoo.address, '공동구매 취소');
    const bal = {};
    for (const m of [c.jinwoo, c.minjae, c.jihyun]) { bal[m.address] = await c.token.balanceOf(m.address); await c.ledger.refundParticipant(sid, m.address); }
    const payeeBefore = await c.token.balanceOf(c.jinju.address);
    await c.ledger.resolveDispute(sid, V.GENUINE, '전원 환불');
    expect(await status(c, sid)).to.equal(S.Refunded);
    for (const m of [c.jinwoo, c.minjae, c.jihyun]) expect(await c.token.balanceOf(m.address)).to.equal(bal[m.address] + await c.ledger.shareOf(sid, m.address));
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(payeeBefore); // 결제자에게 지급 없음
    expect(await c.token.balanceOf(await c.ledger.getAddress())).to.equal(0);
    expect(await c.ledger.committedOf(c.jinju.address)).to.equal(0);
  });

  it('GENUINE_ERROR(2) + 일부만 환불 → 나머지는 결제자에게 지급 (Paid)', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAll(c, sid);
    await c.ledger.raiseDispute(sid, c.jinwoo.address, '내 몫만 착오');
    await c.ledger.refundParticipant(sid, c.jinwoo.address);
    const before = await c.token.balanceOf(c.jinju.address);
    await c.ledger.resolveDispute(sid, V.GENUINE, '이의제기자만 환불');
    expect(await status(c, sid)).to.equal(S.Paid);
    expect(await c.token.balanceOf(c.jinju.address)).to.equal(before + SHARES[2] + SHARES[3]);
    expect(await c.ledger.spentOf(c.jinwoo.address)).to.equal(0);
    expect(await c.ledger.spentOf(c.minjae.address)).to.equal(SHARES[2]);
  });

  it('현금(OFFLINE) 멤버가 있으면 GENUINE_ERROR 라도 Refunded 종료가 아니라 지급으로 처리 (현금은 체인이 못 돌려줌)', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAs(c, sid, c.jinwoo, SHARES[1]);
    await lockAs(c, sid, c.minjae, SHARES[2]);
    await c.ledger.markOfflinePayment(sid, c.jihyun.address);
    await c.ledger.raiseDispute(sid, c.jinwoo.address, 'r');
    await c.ledger.refundParticipant(sid, c.jinwoo.address);
    await c.ledger.refundParticipant(sid, c.minjae.address);
    await c.ledger.resolveDispute(sid, V.GENUINE, 'r');
    expect(await status(c, sid)).to.equal(S.Paid); // _allOthersRefunded 가 OFFLINE 때문에 false
  });
});

// ───────────────────────────────────────────── 지출 통제 중단
describe('ShareLedger — 지출 통제 중단(blockSettlement)', () => {
  it('Open 정산 중단: 예치한 사람은 즉시 환불 · committedOf 정리 · Blocked 이벤트 · 이후 예치 거부', async () => {
    const c = await deploy();
    const sid = await open(c);
    await lockAs(c, sid, c.jinwoo, SHARES[1]);
    const before = await c.token.balanceOf(c.jinwoo.address);
    await expect(c.ledger.connect(c.jinwoo).blockSettlement(sid, c.jihyun.address, 2, 'x')).to.be.revertedWith('Ledger: not agent');
    await expect(c.ledger.blockSettlement(sid, c.jihyun.address, 2, '1인 예산 초과'))
      .to.emit(c.ledger, 'Blocked').withArgs(sid, c.jihyun.address, 2, '1인 예산 초과')
      .and.to.emit(c.ledger, 'Refunded').withArgs(sid, c.jinwoo.address, SHARES[1]);
    expect(await status(c, sid)).to.equal(S.Blocked);
    expect(await c.token.balanceOf(c.jinwoo.address)).to.equal(before + SHARES[1]);
    expect(await c.ledger.committedOf(c.minjae.address)).to.equal(0);
    expect(await c.token.balanceOf(await c.ledger.getAddress())).to.equal(0);
    await c.token.connect(c.minjae).approve(await c.ledger.getAddress(), SHARES[2]);
    await expect(c.ledger.connect(c.minjae).lockForSettlement(sid)).to.be.revertedWith('Ledger: not open');
  });

  it('등록 전(None) id 도 중단 기록 가능 · 이미 Locked/Paid 면 거부', async () => {
    const c = await deploy();
    await expect(c.ledger.blockSettlement(id('never'), c.jinju.address, 5, '총예산 초과')).to.emit(c.ledger, 'Blocked');
    expect(await status(c, id('never'))).to.equal(S.Blocked);
    const sid = await open(c);
    await lockAll(c, sid);
    await expect(c.ledger.blockSettlement(sid, c.jinju.address, 9, 'late')).to.be.revertedWith('Ledger: already closed');
  });
});

// ───────────────────────────────────────────── AI 구매 대행
describe('ShareLedger — AI 구매 대행(createPurchase · approvePurchase · executePurchase)', () => {
  async function openPurchase(c, sid = 'p1') {
    const addrs = c.members.map((m) => m.address);
    await c.ledger.createPurchase(id(sid), await c.token.getAddress(), c.merchant.address, addrs, SHARES, cond('c'), '삼겹살 주문');
    return id(sid);
  }

  it('createPurchase: 가맹점이 멤버면 거부 · 구매 정산은 lockForSettlement 대신 approvePurchase', async () => {
    const c = await deploy();
    const addrs = c.members.map((m) => m.address);
    await expect(c.ledger.createPurchase(id('bad'), await c.token.getAddress(), c.jinju.address, addrs, SHARES, cond('c'), 'p')).to.be.revertedWith('Ledger: merchant is member');
    const sid = await openPurchase(c);
    expect(await c.ledger.isPurchase(sid)).to.equal(true);
    await c.token.connect(c.jinju).approve(await c.ledger.getAddress(), SHARES[0]);
    await expect(c.ledger.connect(c.jinju).lockForSettlement(sid)).to.be.revertedWith('Ledger: use approvePurchase');
    await expect(c.ledger.markOfflinePayment(sid, c.jinju.address)).to.be.revertedWith('Ledger: purchase needs escrow');
  });

  it('approvePurchase: 잔액·한도 확인만, 돈은 안 움직임 · executePurchase 는 전원 승인 후 에이전트만', async () => {
    const c = await deploy();
    const sid = await openPurchase(c);
    const ledgerAddr = await c.ledger.getAddress();
    await expect(c.ledger.connect(c.jinju).approvePurchase(sid)).to.be.revertedWith('Ledger: allowance too low');
    for (let i = 0; i < 4; i++) {
      await c.token.connect(c.members[i]).approve(ledgerAddr, SHARES[i]);
      await expect(c.ledger.connect(c.members[i]).approvePurchase(sid)).to.emit(c.ledger, 'PurchaseApproved').withArgs(sid, c.members[i].address, SHARES[i]);
      expect(await c.token.balanceOf(c.members[i].address)).to.equal(100000); // 아직 안 빠짐
      if (i < 3) await expect(c.ledger.executePurchase(sid, id('order'))).to.be.revertedWith('Ledger: not all approved');
    }
    await expect(c.ledger.connect(c.jinju).executePurchase(sid, id('order'))).to.be.revertedWith('Ledger: not agent');
    await expect(c.ledger.executePurchase(sid, id('order-1')))
      .to.emit(c.ledger, 'PurchaseExecuted').withArgs(sid, c.merchant.address, TOTAL, id('order-1'));
    expect(await c.token.balanceOf(c.merchant.address)).to.equal(TOTAL);
    for (let i = 0; i < 4; i++) expect(await c.token.balanceOf(c.members[i].address)).to.equal(100000n - SHARES[i]);
    expect(await status(c, sid)).to.equal(S.Paid);
    expect(await c.ledger.orderRefOf(sid)).to.equal(id('order-1'));
  });

  it('한 명이라도 인출 실패(한도 회수)면 전체 취소 — 일부만 빠져나가는 일 없음', async () => {
    const c = await deploy();
    const sid = await openPurchase(c);
    const ledgerAddr = await c.ledger.getAddress();
    for (let i = 0; i < 4; i++) { await c.token.connect(c.members[i]).approve(ledgerAddr, SHARES[i]); await c.ledger.connect(c.members[i]).approvePurchase(sid); }
    await c.token.connect(c.jihyun).approve(ledgerAddr, 0); // 승인 뒤 한도 회수
    await expect(c.ledger.executePurchase(sid, id('o'))).to.be.revertedWith('PIE: insufficient allowance');
    for (let i = 0; i < 4; i++) expect(await c.token.balanceOf(c.members[i].address)).to.equal(100000);
    expect(await c.token.balanceOf(c.merchant.address)).to.equal(0);
    expect(await status(c, sid)).to.equal(S.Open);
  });

  it('구매 정산 중단(blockSettlement): 승인 상태 무효화, 인출된 돈 없음', async () => {
    const c = await deploy();
    const sid = await openPurchase(c);
    await c.token.connect(c.jinju).approve(await c.ledger.getAddress(), SHARES[0]);
    await c.ledger.connect(c.jinju).approvePurchase(sid);
    await c.ledger.blockSettlement(sid, c.jinju.address, 4, '비허용 가맹점');
    expect(await mstate(c, sid, c.jinju)).to.equal(M.WAIT);
    expect(await status(c, sid)).to.equal(S.Blocked);
  });
});

// ───────────────────────────────────────────── 데모 시나리오 통합
describe('데모 시나리오 (Run 1 · Run 1.5 · Run 2) — 컨트랙트 단에서 끝까지', () => {
  it('Run 1: 등록 → 3명 예치 → Locked → 보류 → 지급. 결제자가 나머지 3명 몫 수령, 자금추적 합계 일치', async () => {
    const c = await deploy();
    const sid = await open(c, 'run1');
    await lockAll(c, sid);
    await time.increase(WINDOW + 1);
    await c.ledger.releaseToRecipient(sid);
    expect(await status(c, sid)).to.equal(S.Paid);
    let spent = 0n;
    for (const m of c.members) spent += await c.ledger.spentOf(m.address);
    expect(spent).to.equal(TOTAL);
  });

  it('Run 1.5: 지출 통제 위반 → 등록 없이 Blocked 기록 (온체인 토큰 이동 0)', async () => {
    const c = await deploy();
    const ledgerAddr = await c.ledger.getAddress();
    await c.ledger.blockSettlement(id('run1_5'), c.jihyun.address, 5, '총예산 30,000 < 35,900');
    expect(await status(c, id('run1_5'))).to.equal(S.Blocked);
    expect(await c.token.balanceOf(ledgerAddr)).to.equal(0);
  });

  it('Run 2: 예치 → 이의제기(동결) → GENUINE_ERROR → 전원 환불 → Refunded, 잔액 전부 복구', async () => {
    const c = await deploy();
    const sid = await open(c, 'run2');
    await lockAll(c, sid);
    await c.ledger.raiseDispute(sid, c.jinwoo.address, '감면 누락');
    for (const m of [c.jinwoo, c.minjae, c.jihyun]) await c.ledger.refundParticipant(sid, m.address);
    await c.ledger.resolveDispute(sid, V.GENUINE, '계산 단계 착오');
    expect(await status(c, sid)).to.equal(S.Refunded);
    for (const m of c.members) expect(await c.token.balanceOf(m.address)).to.equal(100000);
    expect(await c.token.balanceOf(await c.ledger.getAddress())).to.equal(0);
  });
});
