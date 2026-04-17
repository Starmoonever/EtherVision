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
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchJustLendMarketStatePeriodWithMeta,
  fetchJustLendMarketStateWithMeta,
  type JustLendMarketItem,
  type JustLendMarketStateResponse,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus } from './ChartAssist';
import { justLendChartTheme } from './justlendTheme';

const marketPalette = justLendChartTheme.palettes.market;
const USD_CALCULATION_SCALE = 10;
const JUSTLEND_MARKET_HISTORY_START = '2020-12-01T00:00:00Z';

type MarketHistoryRange = '1D' | '7D' | '1M' | 'ALL';

interface JustLendMarketHistoryPointView {
  timestamp: string;
  timeLabel: string;
  cash: number;
  totalBorrows: number;
  totalReserves: number;
  totalSupply: number;
  cashUsd: number;
  borrowUsd: number;
  reserveUsd: number;
  supplyUsd: number;
  utilizationPct: number;
  borrowRatePct: number;
  supplyRatePct: number;
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function decimalToScaledBigInt(value: string | number | null | undefined, scale: number): bigint {
  const normalized = String(value ?? '0').trim();
  if (!normalized) return 0n;

  const negative = normalized.startsWith('-');
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [integerPartRaw, fractionPartRaw = ''] = unsigned.split('.');
  const integerPart = integerPartRaw.replace(/\D/g, '') || '0';
  const fractionPart = fractionPartRaw.replace(/\D/g, '').slice(0, scale).padEnd(scale, '0');
  const scaled = BigInt(integerPart) * 10n ** BigInt(scale) + BigInt(fractionPart || '0');
  return negative ? -scaled : scaled;
}

function multiplyDecimalStrings(
  left: string | number | null | undefined,
  right: string | number | null | undefined,
  scale: number = USD_CALCULATION_SCALE,
): number {
  const factor = 10n ** BigInt(scale);
  const leftScaled = decimalToScaledBigInt(left, scale);
  const rightScaled = decimalToScaledBigInt(right, scale);
  const product = leftScaled * rightScaled;
  const rounded =
    product >= 0 ? (product + factor / 2n) / factor : (product - factor / 2n) / factor;
  return Number(rounded) / Number(factor);
}

function ratioToPercent(value: string | number): number {
  const num = toNum(value);
  return num <= 1 ? num * 100 : num;
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
    maximumFractionDigits: 1,
  }).format(value)}`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatRawAmount(value: number): string {
  return value.toLocaleString(undefined, {
    maximumFractionDigits: 6,
  });
}

function formatDateTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function formatHistoryTimeLabel(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  const date = new Date(parsed);
  const pad = (num: number) => String(num).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function marketLabel(item: JustLendMarketItem): string {
  return item.underlying_symbol || item.symbol || item.market.slice(0, 6);
}

function formatUtcSecond(value: Date): string {
  return value.toISOString().slice(0, 19) + 'Z';
}

function getHistoryRangeBounds(range: MarketHistoryRange): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end);

  if (range === 'ALL') {
    return {
      start: JUSTLEND_MARKET_HISTORY_START,
      end: formatUtcSecond(end),
    };
  }

  if (range === '1D') {
    start.setUTCDate(start.getUTCDate() - 1);
  } else if (range === '7D') {
    start.setUTCDate(start.getUTCDate() - 7);
  } else {
    start.setUTCMonth(start.getUTCMonth() - 1);
  }

  return {
    start: formatUtcSecond(start),
    end: formatUtcSecond(end),
  };
}

function buildHistoryPoint(point: JustLendMarketStateResponse): JustLendMarketHistoryPointView {
  return {
    timestamp: point.timestamp,
    timeLabel: formatHistoryTimeLabel(point.timestamp),
    cash: toNum(point.cash),
    totalBorrows: toNum(point.total_borrows),
    totalReserves: toNum(point.total_reserves),
    totalSupply: toNum(point.total_supply),
    cashUsd: multiplyDecimalStrings(point.cash, point.price_usd),
    borrowUsd: multiplyDecimalStrings(point.total_borrows, point.price_usd),
    reserveUsd: multiplyDecimalStrings(point.total_reserves, point.price_usd),
    supplyUsd: multiplyDecimalStrings(point.total_supply, point.price_usd),
    utilizationPct: ratioToPercent(point.utilization),
    borrowRatePct: ratioToPercent(point.borrow_rate),
    supplyRatePct: ratioToPercent(point.supply_rate),
  };
}

const marketChartTick = { fill: justLendChartTheme.axis.secondary, fontSize: 12 };
const marketTooltipContentStyle = {
  backgroundColor: justLendChartTheme.tooltip.background,
  borderColor: justLendChartTheme.tooltip.border,
  color: justLendChartTheme.tooltip.text,
};
const marketTooltipLabelStyle = {
  color: justLendChartTheme.tooltip.text,
};
const marketTooltipItemStyle = {
  color: justLendChartTheme.tooltip.text,
};
const marketHistoryTheme = justLendChartTheme.marketHistory;

function HistoryChartState({
  loading,
  error,
  empty,
}: {
  loading: boolean;
  error: string;
  empty: boolean;
}) {
  if (!loading && !error && !empty) return null;

  return (
    <div
      className="card"
      style={{
        minHeight: 280,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: error ? '#fca5a5' : '#94a3b8',
      }}
    >
      {loading ? <div className="spinner"></div> : error || '当前时间范围内暂无历史市场状态数据'}
    </div>
  );
}

function JustLendRateHistoryChart({ data }: { data: JustLendMarketHistoryPointView[] }) {
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="card-header">
        <span className="card-title">历史利率趋势</span>
        <span className="badge" style={justLendChartTheme.badge.info}>
          Rate
        </span>
      </div>
      <div style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 16, right: 18, left: 4, bottom: 8 }}>
            <CartesianGrid
              stroke={marketHistoryTheme.grid}
              strokeDasharray="4 8"
              vertical={false}
            />
            <XAxis
              dataKey="timeLabel"
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={{ stroke: marketHistoryTheme.axisLine }}
              tickLine={false}
              minTickGap={28}
            />
            <YAxis
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => formatPercent(Number(value))}
            />
            <Tooltip
              cursor={false}
              contentStyle={marketTooltipContentStyle}
              labelStyle={marketTooltipLabelStyle}
              itemStyle={marketTooltipItemStyle}
              formatter={(value: unknown, name: string | number | undefined) => [
                formatPercent(Number(value ?? 0)),
                String(name ?? ''),
              ]}
            />
            <Legend
              iconType="circle"
              wrapperStyle={{ color: justLendChartTheme.legend.text, fontSize: 12, paddingTop: 8 }}
            />
            <Line
              type="monotone"
              dataKey="supplyRatePct"
              name="Supply Rate"
              stroke={marketHistoryTheme.supplyRate}
              strokeWidth={2.2}
              dot={false}
              activeDot={{ r: 4 }}
            />
            <Line
              type="monotone"
              dataKey="borrowRatePct"
              name="Borrow Rate"
              stroke={marketHistoryTheme.borrowRate}
              strokeWidth={2.2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function JustLendMarketScaleHistoryChart({ data }: { data: JustLendMarketHistoryPointView[] }) {
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="card-header">
        <span className="card-title">市场规模历史</span>
        <span className="badge" style={justLendChartTheme.badge.neutral}>
          USD Area
        </span>
      </div>
      <div style={{ height: 340 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 16, right: 18, left: 4, bottom: 8 }}>
            <defs>
              <linearGradient id="justlend-history-cash" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={marketHistoryTheme.cash} stopOpacity={0.42} />
                <stop offset="100%" stopColor={marketHistoryTheme.cash} stopOpacity={0.08} />
              </linearGradient>
              <linearGradient id="justlend-history-borrows" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={marketHistoryTheme.borrows} stopOpacity={0.42} />
                <stop offset="100%" stopColor={marketHistoryTheme.borrows} stopOpacity={0.08} />
              </linearGradient>
              <linearGradient id="justlend-history-reserves" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={marketHistoryTheme.reserves} stopOpacity={0.35} />
                <stop offset="100%" stopColor={marketHistoryTheme.reserves} stopOpacity={0.06} />
              </linearGradient>
            </defs>
            <CartesianGrid
              stroke={marketHistoryTheme.grid}
              strokeDasharray="4 8"
              vertical={false}
            />
            <XAxis
              dataKey="timeLabel"
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={{ stroke: marketHistoryTheme.axisLine }}
              tickLine={false}
              minTickGap={28}
            />
            <YAxis
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => formatUsdCompact(Number(value))}
            />
            <Tooltip
              cursor={false}
              contentStyle={marketTooltipContentStyle}
              labelStyle={marketTooltipLabelStyle}
              itemStyle={marketTooltipItemStyle}
              formatter={(value: unknown, name: string | number | undefined) => [
                formatUsd(Number(value ?? 0)),
                String(name ?? ''),
              ]}
            />
            <Legend
              iconType="circle"
              wrapperStyle={{ color: justLendChartTheme.legend.text, fontSize: 12, paddingTop: 8 }}
            />
            <Area
              type="monotone"
              dataKey="cashUsd"
              name="Cash"
              stackId="marketSize"
              stroke={marketHistoryTheme.cash}
              fill="url(#justlend-history-cash)"
              strokeWidth={1.8}
            />
            <Area
              type="monotone"
              dataKey="borrowUsd"
              name="Borrows"
              stackId="marketSize"
              stroke={marketHistoryTheme.borrows}
              fill="url(#justlend-history-borrows)"
              strokeWidth={1.8}
            />
            <Area
              type="monotone"
              dataKey="reserveUsd"
              name="Reserves"
              stackId="marketSize"
              stroke={marketHistoryTheme.reserves}
              fill="url(#justlend-history-reserves)"
              strokeWidth={1.5}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div style={{ color: '#94a3b8', fontSize: '0.78rem', marginTop: '0.65rem' }}>
        注：JustLend 市场快照中 total_supply 通常接近 cash + total_borrows - total_reserves，本图将
        reserves 单独展示，避免误读资金构成。
      </div>
    </div>
  );
}

function JustLendUtilizationBorrowChart({ data }: { data: JustLendMarketHistoryPointView[] }) {
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <div className="card-header">
        <span className="card-title">利用率与借款利率</span>
        <span className="badge" style={justLendChartTheme.badge.success}>
          Compare
        </span>
      </div>
      <div style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 16, right: 18, left: 4, bottom: 8 }}>
            <defs>
              <linearGradient id="justlend-history-utilization" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={marketHistoryTheme.utilization} stopOpacity={0.34} />
                <stop offset="100%" stopColor={marketHistoryTheme.utilization} stopOpacity={0.04} />
              </linearGradient>
            </defs>
            <CartesianGrid
              stroke={marketHistoryTheme.grid}
              strokeDasharray="4 8"
              vertical={false}
            />
            <XAxis
              dataKey="timeLabel"
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={{ stroke: marketHistoryTheme.axisLine }}
              tickLine={false}
              minTickGap={28}
            />
            <YAxis
              yAxisId="utilization"
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => `${Number(value).toFixed(0)}%`}
            />
            <YAxis
              yAxisId="rate"
              orientation="right"
              tick={{ fill: marketHistoryTheme.axis, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value) => formatPercent(Number(value))}
            />
            <Tooltip
              cursor={false}
              contentStyle={marketTooltipContentStyle}
              labelStyle={marketTooltipLabelStyle}
              itemStyle={marketTooltipItemStyle}
              formatter={(value: unknown, name: string | number | undefined) => [
                formatPercent(Number(value ?? 0)),
                String(name ?? ''),
              ]}
            />
            <Legend
              iconType="circle"
              wrapperStyle={{ color: justLendChartTheme.legend.text, fontSize: 12, paddingTop: 8 }}
            />
            <Area
              yAxisId="utilization"
              type="monotone"
              dataKey="utilizationPct"
              name="Utilization"
              stroke={marketHistoryTheme.utilization}
              fill={marketHistoryTheme.utilizationFill}
              strokeWidth={1.8}
            />
            <Line
              yAxisId="rate"
              type="monotone"
              dataKey="borrowRatePct"
              name="Borrow Rate"
              stroke={marketHistoryTheme.borrowRateCompare}
              strokeWidth={2.4}
              dot={false}
              activeDot={{ r: 4 }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface JustLendMarketDashboardProps {
  markets: JustLendMarketItem[];
  selectedMarket: string;
  marketsLoading?: boolean;
  marketLoadError?: string;
}

export function JustLendMarketDashboard({
  markets,
  selectedMarket,
  marketsLoading = false,
  marketLoadError = '',
}: JustLendMarketDashboardProps) {
  const [marketState, setMarketState] = useState<JustLendMarketStateResponse | null>(null);
  const [loadingState, setLoadingState] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const [historyRange, setHistoryRange] = useState<MarketHistoryRange>('1M');
  const [historyData, setHistoryData] = useState<JustLendMarketHistoryPointView[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [historyMeta, setHistoryMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    if (!selectedMarket) return;
    let cancelled = false;

    const loadState = async () => {
      setLoadingState(true);
      setError('');
      try {
        const result = await fetchJustLendMarketStateWithMeta(selectedMarket);
        if (cancelled) return;
        setMarketState(result.data);
        setMeta((current) =>
          mergeRequestMetas([
            { fetchedAt: Date.now(), fromCache: current.cacheStatus === 'hit' },
            result.meta,
          ]),
        );
      } catch (loadError) {
        if (cancelled) return;
        setMarketState(null);
        setError(loadError instanceof Error ? loadError.message : '无法加载 JustLend 单市场状态');
      } finally {
        if (!cancelled) setLoadingState(false);
      }
    };

    void loadState();
    return () => {
      cancelled = true;
    };
  }, [selectedMarket]);

  useEffect(() => {
    if (!selectedMarket) {
      setHistoryData([]);
      return;
    }

    let cancelled = false;
    const { start, end } = getHistoryRangeBounds(historyRange);

    const loadHistory = async () => {
      setHistoryLoading(true);
      setHistoryError('');
      try {
        const result = await fetchJustLendMarketStatePeriodWithMeta({
          market: selectedMarket,
          start,
          end,
        });
        if (cancelled) return;

        const points = (result.data.points ?? [])
          .map(buildHistoryPoint)
          .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp));

        setHistoryData(points);
        setHistoryMeta(mergeRequestMetas([result.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setHistoryData([]);
        setHistoryError(loadError instanceof Error ? loadError.message : '无法加载历史市场状态');
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    };

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [historyRange, selectedMarket]);

  const selectedMarketItem = useMemo(
    () => markets.find((item) => item.market === selectedMarket) ?? null,
    [markets, selectedMarket],
  );

  const marketMetrics = useMemo(() => {
    if (!marketState) return null;
    const priceUsd = toNum(marketState.price_usd);
    const cash = toNum(marketState.cash);
    const totalBorrows = toNum(marketState.total_borrows);
    const totalReserves = toNum(marketState.total_reserves);
    const totalSupply = toNum(marketState.total_supply);
    const cashUsd = multiplyDecimalStrings(marketState.cash, marketState.price_usd);
    const borrowUsd = multiplyDecimalStrings(marketState.total_borrows, marketState.price_usd);
    const reserveUsd = multiplyDecimalStrings(marketState.total_reserves, marketState.price_usd);
    const supplyUsd = multiplyDecimalStrings(marketState.total_supply, marketState.price_usd);
    return {
      priceUsd,
      cash,
      totalBorrows,
      totalReserves,
      totalSupply,
      cashUsd,
      borrowUsd,
      reserveUsd,
      supplyUsd,
      utilizationPct: ratioToPercent(marketState.utilization),
      borrowRatePct: ratioToPercent(marketState.borrow_rate),
      supplyRatePct: ratioToPercent(marketState.supply_rate),
      collateralFactorPct: ratioToPercent(marketState.collateral_factor),
      reserveFactorPct: ratioToPercent(marketState.reserve_factor),
      borrowCap: toNum(marketState.borrow_cap),
      supplyCap: toNum(marketState.supply_cap),
      exchangeRate: toNum(marketState.exchange_rate),
      priceInTrx: toNum(marketState.underlying_price_in_trx),
    };
  }, [marketState]);

  const balanceCompositionData = useMemo(() => {
    if (!marketMetrics) return [];
    return [
      {
        name: 'Cash',
        value: marketMetrics.cashUsd,
        label: formatUsd(marketMetrics.cashUsd),
      },
      {
        name: 'Borrows',
        value: marketMetrics.borrowUsd,
        label: formatUsd(marketMetrics.borrowUsd),
      },
      {
        name: 'Reserves',
        value: marketMetrics.reserveUsd,
        label: formatUsd(marketMetrics.reserveUsd),
      },
    ];
  }, [marketMetrics]);

  const rateAndFactorData = useMemo(() => {
    if (!marketMetrics) return [];
    return [
      {
        name: 'Borrow Rate',
        value: marketMetrics.borrowRatePct,
        fill: justLendChartTheme.series.borrowRate,
      },
      {
        name: 'Supply Rate',
        value: marketMetrics.supplyRatePct,
        fill: justLendChartTheme.series.supplyRate,
      },
      {
        name: 'Utilization',
        value: marketMetrics.utilizationPct,
        fill: justLendChartTheme.series.utilization,
      },
      {
        name: 'Collateral Factor',
        value: marketMetrics.collateralFactorPct,
        fill: justLendChartTheme.series.collateralFactor,
      },
      {
        name: 'Reserve Factor',
        value: marketMetrics.reserveFactorPct,
        fill: justLendChartTheme.series.reserveFactor,
      },
    ];
  }, [marketMetrics]);

  const balanceDetails = useMemo(() => {
    if (!marketMetrics) return [];
    return [
      {
        name: 'Cash',
        color: marketPalette[0],
        primary: formatUsd(marketMetrics.cashUsd),
        secondary: `数量 ${formatRawAmount(marketMetrics.cash)}`,
      },
      {
        name: 'Borrows',
        color: marketPalette[1],
        primary: formatUsd(marketMetrics.borrowUsd),
        secondary: `数量 ${formatRawAmount(marketMetrics.totalBorrows)}`,
      },
      {
        name: 'Reserves',
        color: marketPalette[2],
        primary: formatUsd(marketMetrics.reserveUsd),
        secondary: `数量 ${formatRawAmount(marketMetrics.totalReserves)}`,
      },
    ];
  }, [marketMetrics]);

  const rateAndFactorDetails = useMemo(() => {
    if (!marketMetrics) return [];
    return [
      {
        name: 'Borrow Rate',
        color: justLendChartTheme.series.borrowRate,
        primary: formatPercent(marketMetrics.borrowRatePct),
        secondary: '当前借款利率',
      },
      {
        name: 'Supply Rate',
        color: justLendChartTheme.series.supplyRate,
        primary: formatPercent(marketMetrics.supplyRatePct),
        secondary: '当前供应利率',
      },
      {
        name: 'Utilization',
        color: justLendChartTheme.series.utilization,
        primary: formatPercent(marketMetrics.utilizationPct),
        secondary: '资金利用率',
      },
      {
        name: 'Collateral Factor',
        color: justLendChartTheme.series.collateralFactor,
        primary: formatPercent(marketMetrics.collateralFactorPct),
        secondary: '抵押系数',
      },
      {
        name: 'Reserve Factor',
        color: justLendChartTheme.series.reserveFactor,
        primary: formatPercent(marketMetrics.reserveFactorPct),
        secondary: '储备系数',
      },
    ];
  }, [marketMetrics]);

  if (marketsLoading) {
    return (
      <div
        className="card"
        style={{ minHeight: 360, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  if ((marketLoadError || error) && !marketState && !markets.length) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">JustLend 宏观市场评估</span>
          <span className="badge" style={justLendChartTheme.badge.danger}>
            Error
          </span>
        </div>
        <div className="justlend-banner justlend-banner-warn">
          <div className="justlend-banner-title">无法读取 JustLend 市场数据</div>
          <div className="justlend-banner-copy">{marketLoadError || error}</div>
        </div>
      </div>
    );
  }

  const summaryCards = marketMetrics
    ? [
        { label: '当前价格', value: formatUsd(marketMetrics.priceUsd), tone: 'blue' as const },
        {
          label: '利用率',
          value: formatPercent(marketMetrics.utilizationPct),
          tone: 'green' as const,
        },
        { label: '借款规模', value: formatUsd(marketMetrics.borrowUsd), tone: 'red' as const },
        { label: '可用现金', value: formatUsd(marketMetrics.cashUsd), tone: 'blue' as const },
        {
          label: '供应利率',
          value: formatPercent(marketMetrics.supplyRatePct),
          tone: 'green' as const,
        },
        {
          label: '借款利率',
          value: formatPercent(marketMetrics.borrowRatePct),
          tone: 'red' as const,
        },
      ]
    : [];

  const overviewMetaItems = [
    { label: '市场地址', value: selectedMarketItem?.market ?? '--', mono: true },
    { label: 'Underlying', value: marketState?.underlying_symbol ?? '--' },
    { label: '快照时间', value: marketState ? formatDateTime(marketState.timestamp) : '--' },
  ];

  return (
    <div className="justlend-market-board">
      <div className="card justlend-market-hero" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">JustLend 宏观市场评估</span>
            <span className="badge green-badge">{marketState?.chain?.toUpperCase() ?? 'TRON'}</span>
            <span className="badge" style={justLendChartTheme.badge.info}>
              {marketState?.protocol ?? 'trx'}
            </span>
            {selectedMarketItem ? (
              <span className="badge" style={justLendChartTheme.badge.success}>
                {marketLabel(selectedMarketItem)}
              </span>
            ) : null}
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div style={{ display: 'grid', gap: '0.9rem' }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'minmax(220px, 280px) minmax(0, 1fr)',
              gap: '1.25rem',
              alignItems: 'stretch',
            }}
          >
            <div
              style={{
                background: '#0f172a',
                border: `1px solid ${justLendChartTheme.grid}`,
                borderRadius: '16px',
                padding: '1rem 1.1rem',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                gap: '0.7rem',
                minHeight: '176px',
              }}
            >
              <div style={{ textAlign: 'center' }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.5rem',
                    marginBottom: '0.65rem',
                  }}
                >
                  <span className="card-title" style={{ fontSize: '1rem' }}>
                    {selectedMarketItem ? marketLabel(selectedMarketItem) : 'Market'} 实时价格
                  </span>
                  <span className="badge green-badge">Live</span>
                </div>
                <div className="metric-value blue" style={{ fontSize: '2rem' }}>
                  {marketMetrics ? formatUsd(marketMetrics.priceUsd) : '--'}
                </div>
                <div className="metric-label" style={{ marginTop: '0.35rem' }}>
                  {marketMetrics
                    ? `${marketMetrics.priceInTrx.toLocaleString(undefined, {
                        maximumFractionDigits: 6,
                      })} TRX`
                    : 'TRON Oracle Snapshot'}
                </div>
              </div>
            </div>

            <div
              style={{
                background: '#0b1220',
                border: `1px solid ${justLendChartTheme.grid}`,
                borderRadius: '16px',
                padding: '1rem 1.1rem',
                display: 'grid',
                gap: '0.9rem',
              }}
            >
              <div>
                <div className="justlend-market-kicker">Selected Market</div>
                <h2 className="justlend-market-title">
                  {selectedMarketItem
                    ? `${marketLabel(selectedMarketItem)} 当前状态`
                    : '请选择市场'}
                </h2>
                <p className="justlend-market-copy">
                  {marketState
                    ? `当前展示 ${marketState.underlying_symbol} 市场的最新状态快照，更新时间 ${formatDateTime(
                        marketState.timestamp,
                      )}。`
                    : '市场列表已加载，正在读取该市场的最新状态。'}
                </p>
              </div>

              <div className="justlend-overview-pills">
                {overviewMetaItems.map((item) => (
                  <div key={item.label} className="justlend-overview-pill">
                    <span className="justlend-overview-pill-label">{item.label}</span>
                    <span
                      className={`justlend-overview-pill-value ${item.mono ? 'mono' : ''}`}
                      title={item.value}
                      style={
                        item.mono
                          ? {
                              whiteSpace: 'normal',
                              overflow: 'visible',
                              textOverflow: 'unset',
                              wordBreak: 'break-all',
                            }
                          : undefined
                      }
                    >
                      {item.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {error && marketState ? (
            <div className="justlend-banner justlend-banner-warn">
              <div className="justlend-banner-title">读取最新市场状态时出现异常</div>
              <div className="justlend-banner-copy">{error}</div>
            </div>
          ) : null}
        </div>
      </div>

      {loadingState && !marketState ? (
        <div
          className="card"
          style={{
            minHeight: 320,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div className="spinner"></div>
        </div>
      ) : null}

      {marketState && marketMetrics ? (
        <>
          <div className="summary-grid protocol-summary-grid">
            {summaryCards.map((item) => (
              <div key={item.label} className="metric-box">
                <span className="metric-label">{item.label}</span>
                <span className={`metric-value ${item.tone}`}>{item.value}</span>
              </div>
            ))}
          </div>

          <div className="justlend-structure-grid">
            <div className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <span className="card-title">资金结构</span>
                <span className="badge" style={justLendChartTheme.badge.neutral}>
                  USD View
                </span>
              </div>
              <div style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={balanceCompositionData}
                    margin={{ top: 16, right: 18, left: 8, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={justLendChartTheme.grid} />
                    <XAxis
                      dataKey="name"
                      stroke={justLendChartTheme.axis.secondary}
                      tick={marketChartTick}
                    />
                    <YAxis
                      stroke={justLendChartTheme.axis.primary}
                      tick={marketChartTick}
                      tickFormatter={(value) => formatUsdCompact(Number(value))}
                    />
                    <Tooltip
                      cursor={false}
                      contentStyle={marketTooltipContentStyle}
                      labelStyle={marketTooltipLabelStyle}
                      itemStyle={marketTooltipItemStyle}
                      formatter={(value: unknown) => [formatUsd(Number(value ?? 0)), '金额']}
                    />
                    <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={46} activeBar={false}>
                      {balanceCompositionData.map((item, index) => (
                        <Cell key={item.name} fill={marketPalette[index % marketPalette.length]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="justlend-market-list">
                {balanceDetails.map((item) => (
                  <div key={item.name} className="justlend-allocation-item">
                    <div className="justlend-allocation-main">
                      <span className="justlend-risk-dot" style={{ background: item.color }} />
                      <span className="token-symbol">{item.name}</span>
                      <span className="justlend-allocation-share">{item.primary}</span>
                    </div>
                    <div className="justlend-allocation-meta">
                      <span className="mono">{item.secondary}</span>
                      <span className="mono">{item.primary}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <span className="card-title">利率与参数</span>
                <span className="badge" style={justLendChartTheme.badge.info}>
                  Snapshot
                </span>
              </div>
              <div style={{ height: 320 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={rateAndFactorData}
                    margin={{ top: 16, right: 18, left: 8, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke={justLendChartTheme.grid} />
                    <XAxis
                      dataKey="name"
                      stroke={justLendChartTheme.axis.secondary}
                      tick={marketChartTick}
                    />
                    <YAxis
                      stroke={justLendChartTheme.axis.primary}
                      tick={marketChartTick}
                      domain={[0, 100]}
                      tickFormatter={(value) => `${Number(value)}%`}
                    />
                    <Tooltip
                      cursor={false}
                      contentStyle={marketTooltipContentStyle}
                      labelStyle={marketTooltipLabelStyle}
                      itemStyle={marketTooltipItemStyle}
                      formatter={(value: unknown) => [formatPercent(Number(value ?? 0)), '当前值']}
                    />
                    <Bar dataKey="value" radius={[8, 8, 0, 0]} maxBarSize={34} activeBar={false}>
                      {rateAndFactorData.map((item) => (
                        <Cell key={item.name} fill={item.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div
                className="justlend-allocation-list"
                style={{
                  flexDirection: 'column',
                  gap: '0.6rem',
                  overflowX: 'hidden',
                  overflowY: 'auto',
                  maxHeight: '224px',
                  paddingRight: '0.25rem',
                  paddingBottom: 0,
                }}
              >
                {rateAndFactorDetails.map((item) => (
                  <div key={item.name} className="justlend-allocation-item">
                    <div className="justlend-allocation-main">
                      <span className="justlend-risk-dot" style={{ background: item.color }} />
                      <span className="token-symbol">{item.name}</span>
                      <span className="justlend-allocation-share">{item.primary}</span>
                    </div>
                    <div className="justlend-allocation-meta">
                      <span>{item.secondary}</span>
                      <span className="mono">{item.primary}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div>
            <div className="card" style={{ marginBottom: 0 }}>
              <div className="card-header">
                <span className="card-title">市场参数面板</span>
                <span className="badge" style={justLendChartTheme.badge.neutral}>
                  Params
                </span>
              </div>
              <div className="summary-grid protocol-summary-grid" style={{ marginTop: 0 }}>
                <div className="metric-box">
                  <span className="metric-label">Collateral Factor</span>
                  <span className="metric-value green">
                    {formatPercent(marketMetrics.collateralFactorPct)}
                  </span>
                </div>
                <div className="metric-box">
                  <span className="metric-label">Reserve Factor</span>
                  <span className="metric-value red">
                    {formatPercent(marketMetrics.reserveFactorPct)}
                  </span>
                </div>
                <div className="metric-box">
                  <span className="metric-label">Exchange Rate</span>
                  <span
                    className="metric-value blue"
                    style={{
                      fontSize: '0.84rem',
                      lineHeight: 1.35,
                      wordBreak: 'break-all',
                      whiteSpace: 'normal',
                    }}
                  >
                    {marketMetrics.exchangeRate.toLocaleString(undefined, {
                      maximumFractionDigits: 12,
                    })}
                  </span>
                </div>
                <div className="metric-box">
                  <span className="metric-label">Price In TRX</span>
                  <span className="metric-value">
                    {marketMetrics.priceInTrx.toLocaleString(undefined, {
                      maximumFractionDigits: 6,
                    })}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div className="card" style={{ marginBottom: 0 }}>
            <div
              className="card-header"
              style={{ alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                <span className="card-title">历史市场状态</span>
                <span className="badge" style={justLendChartTheme.badge.info}>
                  Period
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <ChartDataStatus meta={historyMeta} />
                <div className="switch-group" aria-label="JustLend market history range">
                  {(['1D', '7D', '1M', 'ALL'] as const).map((range) => {
                    const active = historyRange === range;
                    return (
                      <button
                        key={range}
                        type="button"
                        onClick={() => setHistoryRange(range)}
                        className={`switch-btn ${active ? 'active' : ''}`}
                      >
                        {range}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
            <div className="justlend-market-copy" style={{ marginBottom: '1rem' }}>
              基于当前所选市场的历史快照，观察利率、资金规模与利用率变化。
            </div>

            <HistoryChartState
              loading={historyLoading}
              error={historyError}
              empty={historyData.length === 0}
            />

            {!historyLoading && !historyError && historyData.length > 0 ? (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
                  gap: '1rem',
                  alignItems: 'stretch',
                }}
              >
                <JustLendRateHistoryChart data={historyData} />
                <JustLendUtilizationBorrowChart data={historyData} />
                <div style={{ gridColumn: '1 / -1' }}>
                  <JustLendMarketScaleHistoryChart data={historyData} />
                </div>
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </div>
  );
}
