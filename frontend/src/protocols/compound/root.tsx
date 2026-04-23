import { useEffect, useMemo, useState } from 'react';
import { fetchCompoundMarkets, fetchCompoundUserPosition } from '../../api/compound';
import type { CompoundMarket, CompoundUserPositionItem } from '../../api/compound';
import type { ProtocolRootProps } from '../../shared/types/app';
import { CompoundMarketPage } from './pages/CompoundMarketPage';
import { CompoundPersonalPage } from './pages/CompoundPersonalPage';

interface CompoundVersionState {
  data: CompoundUserPositionItem[] | null;
  loading: boolean;
  notFound: boolean;
}

type CompoundCacheEntry =
  | { kind: 'data'; data: CompoundUserPositionItem[] }
  | { kind: 'not_found' };

const COMPOUND_V2_PERSONAL_MARKETS = new Set(['ceth', 'cwbtc', 'cusdt', 'cdai']);
const emptyCompoundState = (): CompoundVersionState => ({
  data: null,
  loading: false,
  notFound: false,
});

const compoundPositionCache = new Map<string, CompoundCacheEntry>();

function getVisibleCompoundMarkets(
  activeTab: 'personal' | 'market',
  version: 'v2' | 'v3',
  marketsVersion: 'v2' | 'v3' | null,
  markets: CompoundMarket[],
): CompoundMarket[] {
  if (marketsVersion !== version) return [];
  if (activeTab === 'personal' && version === 'v2') {
    return markets.filter((item) => COMPOUND_V2_PERSONAL_MARKETS.has(item.symbol.toLowerCase()));
  }
  return markets;
}

const compoundCacheKey = (address: string, market: string, version: string) =>
  `${version}:${address.toLowerCase()}:${market.toLowerCase()}`;

export function CompoundProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3'>('v3');
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3');
  const [compoundMarkets, setCompoundMarkets] = useState<CompoundMarket[]>([]);
  const [compoundMarketsVersion, setCompoundMarketsVersion] = useState<'v2' | 'v3' | null>(null);
  const [compoundMarket, setCompoundMarket] = useState<string>('all');
  const [compoundAddress, setCompoundAddress] = useState('');
  const [compoundState, setCompoundState] = useState<CompoundVersionState>(emptyCompoundState());

  const activeCompoundMarketsVersion = activeTab === 'personal' ? personalVersion : marketVersion;
  const visibleMarkets = useMemo(
    () =>
      getVisibleCompoundMarkets(
        activeTab,
        activeCompoundMarketsVersion,
        compoundMarketsVersion,
        compoundMarkets,
      ),
    [activeCompoundMarketsVersion, activeTab, compoundMarkets, compoundMarketsVersion],
  );

  const selectedMarketSymbol = useMemo(
    () =>
      compoundMarket === 'all'
        ? 'all'
        : (visibleMarkets.find((item) => item.address === compoundMarket)?.symbol ??
          compoundMarket),
    [compoundMarket, visibleMarkets],
  );

  useEffect(() => {
    setCompoundState(emptyCompoundState());
  }, [compoundAddress, compoundMarket]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;

    const loadCompoundMarkets = async () => {
      try {
        const version = activeCompoundMarketsVersion;
        setCompoundMarketsVersion(null);
        setCompoundMarkets([]);
        const markets = await fetchCompoundMarkets(version);
        const nextVisible = getVisibleCompoundMarkets(activeTab, version, version, markets);

        if (cancelled) return;

        setCompoundMarkets(markets);
        setCompoundMarketsVersion(version);
        setCompoundMarket((currentMarket) => {
          if (activeTab === 'personal') {
            if (currentMarket === 'all') return 'all';
            if (!nextVisible.find((item) => item.address === currentMarket)) {
              return nextVisible[0]?.address ?? 'all';
            }
            return currentMarket;
          }

          if (!nextVisible.find((item) => item.address === currentMarket)) {
            return nextVisible[0]?.address ?? currentMarket;
          }
          return currentMarket;
        });
      } catch (loadError) {
        console.error(loadError);
        setError('无法加载 Compound 市场列表');
      }
    };

    void loadCompoundMarkets();
    return () => {
      cancelled = true;
    };
  }, [active, activeCompoundMarketsVersion, activeTab]);

  useEffect(() => {
    if (!active || !compoundAddress || activeTab !== 'personal') return;

    const loadCompound = async () => {
      setError('');

      const cacheKey = compoundCacheKey(compoundAddress, compoundMarket, personalVersion);
      const cached = compoundPositionCache.get(cacheKey);
      if (cached) {
        if (cached.kind === 'not_found') {
          setCompoundState({ data: null, loading: false, notFound: true });
          return;
        }
        setCompoundState({ data: cached.data, loading: false, notFound: false });
        return;
      }

      setCompoundState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        const response = await fetchCompoundUserPosition(
          personalVersion,
          compoundMarket,
          compoundAddress,
        );
        if (response.positions && response.positions.length > 0) {
          const positions = response.positions;

          if (compoundMarket === 'all') {
            const foundMarkets = new Set<string>();
            for (const item of positions) {
              compoundPositionCache.set(
                compoundCacheKey(compoundAddress, item.market, personalVersion),
                {
                  kind: 'data',
                  data: [item],
                },
              );
              foundMarkets.add(item.market.toLowerCase());
            }

            for (const item of compoundMarkets) {
              if (!foundMarkets.has(item.address.toLowerCase())) {
                compoundPositionCache.set(
                  compoundCacheKey(compoundAddress, item.address, personalVersion),
                  { kind: 'not_found' },
                );
              }
            }
          }

          compoundPositionCache.set(cacheKey, { kind: 'data', data: positions });
          setCompoundState({ data: positions, loading: false, notFound: false });
          return;
        }

        if (compoundMarket === 'all') {
          compoundPositionCache.set(cacheKey, { kind: 'data', data: [] });
          setCompoundState({ data: [], loading: false, notFound: false });
        } else {
          compoundPositionCache.set(cacheKey, { kind: 'not_found' });
          setCompoundState({ data: null, loading: false, notFound: true });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          if (compoundMarket === 'all') {
            compoundPositionCache.set(cacheKey, { kind: 'data', data: [] });
            setCompoundState({ data: [], loading: false, notFound: false });
          } else {
            compoundPositionCache.set(cacheKey, { kind: 'not_found' });
            setCompoundState({ data: null, loading: false, notFound: true });
          }
          return;
        }

        setCompoundState({ data: null, loading: false, notFound: false });
        console.error(loadError);
      }
    };

    void loadCompound();
  }, [active, activeTab, compoundAddress, compoundMarket, compoundMarkets, personalVersion]);

  if (!active) return null;

  return activeTab === 'personal' ? (
    <CompoundPersonalPage
      personalVersion={personalVersion}
      visibleMarkets={visibleMarkets}
      selectedMarketSymbol={selectedMarketSymbol}
      compoundMarket={compoundMarket}
      compoundAddress={compoundAddress}
      compoundState={compoundState}
      error={error}
      onSearch={(address) => {
        setError('');
        setCompoundAddress(address);
      }}
      onVersionChange={setPersonalVersion}
      onMarketChange={setCompoundMarket}
    />
  ) : (
    <CompoundMarketPage
      marketVersion={marketVersion}
      visibleMarkets={visibleMarkets}
      compoundMarket={
        compoundMarket === 'all' ? (visibleMarkets[0]?.address ?? 'all') : compoundMarket
      }
      onVersionChange={setMarketVersion}
      onMarketChange={setCompoundMarket}
    />
  );
}
