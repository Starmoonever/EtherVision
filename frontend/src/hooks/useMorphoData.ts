import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchMorphoMarketsWithMeta,
  type MorphoMarketConfig,
  type MorphoMarketSortField,
  type MorphoMarketSortOrder,
  type MorphoMarketState,
} from '../api/morpho';

export interface MorphoMarketView extends MorphoMarketConfig {
  total_collateral_usd: string | null;
  total_debt_usd: string | null;
  total_supply_assets: string | null;
  total_supply_assets_is_raw: boolean;
  total_borrow_assets: string | null;
  total_borrow_assets_is_raw: boolean;
  supply_apy: string | null;
  borrow_apy: string | null;
  available_liquidity: string | null;
  available_liquidity_is_raw: boolean;
  utilization: string | null;
  borrow_capacity_usage_rough: string | null;
  is_liquidatable: boolean | null;
  eth_down_liq_price_usd: string | null;
  total_market_size_usd: string | null;
  loan_token_price_usd: string | null;
  collateral_token_price_usd: string | null;
  loan_token_address: string | null;
  collateral_token_address: string | null;
  state_loaded: boolean;
}

export interface UseMorphoDataResult {
  markets: MorphoMarketView[];
  marketCount: number;
  page: number;
  pageSize: number;
  totalPages: number;
  loading: boolean;
  error: string;
  fetchedAt: number | null;
  fromCache: boolean;
  reload: () => Promise<void>;
}

export interface UseMorphoDataOptions {
  page?: number;
  pageSize?: number;
  sortBy?: MorphoMarketSortField;
  sortOrder?: MorphoMarketSortOrder;
  loan?: string;
  collateral?: string;
}

export function mergeMorphoMarketData(
  config: MorphoMarketConfig,
  state: MorphoMarketState | null,
): MorphoMarketView {
  return {
    ...config,
    collateral_symbol: state?.collateral_symbol ?? config.collateral_symbol,
    loan_symbol: state?.loan_symbol ?? config.loan_symbol,
    lltv: state?.lltv ?? config.lltv,
    oracle: state?.oracle ?? config.oracle,
    irm: state?.irm ?? config.irm,
    collateral_decimals: state?.collateral_decimals ?? config.collateral_decimals ?? null,
    loan_decimals: state?.loan_decimals ?? config.loan_decimals ?? null,
    loan_token_address: state?.loan_token_address ?? config.loan_token_address ?? null,
    collateral_token_address:
      state?.collateral_token_address ?? config.collateral_token_address ?? null,
    total_collateral_usd: state?.total_collateral_usd ?? null,
    total_debt_usd: state?.total_debt_usd ?? null,
    total_supply_assets: state?.total_supply_assets ?? null,
    total_supply_assets_is_raw: state?.total_supply_assets_is_raw ?? true,
    total_borrow_assets: state?.total_borrow_assets ?? null,
    total_borrow_assets_is_raw: state?.total_borrow_assets_is_raw ?? true,
    supply_apy: state?.supply_apy ?? null,
    borrow_apy: state?.borrow_apy ?? null,
    available_liquidity: state?.available_liquidity ?? null,
    available_liquidity_is_raw: state?.available_liquidity_is_raw ?? true,
    utilization: state?.utilization ?? config.utilization ?? null,
    borrow_capacity_usage_rough: state?.borrow_capacity_usage_rough ?? null,
    is_liquidatable: state?.is_liquidatable ?? null,
    eth_down_liq_price_usd: state?.eth_down_liq_price_usd ?? null,
    total_market_size_usd: state?.total_market_size_usd ?? config.total_market_size_usd ?? null,
    loan_token_price_usd: null,
    collateral_token_price_usd: null,
    state_loaded: Boolean(state),
  };
}

export function useMorphoData(options: UseMorphoDataOptions = {}): UseMorphoDataResult {
  const requestedPage = options.page ?? 1;
  const requestedPageSize = options.pageSize ?? 10;
  const requestedSortBy = options.sortBy;
  const requestedSortOrder = options.sortBy ? (options.sortOrder ?? 'desc') : undefined;
  const requestedLoan = options.loan?.trim() || undefined;
  const requestedCollateral = options.collateral?.trim() || undefined;
  const [markets, setMarkets] = useState<MorphoMarketView[]>([]);
  const [marketCount, setMarketCount] = useState(0);
  const [page, setPage] = useState(requestedPage);
  const [pageSize, setPageSize] = useState(requestedPageSize);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [fromCache, setFromCache] = useState(false);

  const load = useCallback(
    async (force = false) => {
      setLoading(true);
      setError('');

      try {
        const marketsResult = await fetchMorphoMarketsWithMeta({
          force,
          page: requestedPage,
          pageSize: requestedPageSize,
          sortBy: requestedSortBy,
          sortOrder: requestedSortOrder,
          loan: requestedLoan,
          collateral: requestedCollateral,
        });
        const configs = marketsResult.data.markets;
        const merged = configs.map((config) => mergeMorphoMarketData(config, null));

        if (!merged.length) {
          setError('当前筛选条件下没有可展示的 Morpho 市场。');
          return;
        }

        setMarkets(merged);
        setMarketCount(marketsResult.data.market_count);
        setPage(marketsResult.data.page);
        setPageSize(marketsResult.data.page_size);
        setTotalPages(marketsResult.data.total_pages);
        setFetchedAt(marketsResult.meta.fetchedAt);
        setFromCache(marketsResult.meta.fromCache);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : '无法加载 Morpho 市场数据');
      } finally {
        setLoading(false);
      }
    },
    [
      requestedCollateral,
      requestedLoan,
      requestedPage,
      requestedPageSize,
      requestedSortBy,
      requestedSortOrder,
    ],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const reload = useCallback(async () => {
    await load(true);
  }, [load]);

  return useMemo(
    () => ({
      markets,
      marketCount,
      page,
      pageSize,
      totalPages,
      loading,
      error,
      fetchedAt,
      fromCache,
      reload,
    }),
    [
      error,
      fetchedAt,
      fromCache,
      loading,
      marketCount,
      markets,
      page,
      pageSize,
      reload,
      totalPages,
    ],
  );
}
