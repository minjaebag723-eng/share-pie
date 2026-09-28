"""컨트랙트 배포 후 실행: python scripts/check_chain.py  (CHAIN_MODE=bsc)
에이전트 지갑 가스비, 에이전트 권한, 토큰 정보, 잔액 조회가 되는지 확인합니다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import chain, config  # noqa: E402

if config.CHAIN_MODE != "bsc":
    sys.exit("✗ .env 에 CHAIN_MODE=bsc 로 설정해 주세요")
ch = chain.get()
info = ch.info()
print("✓ 네트워크:", info["network"], "chainId", info["chain_id"])
print("✓ 토큰:", info["token_symbol"], "decimals", info["token_decimals"], info["token"])
print("✓ 장부:", info["ledger"])
print("✓ 에이전트 지갑:", info["agent"])
bnb = ch.w3.eth.get_balance(ch.acct.address) / 1e18
print(("✓" if bnb > 0.01 else "✗"), f"에이전트 tBNB 잔액 {bnb:.4f} (0.01 이상 권장 — 부족하면 faucet)")
print(("✓" if ch.ledger.functions.isAgent(ch.acct.address).call() else "✗"), "ShareLedger isAgent 권한")
print(("✓" if ch.token.functions.isMinter(ch.acct.address).call() else "✗"), "PieToken isMinter 권한 (chargeToken)")
print("✓ 이의제기 기간:", ch.dispute_window(), "초")
print("✓ 에이전트 PIE 계정:", ch.account(ch.acct.address))
