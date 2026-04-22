import { useEffect, useMemo, useState } from 'react';
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchJustLendPositionReplayWithMeta,
  type JustLendPositionReplayAsset,
  type JustLendPositionReplayPoint,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { ChartFallback } from '../shared/components/ChartFallback';
import { justLendChartTheme } from './justlendTheme';

interface JustLendPositionReplayChartProps {
  address: string;
  protocol?: string;
}

interface ReplayPointView {
  txHash: string;
  timestamp: string;
  timestampLabel: string;
  blockNumber: number;
  market: string;
  symbol: string;
  operationType: string;
  operationLabel: string;
  brief: string;
  totalCollateralUsd: number;
  totalDebtUsd: number;
  availableBorrowUsd: number;
  discountedCollateralUsd: number;
  liquidationBufferUsd: number;
  healthFactor: number;
  healthFactorChartValue: number;
  healthFactorLabel: string;
  ltvPct: number;
  ltvChartValue: number;
  liquidationThresholdPct: number;
  assets: JustLendPositionReplayAsset[];
}

interface AssetSlice {
  name: string;
  valueUsd: number;
  percent: number;
  amount: number;
}

interface ReplayTooltipEntry {
  payload: ReplayPointView;
  color?: string;
  name?: string;
  value?: string | number;
}

interface PositionTrendTooltipProps {
  active?: boolean;
  payload?: ReplayTooltipEntry[];
  label?: string;
}

interface OperationMarkerDotProps {
  cx?: number;
  cy?: number;
  payload?: ReplayPointView;
}

type ReplayAssetKind = 'collateral' | 'borrow' | 'supply';
type RiskViewMode = 'ALL' | 'LTV' | '健康因子' | '清算阈值';
type BufferViewMode = 'ALL' | '总债务价值' | '折算抵押价值' | '清算缓冲';
const JUSTLEND_HISTORY_START = '2020-12-01';

const explainItems: ExplainItem[] = [
  {
    term: '仓位规模趋势',
    formula: 'total_collateral_usd / total_debt_usd / available_borrow_usd',
    meaning: '按交易后快照展示账户的抵押规模、债务规模和剩余可借能力变化。',
    riskHint: '如果债务上升而可借额度持续收缩，说明账户正在向更高杠杆方向演变。',
  },
  {
    term: '风险指标趋势',
    formula: 'health_factor, ltv, liquidation_threshold',
    meaning: '把账户风险压缩成更容易读的三条曲线，用来观察安全边际是扩大还是缩小。',
    riskHint: 'LTV 靠近清算阈值、健康因子接近 1 时，需要尽快关注清算压力。',
  },
  {
    term: '清算缓冲',
    formula: 'liquidation_buffer_usd = discounted_collateral_usd - total_debt_usd',
    meaning: '表示折算后可用于支撑债务的抵押价值距离危险线还剩多少美元缓冲。',
    riskHint: '这条线持续贴近 0，说明一次价格波动就可能把仓位推入危险区。',
  },
];

const assetColors = justLendChartTheme.palettes.asset;

