"""네이버 검색 API · Tavily · 상품 페이지를 흉내 내는 테스트 서버 (실제 응답 형식과 동일한 필드).
실행: python -m uvicorn tests.fake_web:app --port 8012
"""
import json
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

BASE = "http://127.0.0.1:8012"

SHOP = [
    {"title": "<b>한정선</b> 요거트 찹쌀떡 6개입 선물세트", "link": "https://smartstore.naver.com/hanjungsun/1", "image": "", "lprice": "24000",
     "hprice": "", "mallName": "한정선 공식스토어", "productId": "1001", "brand": "한정선"},
    {"title": "<b>한정선</b> 생과일 찹쌀떡 12개입 (딸기·샤인머스캣)", "link": "https://smartstore.naver.com/hanjungsun/2", "image": "",
     "lprice": "42000", "hprice": "", "mallName": "네이버 스마트스토어", "productId": "1002", "brand": "한정선"},
    {"title": "<b>한정선</b> 찹쌀떡 3종 세트 9개입", "link": "https://www.ssg.com/item/3", "image": "", "lprice": "33000",
     "hprice": "", "mallName": "SSG닷컴", "productId": "1003", "brand": "한정선"},
    {"title": "<b>한정선</b> 요거트 찹쌀떡 1개", "link": "https://www.11st.co.kr/products/4", "image": "", "lprice": "4500",
     "hprice": "", "mallName": "11번가", "productId": "1004", "brand": "한정선"},
    {"title": "명절 찹쌀떡 선물세트 20개입", "link": "https://www.gmarket.co.kr/5", "image": "", "lprice": "25000",
     "hprice": "", "mallName": "G마켓", "productId": "1005", "brand": ""},
    {"title": "<b>한정선</b> 프리미엄 찹쌀떡 24개입 대용량 박스", "link": "https://www.lotteon.com/6", "image": "", "lprice": "79000",
     "hprice": "", "mallName": "롯데ON", "productId": "1006", "brand": "한정선"},
]
NEWS = [{"title": "편의점이 '명품 디저트' 품었다…'<b>한정선</b>' 찹쌀떡", "originallink": "https://news.example/1",
         "link": "https://news.example/1", "description": "GS25가 성수 디저트 <b>한정선</b> 요거트 찹쌀떡을 3,900원에 출시했다."}]
BLOG = [{"title": "성수 <b>한정선</b> 후기", "link": "https://blog.naver.com/x/1", "description": "줄 서서 먹는 생과일 찹쌀떡, 선물세트도 판매"}]


async def naver(request):
    if not request.headers.get("X-Naver-Client-Id"):
        return JSONResponse({"errorMessage": "Not Exist Client ID"}, status_code=401)
    kind = request.path_params["kind"]
    q = request.query_params.get("query", "")
    if "한정선" not in q:
        return JSONResponse({"items": []})
    items = {"shop.json": SHOP, "news.json": NEWS, "blog.json": BLOG}.get(kind, [])
    return JSONResponse({"total": len(items), "start": 1, "display": len(items), "items": items})


async def tavily(request):
    b = await request.json()
    if "한정선" not in b.get("query", ""):
        return JSONResponse({"results": []})
    return JSONResponse({"query": b["query"], "results": [
        {"title": "한정선 시그니처 찹쌀떡 10구 선물세트 - 한정선 공식몰", "url": f"{BASE}/official/gift", "content": "공식몰 선물세트", "score": 0.9},
        {"title": "한정선 찹쌀떡 8개입 - 쿠팡", "url": f"{BASE}/coupang/123", "content": "로켓배송 한정선 찹쌀떡 8개입 29,800원 무료배송", "score": 0.8},
        {"title": "GS25 한정선 요거트 찹쌀떡 출시", "url": f"{BASE}/news/gs25", "content": "냉동 디저트 한정선 요거트 찹쌀떡 가격은 3,900원", "score": 0.7},
    ]})


