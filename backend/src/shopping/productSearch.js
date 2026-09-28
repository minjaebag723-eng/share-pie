'use strict';

// Shopping 모듈 — 상품 후보 검색 (외부 API, AI 미사용)
// - 기본: SerpApi Google Shopping (gl=kr, hl=ko → 원화 가격)  키: SHOPPING_API_KEY
// - 대체: 목(Mock) 데이터 — 키 없음 / SHOPPING_PROVIDER=mock / SerpApi 에러(키 오류, 한도 초과, 장애) 시
//   Shopping은 선택적 모듈이라, 외부 API 문제로 데모가 멈추지 않게 항상 결과를 돌려준다.

const { searchMockProducts } = require('./mockProducts');
const { logEvent } = require('../logger');

const SERPAPI_URL = 'https://serpapi.com/search.json';
const TIMEOUT_MS = 10_000;
const MAX_RESULTS = 20;

// SerpApi shopping_results 한 건 → { id, name, price, source, link, thumbnail }
// 가격은 원 단위 정수만 받는다. 가격이 없거나 이상한 상품은 버린다.
function normalizeSerpResult(r, i) {
  const price = Math.round(Number(r.extracted_price));
  if (!r.title || !Number.isSafeInteger(price) || price <= 0) return null;
  return {
    id: String(r.product_id || r.position || `serp-${i}`),
    name: String(r.title).trim(),
    price,
    source: r.source || null,
    link: r.product_link || r.link || null,
    thumbnail: r.thumbnail || null,
  };
}

async function searchSerpApi(query) {
  const url = new URL(SERPAPI_URL);
  url.searchParams.set('engine', 'google_shopping');
  url.searchParams.set('q', query);
  url.searchParams.set('gl', 'kr');
  url.searchParams.set('hl', 'ko');
  url.searchParams.set('api_key', process.env.SHOPPING_API_KEY);

  const res = await fetch(url, { signal: AbortSignal.timeout(TIMEOUT_MS) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.error) throw new Error(data.error || `SerpApi HTTP ${res.status}`);

  const seen = new Set();
  return (data.shopping_results || [])
    .map(normalizeSerpResult)
    .filter((p) => p && !seen.has(p.id) && seen.add(p.id))
    .slice(0, MAX_RESULTS);
}

// → { provider: 'serpapi' | 'mock', products, fallbackReason }
async function searchProducts(query) {
  if (process.env.SHOPPING_PROVIDER === 'mock') {
    return { provider: 'mock', products: searchMockProducts(query), fallbackReason: 'SHOPPING_PROVIDER=mock' };
  }
  if (!process.env.SHOPPING_API_KEY) {
    return { provider: 'mock', products: searchMockProducts(query), fallbackReason: 'SHOPPING_API_KEY 없음' };
  }
  try {
    return { provider: 'serpapi', products: await searchSerpApi(query), fallbackReason: null };
  } catch (err) {
    // 에러 메시지에 키가 섞이지 않도록 URL은 남기지 않는다
    console.warn(`[shopping] SerpApi 실패 → 목 데이터로 대체: ${err.message}`);
    logEvent('shopping.provider_error', { query, error: err.message });
    return { provider: 'mock', products: searchMockProducts(query), fallbackReason: `SerpApi 에러: ${err.message}` };
  }
}

module.exports = { searchProducts, searchSerpApi, normalizeSerpResult };