const chartTheme = {
  grid: justLendChartTheme.grid,
  axis: {
    stroke: justLendChartTheme.axis.primary,
    secondaryStroke: justLendChartTheme.axis.secondary,
  },
  tooltipBg: justLendChartTheme.tooltip.background,
  tooltipBorder: justLendChartTheme.tooltip.border,
  bufferTrend: {
    primary: justLendChartTheme.series.bufferDiscountedCollateral,
    secondary: justLendChartTheme.series.bufferDebt,
    tertiary: justLendChartTheme.series.bufferLiquidation,
    hoverLine: justLendChartTheme.series.bufferHoverLine,
    reference: justLendChartTheme.series.bufferReference,
  },
  riskTrend: {
    healthFactor: justLendChartTheme.series.riskHealthFactor,
    ltv: justLendChartTheme.series.riskLtv,
    liquidationThreshold: justLendChartTheme.series.riskLiquidationThreshold,
    hoverLine: justLendChartTheme.series.riskHoverLine,
    reference: justLendChartTheme.series.bufferReference,
  },
  positionTrend: justLendChartTheme.positionTrend,
} as const;

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatUsd(value: number): string {
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatUsdCompact(value: number): string {
  return `$${Intl.NumberFormat(undefined, {
    notation: 'compact',
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value)}`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatHealthFactorLabel(value: string | number): string {
  const raw = String(value).trim().toLowerCase();
  if (raw === 'inf' || raw === 'infinity') return '∞';
  const parsed = toNum(value);
  if (!Number.isFinite(parsed) || parsed >= 1e12) return '∞';
  return parsed.toFixed(2);
}

function ratioToPercent(value: string | number): number {
  const num = toNum(value);
  return num <= 1 ? num * 100 : num;
}

function formatDatetime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function toInputDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function getDefaultHistoryRange(): { start: string; end: string } {
  return {
    start: JUSTLEND_HISTORY_START,
    end: toInputDate(new Date()),
  };
}

function formatRequestBoundary(date: string, endOfDay = false): string {
  return `${date}T${endOfDay ? '23:59:59' : '00:00:00'}Z`;
}

function normalizeOperationType(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) return 'unknown';
  return normalized;
}

function operationLabel(value: string): string {
  const normalized = normalizeOperationType(value);
  const labels: Record<string, string> = {
    deposit: '存入',
    supply: '存入',
    withdraw: '提取',
    redeem: '提取',
    borrow: '借款',
    repay: '还款',
    liquidation: '清算',
    liquidate: '清算',
    unknown: '未知',
  };
  return labels[normalized] ?? value;
}

function buildReplayPoints(points: JustLendPositionReplayPoint[]): ReplayPointView[] {
  return points
    .map((point) => {
      const timestamp = point.timestamp;
      const normalizedType = normalizeOperationType(point.operation_type);
      return {
        txHash: point.tx_hash,
        timestamp,
        timestampLabel: formatDatetime(timestamp),
        blockNumber: point.block_number,
        market: point.market,
        symbol: point.symbol,
        operationType: normalizedType,
        operationLabel: operationLabel(normalizedType),
        brief: point.brief,
        totalCollateralUsd: toNum(point.total_collateral_usd),
        totalDebtUsd: toNum(point.total_debt_usd),
        availableBorrowUsd: toNum(point.available_borrow_usd),
        discountedCollateralUsd: toNum(point.discounted_collateral_usd),
        liquidationBufferUsd: toNum(point.liquidation_buffer_usd),
        healthFactor: toNum(point.health_factor),
        healthFactorChartValue: Math.min(2, toNum(point.health_factor)),
        healthFactorLabel: formatHealthFactorLabel(point.health_factor),
        ltvPct: ratioToPercent(point.ltv),
        ltvChartValue: Math.min(100, ratioToPercent(point.ltv)),
        liquidationThresholdPct: ratioToPercent(point.liquidation_threshold),
        assets: Array.isArray(point.assets) ? point.assets : [],
      };
    })
    .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));
}

function isReplaySupplyAsset(asset: JustLendPositionReplayAsset): boolean {
  return asset.position_type === 'supply';
}

function isReplayBorrowAsset(asset: JustLendPositionReplayAsset): boolean {
  return asset.position_type === 'borrow';
}

function isReplayCollateralAsset(asset: JustLendPositionReplayAsset): boolean {
  return isReplaySupplyAsset(asset) && asset.is_collateral;
}

function summarizeAssets(
  assets: JustLendPositionReplayAsset[],
  kind: ReplayAssetKind,
): AssetSlice[] {
  const grouped = new Map<string, { amount: number; valueUsd: number }>();
  for (const asset of assets) {
    const matches =
      kind === 'collateral'
        ? isReplayCollateralAsset(asset)
        : kind === 'borrow'
          ? isReplayBorrowAsset(asset)
          : isReplaySupplyAsset(asset);
    if (!matches) continue;
    const key = asset.symbol || asset.asset_address;
    const current = grouped.get(key) ?? { amount: 0, valueUsd: 0 };
    current.amount += toNum(asset.amount);
    current.valueUsd += toNum(asset.value_usd);
    grouped.set(key, current);
  }

  const total = Array.from(grouped.values()).reduce((sum, item) => sum + item.valueUsd, 0);
  return Array.from(grouped.entries())
    .map(([name, item]) => ({
      name,
      valueUsd: item.valueUsd,
      amount: item.amount,
      percent: total > 0 ? (item.valueUsd / total) * 100 : 0,
    }))
    .sort((a, b) => b.valueUsd - a.valueUsd)
    .slice(0, 8);
}

