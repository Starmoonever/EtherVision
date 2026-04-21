import { useEffect, useMemo, useState } from 'react';
import { fetchJustLendMarketsWithMeta, type JustLendMarketItem } from '../../../api/justlend';
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

function buildMarketHint(item: JustLendMarketItem): string {
  return item.symbol || item.market;
}

export function JustLendMarketPage() {
  const [markets, setMarkets] = useState<JustLendMarketItem[]>([]);
  const [selectedMarket, setSelectedMarket] = useState('');
  const [showMore, setShowMore] = useState(false);
  const [loadingMarkets, setLoadingMarkets] = useState(false);
  const [marketLoadError, setMarketLoadError] = useState('');
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
      .sort((a, b) =>
        (a.underlying_symbol || a.symbol || a.market).localeCompare(
          b.underlying_symbol || b.symbol || b.market,
        ),
      );
  }, [featuredMarkets, markets]);

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
                      title: buildMarketHint(item),
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
              title: buildMarketHint(item),
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
