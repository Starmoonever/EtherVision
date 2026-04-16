import { useEffect, useMemo, useState } from 'react';
import {
  Brush,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchMorphoPositionReplayWithMeta,
  type MorphoPositionReplayPoint,
} from '../../../api/morpho';
import type { AggregatedRequestMeta } from '../../../api/requestMeta';
import {
  ChartDataStatus,
  ChartInfoButton,
  type ExplainItem,
} from '../../../components/ChartAssist';
import {
  MorphoDynamicLiquidationChart,
  type MorphoPricePoint,
} from './MorphoDynamicLiquidationChart';

interface MorphoPositionHistoryChartProps {
  address: string;
  marketId: string;
  protocol?: 'blue';
  loanTokenSymbol?: string | null;
  collateralTokenSymbol?: string | null;
  debtAmount?: number | null;
  collateralAmount?: number | null;
  lltv?: number | null;
}

interface MorphoHistoryPoint {
  index: number;
  timestamp: string;
  timeLabel: string;
  txHash: string;
  blockNumber: number;
  operationType: string;
  operationLabel: string;
  operationTone: OperationTone;
  operationRank: number;
  brief: string;
  hasPosition: boolean;
  isHealthy: boolean;
  collateralValue: number;
  borrowAssets: number;
  depositValue: number;
  collateralUnitAmount: number;
  collateralPriceInLoanAsset: number | null;
  loanPriceUsd: number | null;
  collateralPriceUsd: number | null;
  operationAmount: number;
  collateralOperationAmount: number | null;
  supplyOperationAmount: number | null;
  borrowOperationAmount: number | null;
  repayOperationAmount: number | null;
  withdrawCollateralOperationAmount: number | null;
  withdrawSupplyOperationAmount: number | null;
  liquidationOperationAmount: number | null;
  neutralOperationAmount: number | null;
  collateralOperationAmountDisplay: number | null;
  supplyOperationAmountDisplay: number | null;
  borrowOperationAmountDisplay: number | null;
  repayOperationAmountDisplay: number | null;
  withdrawCollateralOperationAmountDisplay: number | null;
  withdrawSupplyOperationAmountDisplay: number | null;
  liquidationOperationAmountDisplay: number | null;
  neutralOperationAmountDisplay: number | null;
  ltvPercent: number | null;
  healthFactor: number | null;
}

interface TooltipPayloadEntry {
  color?: string;
  name?: string;
  value?: number | string;
  payload: MorphoHistoryPoint;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string;
  loanTokenSymbol: string;
}

type OperationTone =
  | 'collateral'
  | 'supply'
  | 'borrow'
  | 'repay'
  | 'withdrawCollateral'
  | 'withdrawSupply'
  | 'liquidation'
  | 'neutral';
type OperationToneSet = Set<OperationTone>;

interface OperationMeta {
  label: string;
  rank: number;
  tone: OperationTone;
}

const MORPHO_BLUE_START_DATE = '2023-12-28 00:00:00';
const OPERATION_ROWS: Array<{ rank: number; label: string; tone: OperationTone }> = [
  { rank: 0, label: '新增抵押', tone: 'collateral' },
  { rank: 1, label: '供给', tone: 'supply' },
  { rank: 2, label: '借入', tone: 'borrow' },
  { rank: 3, label: '还款', tone: 'repay' },
  { rank: 4, label: '移除抵押', tone: 'withdrawCollateral' },
  { rank: 5, label: '提取', tone: 'withdrawSupply' },
  { rank: 6, label: '被清算', tone: 'liquidation' },
  { rank: 7, label: '其他', tone: 'neutral' },
];

const OPERATION_AMOUNT_DISPLAY_KEY_BY_TONE: Record<OperationTone, keyof MorphoHistoryPoint> = {
  collateral: 'collateralOperationAmountDisplay',
  supply: 'supplyOperationAmountDisplay',
  borrow: 'borrowOperationAmountDisplay',
  repay: 'repayOperationAmountDisplay',
  withdrawCollateral: 'withdrawCollateralOperationAmountDisplay',
  withdrawSupply: 'withdrawSupplyOperationAmountDisplay',
  liquidation: 'liquidationOperationAmountDisplay',
  neutral: 'neutralOperationAmountDisplay',
} as Record<OperationTone, keyof MorphoHistoryPoint>;

