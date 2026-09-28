'use strict';

// 45000 → "45,000원"
function won(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',') + '원';
}

// AI가 쓴 설명 문장에 "코드가 준 숫자"만 들어 있는지 검사한다.
// AI가 스스로 계산한 금액(환각 포함)이 사용자에게 노출되지 않게 막는 장치.
// - 100 이하 정수(인원수, "3박 4일" 등)는 허용
// - "4만 5천원"처럼 만/천 단위 표기는 검증이 불가능하므로 금지
function findUnverifiedNumbers(text, allowedNumbers) {
  const problems = [];
  const cleaned = String(text).replace(/0x[0-9a-fA-F]+/g, ''); // txHash 제외
  if (/\d\s*[만천]/.test(cleaned)) problems.push('금액은 "45,000원"처럼 숫자와 쉼표로만 쓰세요 (만/천 단위 표기 금지)');
  const allowed = new Set(allowedNumbers.filter((v) => Number.isFinite(v)));
  for (const m of cleaned.matchAll(/\d[\d,]*(?:\.\d+)?/g)) {
    const value = Number(m[0].replace(/,/g, ''));
    if (!Number.isFinite(value)) continue;
    if (Number.isInteger(value) && value <= 100) continue;
    if (!allowed.has(value)) problems.push(`입력 데이터에 없는 숫자 "${m[0]}"를 사용했습니다`);
  }
  return problems;
}

module.exports = { won, findUnverifiedNumbers };
