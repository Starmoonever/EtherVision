import { useEffect, useMemo, useState } from 'react';
import {
  fetchJustLendMarketsWithMeta,
  fetchJustLendMarketStateWithMeta,
  type JustLendMarketItem,
} from '../../../api/justlend';
import { JustLendMarketDashboard } from '../../../components/JustLendMarketDashboard';
import { JustLendPositionAnalysis } from '../../../components/JustLendPositionAnalysis';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';

const FEATURED_MARKETS = ['USDT', 'TRX', 'STRX'];
type JustLendMarketViewMode = 'market' | 'position';

function normalizeSymbol(value: string | null | undefined): string {
  return value?.trim().toUpperCase() ?? '';
}

function marketButtonLabel(item: JustLendMarketItem, markets: JustLendMarketItem[]): string {
  const base = item.underlying_symbol || item.symbol || item.market;
  const normalizedBase = normalizeSymbol(item.underlying_symbol || item.symbol);
  if (!normalizedBase) return base;

  const duplicateCount = markets.filter(
    (candidate) =>
      normalizeSymbol(candidate.underlying_symbol || candidate.symbol) === normalizedBase,
  ).length;

  if (duplicateCount > 1 && item.symbol && normalizeSymbol(item.symbol) !== normalizedBase) {
    return `${base} · ${item.symbol}`;
  }

  return base;
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function estimateMarketBorrowUsd(totalBorrows: string, priceUsd: string): number {
  return toNum(totalBorrows) * toNum(priceUsd);
}

function formatBorrowTitle(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return 'Borrow unavailable';
  return `Borrow ${Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    notation: 'compact',
    maximumFractionDigits: 2,
  }).format(value)}`;
}

export function JustLendMarketPage() {
  const [markets, setMarkets] = useState<JustLendMarketItem[]>([]);
  const [selectedMarket, setSelectedMarket] = useState('');
  const [showMore, setShowMore] = useState(false);
  const [loadingMarkets, setLoadingMarkets] = useState(false);
  const [marketLoadError, setMarketLoadError] = useState('');
  const [marketBorrowUsd, setMarketBorrowUsd] = useState<Record<string, number>>({});
  const [viewMode, setViewMode] = useState<JustLendMarketViewMode>(() => {
    if (typeof window === 'undefined') return 'market';
    const tab = new URLSearchParams(window.location.search).get('tab');
    return tab === 'position' ? 'position' : 'market';
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (viewMode === 'position') {
      url.searchParams.set('tab', 'position');
    } else {
      url.searchParams.delete('tab');
    }
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`);
  }, [viewMode]);

  useEffect(() => {
    let cancelled = false;

    const loadMarkets = async () => {
      setLoadingMarkets(true);
      setMarketLoadError('');
      try {
        const result = await fetchJustLendMarketsWithMeta();
        if (cancelled) return;
        const nextMarkets = result.data.markets ?? [];
        setMarkets(nextMarkets);

        if (!nextMarkets.length) {
          setSelectedMarket('');
          return;
        }

        const preferred = FEATURED_MARKETS.find((symbol) =>
          nextMarkets.some((item) => normalizeSymbol(item.underlying_symbol) === symbol),
        );
        const defaultMarket =
          nextMarkets.find((item) => normalizeSymbol(item.underlying_symbol) === preferred)
            ?.market ?? nextMarkets[0]?.market;
        setSelectedMarket((current) => current || defaultMarket || '');
      } catch (error) {
        if (cancelled) return;
        setMarketLoadError(error instanceof Error ? error.message : '无法加载 JustLend 市场列表');
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
    if (!markets.length) {
      setMarketBorrowUsd({});
      return;
    }

    let cancelled = false;

    const loadBorrowUsd = async () => {
      const entries = await Promise.all(
        markets.map(async (market) => {
          try {
            const result = await fetchJustLendMarketStateWithMeta(market.market);
            return [
              market.market,
              estimateMarketBorrowUsd(result.data.total_borrows, result.data.price_usd),
            ] as const;
          } catch {
            return [market.market, 0] as const;
          }
        }),
      );

      if (!cancelled) {
        setMarketBorrowUsd(Object.fromEntries(entries));
      }
    };

    void loadBorrowUsd();
    return () => {
      cancelled = true;
    };
  }, [markets]);

  const featuredMarkets = useMemo(() => {
    return FEATURED_MARKETS.map((symbol) =>
      markets.find((item) => normalizeSymbol(item.underlying_symbol) === symbol),
    ).filter((item): item is JustLendMarketItem => Boolean(item));
  }, [markets]);

  const selectorMarkets = useMemo(() => {
    return featuredMarkets;
  }, [featuredMarkets]);

  const moreMarkets = useMemo(() => {
    const featuredSet = new Set(featuredMarkets.map((item) => item.market));
    return markets
      .filter((item) => !featuredSet.has(item.market))
      .sort((a, b) => {
        const borrowDiff = (marketBorrowUsd[b.market] ?? 0) - (marketBorrowUsd[a.market] ?? 0);
        if (Math.abs(borrowDiff) > 0.000001) return borrowDiff;
        return (a.underlying_symbol || a.symbol || a.market).localeCompare(
          b.underlying_symbol || b.symbol || b.market,
        );
      });
  }, [featuredMarkets, marketBorrowUsd, markets]);

  return (
    <>
      <PageHero
        title="JustLend 宏观市场评估"
        subtitle="JustLend 市场规模、流动性、利率参数与风险状态综合分析"
        controls={
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '0.85rem',
            }}
          >
            <SegmentedControl
              ariaLabel="JustLend market view mode"
              value={viewMode}
              onChange={setViewMode}
              options={[
                {
                  value: 'market',
                  label: '市场宏观',
                },
                {
                  value: 'position',
                  label: '大户/风险仓位',
                  activeClassName: 'active-purple',
                },
              ]}
            />

            {viewMode === 'market' ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {selectorMarkets.length ? (
                  <SegmentedControl
                    ariaLabel="JustLend market selector"
                    value={selectedMarket}
                    onChange={setSelectedMarket}
                    options={selectorMarkets.map((item) => ({
                      value: item.market,
                      label: marketButtonLabel(item, markets),
                      title: `${item.symbol || item.market} · ${formatBorrowTitle(marketBorrowUsd[item.market] ?? 0)}`,
                    }))}
                  />
                ) : null}
                {moreMarkets.length ? (
                  <button
                    type="button"
                    onClick={() => setShowMore((value) => !value)}
                    className="switch-btn"
                    style={{
                      marginLeft: selectorMarkets.length ? '1rem' : 0,
                      border: '1px solid var(--border-strong)',
                      background: showMore ? 'var(--accent-primary)' : 'var(--surface-muted)',
                      color: showMore ? 'var(--text-strong)' : 'var(--text-muted)',
                    }}
                  >
                    More
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        }
      />

      {viewMode === 'market' && showMore && moreMarkets.length ? (
        <div
          className="hero-switch"
          style={{
            marginTop: '-0.5rem',
            marginBottom: '1rem',
            overflowX: 'auto',
            justifyContent: 'center',
            scrollbarWidth: 'thin',
          }}
          onWheel={(event) => {
            event.currentTarget.scrollLeft += event.deltaY;
          }}
        >
          <SegmentedControl
            ariaLabel="JustLend more markets"
            value={selectedMarket}
            onChange={setSelectedMarket}
            options={moreMarkets.map((item) => ({
              value: item.market,
              label: marketButtonLabel(item, markets),
              title: `${item.symbol || item.market} · ${formatBorrowTitle(marketBorrowUsd[item.market] ?? 0)}`,
            }))}
          />
        </div>
      ) : null}

      {viewMode === 'market' ? (
        <JustLendMarketDashboard
          markets={markets}
          selectedMarket={selectedMarket}
          marketsLoading={loadingMarkets}
          marketLoadError={marketLoadError}
        />
      ) : (
        <JustLendPositionAnalysis markets={markets} />
      )}
    </>
  );
}
