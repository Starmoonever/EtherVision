interface MorphoLtvRiskScaleProps {
  currentLtvPercent: number;
  lltvPercent: number;
  liquidationThresholdPercent: number;
  isHealthy?: boolean;
  formatPercent?: (value: number) => string;
}

type RiskTone = 'safe' | 'warning' | 'danger';

const SVG_WIDTH = 520;
const SVG_HEIGHT = 108;
const TRACK_X = 28;
const TRACK_Y = 48;
const TRACK_WIDTH = 464;
const MAX_LTV_SCALE = 100;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function valueToX(value: number, maxValue: number): number {
  return TRACK_X + (clamp(value, 0, maxValue) / maxValue) * TRACK_WIDTH;
}

function getRiskTone(isHealthy: boolean | undefined): RiskTone {
  return isHealthy === false ? 'danger' : 'safe';
}

function riskCopy(tone: RiskTone): string {
  if (tone === 'danger') return '协议标记为不健康';
  return '协议标记为健康';
}

export function MorphoLtvRiskScale({
  currentLtvPercent,
  lltvPercent,
  liquidationThresholdPercent,
  isHealthy,
  formatPercent = (value) => `${value.toFixed(2)}%`,
}: MorphoLtvRiskScaleProps) {
  const safeCurrentLtv = Number.isFinite(currentLtvPercent) ? currentLtvPercent : 0;
  const safeLltv = Number.isFinite(lltvPercent) ? lltvPercent : 0;
  const safeThreshold = Number.isFinite(liquidationThresholdPercent)
    ? liquidationThresholdPercent
    : safeLltv;
  const currentX = valueToX(safeCurrentLtv, MAX_LTV_SCALE);
  const lltvX = valueToX(safeLltv, MAX_LTV_SCALE);
  const thresholdX = valueToX(safeThreshold, MAX_LTV_SCALE);
  const tone = getRiskTone(isHealthy);
  const thresholdEqualsLltv = Math.abs(safeThreshold - safeLltv) < 0.01;
  const headroomPercent = Math.max(0, safeThreshold - safeCurrentLtv);

  return (
    <div className={`morpho-ltv-risk morpho-ltv-risk-${tone}`}>
      <div className="morpho-ltv-risk-header">
        <div>
          <span className="morpho-ltv-risk-kicker-row">
            <span className="morpho-ltv-risk-kicker">仓位 LTV 风险</span>
            <span
              className="morpho-ltv-risk-help"
              tabIndex={0}
              role="note"
              aria-label="快速解读：Current LTV 表示当前借款占抵押折算价值的比例；LLTV 是 Morpho Blue 市场的清算阈值；安全/危险状态由接口返回的 is_healthy 判断。"
              data-tooltip="Current LTV 是当前借款占抵押折算价值的比例；LLTV 是 Morpho Blue 市场的清算阈值；此卡片的安全状态由接口返回的 is_healthy 判断。"
            >
              ?
            </span>
          </span>
          <strong>{riskCopy(tone)}</strong>
          <small>安全状态由 is_healthy 判断；LTV 刻度用于展示仓位相对阈值的位置。</small>
        </div>
        <span className="morpho-ltv-risk-badge">
          {tone === 'danger' ? '危险' : tone === 'warning' ? '观察' : '安全'}
        </span>
      </div>

      <svg
        className="morpho-ltv-risk-svg"
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        role="img"
        aria-label={`当前 LTV ${formatPercent(safeCurrentLtv)}, LLTV ${formatPercent(
          safeLltv,
        )}, 清算阈值 ${formatPercent(safeThreshold)}.`}
      >
        <defs>
          <linearGradient
            id="morpho-ltv-risk-gradient"
            gradientUnits="userSpaceOnUse"
            x1={TRACK_X}
            x2={TRACK_X + TRACK_WIDTH}
            y1={TRACK_Y}
            y2={TRACK_Y}
          >
            <stop offset="0%" stopColor="#22c55e" />
            <stop offset="62%" stopColor="#f59e0b" />
            <stop offset="100%" stopColor="#ef4444" />
          </linearGradient>
          <filter id="morpho-ltv-risk-glow" x="-20%" y="-100%" width="140%" height="300%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <line
          className="morpho-ltv-risk-track"
          stroke="url(#morpho-ltv-risk-gradient)"
          x1={TRACK_X}
          y1={TRACK_Y}
          x2={TRACK_X + TRACK_WIDTH}
          y2={TRACK_Y}
        />
        <line
          className="morpho-ltv-risk-fill"
          stroke="rgba(248, 250, 252, 0.34)"
          x1={TRACK_X}
          y1={TRACK_Y}
          x2={currentX}
          y2={TRACK_Y}
          filter="url(#morpho-ltv-risk-glow)"
        />

        <g className="morpho-ltv-risk-marker morpho-ltv-risk-marker-lltv">
          <line x1={lltvX} y1="24" x2={lltvX} y2="60" />
          <text x={lltvX} y={thresholdEqualsLltv ? 14 : 16} textAnchor="middle">
            {thresholdEqualsLltv ? 'LLTV / 清算阈值' : 'LLTV'}
          </text>
        </g>

        {!thresholdEqualsLltv && (
          <g className="morpho-ltv-risk-marker morpho-ltv-risk-marker-threshold">
            <line x1={thresholdX} y1="20" x2={thresholdX} y2="64" />
            <text x={thresholdX} y="84" textAnchor="middle">
              清算阈值
            </text>
          </g>
        )}

        <g className="morpho-ltv-risk-current">
          <line x1={currentX} y1="16" x2={currentX} y2="70" />
          <circle cx={currentX} cy={TRACK_Y} r="8" />
          <text x={currentX} y="90" textAnchor="middle">
            当前 LTV
          </text>
        </g>
      </svg>

      <div className="morpho-ltv-risk-values">
        <div>
          <span>当前 LTV</span>
          <strong>{formatPercent(safeCurrentLtv)}</strong>
        </div>
        <div>
          <span>LLTV（清算阈值）</span>
          <strong>{formatPercent(safeLltv)}</strong>
        </div>
        <div>
          <span>距离阈值</span>
          <strong>{formatPercent(headroomPercent)}</strong>
        </div>
      </div>
    </div>
  );
}
