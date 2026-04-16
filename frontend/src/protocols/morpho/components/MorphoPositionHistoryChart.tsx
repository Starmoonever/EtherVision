import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
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

interface MorphoPositionHistoryChartProps {
  address: string;
  marketId: string;
  protocol?: 'blue';
  loanTokenSymbol?: string | null;
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
  operationAmount: number;
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
  | 'withdraw'
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
  { rank: 0, label: '抵押 / 补仓', tone: 'collateral' },
  { rank: 1, label: '存款', tone: 'supply' },
  { rank: 2, label: '借款', tone: 'borrow' },
  { rank: 3, label: '还款', tone: 'repay' },
  { rank: 4, label: '撤回', tone: 'withdraw' },
  { rank: 5, label: '清算', tone: 'liquidation' },
  { rank: 6, label: '其他', tone: 'neutral' },
];
const DEFAULT_SELECTED_OPERATION_TONES = new Set<OperationTone>(
  OPERATION_ROWS.map((row) => row.tone),
);

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
    return { label: '清算', rank: 5, tone: 'liquidation' };
  }
  if (normalized.includes('repay')) {
    return { label: '还款', rank: 3, tone: 'repay' };
  }
  if (normalized.includes('borrow')) {
    return { label: '借款', rank: 2, tone: 'borrow' };
  }
  if (normalized.includes('withdraw') || normalized.includes('remove')) {
    return { label: '撤回', rank: 4, tone: 'withdraw' };
  }
  if (normalized.includes('collateral')) {
    return { label: '抵押 / 补仓', rank: 0, tone: 'collateral' };
  }
  if (normalized.includes('supply') || normalized.includes('deposit')) {
    return { label: '存款', rank: 1, tone: 'supply' };
  }

  return { label: value === 'unknown' ? '其他操作' : value, rank: 6, tone: 'neutral' };
}

function getDepositValue(point: MorphoPositionReplayPoint): number {
  return point.assets.reduce((total, asset) => {
    if (asset.role !== 'loan') return total;
    const amount = toNum(asset.amount);
    return amount > 0 ? total + amount : total;
  }, 0);
}

function normalizeReplayPoint(point: MorphoPositionReplayPoint, index: number): MorphoHistoryPoint {
  const collateralValue = toNum(point.collateral_value_in_loan_asset);
  const borrowAssets = Math.abs(toNum(point.borrow_assets));
  const depositValue = getDepositValue(point);
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
    operationAmount: 0,
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
  if (point.operationTone === 'withdraw') {
    return Math.max(Math.abs(collateralDelta), Math.abs(depositDelta));
  }
  if (point.operationTone === 'collateral' || point.operationTone === 'supply') {
    return Math.max(Math.abs(collateralDelta), Math.abs(depositDelta));
  }
  if (point.operationTone === 'liquidation') {
    return Math.abs(collateralDelta) + Math.abs(debtDelta) + Math.abs(depositDelta);
  }

  return Math.max(Math.abs(collateralDelta), Math.abs(debtDelta), Math.abs(depositDelta));
}

function withOperationAmounts(points: MorphoHistoryPoint[]): MorphoHistoryPoint[] {
  return points.map((point, index) => ({
    ...point,
    index,
    operationAmount: getOperationAmount(point, points[index - 1]),
  }));
}

function getOperationToneColor(tone: OperationTone): string {
  if (tone === 'collateral') return '#22c55e';
  if (tone === 'supply') return '#14b8a6';
  if (tone === 'borrow') return '#f97316';
  if (tone === 'repay') return '#38bdf8';
  if (tone === 'withdraw') return '#facc15';
  if (tone === 'liquidation') return '#ef4444';
  return '#94a3b8';
}

function isOperationSelected(point: MorphoHistoryPoint, selectedTones: OperationToneSet): boolean {
  return selectedTones.has(point.operationTone);
}

