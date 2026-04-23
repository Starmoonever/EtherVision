import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import {
  fetchMorphoMarketStateWithMeta,
  type MorphoMarketConfig,
  type MorphoMarketSortField,
  type MorphoMarketSortOrder,
} from '../../../api/morpho';
import { fetchAssetPrice } from '../../../api/price';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';
import {
  mergeMorphoMarketData,
  useMorphoData,
  type MorphoMarketView,
} from '../../../hooks/useMorphoData';
import { MorphoMarketTable, type MorphoSortMode } from '../components/MorphoMarketTable';

const MORPHO_MARKETS_PAGE_SIZE = 10;
type MorphoMarketViewMode = 'mainstream' | 'query';

function isMorphoMarketId(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

function createMarketConfigFromId(marketId: string): MorphoMarketConfig {
  return {
    market_id: marketId,
    collateral_symbol: null,
    loan_symbol: null,
    collateral_token_address: null,
    loan_token_address: null,
    collateral_decimals: null,
    loan_decimals: null,
    lltv: null,
    oracle: null,
    irm: null,
    pair: null,
    total_market_size_usd: null,
    utilization: null,
  };
}

async function enrichMarketTokenPrices(market: MorphoMarketView): Promise<MorphoMarketView> {
  const loanPriceAsset = market.loan_token_address || market.loan_symbol;
  const collateralPriceAsset = market.collateral_token_address || market.collateral_symbol;

  const [loanTokenPriceUsd, collateralTokenPriceUsd] = await Promise.all([
    loanPriceAsset
      ? fetchAssetPrice(loanPriceAsset, { chain: 'ethereum' }).catch(() => null)
      : Promise.resolve(null),
    collateralPriceAsset
      ? fetchAssetPrice(collateralPriceAsset, { chain: 'ethereum' }).catch(() => null)
      : Promise.resolve(null),
  ]);

  return {
    ...market,
    loan_token_price_usd: loanTokenPriceUsd === null ? null : String(loanTokenPriceUsd),
    collateral_token_price_usd:
      collateralTokenPriceUsd === null ? null : String(collateralTokenPriceUsd),
  };
}

function resolveMarketSortParams(sortMode: MorphoSortMode): {
  sortBy?: MorphoMarketSortField;
  sortOrder?: MorphoMarketSortOrder;
} {
  if (sortMode === 'loanSymbolAsc') return { sortBy: 'loan_symbol', sortOrder: 'asc' };
  if (sortMode === 'loanSymbolDesc') return { sortBy: 'loan_symbol', sortOrder: 'desc' };
  if (sortMode === 'collateralSymbolAsc') {
    return { sortBy: 'collateral_symbol', sortOrder: 'asc' };
  }
  if (sortMode === 'collateralSymbolDesc') {
    return { sortBy: 'collateral_symbol', sortOrder: 'desc' };
  }
  if (sortMode === 'totalMarketSizeAsc') {
    return { sortBy: 'total_market_size_usd', sortOrder: 'asc' };
  }
  if (sortMode === 'totalMarketSizeDesc') {
    return { sortBy: 'total_market_size_usd', sortOrder: 'desc' };
  }
  if (sortMode === 'utilizationAsc') return { sortBy: 'utilization', sortOrder: 'asc' };
  if (sortMode === 'utilizationDesc') return { sortBy: 'utilization', sortOrder: 'desc' };
  return {};
}

export function MorphoMarketPage() {
  const [activeView, setActiveView] = useState<MorphoMarketViewMode>('mainstream');
  const [marketPage, setMarketPage] = useState(1);
  const [sortMode, setSortMode] = useState<MorphoSortMode>('default');
  const [marketFilters, setMarketFilters] = useState({ loan: '', collateral: '' });
  const sortParams = useMemo(() => resolveMarketSortParams(sortMode), [sortMode]);
  const {
    markets,
    marketCount,
    loading,
    error,
    fetchedAt,
    fromCache,
    reload,
    totalPages: totalMarketPages,
  } = useMorphoData({
    page: marketPage,
    pageSize: MORPHO_MARKETS_PAGE_SIZE,
    sortBy: sortParams.sortBy,
    sortOrder: sortParams.sortOrder,
    loan: marketFilters.loan,
    collateral: marketFilters.collateral,
  });
  const [querySearch, setQuerySearch] = useState('');
  const deferredQuerySearch = useDeferredValue(querySearch);
  const queriedMarketId = useMemo(() => {
    const keyword = deferredQuerySearch.trim();
    return isMorphoMarketId(keyword) ? keyword.toLowerCase() : '';
  }, [deferredQuerySearch]);
  const [expandedMarketId, setExpandedMarketId] = useState('');
  const [marketStateById, setMarketStateById] = useState<Record<string, MorphoMarketView>>({});
  const [marketStateLoadingById, setMarketStateLoadingById] = useState<Record<string, boolean>>({});
  const [marketStateErrorById, setMarketStateErrorById] = useState<Record<string, string>>({});

  const marketsWithLazyState = useMemo(
    () =>
      markets.map(
        (market) =>
          marketStateById[market.market_id] ??
          marketStateById[market.market_id.toLowerCase()] ??
          market,
      ),
    [marketStateById, markets],
  );

  const queriedMarket = useMemo(() => {
    if (!queriedMarketId) return null;
    return (
      marketStateById[queriedMarketId] ??
      mergeMorphoMarketData(createMarketConfigFromId(queriedMarketId), null)
    );
  }, [marketStateById, queriedMarketId]);

  const visibleMarkets = marketsWithLazyState;
  const queryMarkets = useMemo(() => (queriedMarket ? [queriedMarket] : []), [queriedMarket]);

  useEffect(() => {
    setMarketPage((current) => Math.min(Math.max(current, 1), totalMarketPages));
  }, [totalMarketPages]);

  const loadMarketState = useCallback(async (market: MorphoMarketView, force = false) => {
    const marketStateKey = market.market_id.toLowerCase();

    setMarketStateLoadingById((current) => ({
      ...current,
      [market.market_id]: true,
      [marketStateKey]: true,
    }));
    setMarketStateErrorById((current) => {
      const next = { ...current };
      delete next[market.market_id];
      delete next[marketStateKey];
      return next;
    });

    try {
      const result = await fetchMorphoMarketStateWithMeta(market.market_id, { force });
      const merged = mergeMorphoMarketData(market, result.data);
      const enriched = await enrichMarketTokenPrices(merged);
      setMarketStateById((current) => ({
        ...current,
        [market.market_id]: enriched,
        [marketStateKey]: enriched,
      }));
    } catch (stateError) {
      const message = stateError instanceof Error ? stateError.message : '无法加载市场详情';
      setMarketStateErrorById((current) => ({
        ...current,
        [market.market_id]: message,
        [marketStateKey]: message,
      }));
    } finally {
      setMarketStateLoadingById((current) => ({
        ...current,
        [market.market_id]: false,
        [marketStateKey]: false,
      }));
    }
  }, []);

  useEffect(() => {
    if (activeView !== 'query' || !queriedMarketId) return;

    setExpandedMarketId(queriedMarketId);
    if (
      marketStateById[queriedMarketId] ||
      marketStateLoadingById[queriedMarketId] ||
      marketStateErrorById[queriedMarketId]
    ) {
      return;
    }

    void loadMarketState(mergeMorphoMarketData(createMarketConfigFromId(queriedMarketId), null));
  }, [
    activeView,
    loadMarketState,
    marketStateById,
    marketStateErrorById,
    marketStateLoadingById,
    queriedMarketId,
  ]);

  useEffect(() => {
    const activeMarkets = activeView === 'query' ? queryMarkets : visibleMarkets;
    if (
      expandedMarketId &&
      !activeMarkets.some((market) => market.market_id === expandedMarketId)
    ) {
      setExpandedMarketId('');
    }
  }, [activeView, expandedMarketId, queryMarkets, visibleMarkets]);

  const handleToggleMarket = useCallback(
    (market: MorphoMarketView) => {
      if (expandedMarketId === market.market_id) {
        setExpandedMarketId('');
        return;
      }

      setExpandedMarketId(market.market_id);
      if (!market.state_loaded && !marketStateLoadingById[market.market_id]) {
        void loadMarketState(market);
      }
    },
    [expandedMarketId, loadMarketState, marketStateLoadingById],
  );

  const handleReload = async () => {
    setExpandedMarketId('');
    setMarketStateById({});
    setMarketStateErrorById({});
    setMarketStateLoadingById({});
    await reload();
  };

  const refreshedAtText = fetchedAt
    ? new Date(fetchedAt).toLocaleString('zh-CN', {
        hour12: false,
      })
    : 'N/A';
  const querySearchText = querySearch.trim();
  const queryEmptyText = querySearchText
    ? isMorphoMarketId(querySearchText)
      ? '正在等待该市场的 state 详情。'
      : '请输入完整的 0x 开头 32 字节 market id。'
    : '输入完整 market id 后，将直接返回该市场详情。';

  return (
    <>
      <PageHero
        title="Morpho 市场页面"
        subtitle="浏览 Morpho 协议的市场数据，支持按分页查看和按 market id 查询两种模式。"
        controls={
          <SegmentedControl
            ariaLabel="Morpho 市场视图"
            value={activeView}
            onChange={setActiveView}
            options={[
              {
                value: 'mainstream',
                label: '市场列表',
                activeClassName: 'active-purple',
              },
              {
                value: 'query',
                label: '市场查询',
                activeClassName: 'active-purple',
              },
            ]}
          />
        }
      />

      {activeView === 'mainstream' && loading ? (
        <div className="card morpho-market-loading-card">
          <div className="spinner"></div>
        </div>
      ) : activeView === 'mainstream' ? (
        <MorphoMarketTable
          markets={visibleMarkets}
          expandedMarketId={expandedMarketId}
          onToggleMarket={handleToggleMarket}
          marketStateLoadingById={marketStateLoadingById}
          marketStateErrorById={marketStateErrorById}
          title="市场列表"
          subtitle="分页展示市场核心指标，展开单个市场后再加载实时详情。"
          marketFilters={marketFilters}
          onMarketFilterCommit={(filters) => {
            setMarketFilters(filters);
            setMarketPage(1);
          }}
          sortMode={sortMode}
          onSortModeChange={(value) => {
            setSortMode(value);
            setMarketPage(1);
          }}
          totalMarkets={marketCount}
          page={marketPage}
          totalPages={totalMarketPages}
          pageSize={MORPHO_MARKETS_PAGE_SIZE}
          onPageChange={setMarketPage}
          tableError={error}
        />
      ) : (
        <MorphoMarketTable
          markets={queryMarkets}
          expandedMarketId={expandedMarketId}
          onToggleMarket={handleToggleMarket}
          marketStateLoadingById={marketStateLoadingById}
          marketStateErrorById={marketStateErrorById}
          title="市场查询"
          subtitle="输入完整 market id 后直接请求 state 接口，并返回这一个市场的详情。"
          search={querySearch}
          onSearchChange={setQuerySearch}
          searchPlaceholder="输入完整 Morpho market id"
          sortMode={sortMode}
          onSortModeChange={setSortMode}
          totalMarkets={queryMarkets.length}
          page={1}
          totalPages={1}
          pageSize={Math.max(queryMarkets.length, 1)}
          onPageChange={() => undefined}
          showSorting={false}
          showPagination={false}
          showTableHeaderWhenEmpty={false}
          emptyText={queryEmptyText}
        />
      )}

      {activeView === 'mainstream' ? (
        <div className="card morpho-detail-card morpho-market-toolbar">
          <div className="morpho-market-toolbar-copy">
            <strong>数据状态</strong>
            <span>
              最近更新 {refreshedAtText} {fromCache ? '· 缓存命中' : '· 实时拉取'}
            </span>
          </div>
          <div className="morpho-market-toolbar-actions">
            <button type="button" className="switch-btn" onClick={() => void handleReload()}>
              刷新数据
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