function renderAssetLegend(items: AssetSlice[]) {
  if (!items.length) {
    return <div className="justlend-empty-state">当前时点没有可展示的资产明细</div>;
  }

  return (
    <div style={{ display: 'grid', gap: '0.7rem' }}>
      {items.map((item, index) => (
        <div
          key={item.name}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '1rem',
            borderBottom: '1px solid #1e293b',
            paddingBottom: '0.55rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', minWidth: 0 }}>
            <span
              className="justlend-risk-dot"
              style={{ background: assetColors[index % assetColors.length], flexShrink: 0 }}
            />
            <span className="token-symbol" style={{ minWidth: 0 }}>
              {item.name}
            </span>
            <span style={{ color: '#94a3b8', fontSize: '0.82rem' }}>
              {item.percent.toFixed(2)}%
            </span>
          </div>
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              color: '#cbd5e1',
              fontSize: '0.82rem',
              gap: '0.12rem',
            }}
          >
            <span className="mono">{formatUsd(item.valueUsd)}</span>
            <span className="mono" style={{ color: '#94a3b8' }}>
              {item.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function buildActionSummary(point: ReplayPointView): string {
  const brief = point.brief.trim();
  if (!brief) return point.operationLabel;
  if (brief.startsWith(point.operationLabel)) return brief;
  return `${point.operationLabel} ${brief}`;
}

function PositionTrendTooltip({ active, payload, label }: PositionTrendTooltipProps) {
  if (!active || !payload?.length) return null;
  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div
      style={{
        backgroundColor: '#0f172a',
        border: '1px solid #1e293b',
        borderRadius: '10px',
        padding: '0.8rem 0.9rem',
        display: 'grid',
        gap: '0.38rem',
        maxWidth: 320,
      }}
    >
      <div style={{ color: '#e2e8f0', fontWeight: 700 }}>
        {formatDatetime(label ?? point.timestamp)}
      </div>
      <div style={{ color: '#94a3b8', fontSize: '0.82rem' }}>
        操作明细：<span style={{ color: '#f8fafc' }}>{buildActionSummary(point)}</span>
      </div>
      <div style={{ color: '#22c55e', fontSize: '0.84rem' }}>
        总抵押价值：{formatUsd(point.totalCollateralUsd)}
      </div>
      <div style={{ color: '#ef4444', fontSize: '0.84rem' }}>
        总债务价值：{formatUsd(point.totalDebtUsd)}
      </div>
    </div>
  );
}

function renderOperationMarker(
  props: OperationMarkerDotProps,
  selectedOperationType: string,
  color: string,
) {
  const { cx, cy, payload } = props;
  if (
    selectedOperationType === 'ALL' ||
    !payload ||
    payload.operationType !== selectedOperationType ||
    cx === undefined ||
    cy === undefined
  ) {
    return null;
  }

  return (
    <circle
      cx={cx}
      cy={cy}
      r={4.5}
      fill={color}
      stroke={chartTheme.positionTrend.markerStroke}
      strokeWidth={1.4}
    />
  );
}

function PositionTrendDefs() {
  return (
    <defs>
      <linearGradient id="justlend-position-trend-collateral-fill" x1="0" y1="0" x2="0" y2="1">
        <stop
          offset="0%"
          stopColor={chartTheme.positionTrend.collateral}
          stopOpacity={chartTheme.positionTrend.areaOpacityStart}
        />
        <stop
          offset="100%"
          stopColor={chartTheme.positionTrend.collateral}
          stopOpacity={chartTheme.positionTrend.areaOpacityEnd}
        />
      </linearGradient>
      <linearGradient id="justlend-position-trend-debt-fill" x1="0" y1="0" x2="0" y2="1">
        <stop
          offset="0%"
          stopColor={chartTheme.positionTrend.debt}
          stopOpacity={chartTheme.positionTrend.areaOpacityStart}
        />
        <stop
          offset="100%"
          stopColor={chartTheme.positionTrend.debt}
          stopOpacity={chartTheme.positionTrend.areaOpacityEnd}
        />
      </linearGradient>
    </defs>
  );
}

interface PositionTrendSeriesProps {
  dataKey: 'totalCollateralUsd' | 'totalDebtUsd';
  name: string;
  color: string;
  fillId: string;
  selectedOperationType: string;
}

function PositionTrendSeries({
  dataKey,
  name,
  color,
  fillId,
  selectedOperationType,
}: PositionTrendSeriesProps) {
  return (
    <>
      <Area
        type="monotone"
        dataKey={dataKey}
        name={name}
        fill={`url(#${fillId})`}
        stroke="none"
        isAnimationActive={false}
        legendType="none"
      />
      <Line
        type="monotone"
        dataKey={dataKey}
        name={name}
        stroke={color}
        strokeWidth={chartTheme.positionTrend.glowWidth}
        strokeOpacity={chartTheme.positionTrend.glowOpacity}
        dot={false}
        activeDot={false}
        legendType="none"
        isAnimationActive={false}
      />
      <Line
        type="monotone"
        dataKey={dataKey}
        name={name}
        stroke={color}
        strokeWidth={chartTheme.positionTrend.lineWidth}
        dot={
          selectedOperationType === 'ALL'
            ? false
            : (props) => renderOperationMarker(props, selectedOperationType, color)
        }
        activeDot={false}
        isAnimationActive={false}
      />
    </>
  );
}

export function JustLendPositionReplayChart({
  address,
  protocol = 'trx',
}: JustLendPositionReplayChartProps) {
  const [dateRange, setDateRange] = useState(() => getDefaultHistoryRange());
  const [appliedRange, setAppliedRange] = useState(() => getDefaultHistoryRange());
  const [data, setData] = useState<ReplayPointView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const [detailEnabled, setDetailEnabled] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedTimestamp, setSelectedTimestamp] = useState<string | null>(null);
  const [hoveredTimestamp, setHoveredTimestamp] = useState<string | null>(null);
  const [selectedOperationType, setSelectedOperationType] = useState<string>('ALL');
  const [riskViewMode, setRiskViewMode] = useState<RiskViewMode>('ALL');
  const [bufferViewMode, setBufferViewMode] = useState<BufferViewMode>('ALL');

  useEffect(() => {
    const nextRange = getDefaultHistoryRange();
    setDateRange(nextRange);
    setAppliedRange(nextRange);
    setDetailEnabled(false);
    setSelectedTimestamp(null);
    setHoveredTimestamp(null);
    setSelectedOperationType('ALL');
    setRiskViewMode('ALL');
    setBufferViewMode('ALL');
  }, [address]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');
      try {
        const result = await fetchJustLendPositionReplayWithMeta({
          address,
          start: formatRequestBoundary(appliedRange.start),
          end: formatRequestBoundary(appliedRange.end, true),
          protocol,
          useCache: true,
          detail: false,
        });
        if (cancelled) return;
        const points = buildReplayPoints(result.data.points ?? []);
        setData(points);
        setMeta(mergeRequestMetas([result.meta]));
        setSelectedTimestamp((current) => {
          if (current && points.some((item) => item.timestamp === current)) return current;
          return points.length ? points[points.length - 1].timestamp : null;
        });
      } catch (loadError) {
        if (cancelled) return;
        setData([]);
        setError(loadError instanceof Error ? loadError.message : '无法加载历史回放数据');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    if (address) {
      void load();
    }

    return () => {
      cancelled = true;
    };
  }, [address, appliedRange.end, appliedRange.start, protocol]);

  useEffect(() => {
    if (!detailEnabled) return;
    let cancelled = false;

    const loadDetail = async () => {
      setDetailLoading(true);
      try {
        const result = await fetchJustLendPositionReplayWithMeta({
          address,
          start: formatRequestBoundary(appliedRange.start),
          end: formatRequestBoundary(appliedRange.end, true),
          protocol,
          useCache: true,
          detail: true,
        });
        if (cancelled) return;
        const detailPoints = buildReplayPoints(result.data.points ?? []);
        setData(detailPoints);
        setMeta((current) =>
          mergeRequestMetas([
            { fetchedAt: Date.now(), fromCache: current.cacheStatus === 'hit' },
            result.meta,
          ]),
        );
        setSelectedTimestamp((current) => {
          if (current && detailPoints.some((item) => item.timestamp === current)) return current;
          return detailPoints.length ? detailPoints[detailPoints.length - 1].timestamp : null;
        });
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '无法加载资产明细历史');
        }
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    };

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [address, appliedRange.end, appliedRange.start, detailEnabled, protocol]);

  const selectedPoint = useMemo(
    () =>
      data.find((point) => point.timestamp === selectedTimestamp) ?? data[data.length - 1] ?? null,
    [data, selectedTimestamp],
  );
  const collateralAssets = useMemo(
    () => summarizeAssets(selectedPoint?.assets ?? [], 'collateral'),
    [selectedPoint],
  );
  const borrowAssets = useMemo(
    () => summarizeAssets(selectedPoint?.assets ?? [], 'borrow'),
    [selectedPoint],
  );
  const availableOperationTypes = useMemo(() => {
    const seen = new Set<string>();
    const items: string[] = [];
    for (const point of data) {
      const type = point.operationType || 'unknown';
      if (seen.has(type)) continue;
      seen.add(type);
      items.push(type);
    }
    return items;
  }, [data]);

  useEffect(() => {
    if (selectedOperationType === 'ALL') return;
    if (!availableOperationTypes.includes(selectedOperationType)) {
      setSelectedOperationType('ALL');
    }
  }, [availableOperationTypes, selectedOperationType]);

  const assetStructureSection = (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
          <span className="card-title">选中时点资产结构</span>
          <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
            {selectedPoint ? selectedPoint.timestampLabel : '未选中'}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setDetailEnabled(true)}
          disabled={detailEnabled || detailLoading}
          style={{
            borderRadius: '8px',
            border: '1px solid #334155',
            background: detailEnabled ? '#1e293b' : '#0f172a',
            color: '#e2e8f0',
            padding: '0.45rem 0.75rem',
            cursor: detailEnabled ? 'default' : 'pointer',
          }}
        >
          {detailLoading ? '加载明细中...' : detailEnabled ? '已启用资产明细' : '加载资产结构历史'}
        </button>
      </div>

      {!detailEnabled ? (
        <div className="justlend-banner justlend-banner-soft">
          <div className="justlend-banner-title">资产结构按选定时点加载</div>
          <div className="justlend-banner-copy">
            先在上方趋势图或操作明细里选中一个时间点，再点击右上角按钮加载该时点对应的资产结构。
          </div>
        </div>
      ) : detailLoading ? (
        <ChartFallback minHeight="260px" />
      ) : !selectedPoint ? (
        <div className="justlend-empty-state" style={{ minHeight: 220 }}>
          当前没有可选时点
        </div>
      ) : !selectedPoint.assets.length ? (
        <div className="justlend-empty-state" style={{ minHeight: 220 }}>
          当前时点没有资产明细
        </div>
      ) : (
        <div className="justlend-structure-grid">
          <div className="card" style={{ marginBottom: 0, background: '#0f172a' }}>
            <div className="card-header">
              <span className="card-title">抵押资产结构</span>
              <span className="badge green-badge">Collateral</span>
            </div>
            <div style={{ height: 280 }}>
              {collateralAssets.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={collateralAssets}
                      dataKey="valueUsd"
                      nameKey="name"
                      innerRadius={56}
                      outerRadius={92}
                      stroke="#151c2c"
                      strokeWidth={1}
                    >
                      {collateralAssets.map((item, index) => (
                        <Cell key={item.name} fill={assetColors[index % assetColors.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                      formatter={(
                        value: unknown,
                        _name: unknown,
                        entry: { payload?: AssetSlice },
                      ) => [
                        formatUsd(Number(value ?? 0)),
                        `${entry?.payload?.name ?? '资产'} 占比 ${entry?.payload?.percent.toFixed(2) ?? '0.00'}%`,
                      ]}
                    />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="justlend-empty-state">不存在抵押资产</div>
              )}
            </div>
            {renderAssetLegend(collateralAssets)}
          </div>

          <div className="card" style={{ marginBottom: 0, background: '#0f172a' }}>
            <div className="card-header">
              <span className="card-title">债务资产结构</span>
              <span className="badge" style={{ background: '#3f0d0d', color: '#fca5a5' }}>
                Borrow
              </span>
            </div>
            <div style={{ height: 280 }}>
              {borrowAssets.length ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={borrowAssets}
                    layout="vertical"
                    margin={{ top: 10, right: 16, left: 8, bottom: 6 }}
                    barCategoryGap="45%"
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis
                      type="number"
                      stroke="#64748b"
                      tickFormatter={(value) => formatUsdCompact(Number(value))}
                    />
                    <YAxis type="category" dataKey="name" stroke="#94a3b8" width={72} />
                    <Tooltip
                      contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                      itemStyle={{ color: '#22c55e' }}
                      formatter={(
                        value: unknown,
                        _name: unknown,
                        entry: { payload?: AssetSlice },
                      ) => [
                        formatUsd(Number(value ?? 0)),
                        `${entry?.payload?.name ?? '资产'} 占比 ${entry?.payload?.percent.toFixed(2) ?? '0.00'}%`,
                      ]}
                      cursor={false}
                    />
                    <Bar
                      dataKey="valueUsd"
                      name="债务价值"
                      radius={[0, 6, 6, 0]}
                      maxBarSize={20}
                      activeBar={false}
                    >
                      {borrowAssets.map((item, index) => (
                        <Cell key={item.name} fill={assetColors[index % assetColors.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="justlend-empty-state">暂无债务资产</div>
              )}
            </div>
            {renderAssetLegend(borrowAssets)}
          </div>
        </div>
      )}
    </div>
  );

  const handleApplyRange = () => {
    if (!dateRange.start || !dateRange.end) {
      setError('请选择完整时间区间');
      return;
    }
    if (dateRange.start > dateRange.end) {
      setError('开始日期不能晚于结束日期');
      return;
    }
    setError('');
    setAppliedRange(dateRange);
    setDetailEnabled(false);
  };

  if (loading) {
    return <ChartFallback minHeight="320px" />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">历史回放分析</span>
            <ChartInfoButton title="JustLend 历史图表说明" items={explainItems} />
            <span className="badge" style={{ background: '#172554', color: '#bfdbfe' }}>
              {protocol}
            </span>
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div style={{ display: 'grid', gap: '1rem' }}>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              gap: '1rem',
              flexWrap: 'wrap',
              alignItems: 'center',
            }}
          >
            <div className="justlend-history-range-summary">
              <span className="justlend-history-range-summary-label">当前查询范围</span>
              <span className="justlend-history-range-summary-value">
                {appliedRange.start} 至 {appliedRange.end}，共 {data.length} 个快照点。
                {selectedPoint
                  ? ` 当前选中时点：${selectedPoint.timestampLabel}`
                  : ' 当前区间暂无可选时点。'}
              </span>
            </div>
            <div
              style={{ display: 'flex', gap: '0.65rem', flexWrap: 'wrap', alignItems: 'center' }}
            >
              <label
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.3rem',
                  color: '#94a3b8',
                  fontSize: '0.78rem',
                }}
              >
                开始日期
                <input
                  type="date"
                  value={dateRange.start}
                  onChange={(event) => {
                    setDateRange((current) => ({ ...current, start: event.target.value }));
                  }}
                  style={{
                    background: '#0f172a',
                    color: '#e2e8f0',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    padding: '0.45rem 0.65rem',
                  }}
                />
              </label>
              <label
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.3rem',
                  color: '#94a3b8',
                  fontSize: '0.78rem',
                }}
              >
                结束日期
                <input
                  type="date"
                  value={dateRange.end}
                  onChange={(event) => {
                    setDateRange((current) => ({ ...current, end: event.target.value }));
                  }}
                  style={{
                    background: '#0f172a',
                    color: '#e2e8f0',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    padding: '0.45rem 0.65rem',
                  }}
                />
              </label>
              <button
                type="button"
                onClick={handleApplyRange}
                style={{
                  marginTop: '1.1rem',
                  borderRadius: '8px',
                  border: '1px solid #2563eb',
                  background: '#2563eb',
                  color: '#eff6ff',
                  padding: '0.5rem 0.9rem',
                  cursor: 'pointer',
                }}
              >
                应用时间范围
              </button>
            </div>
          </div>

          {error ? (
            <div className="justlend-banner justlend-banner-warn">
              <div className="justlend-banner-title">历史回放暂不可用</div>
              <div className="justlend-banner-copy">{error}</div>
            </div>
          ) : null}
        </div>
      </div>

      {!error && !data.length ? (
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="justlend-empty-state" style={{ minHeight: 220 }}>
            当前时间范围内没有 JustLend 历史回放数据
          </div>
        </div>
      ) : null}

      {!error && data.length ? (
        <>
          <div className="card" style={{ marginBottom: 0 }}>
            <div className="card-header">
              <span className="card-title">仓位规模趋势</span>
              <span className="badge green-badge">Overview</span>
            </div>
            <div
              style={{
                display: 'flex',
                gap: '0.55rem',
                flexWrap: 'wrap',
                marginBottom: '0.9rem',
              }}
            >
              {['ALL', ...availableOperationTypes].map((operationType) => {
                const active = selectedOperationType === operationType;
                return (
                  <button
                    key={operationType}
                    type="button"
                    onClick={() => setSelectedOperationType(operationType)}
                    style={{
                      borderRadius: '999px',
                      border: `1px solid ${active ? '#2563eb' : '#334155'}`,
                      background: active ? '#2563eb' : '#0f172a',
                      color: active ? '#eff6ff' : '#cbd5e1',
                      padding: '0.38rem 0.8rem',
                      cursor: 'pointer',
                      fontSize: '0.8rem',
                      lineHeight: 1.2,
                    }}
                  >
                    {operationType}
                  </button>
                );
              })}
            </div>
            <div style={{ height: 320 }}>
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart
                  data={data}
                  onClick={(state) =>
                    setSelectedTimestamp(state?.activeLabel ? String(state.activeLabel) : null)
                  }
                  onMouseMove={(state) =>
                    setHoveredTimestamp(state?.activeLabel ? String(state.activeLabel) : null)
                  }
                  onMouseLeave={() => setHoveredTimestamp(null)}
                  margin={{ top: 12, right: 18, left: 4, bottom: 2 }}
                >
                  <PositionTrendDefs />
                  <CartesianGrid
                    stroke={chartTheme.positionTrend.grid}
                    strokeDasharray="4 8"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="timestamp"
                    tick={{ fill: chartTheme.positionTrend.axis, fontSize: 11 }}
                    axisLine={{ stroke: chartTheme.positionTrend.axisLine }}
                    tickLine={false}
                    tickFormatter={(value) => String(value).slice(0, 10)}
                    minTickGap={24}
                  />
                  <YAxis
                    tick={{ fill: chartTheme.positionTrend.axis, fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={(value) => formatUsdCompact(Number(value))}
                  />
                  {hoveredTimestamp || selectedPoint ? (
                    <ReferenceLine
                      x={hoveredTimestamp ?? selectedPoint?.timestamp}
                      stroke={chartTheme.positionTrend.hoverLine}
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                    />
                  ) : null}
                  <Tooltip content={<PositionTrendTooltip />} cursor={false} />
                  <Legend
                    iconType="circle"
                    wrapperStyle={{
                      color: chartTheme.positionTrend.legendText,
                      fontSize: 12,
                      paddingTop: 10,
                    }}
                  />
                  <PositionTrendSeries
                    dataKey="totalCollateralUsd"
                    name="总抵押价值"
                    color={chartTheme.positionTrend.collateral}
                    fillId="justlend-position-trend-collateral-fill"
                    selectedOperationType={selectedOperationType}
                  />
                  <PositionTrendSeries
                    dataKey="totalDebtUsd"
                    name="总债务价值"
                    color={chartTheme.positionTrend.debt}
                    fillId="justlend-position-trend-debt-fill"
                    selectedOperationType={selectedOperationType}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          </div>

          {assetStructureSection}

          <div className="justlend-structure-grid">
            <div className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <span className="card-title">风险指标趋势</span>
                <span className="badge" style={{ background: '#3f3f1a', color: '#fde68a' }}>
                  Risk
                </span>
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: '0.55rem',
                  flexWrap: 'wrap',
                  marginBottom: '0.9rem',
                }}
              >
                {(['ALL', 'LTV', '健康因子', '清算阈值'] as RiskViewMode[]).map((mode) => {
                  const active = riskViewMode === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setRiskViewMode(mode)}
                      style={{
                        borderRadius: '999px',
                        border: `1px solid ${active ? '#2563eb' : '#334155'}`,
                        background: active ? '#2563eb' : '#0f172a',
                        color: active ? '#eff6ff' : '#cbd5e1',
                        padding: '0.38rem 0.8rem',
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        lineHeight: 1.2,
                      }}
                    >
                      {mode}
                    </button>
                  );
                })}
              </div>
              <div style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
                    <XAxis
                      dataKey="timestamp"
                      stroke={chartTheme.axis.stroke}
                      tickFormatter={(value) => String(value).slice(0, 10)}
                      minTickGap={32}
                    />
                    {riskViewMode === 'ALL' ? (
                      <>
                        <YAxis
                          yAxisId="hf"
                          stroke={chartTheme.axis.stroke}
                          domain={[0, 2]}
                          ticks={[0, 0.5, 1, 1.5, 2]}
                        />
                        <YAxis
                          yAxisId="ratio"
                          orientation="right"
                          stroke={chartTheme.axis.stroke}
                          domain={[0, 100]}
                          tickFormatter={(value) => `${Number(value)}%`}
                        />
                        <ReferenceLine
                          yAxisId="hf"
                          y={1}
                          stroke={chartTheme.riskTrend.reference}
                          strokeDasharray="4 4"
                        />
                      </>
                    ) : null}
                    {riskViewMode === '健康因子' ? (
                      <>
                        <YAxis
                          yAxisId="hf"
                          stroke={chartTheme.axis.stroke}
                          domain={[0, 2]}
                          ticks={[0, 0.5, 1, 1.5, 2]}
                        />
                        <ReferenceLine
                          yAxisId="hf"
                          y={1}
                          stroke={chartTheme.riskTrend.reference}
                          strokeDasharray="4 4"
                        />
                      </>
                    ) : null}
                    {riskViewMode === '清算阈值' ? (
                      <YAxis
                        yAxisId="ratio"
                        stroke={chartTheme.axis.stroke}
                        domain={[0, 100]}
                        tickFormatter={(value) => `${Number(value)}%`}
                      />
                    ) : null}
                    {riskViewMode === 'LTV' ? (
                      <YAxis
                        yAxisId="ratio"
                        stroke={chartTheme.axis.stroke}
                        tickFormatter={(value) => `${Number(value)}%`}
                      />
                    ) : null}
                    <Tooltip
                      contentStyle={{
                        backgroundColor: chartTheme.tooltipBg,
                        borderColor: chartTheme.tooltipBorder,
                      }}
                      labelFormatter={(value) => formatDatetime(String(value))}
                      formatter={(
                        value: unknown,
                        name: unknown,
                        entry: { payload?: ReplayPointView },
                      ) => {
                        const point = entry?.payload;
                        if (String(name) === '健康因子') {
                          return [point?.healthFactorLabel ?? String(value), String(name)];
                        }
                        if (String(name) === 'LTV') {
                          return [formatPercent(point?.ltvPct ?? Number(value ?? 0)), String(name)];
                        }
                        if (String(name) === '清算阈值') {
                          return [
                            formatPercent(point?.liquidationThresholdPct ?? Number(value ?? 0)),
                            String(name),
                          ];
                        }
                        return [formatPercent(Number(value ?? 0)), String(name)];
                      }}
                      cursor={{ stroke: '#f8fafc', strokeWidth: 1.5 }}
                    />
                    <Legend />
                    {riskViewMode === 'ALL' || riskViewMode === '健康因子' ? (
                      <Line
                        yAxisId="hf"
                        type="monotone"
                        dataKey="healthFactorChartValue"
                        name="健康因子"
                        stroke={chartTheme.riskTrend.healthFactor}
                        strokeWidth={2.1}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    ) : null}
                    {riskViewMode === 'ALL' || riskViewMode === 'LTV' ? (
                      <Line
                        yAxisId="ratio"
                        type="monotone"
                        dataKey={riskViewMode === 'ALL' ? 'ltvChartValue' : 'ltvPct'}
                        name="LTV"
                        stroke={chartTheme.riskTrend.ltv}
                        strokeWidth={2.1}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    ) : null}
                    {riskViewMode === 'ALL' || riskViewMode === '清算阈值' ? (
                      <Line
                        yAxisId="ratio"
                        type="monotone"
                        dataKey="liquidationThresholdPct"
                        name="清算阈值"
                        stroke={chartTheme.riskTrend.liquidationThreshold}
                        strokeWidth={2.1}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    ) : null}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <span className="card-title">缓冲变化趋势</span>
                <span className="badge" style={{ background: '#0f172a', color: '#cbd5e1' }}>
                  Buffer
                </span>
              </div>
              <div
                style={{
                  display: 'flex',
                  gap: '0.55rem',
                  flexWrap: 'wrap',
                  marginBottom: '0.9rem',
                }}
              >
                {(['ALL', '总债务价值', '折算抵押价值', '清算缓冲'] as BufferViewMode[]).map(
                  (mode) => {
                    const active = bufferViewMode === mode;
                    return (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setBufferViewMode(mode)}
                        style={{
                          borderRadius: '999px',
                          border: `1px solid ${active ? '#2563eb' : '#334155'}`,
                          background: active ? '#2563eb' : '#0f172a',
                          color: active ? '#eff6ff' : '#cbd5e1',
                          padding: '0.38rem 0.8rem',
                          cursor: 'pointer',
                          fontSize: '0.8rem',
                          lineHeight: 1.2,
                        }}
                      >
                        {mode}
                      </button>
                    );
                  },
                )}
              </div>
              <div style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} />
                    <XAxis
                      dataKey="timestamp"
                      stroke={chartTheme.axis.stroke}
                      tickFormatter={(value) => String(value).slice(0, 10)}
                      minTickGap={32}
                    />
                    <YAxis
                      stroke={chartTheme.axis.stroke}
                      tickFormatter={(value) => formatUsdCompact(Number(value))}
                    />
                    {bufferViewMode === 'ALL' || bufferViewMode === '清算缓冲' ? (
                      <ReferenceLine
                        y={0}
                        stroke={chartTheme.bufferTrend.reference}
                        strokeDasharray="4 4"
                      />
                    ) : null}
                    <Tooltip
                      contentStyle={{
                        backgroundColor: chartTheme.tooltipBg,
                        borderColor: chartTheme.tooltipBorder,
                      }}
                      labelFormatter={(value) => formatDatetime(String(value))}
                      formatter={(value: unknown, name: unknown) => [
                        formatUsd(Number(value ?? 0)),
                        String(name),
                      ]}
                    />
                    <Legend />
                    {bufferViewMode === 'ALL' || bufferViewMode === '折算抵押价值' ? (
                      <Line
                        type="monotone"
                        dataKey="discountedCollateralUsd"
                        name="折算抵押价值"
                        stroke={chartTheme.bufferTrend.primary}
                        strokeWidth={2.1}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    ) : null}
                    {bufferViewMode === 'ALL' || bufferViewMode === '清算缓冲' ? (
                      <Line
                        type="monotone"
                        dataKey="liquidationBufferUsd"
                        name="清算缓冲"
                        stroke={chartTheme.bufferTrend.secondary}
                        strokeWidth={2.1}
                        dot={false}
                        activeDot={{ r: 5 }}
                      />
                    ) : null}
                    {bufferViewMode === 'ALL' || bufferViewMode === '总债务价值' ? (
                      <Line
                        type="monotone"
                        dataKey="totalDebtUsd"
                        name="总债务价值"
                        stroke={chartTheme.bufferTrend.tertiary}
                        strokeWidth={1.8}
                        strokeDasharray="5 4"
                        dot={false}
                        activeDot={{ r: 4 }}
                      />
                    ) : null}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