function ChartOperationDot(props: unknown, selectedTones: OperationToneSet) {
  const { cx, cy, payload } = props as {
    cx?: number;
    cy?: number;
    payload?: MorphoHistoryPoint;
  };
  if (cx === undefined || cy === undefined || !payload) return <g />;

  const selected = isOperationSelected(payload, selectedTones);
  const color = getOperationToneColor(payload.operationTone);
  const riskStroke = payload.isHealthy ? color : '#fecaca';

  return (
    <g className={selected ? 'morpho-history-linked-dot' : 'morpho-history-linked-dot muted'}>
      <circle
        cx={cx}
        cy={cy}
        r={selected ? 7.5 : 3.2}
        fill={color}
        opacity={selected ? 0.2 : 0.08}
      />
      <circle
        cx={cx}
        cy={cy}
        r={selected ? 4.2 : 2.3}
        fill={color}
        stroke={riskStroke}
        strokeWidth={payload.isHealthy ? 1.1 : 1.8}
      />
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
  return (
    <div className="morpho-operation-timeline">
      <div className="morpho-operation-timeline-header">
        <div>
          <strong>操作金额图</strong>
          <span>柱高表示本次操作造成的仓位金额变化，颜色表示操作类型</span>
        </div>
        <div className="morpho-operation-legend">
          {OPERATION_ROWS.map((row) => (
            <button
              key={row.tone}
              type="button"
              className={selectedTones.has(row.tone) ? 'active' : ''}
              onClick={() => onToggleTone(row.tone)}
              aria-pressed={selectedTones.has(row.tone)}
            >
              <i style={{ background: getOperationToneColor(row.tone) }} />
              {row.label.split(' / ')[0]}
            </button>
          ))}
        </div>
      </div>

      <div className="morpho-operation-chart-shell">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={points} margin={{ top: 10, right: 18, left: 4, bottom: 2 }}>
            <CartesianGrid stroke="#1f2a3d" strokeDasharray="4 8" vertical={false} />
            <XAxis
              dataKey="timeLabel"
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={{ stroke: '#263449' }}
              tickLine={false}
              minTickGap={24}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => formatCompact(Number(value), 2)}
            />
            <Tooltip content={<CustomTooltip loanTokenSymbol={loanTokenSymbol} />} />
            <Bar dataKey="operationAmount" name="操作金额" radius={[8, 8, 2, 2]}>
              {points.map((point) => (
                <Cell
                  key={`${point.txHash}-${point.blockNumber}`}
                  fill={getOperationToneColor(point.operationTone)}
                  fillOpacity={selectedTones.has(point.operationTone) ? 0.9 : 0.18}
                />
              ))}
            </Bar>
          </BarChart>
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
}: MorphoPositionHistoryChartProps) {
  const [range, setRange] = useState(() => getDefaultRange());
  const [appliedRange, setAppliedRange] = useState(range);
  const [points, setPoints] = useState<MorphoHistoryPoint[]>([]);
  const [selectedOperationTones, setSelectedOperationTones] = useState<OperationToneSet>(
    () => new Set(DEFAULT_SELECTED_OPERATION_TONES),
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
          { detail: false },
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
      return next.size > 0 ? next : new Set(DEFAULT_SELECTED_OPERATION_TONES);
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
                  dot={(props) => ChartOperationDot(props, selectedOperationTones)}
                  activeDot={{ r: 5, stroke: '#bfdbfe', strokeWidth: 2 }}
                />
                <Line
                  yAxisId="asset"
                  type="monotone"
                  dataKey="borrowAssets"
                  name={`总债务值 (${symbol})`}
                  stroke="#f97316"
                  strokeWidth={2.1}
                  dot={(props) => ChartOperationDot(props, selectedOperationTones)}
                  activeDot={{ r: 5, stroke: '#fed7aa', strokeWidth: 2 }}
                />
                <Line
                  yAxisId="asset"
                  type="monotone"
                  dataKey="depositValue"
                  name={`总存款值 (${symbol})`}
                  stroke="#22c55e"
                  strokeWidth={2.1}
                  dot={(props) => ChartOperationDot(props, selectedOperationTones)}
                  activeDot={{ r: 5, stroke: '#bbf7d0', strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </section>

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
