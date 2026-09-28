#!/usr/bin/env python3
"""[blockchain 담당] 새 백엔드 버전에 블록체인 쪽 패치·파일·.env 를 한 번에 얹는 스크립트 (멱등 — 이미 있으면 건너뜀).

사용 (이전 폴더에서 실행, 새 폴더를 target 으로):
    py tools/apply_blockchain_patches.py --target "../share-pie-ai-NEW"
    py tools/apply_blockchain_patches.py            # 현재 폴더에 패치만 (파일 복사 없음)

하는 일
  1) 코드 패치 (agent/chain.py · agent/config.py · agent/service.py)
     - 가스 가격 +25% 버퍼            (Sepolia mempool 지연 → 120초 실패 방지)
     - 가스 자동 지급 (native_balance / send_gas / _gas_drip / GAS_DRIP_* 설정)
     - 가드 A: 금액 오파싱 방어 — 문장에 '만/억'이 있는데 총액이 그보다 작으면 등록 거부 (AMOUNT_SUSPECT)
     - 가드 B: GENUINE_ERROR 인데 refund=none 이면 disputer 로 보정 (착오 판정인데 결제자에게 지급되는 모순 방지)
     - 가드 C: 온체인 송금 목적(purpose) 60자 제한 (가스)
  2) 파일 복사 (--target 일 때): hardhat.config.js, package.json, hardhat/(node_modules 제외), contracts/abi/, tools/, run-public.cmd, docs/BETA-PUBLIC.md, docs/evidence/
  3) .env 값 (--target 일 때 이전 .env 에서 복사): CHAIN_MODE, BSC_RPC_URL, BSC_CHAIN_ID, BSC_EXPLORER, LEDGER_ADDRESS, TOKEN_ADDRESS,
     LEDGER_DEPLOY_BLOCK, AGENT_PRIVATE_KEY, KILN_TOOL_MODE, GAS_DRIP_ETH, GAS_DRIP_MIN_ETH, GAS_DRIP_COOLDOWN_SEC, DISPUTE_WINDOW_SEC
앵커를 못 찾으면 "수동 확인" 으로 표시하고 계속 진행한다. 비밀키는 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import ast
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent   # 스크립트가 든 백엔드 폴더 (이전 버전)
ENV_KEYS = ["CHAIN_MODE", "BSC_RPC_URL", "BSC_CHAIN_ID", "BSC_EXPLORER", "LEDGER_ADDRESS", "TOKEN_ADDRESS", "LEDGER_DEPLOY_BLOCK",
            "AGENT_PRIVATE_KEY", "KILN_TOOL_MODE", "SERPAPI_API_KEY", "SERPAPI_SHOP_ENGINES", "BETA_PLAN", "GAS_DRIP_ETH", "GAS_DRIP_MIN_ETH", "GAS_DRIP_COOLDOWN_SEC", "DISPUTE_WINDOW_SEC"]
COPY_ITEMS = ["hardhat.config.js", "package.json", "hardhat", "contracts/abi", "tools", "run-public.cmd", "docs/BETA-PUBLIC.md", "docs/evidence"]

GAS_DRIP_FN = '''

def _gas_drip(name: str, wallet: str, ch) -> dict[str, Any] | None:
    """[blockchain 담당] 실제 체인에서 사용자가 예치(MetaMask 서명)하려면 가스가 필요하다.
    faucet 을 직접 찾지 않아도 되게, 지갑 등록 시 잔액이 GAS_DRIP_MIN_ETH 미만이면 에이전트가 GAS_DRIP_ETH 를 보낸다.
    같은 지갑은 GAS_DRIP_COOLDOWN_SEC 에 한 번만. 테스트넷 전용 · 실패해도 등록은 막지 않는다."""
    if ch.mode == "mock" or config.GAS_DRIP_ETH <= 0:
        return None
    key = wallet.lower()
    last = store.kv_get("gas_drip", key) or {}
    if last.get("at") and time.time() - float(last["at"]) < config.GAS_DRIP_COOLDOWN_SEC:
        return {"skipped": "cooldown", "last_tx_hash": last.get("tx_hash")}
    try:
        bal = ch.native_balance(wallet)
        if bal >= config.GAS_DRIP_MIN_ETH:
            return {"skipped": "enough", "balance_eth": bal}
        tx = ch.send_gas(wallet, config.GAS_DRIP_ETH)
    except chainmod.ChainError as e:
        print(f"[가스 지급 실패] {name} {wallet}: {e.code} {e.message}")
        return {"skipped": "failed", "error": e.code}
    if not tx:
        return None
    store.kv_put("gas_drip", key, {"at": time.time(), "tx_hash": tx["tx_hash"], "amount_eth": config.GAS_DRIP_ETH, "name": name})
    print(f"[가스 지급] {name} {wallet} ← {config.GAS_DRIP_ETH} ETH ({tx['tx_hash']})")
    return {"amount_eth": config.GAS_DRIP_ETH, "tx_hash": tx["tx_hash"], "url": ch.explorer_tx(tx["tx_hash"])}
'''

SEND_GAS_FN = '''
    # [blockchain 담당] 가스 자동 지급 — 에이전트 지갑에서 네이티브 코인(ETH/tBNB) 소량 전송
    def native_balance(self, addr: str) -> float:
        try:
            return float(self.w3.from_wei(self.w3.eth.get_balance(self._cs(addr)), "ether"))
        except Exception as e:
            raise ChainError("CHAIN_UNAVAILABLE", f"잔액 조회 실패: {e}") from e

    def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:
        with self._send_lock:
            try:
                tx = {
                    "from": self.acct.address, "to": self._cs(to), "value": self.w3.to_wei(eth, "ether"),
                    "nonce": self.w3.eth.get_transaction_count(self.acct.address, "pending"),
                    "chainId": config.BSC_CHAIN_ID, "gas": 21000,
                    "gasPrice": int(self.w3.eth.gas_price * 5 // 4),
                }
                signed = self.acct.sign_transaction(tx)
                raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")
                h = self.w3.eth.send_raw_transaction(raw)
                rcpt = self.w3.eth.wait_for_transaction_receipt(h, timeout=120)
            except Exception as e:
                raise ChainError("CHAIN_TX_FAILED", f"가스 지급 실패: {e}") from e
            if rcpt["status"] != 1:
                raise ChainError("CHAIN_TX_FAILED", f"가스 지급 revert: {self.W.to_hex(h)}")
            return {"tx_hash": self.W.to_hex(h), "block": int(rcpt["blockNumber"])}
'''

AMOUNT_GUARD_FN = '''_KO_MAN = re.compile(r"(?:^|[\\s\\d일이삼사오육칠팔구십백천])만(?=[\\s\\d원이삼사오육칠팔구천백십]|$)")   # 숫자로서의 '만' (만나·만들 제외)
_KO_EOK = re.compile(r"(?:^|[\\s\\d일이삼사오육칠팔구십백천])억(?=[\\s\\d원이삼사오육칠팔구천백십만]|$)")


def _amount_sanity(rule_text: str, total: int) -> None:
    """[blockchain 담당] 가드 A — 한글 금액 오파싱 방어. 문장에 숫자 '만'이 있는데 총액이 1만 미만이거나(예: '만2천원'→2,000),
    '억'이 있는데 1억 미만이면 잘못 읽힌 것이 거의 확실하다. 온체인에 올리면 되돌리는 데 이의제기·환불(가스)이 필요하므로 등록 전에 거부한다."""
    t = rule_text or ""
    bad = None
    if _KO_EOK.search(t) and total < 100_000_000:
        bad = "억"
    elif _KO_MAN.search(t) and total < 10_000:
        bad = "만"
    if bad:
        raise ServiceError("AMOUNT_SUSPECT",
                           f"총액이 {total:,}원으로 읽혔는데 문장에 '{bad}' 단위가 있어요. 금액을 숫자로 다시 말해 주세요 (예: 12000원).",
                           "settlement.request", 409, {"total": total, "unit": bad})


'''

CREATE_OLD = '''    def create_settlement(self, cid, payee, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createSettlement(
            self._b32(cid), self.token_addr, self._cs(payee), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), purpose))

    def create_purchase(self, cid, merchant, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createPurchase(
            self._b32(cid), self.token_addr, self._cs(merchant), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), purpose))
'''
CREATE_NEW = '''    PURPOSE_MAX = 60   # [blockchain 담당] 가드 C — 온체인 문자열은 길이 = 가스. AI 가 목적 문구를 길게 써도 여기서 자른다

    def create_settlement(self, cid, payee, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createSettlement(
            self._b32(cid), self.token_addr, self._cs(payee), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), (purpose or "")[:self.PURPOSE_MAX]))

    def create_purchase(self, cid, merchant, members, shares, cond_hash, purpose) -> dict[str, Any]:
        return self._send(self.ledger.functions.createPurchase(
            self._b32(cid), self.token_addr, self._cs(merchant), [self._cs(m) for m in members],
            [self._units(a) for a in shares], self._b32(cond_hash), (purpose or "")[:self.PURPOSE_MAX]))
'''

SERPAPI_FNS = r'''def _serpapi_get(params: dict[str, Any]) -> dict[str, Any]:
    with _http() as c:
        r = c.get(f"{config.SERPAPI_API_BASE}/search.json", params={**params, "api_key": config.SERPAPI_API_KEY})
        r.raise_for_status()
        return r.json()


def _serpapi_shop(query: str, n: int) -> list[dict[str, Any]]:
    """[blockchain 담당] SerpApi 쇼핑 검색 — SERPAPI_SHOP_ENGINES 순서(기본 naver → google_shopping)로 시도, 상품이 나오면 멈춤.
    출력은 serper_shop 과 같은 형식이라 호출부 변경 없음. 가격은 소스 원본에서 코드가 꺼낸다."""
    for engine in config.SERPAPI_SHOP_ENGINES:
        try:
            if engine == "naver":
                data = _serpapi_get({"engine": "naver", "query": query})
            else:
                data = _serpapi_get({"engine": "google_shopping", "q": query, "gl": "kr", "hl": "ko", "num": n})
        except Exception as e:
            print(f"[serpapi {engine}] 실패: {e}")
            continue
        out = []
        for it in data.get("shopping_results", []) or []:
            raw = it.get("extracted_price") if it.get("extracted_price") is not None else it.get("price")
            price = _price_str(raw)
            ptxt = str(it.get("price") or "")
            if price <= 0 or ("$" in ptxt and "₩" not in ptxt and "원" not in ptxt):
                continue  # 원화가 아닌 가격은 제외
            title = _clean(it.get("title"))
            link = it.get("link") or it.get("product_link") or ""
            out.append({"id": _oid("serpapi", link or title, str(price)), "title": title, "price": price,
                        "mall": it.get("source") or it.get("seller") or mall_from_host(urlparse(link).hostname or ""),
                        "url": link, "image": it.get("thumbnail"), "source": "serper", "verified": True,
                        "qty": parse_qty(title)})
            if len(out) >= n:
                break
        if out:
            return out
    return []


def _serpapi_web(query: str, n: int) -> list[dict[str, Any]]:
    """[blockchain 담당] SerpApi 구글 웹 검색 — serper_web 과 같은 형식."""
    data = _serpapi_get({"engine": "google", "q": query, "gl": "kr", "hl": "ko", "num": n})
    return [{"title": _clean(x.get("title")), "text": _clean(x.get("snippet"))[:500], "url": x.get("link"),
             "source": "serper_web", "score": 1.0 / (1 + i)} for i, x in enumerate(data.get("organic_results", []) or [])]


'''

# (파일, 이름, 이미적용 마커, [(old, new), ...])
PATCHES = [
    ("agent/chain.py", "가스 가격 +25% 버퍼", "gas_price * 5 // 4),\n                })" , [(
        '                    "gasPrice": self.w3.eth.gas_price,\n                })',
        '                    # [blockchain 담당] 가스 가격 +25% 버퍼 — 정확히 gas_price 로 보내면 Sepolia 에서 mempool 에 걸려 120초 후 실패\n'
        '                    "gasPrice": int(self.w3.eth.gas_price * 5 // 4),\n                })')]),

    ("agent/chain.py", "가스 자동 지급 (모의 체인 no-op)", "def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:\n        return None", [(
        '    def mock_transfer(self, frm: str, to: str, amount: int) -> dict[str, Any]:',
        '    # [blockchain 담당] 모의 체인은 가스가 필요 없다\n'
        '    def native_balance(self, addr: str) -> float:\n        return 1.0\n\n'
        '    def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:\n        return None\n\n'
        '    def mock_transfer(self, frm: str, to: str, amount: int) -> dict[str, Any]:')]),

    ("agent/chain.py", "가스 자동 지급 (실제 체인 send_gas)", "def send_gas(self, to: str, eth: float) -> dict[str, Any] | None:\n        with self._send_lock", [(
        '        return self._send(self.token.functions.chargeToken(self._cs(to), self._units(amount)))\n',
        '        return self._send(self.token.functions.chargeToken(self._cs(to), self._units(amount)))\n' + SEND_GAS_FN)]),

    ("agent/chain.py", "가드 C: purpose 60자 제한", "PURPOSE_MAX", [(CREATE_OLD, CREATE_NEW)]),

    ("agent/config.py", "GAS_DRIP_* 설정", "GAS_DRIP_ETH", [(
        'CHARGE_COOLDOWN_SEC = int(_get("CHARGE_COOLDOWN_SEC", "60") or 0)\n',
        'CHARGE_COOLDOWN_SEC = int(_get("CHARGE_COOLDOWN_SEC", "60") or 0)\n'
        '# [blockchain 담당] 지갑 등록 시 가스(네이티브 코인) 자동 지급 — 실제 체인 모드에서만. 사용자가 faucet 없이 바로 예치할 수 있게.\n'
        'GAS_DRIP_ETH = float(_get("GAS_DRIP_ETH", "0.002") or 0)                 # 0 이면 끔\n'
        'GAS_DRIP_MIN_ETH = float(_get("GAS_DRIP_MIN_ETH", "0.001") or 0)         # 지갑 잔액이 이 값 미만일 때만 지급\n'
        'GAS_DRIP_COOLDOWN_SEC = int(_get("GAS_DRIP_COOLDOWN_SEC", "86400") or 0) # 같은 지갑 재지급 간격 (기본 하루)\n')]),

    ("agent/service.py", "가스 자동 지급 (_gas_drip)", "def _gas_drip(", [(
        '    out = store.set_member(name, wallet)\n'
        '    retry_pending([name])          # 이 사람 지갑을 기다리던 정산이 있으면 자동 시작\n'
        '    return out\n',
        '    out = dict(store.set_member(name, wallet))\n'
        '    out["gas"] = _gas_drip(name, wallet, ch)   # [blockchain 담당] 가스 자동 지급 (실패해도 등록은 성공)\n'
        '    retry_pending([name])          # 이 사람 지갑을 기다리던 정산이 있으면 자동 시작\n'
        '    return out\n' + GAS_DRIP_FN)]),

    ("agent/service.py", "가드 A: 금액 오파싱 방어 (AMOUNT_SUSPECT)", "AMOUNT_SUSPECT", [(
        '@_locked\ndef propose(*, group_name: str, members: list[str], shares: list[list[Any]], total: int, payer: str,\n',
        AMOUNT_GUARD_FN + '@_locked\ndef propose(*, group_name: str, members: list[str], shares: list[list[Any]], total: int, payer: str,\n'),
        (
        '    ch = _chain()\n    share_map = {n: int(a) for n, a in shares}\n    if set(share_map) != set(members):\n'
        '        raise ServiceError("BAD_REQUEST", "members와 shares의 이름이 달라요", "settlement.request")\n',
        '    ch = _chain()\n    share_map = {n: int(a) for n, a in shares}\n    if set(share_map) != set(members):\n'
        '        raise ServiceError("BAD_REQUEST", "members와 shares의 이름이 달라요", "settlement.request")\n'
        '    _amount_sanity(rule_text, int(total))   # [blockchain 담당] 가드 A — 오파싱된 총액을 온체인에 올리지 않는다\n')]),

    ("agent/service.py", "가드 B: GENUINE_ERROR + refund=none 보정", "REFUND_GUARD", [(
        '    ch = _chain()\n    refunded = []\n    if d["verdict"] == "GENUINE_ERROR":\n',
        '    ch = _chain()\n    refunded = []\n'
        '    if d["verdict"] == "GENUINE_ERROR" and d.get("refund") not in ("all", "disputer"):   # [blockchain 담당] REFUND_GUARD\n'
        '        # 착오 판정인데 환불 대상이 없으면 컨트랙트는 남은 예치금을 결제자에게 지급해 버린다 → 최소한 제기자에게 환불\n'
        '        d["refund"] = "disputer"\n'
        '        d["guard"] = ((d.get("guard") or "") + " · GENUINE_ERROR인데 refund=none → disputer 로 보정").strip(" ·")\n'
        '    if d["verdict"] == "GENUINE_ERROR":\n')]),
    # ── v2: 혼잡 시(블록 100% 가득) 25% 버퍼로는 120초 안에 안 실림 → 가스 가격 2배 + 대기 300초 (실제 발생: 스모크 테스트 nonce 82)
    ("agent/config.py", "CHAIN_TX_TIMEOUT_SEC 설정", "CHAIN_TX_TIMEOUT_SEC", [(
        'GAS_DRIP_COOLDOWN_SEC = int(_get("GAS_DRIP_COOLDOWN_SEC", "86400") or 0) # 같은 지갑 재지급 간격 (기본 하루)\n',
        'GAS_DRIP_COOLDOWN_SEC = int(_get("GAS_DRIP_COOLDOWN_SEC", "86400") or 0) # 같은 지갑 재지급 간격 (기본 하루)\n'
        '# [blockchain 담당] 트랜잭션 영수증 대기(초). 테스트넷 혼잡 시 2~4분 걸릴 수 있어 넉넉히\n'
        'CHAIN_TX_TIMEOUT_SEC = int(_get("CHAIN_TX_TIMEOUT_SEC", "300") or 300)\n'
        '# [blockchain 담당] 가스 가격 배수 (2 = 현재 시세의 2배). 혼잡한 블록에서도 다음 블록에 실리게\n'
        'GAS_PRICE_MULTIPLIER = float(_get("GAS_PRICE_MULTIPLIER", "2") or 2)\n')]),

    ("agent/chain.py", "가스 가격 v2 (_gas_price 헬퍼 · 배수 · 대기 시간)", "def _gas_price(self)", [
        ('int(self.w3.eth.gas_price * 5 // 4)', 'self._gas_price()', 'all'),
        ('wait_for_transaction_receipt(h, timeout=120)', 'wait_for_transaction_receipt(h, timeout=config.CHAIN_TX_TIMEOUT_SEC)', 'all'),
        ('    def _send(self, fn) -> dict[str, Any]:\n',
         '    # [blockchain 담당] 가스 가격: 시세 × GAS_PRICE_MULTIPLIER, 최소 시세 + 0.5 gwei. 테스트넷은 가스가 공짜라 넉넉히 주는 편이 안전\n'
         '    def _gas_price(self) -> int:\n'
         '        gp = int(self.w3.eth.gas_price)\n'
         '        return max(int(gp * config.GAS_PRICE_MULTIPLIER), gp + int(self.w3.to_wei(0.5, "gwei")))\n\n'
         '    def _send(self, fn) -> dict[str, Any]:\n'),
    ]),
    # ── SerpApi 검색 공급자 + 베타 요금제 (2026-09-29 밤 추가) ──
    ("agent/config.py", "SERPAPI 지원 설정", "SERPAPI_API_KEY", [(
        'SERPER_API_BASE = _get("SERPER_API_BASE", "https://google.serper.dev").rstrip("/")\n',
        'SERPER_API_BASE = _get("SERPER_API_BASE", "https://google.serper.dev").rstrip("/")\n'
        '# [blockchain 담당] SerpApi (serpapi.com) — 키가 있으면 Serper 대신 이걸로 구글 쇼핑·구글 웹·네이버 쇼핑 검색 (같은 출력 형식)\n'
        'SERPAPI_API_KEY = _get("SERPAPI_API_KEY")\n'
        'SERPAPI_API_BASE = _get("SERPAPI_API_BASE", "https://serpapi.com").rstrip("/")\n'
        'SERPAPI_SHOP_ENGINES = [e.strip() for e in (_get("SERPAPI_SHOP_ENGINES", "naver,google_shopping") or "").split(",") if e.strip()]  # 네이버(관련도 높음) → 구글 쇼핑(기프티콘 등 보조)\n')]),

    ("agent/websearch.py", "SERPAPI 지원 (serper 소스 대체)", "def _serpapi_shop(", [
        ('            "serper": bool(config.SERPER_API_KEY),\n',
         '            "serper": bool(config.SERPAPI_API_KEY or config.SERPER_API_KEY),   # [blockchain 담당] SerpApi 키가 있으면 SerpApi 로\n'),
        ('def serper_shop(query: str, n: int = 20) -> list[dict[str, Any]]:\n'
         '    """구글 쇼핑 결과 (여러 쇼핑몰의 가격·판매처·링크)."""\n'
         '    if not enabled_sources()["serper"]:\n        return []\n\n    def go():\n',
         SERPAPI_FNS +
         'def serper_shop(query: str, n: int = 20) -> list[dict[str, Any]]:\n'
         '    """구글 쇼핑 결과 (여러 쇼핑몰의 가격·판매처·링크). SerpApi 키가 있으면 SerpApi 로."""\n'
         '    if not enabled_sources()["serper"]:\n        return []\n'
         '    if config.SERPAPI_API_KEY:\n        return _cached("serpapi:" + query, lambda: _serpapi_shop(query, n))\n\n    def go():\n'),
        ('    if not enabled_sources()["serper"]:\n        return []\n\n    def go():\n        with _http() as c:\n            r = c.post(f"{config.SERPER_API_BASE}/search"',
         '    if not enabled_sources()["serper"]:\n        return []\n'
         '    if config.SERPAPI_API_KEY:\n        return _cached("serpapiweb:" + query, lambda: _serpapi_web(query, n))\n\n    def go():\n        with _http() as c:\n            r = c.post(f"{config.SERPER_API_BASE}/search"'),
    ]),

    ("agent/service.py", "/api/shopping/search ok_web 직렬화 보완", "인터넷 검색 결과가 응답에서 빠지던 것 보완", [(
        '    elif r["status"] == "no_match":\n        out["advice"] = r["advice"]\n        out["budget_per_person"] = r.get("budget_per_person")\n    else:\n        out["question"] = r.get("question")\n    return out\n',
        '    elif r["status"] == "no_match":\n        out["advice"] = r["advice"]\n        out["budget_per_person"] = r.get("budget_per_person")\n'
        '    elif r["status"] == "ok_web":   # [blockchain 담당] 인터넷 검색 결과가 응답에서 빠지던 것 보완 (채팅 경로 _chat_shop_web 과 같은 내용)\n'
        '        q = r["query"]\n'
        '        out["candidates"] = [{"id": c["id"], **shopping.web_product_public(c, q.get("allowed_malls") or []),\n'
        '                              "per": c.get("per"), "packs": c.get("packs"), "within": c.get("within")} for c in r["candidates"]]\n'
        '        out["explain"] = r["explain"]\n'
        '        out["web"] = {"queries": r["web"].get("queries"), "stats": r["web"].get("stats"), "errors": r["web"].get("errors")}\n'
        '    else:\n        out["question"] = r.get("question")\n    return out\n')]),
]


def apply_patches(target: Path) -> list[tuple[str, str, str]]:
    results = []
    for rel, name, marker, pairs in PATCHES:
        f = target / rel
        if not f.exists():
            results.append((rel, name, "파일 없음 → 수동 확인"))
            continue
        s = f.read_text(encoding="utf-8")
        if marker in s:
            results.append((rel, name, "이미 적용"))
            continue
        ok = True
        for pair in pairs:
            old, new = pair[0], pair[1]
            mode = pair[2] if len(pair) > 2 else "one"
            n = s.count(old)
            if (mode == "one" and n != 1) or (mode == "all" and n < 1):
                ok = False
                break
            s = s.replace(old, new)
        if not ok:
            results.append((rel, name, "앵커 불일치 → 수동 확인"))
            continue
        f.write_text(s, encoding="utf-8", newline="\n")
        results.append((rel, name, "적용"))
    svc = target / "agent/service.py"
    if svc.exists():
        s = svc.read_text(encoding="utf-8")
        if "_KO_MAN" in s and not re.search(r"^import re$|^import re,|^import .*, re$|^from re import", s, re.M):
            s = s.replace("from __future__ import annotations\n", "from __future__ import annotations\n\nimport re\n", 1)
            svc.write_text(s, encoding="utf-8", newline="\n")
            results.append(("agent/service.py", "import re 추가", "적용"))
    return results


def copy_files(src: Path, dst: Path) -> list[str]:
    out = []
    for item in COPY_ITEMS:
        s, d = src / item, dst / item
        if not s.exists():
            out.append(f"{item}: 원본 없음")
            continue
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("node_modules", "cache", "artifacts", "__pycache__", "members-*.json"))
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)
        out.append(f"{item}: 복사")
    gi = dst / ".gitignore"
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    add = [l for l in ["node_modules/", "hardhat/cache/", "hardhat/artifacts/", "hardhat/deployments/members-*.json", "tools/"] if l not in lines]
    if add:
        gi.write_text("\n".join(lines + add) + "\n", encoding="utf-8")
        out.append(".gitignore: " + ", ".join(add))
    return out


def read_env(p: Path) -> dict[str, str]:
    d = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$", line)
            if m and not line.lstrip().startswith("#"):
                d[m.group(1)] = m.group(2)
    return d


def write_env(target: Path, values: dict[str, str]) -> list[str]:
    f = target / ".env"
    s = f.read_text(encoding="utf-8") if f.exists() else ""
    out = []
    for k in ENV_KEYS:
        v = values.get(k)
        if v is None:
            out.append(f"{k}: 원본 .env 에 없음")
            continue
        pat = re.compile(rf"^{k}=.*$", re.M)
        m = pat.search(s)
        if m:
            if m.group(0) == f"{k}={v}":
                out.append(f"{k}: 동일")
                continue
            s = pat.sub(f"{k}={v}", s, count=1)
            out.append(f"{k}: 갱신")
        else:
            s += ("" if s.endswith("\n") or not s else "\n") + f"{k}={v}\n"
            out.append(f"{k}: 추가")
    f.write_text(s, encoding="utf-8", newline="\n")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=None, help="새 백엔드 폴더 (없으면 현재 폴더에 패치만)")
    ap.add_argument("--env-from", default=None, help=".env 값을 가져올 이전 .env (기본: 이 스크립트가 든 폴더의 .env)")
    a = ap.parse_args()
    target = Path(a.target).resolve() if a.target else HERE
    print(f"대상 폴더: {target}")
    if not (target / "agent" / "chain.py").exists():
        print("❌ agent/chain.py 가 없어요. 백엔드 폴더가 맞는지 확인하세요.")
        return 1
    if a.target and target != HERE:
        print("\n[파일 복사]")
        for x in copy_files(HERE, target):
            print("  -", x)
        print("\n[.env]")
        for x in write_env(target, read_env(Path(a.env_from) if a.env_from else HERE / ".env")):
            print("  -", x)
    print("\n[코드 패치]")
    manual = 0
    for rel, name, status in apply_patches(target):
        print(f"  - {rel:18s} {name:36s} → {status}")
        manual += "수동" in status
    print("\n[문법]")
    for rel in ("agent/chain.py", "agent/config.py", "agent/service.py"):
        try:
            ast.parse((target / rel).read_text(encoding="utf-8"))
            print(f"  - {rel}: OK")
        except SyntaxError as e:
            print(f"  - {rel}: ❌ {e}")
            manual += 1
    print("\n다음: 서버 재시작 → cd hardhat && npm install (새 폴더면) && npm run smoke")
    if manual:
        print(f"⚠️ 수동 확인 {manual}건 — 위 목록의 '수동 확인' 항목을 코드에서 직접 맞춰 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
