interface PriceGaugeProps {
  currentPrice: number;
  liquidationPrice: number | null;
  predictedPrice?: number | null;
  formatPrice: (price: number) => string;
  arcDegrees?: number;
  maxPrice?: number;
  minPrice?: number;
  priceUnit?: string;
  valueLabel?: string;
  showStats?: boolean;
  className?: string;
}

interface GaugeGeometry {
  cx: number;
  cy: number;
  radius: number;
  startAngle: number;
  gaugeAngle: number;
}

const SVG_WIDTH = 500;
const SVG_HEIGHT = 172;
const DEFAULT_GEOMETRY: GaugeGeometry = {
  cx: 250,
  cy: 130,
  radius: 118,
  startAngle: -60,
  gaugeAngle: 120,
};

function formatGaugeLabelPrice(price: number, formatPrice: (price: number) => string) {
  const formatted = formatPrice(price);
  const match = formatted.match(/^([^0-9-]*)(-?\d+(?:\.\d+)?)(.*)$/);

  if (!match) return formatted;

  const [, prefix, numeric, suffix] = match;
  const compact = Number(numeric)
    .toFixed(4)
    .replace(/\.?0+$/, '');
  return `${prefix}${compact}${suffix}`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function isFinitePositive(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function polarToCartesian(cx: number, cy: number, radius: number, angleDeg: number) {
  const angleRad = ((angleDeg - 90) * Math.PI) / 180;
  return {
    x: cx + radius * Math.cos(angleRad),
    y: cy + radius * Math.sin(angleRad),
  };
}

function pointBetween(
  start: { x: number; y: number },
  end: { x: number; y: number },
  progress: number,
) {
  return {
    x: start.x + (end.x - start.x) * progress,
    y: start.y + (end.y - start.y) * progress,
  };
}

function describeArc(cx: number, cy: number, radius: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, radius, endAngle);
  const end = polarToCartesian(cx, cy, radius, startAngle);
  const largeArcFlag = Math.abs(endAngle - startAngle) <= 180 ? '0' : '1';

  return `M ${start.x} ${start.y} A ${radius} ${radius} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`;
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

export function PriceGauge({
  currentPrice,
  liquidationPrice,
  predictedPrice = null,
  formatPrice,
  arcDegrees = 120,
  maxPrice,
  minPrice,
  priceUnit,
  showStats = true,
  className = '',
}: PriceGaugeProps) {
  const safeCurrentPrice = Number.isFinite(currentPrice) ? currentPrice : 0;
  const safeLiquidationPrice = isFinitePositive(liquidationPrice) ? liquidationPrice : null;
  const safePredictedPrice = isFinitePositive(predictedPrice) ? predictedPrice : null;
  const bufferPercent = getBufferPercent(safeCurrentPrice, safeLiquidationPrice);
  const predictedBufferPercent = getBufferPercent(safePredictedPrice ?? 0, safeLiquidationPrice);
  const safeGaugeAngle = clamp(arcDegrees, 90, 180);
  const startAngle = -safeGaugeAngle / 2;
  const endAngle = safeGaugeAngle / 2;
  const geometry = {
    ...DEFAULT_GEOMETRY,
    startAngle,
    gaugeAngle: safeGaugeAngle,
  };

  const highestScenarioPrice = Math.max(safeCurrentPrice, safePredictedPrice ?? 0);
  const safeMinPrice =
    minPrice && Number.isFinite(minPrice)
      ? minPrice
      : safeLiquidationPrice !== null
        ? safeLiquidationPrice
        : Math.max(safeCurrentPrice * 0.8, 0);
  const inferredMaxPrice =
    safeLiquidationPrice !== null && highestScenarioPrice > safeLiquidationPrice
      ? safeLiquidationPrice + (highestScenarioPrice - safeLiquidationPrice) * 1.35
      : Math.max(highestScenarioPrice * 1.25, safeMinPrice * 1.25, 1);
  const safeMaxPrice =
    maxPrice && Number.isFinite(maxPrice) && maxPrice > safeMinPrice
      ? maxPrice
      : Math.max(inferredMaxPrice, highestScenarioPrice, safeMinPrice + 1e-12);

  const currentAngle = mapPriceToAngle(
    safeCurrentPrice,
    safeMinPrice,
    safeMaxPrice,
    startAngle,
    endAngle,
  );
  const predictedAngle =
    safePredictedPrice === null
      ? null
      : mapPriceToAngle(safePredictedPrice, safeMinPrice, safeMaxPrice, startAngle, endAngle);
  const currentPoint = polarToCartesian(geometry.cx, geometry.cy, geometry.radius, currentAngle);
  const needleBase = { x: geometry.cx, y: geometry.cy - 22 };
  const needleEnd = pointBetween(needleBase, currentPoint, 0.46);
  const predictedPoint =
    predictedAngle === null
      ? null
      : polarToCartesian(geometry.cx, geometry.cy, geometry.radius, predictedAngle);
  const predictedNeedleEnd =
    predictedAngle === null ? null : pointBetween(needleBase, predictedPoint!, 0.42);
  const predictedArcStart = predictedAngle === null ? null : Math.min(currentAngle, predictedAngle);
  const predictedArcEnd = predictedAngle === null ? null : Math.max(currentAngle, predictedAngle);

  const liquidationTickStart = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius - 14,
    startAngle,
  );
  const liquidationTickEnd = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius + 14,
    startAngle,
  );
  const liquidationLabelPoint = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius + 58,
    startAngle - 1,
  );
  const rightLabelPoint = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius + 52,
    endAngle + 1,
  );
  const isLowBuffer = bufferPercent !== null && bufferPercent < 10;
  const riskLevel = describeRiskLevel(bufferPercent);
  const isPredictedLiquidatable = predictedBufferPercent !== null && predictedBufferPercent <= 0;
  const bufferText =
    bufferPercent === null
      ? '--'
      : bufferPercent < 0
        ? `低于清算价 ${Math.abs(bufferPercent).toFixed(2)}%`
        : `${bufferPercent.toFixed(2)}% Buffer`;
  const accessibleBufferText =
    bufferPercent === null
      ? '--'
      : bufferPercent < 0
        ? `低于清算价 ${Math.abs(bufferPercent).toFixed(2)}%`
        : `可下跌 ${bufferPercent.toFixed(2)}% 至清算`;
  const hoverText =
    bufferPercent === null
      ? '当前仓位无法计算清算距离。'
      : bufferPercent < 0
        ? '当前价格已低于清算价。'
        : `价格下跌 ${bufferPercent.toFixed(2)}% 将触发清算`;
  const shouldShowStats = showStats || safePredictedPrice !== null;

  return (
    <div className={`price-gauge ${isLowBuffer ? 'price-gauge-low-buffer' : ''} ${className}`}>
      <div className="price-gauge-top-readout">
        <strong>{safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '--'}</strong>
      </div>

      <svg
        className="price-gauge-svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        role="img"
        aria-label={`清算风险仪表盘。风险等级 ${riskLevel}。清算价 ${safeLiquidationPrice === null ? '不可用' : formatPrice(safeLiquidationPrice)}，当前报价 ${safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '不可用'}，距离 ${accessibleBufferText}。`}
      >
        <title>{hoverText}</title>
        <defs>
          <linearGradient
            id="price-gauge-risk-gradient"
            gradientUnits="userSpaceOnUse"
            x1="116"
            x2="384"
            y1="130"
            y2="130"
          >
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="34%" stopColor="#f97316" />
            <stop offset="62%" stopColor="#facc15" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
          <linearGradient
            id="price-gauge-buffer-gradient"
            gradientUnits="userSpaceOnUse"
            x1="116"
            x2="384"
            y1="130"
            y2="130"
          >
            <stop offset="0%" stopColor="#ef4444" stopOpacity="0.94" />
            <stop offset="58%" stopColor="#f59e0b" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="1" />
          </linearGradient>
          <filter id="price-gauge-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="2.8" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path
          className="price-gauge-track"
          d={describeArc(geometry.cx, geometry.cy, geometry.radius, startAngle, endAngle)}
        />
        <path
          className="price-gauge-risk-arc"
          d={describeArc(geometry.cx, geometry.cy, geometry.radius, startAngle, endAngle)}
        />
        {safeLiquidationPrice !== null && (
          <path
            className="price-gauge-buffer-arc"
            d={describeArc(geometry.cx, geometry.cy, geometry.radius, startAngle, currentAngle)}
            strokeDasharray="7 7"
            filter="url(#price-gauge-glow)"
          />
        )}
        {predictedArcStart !== null &&
          predictedArcEnd !== null &&
          Math.abs(predictedArcEnd - predictedArcStart) > 0.001 && (
            <path
              className={`price-gauge-predicted-delta ${
                isPredictedLiquidatable ? 'price-gauge-predicted-delta-danger' : ''
              }`}
              d={describeArc(
                geometry.cx,
                geometry.cy,
                geometry.radius + 8,
                predictedArcStart,
                predictedArcEnd,
              )}
            />
          )}

        <g className="price-gauge-liquidation-tick">
          <line
            x1={liquidationTickStart.x}
            y1={liquidationTickStart.y}
            x2={liquidationTickEnd.x}
            y2={liquidationTickEnd.y}
          />
          <circle cx={liquidationTickEnd.x} cy={liquidationTickEnd.y} r="6" />
          <text x={liquidationTickEnd.x} y={liquidationTickEnd.y - 14} textAnchor="middle">
            !
          </text>
          <text
            className="price-gauge-liquidation-label"
            x={liquidationLabelPoint.x}
            y={liquidationLabelPoint.y + 50}
            textAnchor="middle"
          >
            Liq{' '}
            {safeLiquidationPrice === null
              ? '--'
              : formatGaugeLabelPrice(safeLiquidationPrice, formatPrice)}
          </text>
        </g>

        <text
          className="price-gauge-side-label price-gauge-side-label-right"
          x={rightLabelPoint.x - 20}
          y={rightLabelPoint.y + 45}
          textAnchor="middle"
        >
          安全区
        </text>

        {predictedNeedleEnd !== null && (
          <g
            className={`price-gauge-predicted-needle ${
              isPredictedLiquidatable ? 'price-gauge-predicted-danger' : ''
            }`}
          >
            <line
              x1={needleBase.x}
              y1={needleBase.y}
              x2={predictedNeedleEnd.x}
              y2={predictedNeedleEnd.y}
            />
          </g>
        )}
        <g className="price-gauge-needle">
          <line x1={needleBase.x} y1={needleBase.y} x2={needleEnd.x} y2={needleEnd.y} />
        </g>
        {predictedPoint !== null && (
          <circle
            className={`price-gauge-predicted-point ${
              isPredictedLiquidatable ? 'price-gauge-predicted-danger' : ''
            }`}
            cx={predictedPoint.x}
            cy={predictedPoint.y}
            r="4"
          />
        )}
        <circle
          className="price-gauge-current-point"
          cx={currentPoint.x}
          cy={currentPoint.y}
          r="6"
        />
        <circle className="price-gauge-hub" cx={needleBase.x} cy={needleBase.y} r="4.5" />
      </svg>

      <div className="price-gauge-bottom-cards">
        <div className="price-gauge-bottom-card">
          <span>清算报价</span>
          <div className="price-gauge-bottom-value-row">
            <strong>
              {safeLiquidationPrice === null ? '--' : formatPrice(safeLiquidationPrice)}
            </strong>
            {safeLiquidationPrice !== null && priceUnit && <small>{priceUnit}</small>}
          </div>
        </div>
        <div className="price-gauge-bottom-card price-gauge-bottom-card-buffer">
          <span>清算缓冲</span>
          <strong>{bufferText}</strong>
        </div>
        <div className="price-gauge-bottom-card">
          <span>当前报价</span>
          <div className="price-gauge-bottom-value-row">
            <strong>{safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '--'}</strong>
            {safeCurrentPrice > 0 && priceUnit && <small>{priceUnit}</small>}
          </div>
        </div>
      </div>

      {shouldShowStats && showStats && (
        <div className="price-gauge-stats">
          <div>
            <span>当前报价</span>
            <strong>{safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '--'}</strong>
          </div>
          <div>
            <span>清算报价</span>
            <strong>
              {safeLiquidationPrice === null ? '--' : formatPrice(safeLiquidationPrice)}
            </strong>
          </div>
        </div>
      )}
    </div>
  );
}
