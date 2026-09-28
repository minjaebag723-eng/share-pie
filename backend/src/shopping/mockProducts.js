'use strict';

// Shopping 모듈 목(Mock) 상품 데이터
// SerpApi 키가 없거나, 한도 초과/장애일 때 데모가 멈추지 않도록 쓰는 대체 후보.
// 가격은 UI 목업(Share_Pie_dc.html의 P 목록)과 비슷한 수준으로 맞춤. 실제 판매 상품이 아님.

const MOCK_PRODUCTS = [
  { id: 'mock-meat-1', name: '삼겹살 1.2kg', price: 35900, source: '공동구매(목 데이터)', keywords: ['고기', '삼겹', '돼지', '뒤풀이', '바베큐', '바비큐'] },
  { id: 'mock-meat-2', name: '목살 1.5kg', price: 39900, source: '공동구매(목 데이터)', keywords: ['고기', '목살', '돼지', '뒤풀이', '바베큐', '바비큐'] },
  { id: 'mock-meat-3', name: '돼지고기 혼합세트 1.4kg', price: 42900, source: '공동구매(목 데이터)', keywords: ['고기', '삼겹', '목살', '돼지', '뒤풀이', '바베큐', '바비큐'] },
  { id: 'mock-meat-4', name: '한우 등심 600g', price: 89000, source: '공동구매(목 데이터)', keywords: ['고기', '한우', '소고기', '등심'] },
  { id: 'mock-fruit-1', name: '제철 딸기 1kg', price: 18900, source: '공동구매(목 데이터)', keywords: ['과일', '딸기'] },
  { id: 'mock-fruit-2', name: '제주 감귤 5kg', price: 24900, source: '공동구매(목 데이터)', keywords: ['과일', '귤', '감귤', '제주'] },
  { id: 'mock-fruit-3', name: '부사 사과 3kg', price: 29900, source: '공동구매(목 데이터)', keywords: ['과일', '사과'] },
  { id: 'mock-snack-1', name: '과자 대용량 세트 20봉', price: 22900, source: '공동구매(목 데이터)', keywords: ['과자', '간식', '스낵'] },
  { id: 'mock-snack-2', name: '견과류 하루한줌 30봉', price: 27900, source: '공동구매(목 데이터)', keywords: ['견과', '간식'] },
  { id: 'mock-drink-1', name: '탄산음료 500ml 24병', price: 19900, source: '공동구매(목 데이터)', keywords: ['음료', '탄산', '콜라', '사이다'] },
  { id: 'mock-drink-2', name: '생수 2L 12병', price: 9900, source: '공동구매(목 데이터)', keywords: ['음료', '생수', '물'] },
];

// 검색어에 들어 있는 키워드가 많이 겹치는 순으로 반환 (하나도 안 겹치면 제외)
function searchMockProducts(query) {
  const q = String(query || '').replace(/\s+/g, '');
  return MOCK_PRODUCTS
    .map((p) => ({ p, score: p.keywords.filter((k) => q.includes(k)).length + (q.includes(p.name.replace(/\s+/g, '')) ? 5 : 0) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(({ p }) => ({ id: p.id, name: p.name, price: p.price, source: p.source, link: null, thumbnail: null }));
}

module.exports = { MOCK_PRODUCTS, searchMockProducts };
