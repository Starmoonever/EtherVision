import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  fetchMorphoMarketsWithMeta,
  type MorphoMarketConfig,
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
  borrow_market_size_usd: string | null;
  available_space_usd: string | null;
  available_liquidity_usd: string | null;
  loan_token_price_usd: string | null;
  collateral_token_price_usd: string | null;
  loan_token_address: string | null;
  collateral_token_address: string | null;
  state_loaded: boolean;
}

export interface UseMorphoDataResult {
  markets: MorphoMarketView[];
  loading: boolean;
  error: string;
  fetchedAt: number | null;
  fromCache: boolean;
  reload: () => Promise<void>;
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
    loan_token_address: state?.loan_token_address ?? null,
    collateral_token_address: state?.collateral_token_address ?? null,
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
    utilization: state?.utilization ?? null,
    borrow_capacity_usage_rough: state?.borrow_capacity_usage_rough ?? null,
    is_liquidatable: state?.is_liquidatable ?? null,
    eth_down_liq_price_usd: state?.eth_down_liq_price_usd ?? null,
    total_market_size_usd: config.total_market_size_usd ?? null,
    borrow_market_size_usd: null,
    available_space_usd: null,
    available_liquidity_usd: null,
    loan_token_price_usd: null,
    collateral_token_price_usd: null,
    state_loaded: Boolean(state),
  };
}

export function useMorphoData(): UseMorphoDataResult {
  const [markets, setMarkets] = useState<MorphoMarketView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [fetchedAt, setFetchedAt] = useState<number | null>(null);
  const [fromCache, setFromCache] = useState(false);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setError('');

    try {
      const marketsResult = await fetchMorphoMarketsWithMeta({ force });
      const configs = marketsResult.data.markets;
      const merged = configs.map((config) => mergeMorphoMarketData(config, null));

      setMarkets(merged);
      setFetchedAt(marketsResult.meta.fetchedAt);
      setFromCache(marketsResult.meta.fromCache);

      if (!merged.length) {
        setError('Morpho 市场列表为空');
      }
    } catch (loadError) {
      setMarkets([]);
      setFetchedAt(null);
      setFromCache(false);
      setError(loadError instanceof Error ? loadError.message : '无法加载 Morpho 市场数据');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  const reload = useCallback(async () => {
    await load(true);
  }, [load]);

  return useMemo(
    () => ({
      markets,
      loading,
      error,
      fetchedAt,
      fromCache,
      reload,
    }),
    [error, fetchedAt, fromCache, loading, markets, reload],
  );
}
