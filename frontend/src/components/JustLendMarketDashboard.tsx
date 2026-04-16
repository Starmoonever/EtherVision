import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchJustLendMarketStateWithMeta,
  type JustLendMarketItem,
  type JustLendMarketStateResponse,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus } from './ChartAssist';
import { justLendChartTheme } from './justlendTheme';

const marketPalette = justLendChartTheme.palettes.market;

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
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

function marketLabel(item: JustLendMarketItem): string {
  return item.underlying_symbol || item.symbol || item.market.slice(0, 6);
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
    const cashUsd = cash * priceUsd;
    const borrowUsd = totalBorrows * priceUsd;
    const reserveUsd = totalReserves * priceUsd;
    const supplyUsd = totalSupply * priceUsd;
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
                  <span className="metric-label">Borrow Cap</span>
                  <span className="metric-value">{marketMetrics.borrowCap.toLocaleString()}</span>
                </div>
                <div className="metric-box">
                  <span className="metric-label">Supply Cap</span>
                  <span className="metric-value">{marketMetrics.supplyCap.toLocaleString()}</span>
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
        </>
      ) : null}
    </div>
  );
}
