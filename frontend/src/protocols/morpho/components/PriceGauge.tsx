interface PriceGaugeProps {
  currentPrice: number;
  liquidationPrice: number | null;
  formatPrice: (price: number) => string;
  arcDegrees?: number;
  maxPrice?: number;
  minPrice?: number;
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

const SVG_WIDTH = 420;
const SVG_HEIGHT = 188;
const DEFAULT_GEOMETRY: GaugeGeometry = {
  cx: 210,
  cy: 158,
  radius: 116,
  startAngle: -60,
  gaugeAngle: 120,
};

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
  return '更安全';
}

export function PriceGauge({
  currentPrice,
  liquidationPrice,
  formatPrice,
  arcDegrees = 120,
  maxPrice,
  minPrice,
  valueLabel = '当前报价',
  showStats = true,
  className = '',
}: PriceGaugeProps) {
  const safeCurrentPrice = Number.isFinite(currentPrice) ? currentPrice : 0;
  const safeLiquidationPrice = isFinitePositive(liquidationPrice) ? liquidationPrice : null;
  const bufferPercent = getBufferPercent(safeCurrentPrice, safeLiquidationPrice);
  const safeGaugeAngle = clamp(arcDegrees, 90, 180);
  const startAngle = -safeGaugeAngle / 2;
  const endAngle = safeGaugeAngle / 2;
  const geometry = {
    ...DEFAULT_GEOMETRY,
    startAngle,
    gaugeAngle: safeGaugeAngle,
  };
  const safeMinPrice =
    minPrice && Number.isFinite(minPrice)
      ? minPrice
      : safeLiquidationPrice !== null
        ? safeLiquidationPrice
        : Math.max(safeCurrentPrice * 0.8, 0);
  const inferredMaxPrice =
    safeLiquidationPrice !== null && safeCurrentPrice > safeLiquidationPrice
      ? safeLiquidationPrice + (safeCurrentPrice - safeLiquidationPrice) * 1.35
      : Math.max(safeCurrentPrice * 1.25, safeMinPrice * 1.25, 1);
  const safeMaxPrice =
    maxPrice && Number.isFinite(maxPrice) && maxPrice > safeMinPrice
      ? maxPrice
      : Math.max(inferredMaxPrice, safeCurrentPrice, safeMinPrice + 1e-12);
  const currentAngle = mapPriceToAngle(
    safeCurrentPrice,
    safeMinPrice,
    safeMaxPrice,
    startAngle,
    endAngle,
  );
  const liquidationAngle =
    safeLiquidationPrice === null
      ? geometry.startAngle
      : mapPriceToAngle(safeLiquidationPrice, safeMinPrice, safeMaxPrice, startAngle, endAngle);
  const arcEndAngle = endAngle;
  const bufferEndAngle = Math.max(currentAngle, liquidationAngle + 0.001);
  const needleEnd = polarToCartesian(geometry.cx, geometry.cy, geometry.radius, currentAngle);
  const needleStart = polarToCartesian(geometry.cx, geometry.cy, 16, currentAngle);
  const liquidationTickStart = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius - 14,
    liquidationAngle,
  );
  const liquidationTickEnd = polarToCartesian(
    geometry.cx,
    geometry.cy,
    geometry.radius + 14,
    liquidationAngle,
  );
  const isLowBuffer = bufferPercent !== null && bufferPercent < 10;
  const riskLevel = describeRiskLevel(bufferPercent);
  const absoluteDistance =
    safeLiquidationPrice === null || !isFinitePositive(safeCurrentPrice)
      ? null
      : safeCurrentPrice - safeLiquidationPrice;
  const distanceText =
    bufferPercent === null
      ? '--'
      : bufferPercent < 0
        ? `低于清算价 ${Math.abs(bufferPercent).toFixed(2)}%`
        : `${bufferPercent.toFixed(2)}% 缓冲`;
  const absoluteText = absoluteDistance === null ? '--' : formatPrice(Math.abs(absoluteDistance));
  const hoverText =
    bufferPercent === null
      ? '当前仓位无法计算清算距离。'
      : bufferPercent < 0
        ? '当前价格已低于清算价。'
        : `价格下跌 ${bufferPercent.toFixed(2)}% 将触发清算`;

  return (
    <div className={`price-gauge ${isLowBuffer ? 'price-gauge-low-buffer' : ''} ${className}`}>
      <svg
        className="price-gauge-svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        role="img"
        aria-label={`清算风险仪表盘。风险等级 ${riskLevel}。清算价 ${safeLiquidationPrice === null ? '不可用' : formatPrice(safeLiquidationPrice)}，当前报价 ${safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '不可用'}，距离 ${distanceText}。`}
      >
        <title>{hoverText}</title>
        <defs>
          <linearGradient id="price-gauge-risk-gradient" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="45%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
          <linearGradient id="price-gauge-buffer-gradient" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" stopOpacity="0.95" />
            <stop offset="55%" stopColor="#f59e0b" stopOpacity="0.92" />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity="1" />
          </linearGradient>
          <filter id="price-gauge-glow" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="3.5" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <path
          className="price-gauge-track"
          d={describeArc(
            geometry.cx,
            geometry.cy,
            geometry.radius,
            geometry.startAngle,
            arcEndAngle,
          )}
        />
        <path
          className="price-gauge-risk-arc"
          d={describeArc(
            geometry.cx,
            geometry.cy,
            geometry.radius,
            geometry.startAngle,
            arcEndAngle,
          )}
        />
        {safeLiquidationPrice !== null && (
          <path
            className="price-gauge-buffer-arc"
            d={describeArc(
              geometry.cx,
              geometry.cy,
              geometry.radius,
              liquidationAngle,
              bufferEndAngle,
            )}
            strokeDasharray="8 6"
            filter="url(#price-gauge-glow)"
          />
        )}

        {safeLiquidationPrice !== null && (
          <g className="price-gauge-liquidation-tick">
            <line
              x1={liquidationTickStart.x}
              y1={liquidationTickStart.y}
              x2={liquidationTickEnd.x}
              y2={liquidationTickEnd.y}
            />
            <circle cx={liquidationTickEnd.x} cy={liquidationTickEnd.y} r="7" />
            <text x={liquidationTickEnd.x} y={liquidationTickEnd.y - 14} textAnchor="middle">
              !
            </text>
            <text
              className="price-gauge-liquidation-label"
              x={liquidationTickEnd.x}
              y={liquidationTickEnd.y + 26}
              textAnchor="middle"
            >
              清算价
            </text>
          </g>
        )}

        <g className="price-gauge-needle">
          <line x1={needleStart.x} y1={needleStart.y} x2={needleEnd.x} y2={needleEnd.y} />
          <circle cx={needleEnd.x} cy={needleEnd.y} r="6" />
        </g>
        <circle className="price-gauge-hub" cx={geometry.cx} cy={geometry.cy} r="10" />

        <text className="price-gauge-side-label price-gauge-side-label-left" x="94" y="178">
          清算
        </text>
        <text className="price-gauge-side-label price-gauge-side-label-mid" x="210" y="58">
          价格递增 →
        </text>
        <text className="price-gauge-side-label price-gauge-side-label-right" x="326" y="178">
          更安全
        </text>
      </svg>

      <div className="price-gauge-readout">
        <span>{valueLabel}</span>
        <strong>{safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '--'}</strong>
        <small>{distanceText}</small>
      </div>

      {showStats && (
        <div className="price-gauge-stats">
          <div>
            <span>清算价</span>
            <strong>
              {safeLiquidationPrice === null ? '--' : formatPrice(safeLiquidationPrice)}
            </strong>
          </div>
          <div>
            <span>当前报价</span>
            <strong>{safeCurrentPrice > 0 ? formatPrice(safeCurrentPrice) : '--'}</strong>
          </div>
          <div>
            <span>距离清算</span>
            <strong>{bufferPercent === null ? '--' : `${bufferPercent.toFixed(2)}%`}</strong>
            <small>{absoluteDistance !== null ? absoluteText : '--'}</small>
          </div>
        </div>
      )}
    </div>
  );
}