async def serper_shop(request):
    if not request.headers.get("X-API-KEY"):
        return JSONResponse({"message": "Unauthorized"}, status_code=403)
    b = await request.json()
    if "교촌" in b.get("q", ""):
        return JSONResponse({"shopping": [
            {"title": "교촌치킨 허니콤보 기프티콘", "source": "카카오톡 선물하기", "link": "https://gift.kakao.com/product/1", "price": "₩23,000"},
            {"title": "교촌 허니콤보 + 콜라1.25L", "source": "기프티쇼", "link": "https://giftishow.com/2", "price": "25,000원"},
            {"title": "허니 머스타드 소스", "source": "쿠팡", "link": "https://coupang.com/3", "price": "3,000원"}]})
    if "한정선" not in b.get("q", ""):
        return JSONResponse({"shopping": []})
    return JSONResponse({"searchParameters": b, "shopping": [
        {"title": "한정선 요거트 찹쌀떡 8개입 선물박스", "source": "쿠팡", "link": "https://www.coupang.com/vp/products/77",
         "price": "₩29,800", "imageUrl": "", "position": 1},
        {"title": "한정선 생과일 찹쌀떡 6구", "source": "컬리", "link": "https://www.kurly.com/goods/88", "price": "21,500원", "position": 2},
        {"title": "Hanjungsun mochi (US)", "source": "Amazon", "link": "https://amazon.com/x", "price": "$25.00", "position": 3},
    ]})


async def serper_search(request):
    b = await request.json()
    return JSONResponse({"organic": [
        {"title": "한정선 시그니처 찹쌀떡 10구 선물세트 - 한정선 공식몰", "link": f"{BASE}/official/gift", "snippet": "공식몰 선물세트"},
        {"title": "GS25 한정선 요거트 찹쌀떡 출시", "link": f"{BASE}/news/gs25", "snippet": "가격은 3,900원"}]} if "한정선" in b.get("q", "") else {"organic": []})


async def serpapi(request):   # serpapi.com /search.json 흉내 — Serper 가짜 데이터를 SerpApi 형식으로
    q = dict(request.query_params)
    if not q.get("api_key"):
        return JSONResponse({"error": "Invalid API key"}, status_code=401)
    from starlette.requests import Request as _R
    body = json.dumps({"q": q.get("q", "")}).encode()

    async def rcv():
        return {"type": "http.request", "body": body}
    fake = _R({"type": "http", "method": "POST", "headers": [(b"x-api-key", b"x")], "path": "/", "query_string": b""}, rcv)
    if q.get("engine") == "google_shopping":
        src = json.loads((await serper_shop(fake)).body).get("shopping", [])
        return JSONResponse({"shopping_results": [{"title": x["title"], "source": x.get("source"), "price": x.get("price"),
                                                   "product_link": x.get("link"), "thumbnail": x.get("imageUrl", "")} for x in src]})
    src = json.loads((await serper_search(fake)).body).get("organic", [])
    return JSONResponse({"organic_results": src})


async def official(_):
    return HTMLResponse("""<html><head><meta property="og:title" content="한정선 시그니처 찹쌀떡 10구 선물세트">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"한정선 시그니처 찹쌀떡 10구 선물세트",
"offers":{"@type":"Offer","price":"36000","priceCurrency":"KRW"}}</script></head><body>...</body></html>""")


async def coupang_page(_):
    return PlainTextResponse("Access Denied", status_code=403)  # 실제 쿠팡처럼 봇 차단


async def news(_):
    return HTMLResponse("<html><head><title>GS25 한정선</title></head><body>가격은 3,900원</body></html>")


async def nominatim(request):   # OpenStreetMap 역지오코딩 흉내
    lat = float(request.query_params.get("lat", 0))
    if lat > 37.54:
        a = {"city": "서울특별시", "borough": "성동구", "quarter": "성수동1가", "country": "대한민국"}
    else:
        a = {"city": "서울특별시", "borough": "강남구", "quarter": "역삼1동", "country": "대한민국"}
    return JSONResponse({"address": a, "display_name": "..."})


async def kakao_region(request):   # 카카오 로컬 coord2regioncode 흉내
    if not request.headers.get("authorization", "").startswith("KakaoAK "):
        return JSONResponse({"msg": "unauthorized"}, status_code=401)
    return JSONResponse({"documents": [
        {"region_type": "B", "region_1depth_name": "서울특별시", "region_2depth_name": "성동구", "region_3depth_name": "성수동1가"},
        {"region_type": "H", "region_1depth_name": "서울특별시", "region_2depth_name": "성동구", "region_3depth_name": "성수1가1동"}]})


app = Starlette(routes=[
    Route("/reverse", nominatim),
    Route("/v2/local/geo/coord2regioncode.json", kakao_region),
    Route("/v1/search/{kind}", naver),
    Route("/search", tavily, methods=["POST"]),
    Route("/serper/shopping", serper_shop, methods=["POST"]),
    Route("/serper/search", serper_search, methods=["POST"]),
    Route("/serpapi/search.json", serpapi),
    Route("/official/gift", official),
    Route("/coupang/{pid}", coupang_page),
    Route("/news/gs25", news),
])