const explainItems: ExplainItem[] = [
  {
    term: '三类仓位价值',
    formula: '总抵押值 / 总债务值 / 总存款值',
    meaning: '用借款资产口径同时展示抵押折算价值、债务规模，以及 loan asset 存款规模。',
    riskHint: '债务线上升而抵押线没有同步上升时，安全边际通常会被压缩。',
  },
  {
    term: '操作金额',
    formula: '按相邻快照差值估算',
    meaning: '根据每次交易前后抵押、债务或存款的变化，估算这次操作影响的金额。',
    riskHint: '大额借款、撤回或清算节点应重点和健康因子变化一起观察。',
  },
  {
    term: '健康因子',
    formula: 'health_factor',
    meaning: '交易后仓位距离清算边界的安全缓冲，越高越安全。',
    riskHint: '健康因子持续下行通常表示仓位在加杠杆；接近 1 时需要重点关注。',
  },
];

const operationExplainItems: ExplainItem[] = [
  {
    term: '操作金额线',
    formula: '按相邻两次快照的仓位差值估算',
    meaning: '每种操作独立成线，同类操作点会连起来，用于观察该操作类型的金额变化趋势。',
    riskHint: '大额借款、撤回抵押或清算点通常比普通存款更值得复盘。',
  },
  {
    term: '操作总量',
    formula: 'sum(operationAmount) by operation_type',
    meaning: '对当前查询时间范围内同一类操作金额求和，显示在图表上方的小条形概览中。',
    riskHint: '总量最大的操作类型通常代表账户主要行为模式，例如持续加杠杆或持续补抵押。',
  },
  {
    term: '对数轴',
    formula: 'log(operationAmount)',
    meaning: '用对数轴减弱极大离群值的压制，让小额操作也能被看见。',
    riskHint: '对数轴强调相对变化，精确金额请以 tooltip 和总量栏为准。',
  },
];

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toNullableNum(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'string' && value.toLowerCase() === 'inf') return null;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatDateTimeInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(
    date.getUTCHours(),
  )}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

function getDefaultRange(): { start: string; end: string } {
  const end = new Date();
  return {
    start: MORPHO_BLUE_START_DATE,
    end: formatDateTimeInput(end),
  };
}

