import { useEffect, useMemo, useState } from 'react';
import { fetchJustLendMarketsWithMeta, type JustLendMarketItem } from '../../../api/justlend';
import { JustLendMarketDashboard } from '../../../components/JustLendMarketDashboard';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';

const FEATURED_MARKETS = ['BTT', 'NFT', 'WIN', 'TRX', 'STRX'];

export function JustLendMarketPage() {
  const [markets, setMarkets] = useState<JustLendMarketItem[]>([]);
  const [selectedMarket, setSelectedMarket] = useState('');
  const [showMore, setShowMore] = useState(false);
  const [loadingMarkets, setLoadingMarkets] = useState(false);
  const [marketLoadError, setMarketLoadError] = useState('');

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
          nextMarkets.some((item) => item.underlying_symbol?.trim().toUpperCase() === symbol),
        );
        const defaultMarket =
          nextMarkets.find((item) => item.underlying_symbol?.trim().toUpperCase() === preferred)
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
      markets.find((item) => item.underlying_symbol?.trim().toUpperCase() === symbol),
    ).filter((item): item is JustLendMarketItem => Boolean(item));
  }, [markets]);

  const selectorMarkets = useMemo(() => {
    const base = [...featuredMarkets];
    const selected = markets.find((item) => item.market === selectedMarket);
    if (selected && !base.some((item) => item.market === selected.market)) {
      base.push(selected);
    }
    return base;
  }, [featuredMarkets, markets, selectedMarket]);

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
          <>
            {selectorMarkets.length ? (
              <SegmentedControl
                ariaLabel="JustLend market selector"
                value={selectedMarket}
                onChange={setSelectedMarket}
                options={selectorMarkets.map((item) => ({
                  value: item.market,
                  label: item.underlying_symbol || item.symbol,
                  title: item.symbol || item.market,
                }))}
              />
            ) : null}
            {moreMarkets.length ? (
              <button
                type="button"
                onClick={() => setShowMore((value) => !value)}
                className="switch-btn"
                style={{
                  border: '1px solid var(--border-strong)',
                  background: showMore ? 'var(--accent-primary)' : 'var(--surface-muted)',
                  color: showMore ? 'var(--text-strong)' : 'var(--text-muted)',
                }}
              >
                More
              </button>
            ) : null}
          </>
        }
      />

      {showMore && moreMarkets.length ? (
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
              label: item.underlying_symbol || item.symbol,
              title: item.symbol || item.market,
            }))}
          />
        </div>
      ) : null}

      <JustLendMarketDashboard
        markets={markets}
        selectedMarket={selectedMarket}
        marketsLoading={loadingMarkets}
        marketLoadError={marketLoadError}
      />
    </>
  );
}
