export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function isFinitePositive(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

export function mapPriceToAngle(
  price: number,
  minPrice: number,
  maxPrice: number,
  startAngle: number,
  endAngle: number,
) {
  const progress = clamp((price - minPrice) / Math.max(maxPrice - minPrice, 1e-12), 0, 1);
  return startAngle + progress * (endAngle - startAngle);
}

export function getBufferPercent(currentPrice: number, liquidationPrice: number | null) {
  if (!isFinitePositive(currentPrice) || !isFinitePositive(liquidationPrice)) {
    return null;
  }

  return ((currentPrice - liquidationPrice) / currentPrice) * 100;
}

export function describeRiskLevel(bufferPercent: number | null) {
  if (bufferPercent === null) return '未知';
  if (bufferPercent <= 0) return '可清算';
  if (bufferPercent < 10) return '高风险';
  if (bufferPercent < 25) return '观察';
  return '安全区';
}