function formatTimeLabel(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Date(timestamp).toLocaleString(undefined, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatCompact(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '--';
  return value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatShortHash(value: string): string {
  if (!value) return '--';
  return `${value.slice(0, 8)}...${value.slice(-6)}`;
}

function getOperationMeta(value: string): OperationMeta {
  const normalized = value.toLowerCase();

  if (normalized.includes('liquidat')) {
    return { label: '被清算', rank: 6, tone: 'liquidation' };
  }
  if (normalized.includes('repay')) {
    return { label: '还款', rank: 3, tone: 'repay' };
  }
  if (normalized.includes('borrow')) {
    return { label: '借入', rank: 2, tone: 'borrow' };
  }
  if (
    (normalized.includes('withdraw') || normalized.includes('remove')) &&
    normalized.includes('collateral')
  ) {
    return { label: '移除抵押', rank: 4, tone: 'withdrawCollateral' };
  }
  if (normalized.includes('withdraw') || normalized.includes('remove')) {
    return { label: '提取', rank: 5, tone: 'withdrawSupply' };
  }
  if (normalized.includes('collateral')) {
    return { label: '新增抵押', rank: 0, tone: 'collateral' };
  }
  if (normalized.includes('supply') || normalized.includes('deposit')) {
    return { label: '供给', rank: 1, tone: 'supply' };
  }

  return { label: value === 'unknown' ? '其他操作' : value, rank: 7, tone: 'neutral' };
}

function getDepositValue(point: MorphoPositionReplayPoint): number {
  return point.assets.reduce((total, asset) => {
    if (asset.role !== 'loan') return total;
    const amount = toNum(asset.amount);
    return amount > 0 ? total + amount : total;
  }, 0);
}

function getCollateralUnitAmount(point: MorphoPositionReplayPoint): number {
  return point.assets.reduce((total, asset) => {
    if (asset.role !== 'collateral') return total;
    return total + Math.abs(toNum(asset.amount));
  }, 0);
}

function getAssetPriceUsd(
  point: MorphoPositionReplayPoint,
  role: 'loan' | 'collateral',
): number | null {
  const asset = point.assets.find((item) => item.role === role);
  const price = toNullableNum(asset?.price_usd);
  return price !== null && price > 0 ? price : null;
}

function normalizeReplayPoint(point: MorphoPositionReplayPoint, index: number): MorphoHistoryPoint {
  const collateralValue = toNum(point.collateral_value_in_loan_asset);
  const borrowAssets = Math.abs(toNum(point.borrow_assets));
  const depositValue = getDepositValue(point);
  const collateralUnitAmount = getCollateralUnitAmount(point);
  const loanPriceUsd = getAssetPriceUsd(point, 'loan');
  const collateralPriceUsd = getAssetPriceUsd(point, 'collateral');
  const collateralPriceInLoanAsset =
    collateralValue > 0 && collateralUnitAmount > 0
      ? collateralValue / collateralUnitAmount
      : collateralPriceUsd !== null && loanPriceUsd !== null
        ? collateralPriceUsd / loanPriceUsd
        : null;
  const healthFactor = toNullableNum(point.health_factor);
  const operationType = point.operation_type || 'unknown';
  const operation = getOperationMeta(operationType);

  return {
    index,
    timestamp: point.timestamp,
    timeLabel: formatTimeLabel(point.timestamp),
    txHash: point.tx_hash,
    blockNumber: point.block_number,
    operationType,
    operationLabel: operation.label,
    operationTone: operation.tone,
    operationRank: operation.rank,
    brief: point.brief,
    hasPosition: point.has_position,
    isHealthy: point.is_healthy,
    collateralValue,
    borrowAssets,
    depositValue,
    collateralUnitAmount,
    collateralPriceInLoanAsset,
    loanPriceUsd,
    collateralPriceUsd,
    operationAmount: 0,
    collateralOperationAmount: null,
    supplyOperationAmount: null,
    borrowOperationAmount: null,
    repayOperationAmount: null,
    withdrawCollateralOperationAmount: null,
    withdrawSupplyOperationAmount: null,
    liquidationOperationAmount: null,
    neutralOperationAmount: null,
    collateralOperationAmountDisplay: null,
    supplyOperationAmountDisplay: null,
    borrowOperationAmountDisplay: null,
    repayOperationAmountDisplay: null,
    withdrawCollateralOperationAmountDisplay: null,
    withdrawSupplyOperationAmountDisplay: null,
    liquidationOperationAmountDisplay: null,
    neutralOperationAmountDisplay: null,
    ltvPercent: collateralValue > 0 ? (borrowAssets / collateralValue) * 100 : null,
    healthFactor,
  };
}

function getOperationAmount(
  point: MorphoHistoryPoint,
  previous: MorphoHistoryPoint | undefined,
): number {
  const collateralDelta = previous
    ? point.collateralValue - previous.collateralValue
    : point.collateralValue;
  const debtDelta = previous ? point.borrowAssets - previous.borrowAssets : point.borrowAssets;
  const depositDelta = previous ? point.depositValue - previous.depositValue : point.depositValue;

  if (point.operationTone === 'borrow' || point.operationTone === 'repay') {
    return Math.abs(debtDelta);
  }
  if (point.operationTone === 'withdrawCollateral') {
    return Math.abs(collateralDelta);
  }
  if (point.operationTone === 'withdrawSupply') {
    return Math.abs(depositDelta);
  }
  if (point.operationTone === 'collateral') {
    return Math.abs(collateralDelta);
  }
  if (point.operationTone === 'supply') {
    return Math.abs(depositDelta);
  }
  if (point.operationTone === 'liquidation') {
    return Math.abs(collateralDelta) + Math.abs(debtDelta) + Math.abs(depositDelta);
  }

  return Math.max(Math.abs(collateralDelta), Math.abs(debtDelta), Math.abs(depositDelta));
}

function withOperationAmounts(points: MorphoHistoryPoint[]): MorphoHistoryPoint[] {
  return points.map((point, index) => {
    const operationAmount = getOperationAmount(point, points[index - 1]);
    const operationAmountDisplay = operationAmount > 0 ? Math.max(operationAmount, 1) : null;
    return {
      ...point,
      index,
      operationAmount,
      collateralOperationAmount: point.operationTone === 'collateral' ? operationAmount : null,
      supplyOperationAmount: point.operationTone === 'supply' ? operationAmount : null,
      borrowOperationAmount: point.operationTone === 'borrow' ? operationAmount : null,
      repayOperationAmount: point.operationTone === 'repay' ? operationAmount : null,
      withdrawCollateralOperationAmount:
        point.operationTone === 'withdrawCollateral' ? operationAmount : null,
      withdrawSupplyOperationAmount:
        point.operationTone === 'withdrawSupply' ? operationAmount : null,
      liquidationOperationAmount: point.operationTone === 'liquidation' ? operationAmount : null,
      neutralOperationAmount: point.operationTone === 'neutral' ? operationAmount : null,
      collateralOperationAmountDisplay:
        point.operationTone === 'collateral' ? operationAmountDisplay : null,
      supplyOperationAmountDisplay:
        point.operationTone === 'supply' ? operationAmountDisplay : null,
      borrowOperationAmountDisplay:
        point.operationTone === 'borrow' ? operationAmountDisplay : null,
      repayOperationAmountDisplay: point.operationTone === 'repay' ? operationAmountDisplay : null,
      withdrawCollateralOperationAmountDisplay:
        point.operationTone === 'withdrawCollateral' ? operationAmountDisplay : null,
      withdrawSupplyOperationAmountDisplay:
        point.operationTone === 'withdrawSupply' ? operationAmountDisplay : null,
      liquidationOperationAmountDisplay:
        point.operationTone === 'liquidation' ? operationAmountDisplay : null,
      neutralOperationAmountDisplay:
        point.operationTone === 'neutral' ? operationAmountDisplay : null,
    };
  });
}

function getOperationToneColor(tone: OperationTone): string {
  if (tone === 'collateral') return '#3fbb7d';
  if (tone === 'supply') return '#14b8a6';
  if (tone === 'borrow') return '#e45c5c';
  if (tone === 'repay') return '#4a90e2';
  if (tone === 'withdrawCollateral') return '#f5a623';
  if (tone === 'withdrawSupply') return '#8b5cf6';
  if (tone === 'liquidation') return '#ffffff';
  return '#94a3b8';
}

type PositionLineKind = 'collateral' | 'debt' | 'deposit';

function operationAffectsLine(point: MorphoHistoryPoint, line: PositionLineKind): boolean {
  if (point.operationTone === 'liquidation') return line === 'collateral' || line === 'debt';
  if (point.operationTone === 'collateral') return line === 'collateral';
  if (point.operationTone === 'borrow' || point.operationTone === 'repay') return line === 'debt';
  if (point.operationTone === 'supply' || point.operationTone === 'withdrawSupply') {
    return line === 'deposit';
  }
  if (point.operationTone === 'withdrawCollateral') return line === 'collateral';
  return false;
}

function ChartOperationDot(
  props: unknown,
  selectedTones: OperationToneSet,
  line: PositionLineKind,
) {
  const { cx, cy, payload } = props as {
    cx?: number;
    cy?: number;
    payload?: MorphoHistoryPoint;
  };
  if (cx === undefined || cy === undefined || !payload) return <g />;
  if (!selectedTones.has(payload.operationTone)) return <g />;
  if (!operationAffectsLine(payload, line)) return <g />;

  const color = getOperationToneColor(payload.operationTone);
  const riskStroke = payload.isHealthy ? color : '#fecaca';

  return (
    <g className="morpho-history-linked-dot">
      <circle cx={cx} cy={cy} r={7.5} fill={color} opacity={0.2} />
      <circle
        cx={cx}
        cy={cy}
        r={4.2}
        fill={color}
        stroke={riskStroke}
        strokeWidth={payload.isHealthy ? 1.1 : 1.8}
      />
    </g>
  );
}

function OperationAmountDot(props: unknown, color: string, selected: boolean) {
  const { cx, cy, payload, value } = props as {
    cx?: number;
    cy?: number;
    value?: number | null;
    payload?: MorphoHistoryPoint;
  };
  if (cx === undefined || cy === undefined || !payload || value === null || value === undefined) {
    return <g />;
  }
  const radius = Math.min(12, Math.max(4.2, Math.log(Math.max(payload.operationAmount, 1)) * 1.25));
  const outerRadius = radius + 3.6;

  return (
    <g className={selected ? 'morpho-operation-amount-dot' : 'morpho-operation-amount-dot muted'}>
      <title>{`${payload.operationLabel}: ${formatCompact(payload.operationAmount, 6)}`}</title>
      <line
        className="morpho-operation-stem-line"
        x1={cx}
        x2={cx}
        y1={cy}
        y2="92%"
        stroke={color}
        strokeOpacity={selected ? 0.2 : 0.08}
        strokeWidth={selected ? 1.1 : 0.8}
      />
      <circle cx={cx} cy={cy} r={outerRadius} fill={color} opacity={selected ? 0.16 : 0.06} />
      <circle cx={cx} cy={cy} r={radius} fill={color} stroke="#0f172a" strokeWidth={1.2} />
    </g>
  );
}

function OperationTimeline({
  points,
  selectedTones,
  onToggleTone,
  loanTokenSymbol,
}: {
  points: MorphoHistoryPoint[];
  selectedTones: OperationToneSet;
  onToggleTone: (tone: OperationTone) => void;
  loanTokenSymbol: string;
}) {
  const brushStartIndex = Math.max(0, Math.floor(points.length * 0.7));
  const brushEndIndex = Math.max(0, points.length - 1);
  const operationTotals = OPERATION_ROWS.map((row) => ({
    ...row,
    total: points.reduce(
      (sum, point) => sum + (point.operationTone === row.tone ? point.operationAmount : 0),
      0,
    ),
  }));

  return (
    <div className="morpho-operation-timeline">
      <div className="morpho-operation-timeline-header">
        <div>
          <div className="morpho-operation-title-row">
            <strong>操作金额图</strong>
            <ChartInfoButton title="操作金额图说明" items={operationExplainItems} />
          </div>
          <span>横轴为日期，纵轴为操作金额；竖线和圆点表示对应操作发生的金额</span>
        </div>
      </div>

      <div className="morpho-operation-total-grid morpho-operation-total-grid-compact">
        {operationTotals.map((item) => {
          const selected = selectedTones.size === 0 || selectedTones.has(item.tone);
          return (
            <button
              key={item.tone}
              type="button"
              className={selected ? 'active' : ''}
              onClick={() => onToggleTone(item.tone)}
              aria-pressed={selected}
            >
              <span className="morpho-operation-total-head">
                <i style={{ background: getOperationToneColor(item.tone) }} />
                {item.label}
              </span>
              <strong>
                {formatCompact(item.total, 2)} {loanTokenSymbol}
              </strong>
            </button>
          );
        })}
      </div>

      <div className="morpho-operation-chart-shell">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 10, right: 18, left: 4, bottom: 2 }}>
            <CartesianGrid stroke="#1f2a3d" strokeDasharray="4 8" vertical={false} />
            <XAxis
              dataKey="timeLabel"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={{ stroke: '#263449' }}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              type="number"
              scale="log"
              domain={[1, 'dataMax']}
              allowDataOverflow
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => formatCompact(Number(value), 2)}
            />
            <Tooltip content={<CustomTooltip loanTokenSymbol={loanTokenSymbol} />} />
            {OPERATION_ROWS.map((row) => {
              const selected = selectedTones.size === 0 || selectedTones.has(row.tone);
              if (!selected) return null;
              return (
                <Line
                  key={row.tone}
                  type="linear"
                  dataKey={OPERATION_AMOUNT_DISPLAY_KEY_BY_TONE[row.tone]}
                  name={row.label}
                  stroke={getOperationToneColor(row.tone)}
                  strokeWidth={selected ? 1.8 : 1.1}
                  strokeOpacity={selected ? 0.42 : 0.1}
                  connectNulls
                  dot={(props) =>
                    OperationAmountDot(props, getOperationToneColor(row.tone), selected)
                  }
                  activeDot={{
                    r: 5,
                    strokeWidth: 2,
                    fill: getOperationToneColor(row.tone),
                  }}
                />
              );
            })}
            <Brush
              dataKey="timeLabel"
              height={22}
              startIndex={brushStartIndex}
              endIndex={brushEndIndex}
              travellerWidth={8}
              stroke="#4a90e2"
              fill="rgba(15, 23, 42, 0.88)"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const CustomTooltip = ({ active, payload, label, loanTokenSymbol }: CustomTooltipProps) => {
  if (!active || !payload?.length) return null;

  const point = payload[0].payload;

  return (
    <div className="morpho-history-tooltip">
      <div className="morpho-history-tooltip-time">{label}</div>
      <div className="morpho-history-tooltip-op">{point.operationLabel}</div>
      <div className="morpho-history-tooltip-brief">
        {point.brief || point.operationType || '历史仓位点'}
      </div>
      <div className="morpho-history-tooltip-grid">
        <span>抵押折算</span>
        <strong>
          {formatCompact(point.collateralValue, 6)} {loanTokenSymbol}
        </strong>
        <span>负债</span>
        <strong>
          {formatCompact(point.borrowAssets, 6)} {loanTokenSymbol}
        </strong>
        <span>总存款值</span>
        <strong>
          {formatCompact(point.depositValue, 6)} {loanTokenSymbol}
        </strong>
        <span>操作金额</span>
        <strong>
          {formatCompact(point.operationAmount, 6)} {loanTokenSymbol}
        </strong>
        <span>LTV</span>
        <strong>
          {point.ltvPercent === null ? '--' : `${formatCompact(point.ltvPercent, 2)}%`}
        </strong>
        <span>健康因子</span>
        <strong>
          {point.healthFactor === null ? '∞ / --' : formatCompact(point.healthFactor, 2)}
        </strong>
      </div>
      <div
        className={point.isHealthy ? 'morpho-history-status-safe' : 'morpho-history-status-danger'}
      >
        {point.isHealthy ? '协议标记：健康' : '协议标记：不健康'}
      </div>
      <div className="morpho-history-tooltip-hash">Tx {formatShortHash(point.txHash)}</div>
    </div>
  );
};

export function MorphoPositionHistoryChart({
  address,
  marketId,
  protocol = 'blue',
  loanTokenSymbol,
  collateralTokenSymbol,
  debtAmount,
  collateralAmount,
  lltv,
}: MorphoPositionHistoryChartProps) {
  const [range, setRange] = useState(() => getDefaultRange());
  const [appliedRange, setAppliedRange] = useState(range);
  const [points, setPoints] = useState<MorphoHistoryPoint[]>([]);
  const [selectedOperationTones, setSelectedOperationTones] = useState<OperationToneSet>(
    () => new Set(),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const symbol = loanTokenSymbol || 'Loan Asset';

  useEffect(() => {
    if (!address || !marketId) return;

    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const result = await fetchMorphoPositionReplayWithMeta(
          address,
          marketId,
          appliedRange.start,
          appliedRange.end,
          protocol,
          { detail: true },
        );

        if (cancelled) return;

        const nextPoints = withOperationAmounts(
          result.data.points
            .map(normalizeReplayPoint)
            .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)),
        );

        setPoints(nextPoints);
        setMeta({
          lastUpdatedAt: result.meta.fetchedAt,
          cacheStatus: result.meta.fromCache
            ? 'hit'
            : result.data.data_source === 'mixed'
              ? 'mixed'
              : 'miss',
        });
      } catch (err) {
        console.error(err);
        if (!cancelled) {
          setPoints([]);
          setError('无法加载 Morpho 历史仓位数据');
          setMeta({ lastUpdatedAt: null, cacheStatus: 'none' });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [address, appliedRange.end, appliedRange.start, marketId, protocol]);

  const latestPoint = points.length > 0 ? points[points.length - 1] : undefined;
  const unhealthyCount = useMemo(() => points.filter((point) => !point.isHealthy).length, [points]);
  const minHealthFactor = useMemo(() => {
    const values = points
      .map((point) => point.healthFactor)
      .filter((value): value is number => value !== null);
    return values.length > 0 ? Math.min(...values) : null;
  }, [points]);
  const collateralSeries = useMemo<MorphoPricePoint[]>(
    () =>
      points
        .filter((point) => point.collateralPriceInLoanAsset !== null)
        .map((point) => ({
          timestamp: point.timeLabel,
          price:
            point.loanPriceUsd !== null
              ? (point.collateralPriceInLoanAsset ?? 0) * point.loanPriceUsd
              : (point.collateralPriceInLoanAsset ?? 0),
          amount: point.collateralUnitAmount,
        })),
    [points],
  );
  const debtSeries = useMemo<MorphoPricePoint[]>(
    () =>
      points
        .filter((point) => point.collateralPriceInLoanAsset !== null)
        .map((point) => ({
          timestamp: point.timeLabel,
          price: point.loanPriceUsd ?? 1,
          amount: point.borrowAssets,
        })),
    [points],
  );
  const canShowDynamicLiquidationChart =
    collateralSeries.length > 0 &&
    debtSeries.length > 0 &&
    (debtAmount ?? 0) > 0 &&
    (collateralAmount ?? 0) > 0 &&
    (lltv ?? 0) > 0;
  const handleSubmit = () => {
    setAppliedRange(range);
  };

  const toggleOperationTone = (tone: OperationTone) => {
    setSelectedOperationTones((prev) => {
      const next = new Set(prev);
      if (next.has(tone)) {
        next.delete(tone);
      } else {
        next.add(tone);
      }
      return next;
    });
  };

  return (
    <div className="morpho-history-stack">
      <section className="card morpho-history-card">
        <div className="morpho-history-header">
          <div className="morpho-history-title-wrap">
            <div className="morpho-history-title-row">
              <span className="card-title">个人历史信息图</span>
              <ChartInfoButton title="Morpho 历史图说明" items={explainItems} />
            </div>
            <p>按交易快照回放三类仓位价值变化；横轴为日期，纵轴为借款资产口径的价值。</p>
            <div
              className={
                unhealthyCount > 0
                  ? 'morpho-history-health-note morpho-history-health-note-danger'
                  : 'morpho-history-health-note'
              }
            >
              {unhealthyCount > 0
                ? `本区间出现 ${unhealthyCount} 个不健康点位`
                : '本区间未出现不健康点位'}
            </div>
          </div>
          <div className="morpho-history-controls">
            <ChartDataStatus meta={meta} />
            <div className="morpho-history-range">
              <input
                value={range.start}
                onChange={(event) => setRange((prev) => ({ ...prev, start: event.target.value }))}
                aria-label="Morpho 历史起始时间"
              />
              <span>至</span>
              <input
                value={range.end}
                onChange={(event) => setRange((prev) => ({ ...prev, end: event.target.value }))}
                aria-label="Morpho 历史结束时间"
              />
              <button type="button" onClick={handleSubmit} disabled={loading}>
                查询
              </button>
            </div>
          </div>
        </div>

        <div className="morpho-history-summary">
          <div>
            <span>历史点位</span>
            <strong>{points.length}</strong>
          </div>
          <div>
            <span>最新总抵押值</span>
            <strong>
              {formatCompact(latestPoint?.collateralValue ?? 0, 6)} {symbol}
            </strong>
          </div>
          <div>
            <span>最新总债务值</span>
            <strong>
              {formatCompact(latestPoint?.borrowAssets ?? 0, 6)} {symbol}
            </strong>
          </div>
          <div>
            <span>最新总存款值</span>
            <strong>
              {formatCompact(latestPoint?.depositValue ?? 0, 6)} {symbol}
            </strong>
          </div>
          <div>
            <span>最低健康因子</span>
            <strong
              className={minHealthFactor !== null && minHealthFactor <= 1.2 ? 'danger-text' : ''}
            >
              {minHealthFactor === null ? '--' : formatCompact(minHealthFactor, 2)}
            </strong>
          </div>
          <div>
            <span>最新 LTV</span>
            <strong>
              {latestPoint?.ltvPercent === null
                ? '--'
                : `${formatCompact(latestPoint?.ltvPercent ?? 0, 2)}%`}
            </strong>
          </div>
        </div>

        <div className="morpho-history-chart-shell">
          {loading ? (
            <div className="morpho-history-state">
              <div className="spinner"></div>
            </div>
          ) : error ? (
            <div className="morpho-history-state morpho-history-error">{error}</div>
          ) : points.length === 0 ? (
            <div className="morpho-history-state">当前时间范围内没有可展示的 Morpho 历史点位。</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={points} margin={{ top: 12, right: 18, left: 4, bottom: 2 }}>
                <CartesianGrid stroke="#1f2a3d" strokeDasharray="4 8" vertical={false} />
                <XAxis
                  dataKey="timeLabel"
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  axisLine={{ stroke: '#263449' }}
                  tickLine={false}
                  minTickGap={24}
                />
                <YAxis
                  yAxisId="asset"
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(value) => formatCompact(Number(value), 2)}
                />
                <Tooltip content={<CustomTooltip loanTokenSymbol={symbol} />} />
                <Legend
                  iconType="circle"
                  wrapperStyle={{ color: '#cbd5e1', fontSize: 12, paddingTop: 10 }}
                />
                <Line
                  yAxisId="asset"
                  type="monotone"
                  dataKey="collateralValue"
                  name={`总抵押值 (${symbol})`}
                  stroke="#38bdf8"
                  strokeWidth={2.2}
                  dot={(props) => ChartOperationDot(props, selectedOperationTones, 'collateral')}
                  activeDot={false}
                />
                <Line
                  yAxisId="asset"
                  type="monotone"
                  dataKey="borrowAssets"
                  name={`总债务值 (${symbol})`}
                  stroke="#f97316"
                  strokeWidth={2.1}
                  dot={(props) => ChartOperationDot(props, selectedOperationTones, 'debt')}
                  activeDot={false}
                />
                <Line
                  yAxisId="asset"
                  type="monotone"
                  dataKey="depositValue"
                  name={`总存款值 (${symbol})`}
                  stroke="#22c55e"
                  strokeWidth={2.1}
                  dot={(props) => ChartOperationDot(props, selectedOperationTones, 'deposit')}
                  activeDot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

      {canShowDynamicLiquidationChart && (
        <MorphoDynamicLiquidationChart
          collateralSeries={collateralSeries}
          debtSeries={debtSeries}
          debtAmount={debtAmount ?? 0}
          collateralAmount={collateralAmount ?? 0}
          lltv={lltv ?? 0}
          collateralSymbol={collateralTokenSymbol || 'Collateral'}
          debtSymbol={symbol}
        />
      )}

      <section className="card morpho-history-card morpho-operation-card">
        {loading ? (
          <div className="morpho-history-state morpho-operation-state">
            <div className="spinner"></div>
          </div>
        ) : error ? (
          <div className="morpho-history-state morpho-history-error morpho-operation-state">
            {error}
          </div>
        ) : points.length === 0 ? (
          <div className="morpho-history-state morpho-operation-state">
            当前时间范围内没有可展示的用户操作。
          </div>
        ) : (
          <OperationTimeline
            points={points}
            selectedTones={selectedOperationTones}
            onToggleTone={toggleOperationTone}
            loanTokenSymbol={symbol}
          />
        )}
      </section>
    </div>
  );
}
