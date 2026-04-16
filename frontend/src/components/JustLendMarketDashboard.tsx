import { useEffect, useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  fetchJustLendMarketsWithMeta,
  fetchJustLendMarketStateWithMeta,
  type JustLendMarketItem,
  type JustLendMarketStateResponse,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus } from './ChartAssist';
import { justLendChartTheme } from './justlendTheme';

const FEATURED_MARKETS = ['BTT', 'NFT', 'WIN', 'TRX', 'STRX'];
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

function formatDateTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return value;
  return new Date(parsed).toLocaleString();
}

function marketLabel(item: JustLendMarketItem): string {
  return item.underlying_symbol || item.symbol || item.market.slice(0, 6);
}

function formatAddress(value: string): string {
  if (!value) return '--';
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function normalizeMarketSymbol(value: string): string {
  return value.trim().toUpperCase();
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

export function JustLendMarketDashboard() {
  const [markets, setMarkets] = useState<JustLendMarketItem[]>([]);
  const [selectedMarket, setSelectedMarket] = useState<string>('');
  const [marketState, setMarketState] = useState<JustLendMarketStateResponse | null>(null);
  const [showMore, setShowMore] = useState(false);
  const [loadingMarkets, setLoadingMarkets] = useState(false);
  const [loadingState, setLoadingState] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    let cancelled = false;

    const loadMarkets = async () => {
      setLoadingMarkets(true);
      setError('');
      try {
        const result = await fetchJustLendMarketsWithMeta();
        if (cancelled) return;
        const nextMarkets = result.data.markets ?? [];
        setMarkets(nextMarkets);
        setMeta(mergeRequestMetas([result.meta]));

        if (!nextMarkets.length) {
          setSelectedMarket('');
          return;
        }

        const preferred = FEATURED_MARKETS.find((symbol) =>
          nextMarkets.some((item) => normalizeMarketSymbol(item.underlying_symbol) === symbol),
        );
        const defaultMarket =
          nextMarkets.find((item) => normalizeMarketSymbol(item.underlying_symbol) === preferred)
            ?.market ?? nextMarkets[0]?.market;
        setSelectedMarket((current) => current || defaultMarket || '');
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : '无法加载 JustLend 市场列表');
      } finally {
        if (!cancelled) setLoadingMarkets(false);
      }
    };

    void loadMarkets();
    return () => {
      cancelled = true;
    };
  }, []);

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

  const featuredMarkets = useMemo(() => {
    return FEATURED_MARKETS.map((symbol) =>
      markets.find((item) => normalizeMarketSymbol(item.underlying_symbol) === symbol),
    ).filter((item): item is JustLendMarketItem => Boolean(item));
  }, [markets]);

  const moreMarkets = useMemo(() => {
    const featuredSet = new Set(featuredMarkets.map((item) => item.market));
    return markets
      .filter((item) => !featuredSet.has(item.market))
      .sort((a, b) => marketLabel(a).localeCompare(marketLabel(b)));
  }, [featuredMarkets, markets]);

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

  if (loadingMarkets) {
    return (
      <div
        className="card"
        style={{ minHeight: 360, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  if (error && !marketState && !markets.length) {
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
          <div className="justlend-banner-copy">{error}</div>
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
          <div style={{ display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
            {featuredMarkets.map((item, index) => {
              const active = item.market === selectedMarket;
              return (
                <button
                  key={item.market}
                  type="button"
                  onClick={() => setSelectedMarket(item.market)}
                  style={{
                    borderRadius: '999px',
                    border: `1px solid ${
                      active
                        ? marketPalette[index % marketPalette.length]
                        : justLendChartTheme.controls.baseBorder
                    }`,
                    background: active
                      ? marketPalette[index % marketPalette.length]
                      : justLendChartTheme.controls.baseBackground,
                    color: active
                      ? justLendChartTheme.controls.activeText
                      : justLendChartTheme.controls.baseText,
                    padding: '0.42rem 0.9rem',
                    cursor: 'pointer',
                    fontSize: '0.83rem',
                  }}
                >
                  {marketLabel(item)}
                </button>
              );
            })}
            {moreMarkets.length ? (
              <button
                type="button"
                onClick={() => setShowMore((value) => !value)}
                style={{
                  borderRadius: '999px',
                  border: `1px solid ${justLendChartTheme.controls.baseBorder}`,
                  background: showMore
                    ? justLendChartTheme.controls.infoBackground
                    : justLendChartTheme.controls.baseBackground,
                  color: justLendChartTheme.tooltip.text,
                  padding: '0.42rem 0.9rem',
                  cursor: 'pointer',
                  fontSize: '0.83rem',
                }}
              >
                More
              </button>
            ) : null}
          </div>

          {showMore && moreMarkets.length ? (
            <div
              style={{
                display: 'flex',
                gap: '0.55rem',
                overflowX: 'auto',
                paddingBottom: '0.2rem',
                scrollbarWidth: 'thin',
              }}
              onWheel={(event) => {
                event.currentTarget.scrollLeft += event.deltaY;
              }}
            >
              {moreMarkets.map((item) => {
                const active = item.market === selectedMarket;
                return (
                  <button
                    key={item.market}
                    type="button"
                    onClick={() => setSelectedMarket(item.market)}
                    style={{
                      flex: '0 0 auto',
                      borderRadius: '999px',
                      border: `1px solid ${
                        active
                          ? justLendChartTheme.controls.marketMoreActiveBackground
                          : justLendChartTheme.controls.baseBorder
                      }`,
                      background: active
                        ? justLendChartTheme.controls.marketMoreActiveBackground
                        : justLendChartTheme.controls.baseBackground,
                      color: active
                        ? justLendChartTheme.controls.marketMoreActiveText
                        : justLendChartTheme.controls.baseText,
                      padding: '0.4rem 0.85rem',
                      cursor: 'pointer',
                      fontSize: '0.8rem',
                    }}
                  >
                    {marketLabel(item)}
                  </button>
                );
              })}
            </div>
          ) : null}

          <div className="justlend-banner justlend-banner-soft">
            <div className="justlend-banner-title">当前只展示单市场最新状态</div>
            <div className="justlend-banner-copy">
              这版先聚焦“当前市场快照”，帮助你判断该市场此刻的规模、流动性、利用率、利率与参数边界。
            </div>
          </div>

          <div className="justlend-market-hero-grid">
            <div>
              <div className="justlend-market-kicker">Selected Market</div>
              <h2 className="justlend-market-title">
                {selectedMarketItem ? `${marketLabel(selectedMarketItem)} 当前状态` : '请选择市场'}
              </h2>
              <p className="justlend-market-copy">
                {marketState
                  ? `当前展示 ${marketState.underlying_symbol} 市场的最新状态快照，更新时间 ${formatDateTime(marketState.timestamp)}。`
                  : '市场列表已加载，正在读取该市场的最新状态。'}
              </p>
            </div>

            <div className="justlend-market-summary-grid">
              <div className="metric-box">
                <span className="metric-label">市场地址</span>
                <span className="metric-value">
                  {selectedMarketItem ? formatAddress(selectedMarketItem.market) : '--'}
                </span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Underlying</span>
                <span className="metric-value blue">{marketState?.underlying_symbol ?? '--'}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">最后更新</span>
                <span className="metric-value">
                  {marketState ? formatDateTime(marketState.timestamp) : '--'}
                </span>
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
                <div className="justlend-market-list-item">
                  <span className="check-dot dot-ok" />
                  <span>Cash: {formatUsd(marketMetrics.cashUsd)}</span>
                </div>
                <div className="justlend-market-list-item">
                  <span className="check-dot dot-ok" />
                  <span>Total Borrows: {formatUsd(marketMetrics.borrowUsd)}</span>
                </div>
                <div className="justlend-market-list-item">
                  <span className="check-dot dot-ok" />
                  <span>Total Reserves: {formatUsd(marketMetrics.reserveUsd)}</span>
                </div>
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
                    <Legend wrapperStyle={{ color: justLendChartTheme.legend.text }} />
                    <Bar
                      dataKey="value"
                      name="当前值"
                      radius={[8, 8, 0, 0]}
                      maxBarSize={34}
                      activeBar={false}
                    >
                      {rateAndFactorData.map((item) => (
                        <Cell key={item.name} fill={item.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
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
                  <span className="metric-value blue">
                    {marketMetrics.exchangeRate.toLocaleString(undefined, {
                      maximumFractionDigits: 6,
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
