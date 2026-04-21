import { useCallback, useDeferredValue, useEffect, useMemo, useState } from 'react';
import { fetchMorphoMarketStateWithMeta } from '../../../api/morpho';
import { fetchAssetPrice } from '../../../api/price';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import {
  mergeMorphoMarketData,
  useMorphoData,
  type MorphoMarketView,
} from '../../../hooks/useMorphoData';
import { MorphoMarketTable, type MorphoSortMode } from '../components/MorphoMarketTable';

const MORPHO_MARKETS_PAGE_SIZE = 10;

function parseMetric(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeTokenAmount(
  value: string | null | undefined,
  decimals: number | null | undefined,
  isRaw: boolean,
): number | null {
  if (!value) return null;
  if (!isRaw) return parseMetric(value);

  const safeDecimals = Number.isInteger(decimals) ? Number(decimals) : 0;
  const trimmed = value.trim();
  if (!trimmed) return null;

  const negative = trimmed.startsWith('-');
  const digits = negative ? trimmed.slice(1) : trimmed;
  if (!/^\d+$/.test(digits)) return parseMetric(value);

  const paddedDigits = digits.padStart(safeDecimals + 1, '0');
  const integerPart =
    safeDecimals === 0 ? paddedDigits : paddedDigits.slice(0, paddedDigits.length - safeDecimals);
  const fractionalPart =
    safeDecimals === 0 ? '' : paddedDigits.slice(-safeDecimals).replace(/0+$/, '');
  const normalizedText = `${negative ? '-' : ''}${integerPart}${fractionalPart ? `.${fractionalPart}` : ''}`;
  const numeric = Number(normalizedText);
  return Number.isFinite(numeric) ? numeric : null;
}

async function enrichMarketUsdMetrics(market: MorphoMarketView): Promise<MorphoMarketView> {
  const loanPriceAsset = market.loan_token_address || market.loan_symbol;
  const collateralPriceAsset = market.collateral_token_address || market.collateral_symbol;
  if (!loanPriceAsset) return market;

  try {
    const loanTokenPriceUsd = await fetchAssetPrice(loanPriceAsset, { chain: 'ethereum' });
    const collateralTokenPriceUsd = collateralPriceAsset
      ? await fetchAssetPrice(collateralPriceAsset, { chain: 'ethereum' }).catch(() => null)
      : null;
    const supplyAmount = normalizeTokenAmount(
      market.total_supply_assets,
      market.loan_decimals,
      market.total_supply_assets_is_raw,
    );
    const borrowAmount = normalizeTokenAmount(
      market.total_borrow_assets,
      market.loan_decimals,
      market.total_borrow_assets_is_raw,
    );
    const availableLiquidityAmount = normalizeTokenAmount(
      market.available_liquidity,
      market.loan_decimals,
      market.available_liquidity_is_raw,
    );
    const supplyUsd = supplyAmount === null ? null : supplyAmount * loanTokenPriceUsd;
    const borrowUsd = borrowAmount === null ? null : borrowAmount * loanTokenPriceUsd;
    const availableLiquidityUsd =
      availableLiquidityAmount === null ? null : availableLiquidityAmount * loanTokenPriceUsd;

    return {
      ...market,
      total_market_size_usd: supplyUsd === null ? market.total_market_size_usd : String(supplyUsd),
      borrow_market_size_usd: borrowUsd === null ? null : String(borrowUsd),
      available_space_usd:
        supplyUsd === null || borrowUsd === null
          ? null
          : String(Math.max(0, supplyUsd - borrowUsd)),
      available_liquidity_usd:
        availableLiquidityUsd === null ? null : String(Math.max(0, availableLiquidityUsd)),
      loan_token_price_usd: String(loanTokenPriceUsd),
      collateral_token_price_usd:
        collateralTokenPriceUsd === null ? null : String(collateralTokenPriceUsd),
    };
  } catch {
    return market;
  }
}

function sortMarkets(markets: MorphoMarketView[], sortMode: MorphoSortMode): MorphoMarketView[] {
  if (sortMode === 'default') return [...markets];

  const sorted = [...markets];
  sorted.sort((left, right) => {
    const isMarketSizeSort = sortMode.startsWith('totalMarketSize');
    const leftMetric = isMarketSizeSort
      ? parseMetric(left.total_market_size_usd)
      : parseMetric(left.utilization);
    const rightMetric = isMarketSizeSort
      ? parseMetric(right.total_market_size_usd)
      : parseMetric(right.utilization);

    if (leftMetric === null && rightMetric === null) return 0;
    if (leftMetric === null) return 1;
    if (rightMetric === null) return -1;

    return sortMode.endsWith('Asc') ? leftMetric - rightMetric : rightMetric - leftMetric;
  });

  return sorted;
}

export function MorphoMarketPage() {
  const [marketPage, setMarketPage] = useState(1);
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
  });
  const [sortMode, setSortMode] = useState<MorphoSortMode>('default');
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search);
  const [expandedMarketId, setExpandedMarketId] = useState('');
  const [marketStateById, setMarketStateById] = useState<Record<string, MorphoMarketView>>({});
  const [marketStateLoadingById, setMarketStateLoadingById] = useState<Record<string, boolean>>({});
  const [marketStateErrorById, setMarketStateErrorById] = useState<Record<string, string>>({});

  const marketsWithLazyState = useMemo(
    () => markets.map((market) => marketStateById[market.market_id] ?? market),
    [marketStateById, markets],
  );

  const filteredMarkets = useMemo(() => {
    const keyword = deferredSearch.trim().toLowerCase();

    return marketsWithLazyState.filter((market) => {
      if (!keyword) return true;

      return [
        market.pair,
        market.market_id,
        market.loan_symbol,
        market.collateral_symbol,
        market.loan_token_address,
        market.collateral_token_address,
        market.oracle,
        market.irm,
      ]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(keyword));
    });
  }, [deferredSearch, marketsWithLazyState]);

  const visibleMarkets = useMemo(
    () => sortMarkets(filteredMarkets, sortMode),
    [filteredMarkets, sortMode],
  );

  useEffect(() => {
    setMarketPage((current) => Math.min(Math.max(current, 1), totalMarketPages));
  }, [totalMarketPages]);

  useEffect(() => {
    if (
      expandedMarketId &&
      !visibleMarkets.some((market) => market.market_id === expandedMarketId)
    ) {
      setExpandedMarketId('');
    }
  }, [expandedMarketId, visibleMarkets]);

  const loadMarketState = useCallback(async (market: MorphoMarketView, force = false) => {
    setMarketStateLoadingById((current) => ({ ...current, [market.market_id]: true }));
    setMarketStateErrorById((current) => {
      const next = { ...current };
      delete next[market.market_id];
      return next;
    });

    try {
      const result = await fetchMorphoMarketStateWithMeta(market.market_id, { force });
      const merged = mergeMorphoMarketData(market, result.data);
      const enriched = await enrichMarketUsdMetrics(merged);
      setMarketStateById((current) => ({
        ...current,
        [market.market_id]: enriched,
      }));
    } catch (stateError) {
      setMarketStateErrorById((current) => ({
        ...current,
        [market.market_id]: stateError instanceof Error ? stateError.message : '无法加载市场详情',
      }));
    } finally {
      setMarketStateLoadingById((current) => ({ ...current, [market.market_id]: false }));
    }
  }, []);

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

  return (
    <>
      <PageHero
        title="Morpho 市场页面"
        subtitle="市场列表保持轻量加载，展开单个市场后再读取实时详情。"
      />

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

      <ErrorNotice message={error} />

      {loading ? (
        <div className="card morpho-market-loading-card">
          <div className="spinner"></div>
        </div>
      ) : (
        <MorphoMarketTable
          markets={visibleMarkets}
          expandedMarketId={expandedMarketId}
          onToggleMarket={handleToggleMarket}
          marketStateLoadingById={marketStateLoadingById}
          marketStateErrorById={marketStateErrorById}
          search={search}
          onSearchChange={(value) => {
            setSearch(value);
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
        />
      )}
    </>
  );
}
