"""GPS 좌표 → 동네 이름 (역지오코딩). 좌표는 저장하지 않고 '서울 성동구 성수동' 같은 동 단위 이름만 돌려준다.

- KAKAO_REST_KEY 가 있으면 카카오 로컬 API (한국 행정동·법정동 정확)
- 없으면 OpenStreetMap Nominatim (키 불필요 · 초당 1회 제한 → 캐시·간격 준수)
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from . import config


class GeoError(Exception):
    pass


_cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
_last_osm = [0.0]
_CITY = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
         "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
         "강원도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라북도": "전북",
         "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}


def _short_dong(d: str) -> str:
    """'성수1가1동'·'성수동1가' → '성수동' 처럼 사람이 부르는 동 이름으로."""
    import re
    d = (d or "").strip()
    m = re.match(r"^([가-힣]+?)(\d+가)?\d*동$", d) or re.match(r"^([가-힣]+?)동\d*가?$", d)
    if m:
        return m.group(1) + "동"
    return d


def _fmt(city: str, gu: str, dong: str) -> str:
    parts = [_CITY.get(city, city), gu, _short_dong(dong)]
    return " ".join(p for p in parts if p)


def _kakao(lat: float, lng: float) -> dict[str, Any]:
    r = httpx.get(f"{config.KAKAO_API_BASE}/v2/local/geo/coord2regioncode.json", params={"x": lng, "y": lat},
                  headers={"Authorization": f"KakaoAK {config.KAKAO_REST_KEY}"}, timeout=8)
    r.raise_for_status()
    docs = r.json().get("documents") or []
    d = next((x for x in docs if x.get("region_type") == "B"), docs[0] if docs else None)
    if not d:
        raise GeoError("주소를 찾지 못했어요")
    return {"address": _fmt(d.get("region_1depth_name"), d.get("region_2depth_name"), d.get("region_3depth_name")),
            "source": "kakao"}


def _osm(lat: float, lng: float) -> dict[str, Any]:
    with _lock:   # Nominatim 이용 정책: 초당 1회 이하
        wait = 1.05 - (time.time() - _last_osm[0])
        if wait > 0:
            time.sleep(wait)
        _last_osm[0] = time.time()
    r = httpx.get(f"{config.NOMINATIM_BASE}/reverse", params={"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 16,
                                                              "accept-language": "ko", "addressdetails": 1},
                  headers={"User-Agent": "SharePie-hackathon/1.0 (+https://sharepie.app)"}, timeout=8)
    r.raise_for_status()
    a = (r.json() or {}).get("address") or {}
    if not a:
        raise GeoError("주소를 찾지 못했어요")
    city = a.get("city") or a.get("province") or a.get("state") or ""
    gu = a.get("borough") or a.get("county") or a.get("city_district") or (a.get("city") if a.get("province") else "") or ""
    dong = a.get("quarter") or a.get("suburb") or a.get("neighbourhood") or a.get("village") or a.get("town") or ""
    if gu == city:
        gu = ""
    addr = _fmt(city, gu, dong) or a.get("country", "")
    return {"address": addr, "source": "openstreetmap"}


def reverse(lat: float, lng: float) -> dict[str, Any]:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise GeoError("좌표가 올바르지 않아요")
    key = (round(lat, 3), round(lng, 3))   # 약 100m 격자로 캐시 (같은 동네에서 반복 조회 방지)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    try:
        out = _kakao(lat, lng) if config.KAKAO_REST_KEY else _osm(lat, lng)
    except (httpx.HTTPError, ValueError) as e:
        raise GeoError(f"위치 → 동네 변환 실패: {type(e).__name__}") from e
    _cache[key] = (time.time(), out)
    return out
