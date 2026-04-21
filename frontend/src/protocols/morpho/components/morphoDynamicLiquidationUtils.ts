export type MorphoPricePoint = {
  timestamp: string | number;
  price: number;
  amount?: number | null;
};

export type DynamicLiquidationPoint = {
  timestamp: string | number;
  collateralPrice: number;
  debtPrice: number;
  liquidationPrice: number;
  debtLiquidationPrice: number;
  priceRatio: number;
  healthFactor: number;
  liquidationDistancePct: number;
  debtLiquidationDistancePct: number;
  riskMargin: number;
};

function toFiniteNumber(value: number): number | null {
  return Number.isFinite(value) ? value : null;
}

function getExtent(values: number[]): { min: number; max: number } {
  const finiteValues = values.filter((value) => Number.isFinite(value) && value > 0);
  if (finiteValues.length === 0) return { min: 0, max: 1 };

  const min = Math.min(...finiteValues);
  const max = Math.max(...finiteValues);
  if (min === max) {
    const padding = Math.max(Math.abs(max) * 0.08, 1);
    return { min: Math.max(0, min - padding), max: max + padding };
  }

  const padding = (max - min) * 0.12;
  return {
    min: Math.max(0, min - padding),
    max: max + padding,
  };
}

function niceStep(rawStep: number): number {
  if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const niceNormalized = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return niceNormalized * magnitude;
}

export function syncAxis(
  leftValues: number[],
  rightValues: number[],
  splitNumber = 5,
): {
  left: { min: number; max: number; interval: number; splitNumber: number };
  right: { min: number; max: number; interval: number; splitNumber: number };
} {
  const makeAxis = (values: number[]) => {
    const extent = getExtent(values);
    const interval = niceStep((extent.max - extent.min) / splitNumber);
    const min = Math.max(0, Math.floor(extent.min / interval) * interval);
    const max = Math.ceil(extent.max / interval) * interval;
    return { min, max, interval, splitNumber };
  };

  return {
    left: makeAxis(leftValues),
    right: makeAxis(rightValues),
  };
}

export function calculateLiquidationPrice(
  debtPrice: number,
  debtAmount: number,
  collateralAmount: number,
  lltv: number,
): number {
  if (debtPrice <= 0 || debtAmount <= 0 || collateralAmount <= 0 || lltv <= 0) return 0;
  return debtPrice * (debtAmount / (collateralAmount * lltv));
}

export function calculateLiquidationDistancePct(
  collateralPrice: number,
  liquidationPrice: number,
): number {
  if (collateralPrice <= 0 || liquidationPrice <= 0) return 0;
  return ((collateralPrice - liquidationPrice) / collateralPrice) * 100;
}

export function calculateDebtLiquidationPrice(
  collateralPrice: number,
  debtAmount: number,
  collateralAmount: number,
  lltv: number,
): number {
  if (collateralPrice <= 0 || debtAmount <= 0 || collateralAmount <= 0 || lltv <= 0) return 0;
  return collateralPrice * ((collateralAmount * lltv) / debtAmount);
}

export function buildDynamicLiquidationSeries({
  collateralSeries,
  debtSeries,
  debtAmount,
  collateralAmount,
  lltv,
}: {
  collateralSeries: MorphoPricePoint[];
  debtSeries: MorphoPricePoint[];
  debtAmount: number;
  collateralAmount: number;
  lltv: number;
}): DynamicLiquidationPoint[] {
  const debtPriceByTime = new Map<string | number, number>();
  const debtAmountByTime = new Map<string | number, number>();

  debtSeries.forEach((point) => {
    const debtPrice = toFiniteNumber(point.price);
    if (debtPrice !== null && debtPrice > 0) {
      debtPriceByTime.set(point.timestamp, debtPrice);
    }
    if (point.amount !== null && point.amount !== undefined && point.amount > 0) {
      debtAmountByTime.set(point.timestamp, point.amount);
    }
  });

  return collateralSeries
    .map((point) => {
      const collateralPrice = toFiniteNumber(point.price);
      const debtPrice = debtPriceByTime.get(point.timestamp);
      if (collateralPrice === null || collateralPrice <= 0 || debtPrice === undefined) return null;

      const pointDebtAmount = debtAmountByTime.get(point.timestamp) ?? debtAmount;
      const pointCollateralAmount =
        point.amount !== null && point.amount !== undefined && point.amount > 0
          ? point.amount
          : collateralAmount;
      const liquidationPrice = calculateLiquidationPrice(
        debtPrice,
        pointDebtAmount,
        pointCollateralAmount,
        lltv,
      );
      if (liquidationPrice <= 0) return null;

      const debtLiquidationPrice = calculateDebtLiquidationPrice(
        collateralPrice,
        pointDebtAmount,
        pointCollateralAmount,
        lltv,
      );
      if (debtLiquidationPrice <= 0) return null;

      const priceRatio = debtPrice > 0 ? collateralPrice / debtPrice : 0;
      const healthFactor = liquidationPrice > 0 ? collateralPrice / liquidationPrice : 0;

      return {
        timestamp: point.timestamp,
        collateralPrice,
        debtPrice,
        liquidationPrice,
        debtLiquidationPrice,
        priceRatio,
        healthFactor,
        liquidationDistancePct: calculateLiquidationDistancePct(collateralPrice, liquidationPrice),
        debtLiquidationDistancePct: calculateLiquidationDistancePct(
          debtLiquidationPrice,
          debtPrice,
        ),
        riskMargin: collateralPrice - liquidationPrice * 1.1,
      };
    })
    .filter((point): point is DynamicLiquidationPoint => point !== null);
}
