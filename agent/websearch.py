"""여러 사이트를 돌며 실제 상품·가격을 모으는 검색 계층 (전부 코드, 토큰 0).

소스 (키가 있는 것만 자동으로 켜짐)
  naver   네이버 쇼핑 검색 API  — 여러 쇼핑몰의 실제 최저가·판매처·링크 (구조화된 가격 → verified)
  context 네이버 블로그·뉴스 검색 — '한정선' 같은 신상 트렌드의 판매처·가격 언급 (AI 설명용 참고 문맥)
  tavily  Tavily 웹 검색         — 공식몰·쿠팡·편의점 기사 등 일반 웹 (본문 속 가격은 unverified)
  page    상품 페이지 읽기        — 웹 결과 상위 페이지의 schema.org Product 가격 (verified)
  coupang 쿠팡 파트너스 API       — 최종 승인된 파트너 키가 있을 때만
가격 숫자는 항상 소스 원본에서 코드가 꺼낸다. AI는 가격을 만들지 않는다.
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import hmac
import html
import ipaddress
import json
import re
import socket
import time
from typing import Any
from urllib.parse import quote, urlencode, urlparse

import httpx

from . import config

_TAG = re.compile(r"<[^>]+>")
_cache: dict[str, tuple[float, Any]] = {}
CACHE_SEC = 600


def enabled_sources() -> dict[str, bool]:
    return {"naver": bool(config.NAVER_CLIENT_ID and config.NAVER_CLIENT_SECRET),
            "serper": bool(config.SERPER_API_KEY or config.SERPAPI_API_KEY),   # 구글 쇼핑·검색 (Serper 또는 SerpApi)
            "tavily": bool(config.TAVILY_API_KEY),
            "coupang": bool(config.COUPANG_ACCESS_KEY and config.COUPANG_SECRET_KEY)}


def _serpapi() -> bool:
    """SerpApi 키가 있고 Serper 키가 없으면 SerpApi로 (둘 다 있으면 Serper)."""
    return bool(config.SERPAPI_API_KEY) and not config.SERPER_API_KEY


def any_enabled() -> bool:
    return any(enabled_sources().values())


def _clean(s: str | None) -> str:
    return html.unescape(_TAG.sub("", s or "")).strip()


def _cached(key: str, fn):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_SEC:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _oid(*parts: str) -> str:
    return "w" + hashlib.sha1("|".join(parts).encode()).hexdigest()[:9]


# ───────── 수량 파싱: "6개입 x 2" → 12 ─────────
_QTY = re.compile(r"(\d{1,4})\s*(개입|개|입|구|팩|봉|박스|세트|병|캔|알|pcs|ea)", re.I)
_MUL = re.compile(r"[x×*]\s*(\d{1,3})(?!\s*(?:g|kg|ml|l)\b)", re.I)


def parse_qty(title: str) -> int | None:
    m = _QTY.search(title or "")
    if not m:
        return None
    q = int(m.group(1))
    mm = _MUL.search(title[m.end():m.end() + 12])
    if mm:
        q *= int(mm.group(1))
    return q if 0 < q < 10000 else None


_PRICE_TXT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,7})\s*원")


def prices_in_text(text: str) -> list[int]:
    out = []
    for m in _PRICE_TXT.finditer(text or ""):
        v = int(m.group(1).replace(",", ""))
        if 500 <= v <= 5_000_000:
            out.append(v)
    return out


# ───────── 소스별 어댑터 ─────────
def _http() -> httpx.Client:
    return httpx.Client(timeout=config.WEB_TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": "Mozilla/5.0 (SharePie hackathon bot; +https://sharepie.app)"})


def naver_shop(query: str, n: int = 30) -> list[dict[str, Any]]:
    if not enabled_sources()["naver"]:
        return []

    def go():
        with _http() as c:
            r = c.get(f"{config.NAVER_API_BASE}/v1/search/shop.json",
                      params={"query": query, "display": n, "sort": "sim"},
                      headers={"X-Naver-Client-Id": config.NAVER_CLIENT_ID, "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET})
            r.raise_for_status()
            items = r.json().get("items", [])
        out = []
        for it in items:
            price = int(it.get("lprice") or 0)
            if price <= 0:
                continue
            title = _clean(it.get("title"))
            out.append({"id": _oid("naver", it.get("productId") or it.get("link", ""), str(price)), "title": title,
                        "price": price, "mall": it.get("mallName") or "네이버쇼핑", "url": it.get("link"),
                        "image": it.get("image"), "source": "naver", "verified": True, "qty": parse_qty(title),
                        "brand": it.get("brand") or it.get("maker") or ""})
        return out
    return _cached("naver:" + query, go)


def naver_context(query: str, n: int = 4) -> list[dict[str, Any]]:
    if not enabled_sources()["naver"]:
        return []

    def go():
        out = []
        with _http() as c:
            for kind in ("news", "blog"):
                r = c.get(f"{config.NAVER_API_BASE}/v1/search/{kind}.json", params={"query": query, "display": n, "sort": "sim"},
                          headers={"X-Naver-Client-Id": config.NAVER_CLIENT_ID, "X-Naver-Client-Secret": config.NAVER_CLIENT_SECRET})
                if r.status_code >= 400:
                    continue
                for it in r.json().get("items", []):
                    out.append({"title": _clean(it.get("title")), "text": _clean(it.get("description")),
                                "url": it.get("originallink") or it.get("link"), "source": f"naver_{kind}"})
        return out
    return _cached("naverctx:" + query, go)


def _price_str(v) -> int:
    """'₩24,000' / '24,000원' / 'KRW 24000' / 24000 → 24000"""
    if isinstance(v, (int, float)):
        return int(v)
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", str(v or ""))
    return int(m.group(1).replace(",", "")) if m else 0


def serper_shop(query: str, n: int = 20) -> list[dict[str, Any]]:
    """구글 쇼핑 결과 (여러 쇼핑몰의 가격·판매처·링크)."""
    if not enabled_sources()["serper"]:
        return []

    def go():
        with _http() as c:
            if _serpapi():
                r = c.get(f"{config.SERPAPI_API_BASE}/search.json", params={
                    "engine": "google_shopping", "q": query, "gl": "kr", "hl": "ko", "google_domain": "google.co.kr",
                    "num": n, "api_key": config.SERPAPI_API_KEY})
                r.raise_for_status()
                items = [{"title": it.get("title"), "source": it.get("source"), "price": it.get("price") or it.get("extracted_price"),
                          "link": it.get("product_link") or it.get("link"), "imageUrl": it.get("thumbnail")}
                         for it in (r.json().get("shopping_results") or [])]
            else:
                r = c.post(f"{config.SERPER_API_BASE}/shopping", json={"q": query, "gl": "kr", "hl": "ko", "num": n},
                           headers={"X-API-KEY": config.SERPER_API_KEY})
                r.raise_for_status()
                items = r.json().get("shopping", [])
        out = []
        for it in items:
            price = _price_str(it.get("price"))
            if price <= 0 or ("$" in str(it.get("price")) and "₩" not in str(it.get("price"))):
                continue  # 원화가 아닌 가격은 제외
            title = _clean(it.get("title"))
            out.append({"id": _oid("serper", it.get("link") or title, str(price)), "title": title, "price": price,
                        "mall": it.get("source") or mall_from_host(urlparse(it.get("link") or "").hostname or ""),
                        "url": it.get("link"), "image": it.get("imageUrl"), "source": "serper", "verified": True,
                        "qty": parse_qty(title)})
        return out
    return _cached("serper:" + query, go)


def serper_web(query: str, n: int = 8) -> list[dict[str, Any]]:
    """구글 웹 검색 결과 → 상품 페이지 가격 읽기·참고 문맥 (Tavily와 같은 형식)."""
    if not enabled_sources()["serper"]:
        return []

    def go():
        with _http() as c:
            if _serpapi():
                r = c.get(f"{config.SERPAPI_API_BASE}/search.json", params={
                    "engine": "google", "q": query, "gl": "kr", "hl": "ko", "google_domain": "google.co.kr", "num": n,
                    "api_key": config.SERPAPI_API_KEY})
                r.raise_for_status()
                rows = r.json().get("organic_results") or []
            else:
                r = c.post(f"{config.SERPER_API_BASE}/search", json={"q": query, "gl": "kr", "hl": "ko", "num": n},
                           headers={"X-API-KEY": config.SERPER_API_KEY})
                r.raise_for_status()
                rows = r.json().get("organic", [])
            return [{"title": _clean(x.get("title")), "text": _clean(x.get("snippet"))[:500], "url": x.get("link"),
                     "source": "serper_web", "score": 1.0 / (1 + i)} for i, x in enumerate(rows)]
    return _cached("serperweb:" + query, go)


def tavily(query: str, n: int = 8) -> list[dict[str, Any]]:
    if not enabled_sources()["tavily"]:
        return []

    def go():
        with _http() as c:
            r = c.post(f"{config.TAVILY_API_BASE}/search", json={"query": query, "max_results": n, "search_depth": "basic"},
                       headers={"Authorization": f"Bearer {config.TAVILY_API_KEY}"})
            r.raise_for_status()
            return [{"title": _clean(x.get("title")), "text": _clean(x.get("content"))[:500], "url": x.get("url"),
                     "source": "tavily", "score": x.get("score", 0)} for x in r.json().get("results", [])]
    return _cached("tavily:" + query, go)


def coupang(query: str, n: int = 10) -> list[dict[str, Any]]:
    if not enabled_sources()["coupang"]:
        return []

    def go():
        path = "/v2/providers/affiliate_open_api/apis/openapi/products/search"
        qs = urlencode({"keyword": query, "limit": n}, quote_via=quote)
        dt = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        sig = hmac.new(config.COUPANG_SECRET_KEY.encode(), f"{dt}GET{path}{qs}".encode(), hashlib.sha256).hexdigest()
        auth = f"CEA algorithm=HmacSHA256, access-key={config.COUPANG_ACCESS_KEY}, signed-date={dt}, signature={sig}"
        with _http() as c:
            r = c.get(f"{config.COUPANG_API_BASE}{path}?{qs}", headers={"Authorization": auth})
            r.raise_for_status()
            data = (r.json().get("data") or {}).get("productData") or []
        return [{"id": _oid("coupang", str(x.get("productId")), str(x.get("productPrice"))), "title": _clean(x.get("productName")),
                 "price": int(x.get("productPrice") or 0), "mall": "쿠팡" + (" 로켓배송" if x.get("isRocket") else ""),
                 "url": x.get("productUrl"), "image": x.get("productImage"), "source": "coupang", "verified": True,
                 "qty": parse_qty(x.get("productName") or "")} for x in data if x.get("productPrice")]
    return _cached("coupang:" + query, go)


def _public_url(url: str) -> bool:
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        if config.WEB_ALLOW_PRIVATE:
            return True
        for info in socket.getaddrinfo(p.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False  # 서버 내부망 접근(SSRF) 차단
        return True
    except Exception:
        return False


def _ld_products(obj) -> list[dict]:
    out = []
    if isinstance(obj, list):
        for x in obj:
            out += _ld_products(x)
    elif isinstance(obj, dict):
        t = obj.get("@type")
        if t == "Product" or (isinstance(t, list) and "Product" in t):
            out.append(obj)
        for k in ("@graph", "itemListElement", "item"):
            if k in obj:
                out += _ld_products(obj[k])
    return out


def _safe_get(url: str, max_hops: int = 3, max_bytes: int = 1_500_000):
    """리다이렉트를 한 단계씩 따라가며 매번 내부망 주소인지 다시 검사 (SSRF 방지), 본문 크기 제한."""
    with httpx.Client(timeout=config.WEB_TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": "Mozilla/5.0 (SharePie hackathon bot; +https://sharepie.app)"}) as c:
        for _ in range(max_hops + 1):
            if not _public_url(url):
                return None
            with c.stream("GET", url) as r:
                if r.is_redirect and r.headers.get("location"):
                    url = str(r.url.join(r.headers["location"]))
                    continue
                buf = b""
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > max_bytes:
                        break
                hdr = {k: v for k, v in r.headers.items() if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                return httpx.Response(r.status_code, headers=hdr, content=buf, request=r.request)
    return None


def page_offer(url: str, fallback_title: str = "") -> dict[str, Any] | None:
    """상품 페이지의 구조화 가격(schema.org Product / og:price)만 읽는다."""
    if not url or not _public_url(url):
        return None
    try:
        r = _safe_get(url)
        if r is None:
            return None
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", "html"):
            return None
        page = r.text[:600_000]
    except Exception:
        return None
    price, title = None, None
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        for p in _ld_products(data):
            offers = p.get("offers") or {}
            offers = offers[0] if isinstance(offers, list) and offers else offers
            v = offers.get("price") or offers.get("lowPrice") if isinstance(offers, dict) else None
            try:
                price = int(float(str(v).replace(",", "")))
            except (TypeError, ValueError):
                continue
            title = _clean(p.get("name"))
            break
        if price:
            break
    if not price:
        m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([\d.,]+)', page, re.I)
        if m:
            price = int(float(m.group(1).replace(",", "")))
    if not price or price <= 0:
        return None
    if not title:
        m = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page, re.I)
        title = _clean(m.group(1)) if m else fallback_title
    host = urlparse(url).hostname or ""
    return {"id": _oid("page", url, str(price)), "title": title or fallback_title, "price": price, "mall": mall_from_host(host),
            "url": url, "image": None, "source": "page", "verified": True, "qty": parse_qty(title or "")}


_HOSTS = {"coupang.com": "쿠팡", "smartstore.naver.com": "네이버 스마트스토어", "shopping.naver.com": "네이버쇼핑",
          "11st.co.kr": "11번가", "gmarket.co.kr": "G마켓", "auction.co.kr": "옥션", "ssg.com": "SSG",
          "lotteon.com": "롯데ON", "kurly.com": "컬리", "oasis.co.kr": "오아시스", "gsshop.com": "GS SHOP",
          "gs25.gsretail.com": "GS25", "hanjungsun.co.kr": "한정선 공식몰"}


def mall_from_host(host: str) -> str:
    host = (host or "").lower()
    for k, v in _HOSTS.items():
        if host.endswith(k):
            return v
    return host.removeprefix("www.")


def web_offers_from_results(results: list[dict[str, Any]], max_pages: int = 3) -> list[dict[str, Any]]:
    """웹 검색 결과 → (1) 상위 페이지 구조화 가격 (2) 본문에 적힌 가격(unverified)."""
    offers = []
    pages = [r for r in results if r.get("url")][:max_pages]
    with cf.ThreadPoolExecutor(max_workers=3) as ex:
        for off in ex.map(lambda r: page_offer(r["url"], r.get("title", "")), pages):
            if off:
                offers.append(off)
    have = {o["url"] for o in offers}
    for r in results:
        if r.get("url") in have:
            continue
        ps = prices_in_text(r.get("text", "") + " " + r.get("title", ""))
        if ps:
            host = urlparse(r["url"]).hostname or ""
            offers.append({"id": _oid("text", r["url"], str(ps[0])), "title": r["title"], "price": ps[0],
                           "mall": mall_from_host(host), "url": r["url"], "image": None, "source": "web_text",
                           "verified": False, "qty": parse_qty(r["title"])})
    return offers


def gather(queries: list[str], context_query: str | None = None) -> dict[str, Any]:
    """여러 검색어 × 여러 소스를 병렬로 돈다. 반환: offers(가격 있는 후보), context(참고 문맥), stats."""
    queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q][:3]
    stats = {k: 0 for k in ("naver", "serper", "page", "web_text", "coupang", "context")}
    errors = []
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for q in queries:
            jobs.append(("naver", ex.submit(naver_shop, q)))
            jobs.append(("coupang", ex.submit(coupang, q)))
            jobs.append(("tavily", ex.submit(tavily, q + " 가격")))
            jobs.append(("serper", ex.submit(serper_shop, q)))
        if queries and not enabled_sources()["tavily"]:
            jobs.append(("serper_web", ex.submit(serper_web, queries[0] + " 가격")))
        ctx_job = ex.submit(naver_context, context_query or queries[0]) if queries else None
        offers, web_results = [], []
        for kind, fut in jobs:
            try:
                res = fut.result()
            except Exception as e:
                errors.append(f"{kind}: {type(e).__name__}")
                continue
            if kind in ("tavily", "serper_web"):
                web_results += res
            else:
                offers += res
        context = []
        if ctx_job:
            try:
                context = ctx_job.result()
            except Exception as e:
                errors.append(f"context: {type(e).__name__}")
    web_results.sort(key=lambda r: -(r.get("score") or 0))
    offers += web_offers_from_results(web_results)
    context += [r for r in web_results[:4]]
    seen, uniq = set(), []
    for o in offers:
        key = (re.sub(r"\s+", "", o["title"])[:40], o["price"], o["mall"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(o)
        stats[o["source"]] = stats.get(o["source"], 0) + 1
    stats["context"] = len(context)
    return {"offers": uniq, "context": context, "stats": stats, "errors": errors, "queries": queries,
            "sources": enabled_sources()}
