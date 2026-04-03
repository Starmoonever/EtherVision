import { apiFetch, apiFetchRaw } from './client';
import type { DataWithMeta } from './requestMeta';

const COMPOUND_CACHE_TTL_MS = 5 * 60 * 1000;

export interface CompoundMarket {
  address: string;
  symbol: string;
}

interface CompoundMarketsResponse {
  version: string;
  markets: CompoundMarket[];
}

export interface CompoundReserve {
  reserve: string;
  symbol: string;
  decimals: number;
  total_supply: string;
  total_borrow: string;
  utilization: string;
  borrow_apr: string;
  supply_apr: string;
  price_in_base?: string;
  price_usd?: string;
  supply_usd: string;
  borrow_usd: string;
}

export interface CompoundMarketPoint {
  version: string;
  market: string;
  symbol?: string;
  timestamp: string;
  total_supply: string;
  total_borrow: string;
  collateral_usd?: string;
  utilization: string;
  borrow_apr: string;
  supply_apr: string;
  price_usd?: string;
  supply_usd: string;
  borrow_usd: string;
  reserves: CompoundReserve[];
}

export interface CompoundMarketHistoryResponse {
  points: CompoundMarketPoint[];
}

export interface CompoundGovernanceAsset {
  symbol: string;
  borrow_collateral_factor?: string;
}

export interface CompoundGovernanceV3Response {
  tracking_index_scale?: string;
  base_tracking_supply_speed?: string;
  base_tracking_borrow_speed?: string;
  assets?: CompoundGovernanceAsset[];
}

export interface CompoundV2MarketConfig {
  effective_timestamp?: string;
  exchange_rate?: string;
  collateral_factor?: string;
  reserve_factor?: string;
}

export interface CompoundV2MarketConfigResponse {
  version: string;
  market_config: CompoundV2MarketConfig | null;
  protocol_config: unknown | null;
}

export interface CompoundV2MarketConfigPeriodPoint {
  market_config?: CompoundV2MarketConfig | null;
}

export interface CompoundV2MarketConfigPeriodResponse {
  points: CompoundV2MarketConfigPeriodPoint[];
}

interface FetchCompoundMarketHistoryOptions {
  interval?: number;
  detail?: boolean;
}

const V2_MARKET_ALIAS_MAP: Record<string, string> = {
  cdai: 'cDAI',
  dai: 'cDAI',
  cusdc: 'cUSDC',
  usdc: 'cUSDC',
  ceth: 'cETH',
  eth: 'cETH',
  weth: 'cETH',
  cwbtc: 'cWBTC',
  wbtc: 'cWBTC',
  btc: 'cWBTC',
  cbbtc: 'cWBTC',
};

const V2_BASE_ASSET_ALIAS_MAP: Record<string, string> = {
  cdai: 'DAI',
  dai: 'DAI',
  cusdc: 'USDC',
  usdc: 'USDC',
  ceth: 'ETH',
  eth: 'ETH',
  weth: 'ETH',
  cwbtc: 'WBTC',
  wbtc: 'WBTC',
  btc: 'WBTC',
  cbbtc: 'WBTC',
};

const EMPTY_V2_MARKET_CONFIG_RESPONSE: CompoundV2MarketConfigResponse = {
  version: 'v2',
  market_config: null,
  protocol_config: null,
};

const EMPTY_V2_MARKET_CONFIG_PERIOD_RESPONSE: CompoundV2MarketConfigPeriodResponse = {
  points: [],
};

const compoundMarketsCache = new Map<string, { fetchedAt: number; data: CompoundMarket[] }>();
const compoundMarketsInflight = new Map<string, Promise<CompoundMarket[]>>();

const compoundMarketHistoryCache = new Map<
  string,
  { fetchedAt: number; data: CompoundMarketPoint[] }
>();
const compoundMarketHistoryInflight = new Map<string, Promise<CompoundMarketPoint[]>>();

const compoundUserPositionCache = new Map<
  string,
  { fetchedAt: number; data: CompoundUserPositionResponse }
>();
const compoundUserPositionInflight = new Map<string, Promise<CompoundUserPositionResponse>>();

const compoundGovernanceCache = new Map<
  string,
  { fetchedAt: number; data: CompoundGovernanceV3Response }
>();
const compoundGovernanceInflight = new Map<string, Promise<CompoundGovernanceV3Response>>();

const compoundV2ConfigCache = new Map<
  string,
  { fetchedAt: number; data: CompoundV2MarketConfigResponse }
>();
const compoundV2ConfigInflight = new Map<string, Promise<CompoundV2MarketConfigResponse>>();

const compoundV2ConfigPeriodCache = new Map<
  string,
  { fetchedAt: number; data: CompoundV2MarketConfigPeriodResponse }
>();
const compoundV2ConfigPeriodInflight = new Map<
  string,
  Promise<CompoundV2MarketConfigPeriodResponse>
>();

function buildCompoundV2MarketCandidates(market: string): string[] {
  const trimmed = market.trim();
  if (!trimmed) return [];

  const normalized = trimmed.toLowerCase();
  const candidates: string[] = [];
  const push = (value: string | undefined) => {
    if (!value) return;
    if (!candidates.includes(value)) {
      candidates.push(value);
    }
  };

  const alias = V2_MARKET_ALIAS_MAP[normalized];
  push(alias);
  push(trimmed);

  if (!alias && !normalized.startsWith('0x') && !normalized.startsWith('c')) {
    push(`c${trimmed}`);
  }

  return candidates;
}

export function getCompoundV2BaseAssetSymbol(market: string): string {
  const trimmed = market.trim();
  const normalized = trimmed.toLowerCase();

  if (V2_BASE_ASSET_ALIAS_MAP[normalized]) {
    return V2_BASE_ASSET_ALIAS_MAP[normalized];
  }

  if (normalized.startsWith('c') && trimmed.length > 1) {
    return trimmed.slice(1);
  }

  return trimmed;
}

async function fetchFirstCompoundV2ConfigCandidate<T>(
  market: string,
  buildPath: (market: string) => string,
): Promise<T | null> {
  const candidates = buildCompoundV2MarketCandidates(market);

  for (const candidate of candidates) {
    const path = buildPath(candidate);
    const response = await apiFetchRaw(path);

    if (response.ok) {
      return response.json() as Promise<T>;
    }

    if (response.status >= 500) {
      throw new Error(`API error ${response.status}: ${path}`);
    }
  }

  return null;
}

export interface CompoundUserAsset {
  asset: string;
  symbol: string;
  side: string;
  amount: string;
  price_in_base: string;
  price_usd: string;
  value_usd: string;
  discounted_value_usd: string;
  borrow_collateral_factor: string;
  liquidate_collateral_factor: string;
  liquidation_factor: string;
  beta_to_eth: string;
  is_eth_correlated: boolean;
  is_basis_risk_asset: boolean;
}

export interface CompoundUserPositionItem {
  market: string;
  symbol: string;
  timestamp: string;
  block_number: number;
  has_open_position: boolean;
  is_liquidatable: boolean;
  base_token: string;
  base_symbol: string;
  base_price_usd: string;
  eth_price_usd: string;
  total_collateral_usd: string;
  total_debt_usd: string;
  discounted_collateral_usd: string;
  liquidation_buffer_usd: string;
  health_factor: string;
  eth_sensitive_collateral_usd: string;
  eth_sensitive_debt_usd: string;
  net_eth_exposure_usd: string;
  non_eth_collateral_usd: string;
  non_eth_debt_usd: string;
  basis_risk_collateral_usd: string;
  eth_down_liq_price_usd: string;
  eth_up_liq_price_usd: string;
  eth_liq_mode: string;
  dominant_risk: string;
  assets: CompoundUserAsset[];
}

export interface CompoundUserPositionResponse {
  version: string;
  address: string;
  positions: CompoundUserPositionItem[];
}

export async function fetchCompoundMarkets(version: string): Promise<CompoundMarket[]> {
  const result = await fetchCompoundMarketsWithMeta(version);
  return result.data;
}

export async function fetchCompoundMarketsWithMeta(
  version: string,
): Promise<DataWithMeta<CompoundMarket[]>> {
  const key = version;
  const cached = compoundMarketsCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundMarketsInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<CompoundMarketsResponse>(`/compound/markets?version=${version}`)
    .then((data) => {
      if (!data.markets || !Array.isArray(data.markets)) {
        throw new Error('Invalid Compound markets response format');
      }
      compoundMarketsCache.set(key, { fetchedAt: Date.now(), data: data.markets });
      return data.markets;
    })
    .finally(() => {
      compoundMarketsInflight.delete(key);
    });

  compoundMarketsInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundMarketHistory(
  version: string,
  market: string,
  start: string,
  end: string,
  options: FetchCompoundMarketHistoryOptions = {},
): Promise<CompoundMarketPoint[]> {
  const result = await fetchCompoundMarketHistoryWithMeta(version, market, start, end, options);
  return result.data;
}

export async function fetchCompoundMarketHistoryWithMeta(
  version: string,
  market: string,
  start: string,
  end: string,
  options: FetchCompoundMarketHistoryOptions = {},
): Promise<DataWithMeta<CompoundMarketPoint[]>> {
  const key = `${version}|${market}|${start}|${end}|${options.interval ?? ''}|${String(options.detail ?? true)}`;
  const cached = compoundMarketHistoryCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundMarketHistoryInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({
    version,
    market,
    start,
    end,
    detail: String(options.detail ?? true),
  });

  if (options.interval !== undefined) {
    params.set('interval', String(options.interval));
  }

  const request = apiFetch<CompoundMarketHistoryResponse>(
    `/compound/market/state/period?${params.toString()}`,
  )
    .then((data) => {
      if (!data.points || !Array.isArray(data.points)) {
        throw new Error('Invalid Compound market history response format');
      }
      compoundMarketHistoryCache.set(key, { fetchedAt: Date.now(), data: data.points });
      return data.points;
    })
    .finally(() => {
      compoundMarketHistoryInflight.delete(key);
    });

  compoundMarketHistoryInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundUserPosition(
  version: string,
  market: string,
  address: string,
): Promise<CompoundUserPositionResponse> {
  const result = await fetchCompoundUserPositionWithMeta(version, market, address);
  return result.data;
}

export async function fetchCompoundUserPositionWithMeta(
  version: string,
  market: string,
  address: string,
): Promise<DataWithMeta<CompoundUserPositionResponse>> {
  const normalizedAddress = address.toLowerCase();
  const normalizedMarket = market.toLowerCase();
  const key = `${version}|${normalizedMarket}|${normalizedAddress}`;
  const cached = compoundUserPositionCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundUserPositionInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<CompoundUserPositionResponse>(
    `/compound/position?version=${version}&market=${market}&address=${address}`,
  )
    .then((data) => {
      compoundUserPositionCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      compoundUserPositionInflight.delete(key);
    });

  compoundUserPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundMarketGovernanceV3(
  market: string,
  date: string,
): Promise<CompoundGovernanceV3Response> {
  const result = await fetchCompoundMarketGovernanceV3WithMeta(market, date);
  return result.data;
}

export async function fetchCompoundMarketGovernanceV3WithMeta(
  market: string,
  date: string,
): Promise<DataWithMeta<CompoundGovernanceV3Response>> {
  const key = `${market.toLowerCase()}|${date}`;
  const cached = compoundGovernanceCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundGovernanceInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<CompoundGovernanceV3Response>(
    `/compound/market/config?version=v3&market=${market}&date=${encodeURIComponent(date)}&detail=true`,
  )
    .then((data) => {
      compoundGovernanceCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      compoundGovernanceInflight.delete(key);
    });

  compoundGovernanceInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundMarketConfigV2(
  market: string,
  date: string,
): Promise<CompoundV2MarketConfigResponse> {
  const result = await fetchCompoundMarketConfigV2WithMeta(market, date);
  return result.data;
}

export async function fetchCompoundMarketConfigV2WithMeta(
  market: string,
  date: string,
): Promise<DataWithMeta<CompoundV2MarketConfigResponse>> {
  const key = `${market.trim().toLowerCase()}|${date}`;
  const cached = compoundV2ConfigCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundV2ConfigInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = fetchFirstCompoundV2ConfigCandidate<CompoundV2MarketConfigResponse>(
    market,
    (candidate) =>
      `/compound/market/config?version=v2&market=${encodeURIComponent(candidate)}&date=${encodeURIComponent(date)}`,
  )
    .then((data) => {
      const resolved = data ?? EMPTY_V2_MARKET_CONFIG_RESPONSE;
      compoundV2ConfigCache.set(key, { fetchedAt: Date.now(), data: resolved });
      return resolved;
    })
    .finally(() => {
      compoundV2ConfigInflight.delete(key);
    });

  compoundV2ConfigInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundMarketConfigPeriodV2(
  market: string,
  start: string,
  end: string,
): Promise<CompoundV2MarketConfigPeriodResponse> {
  const result = await fetchCompoundMarketConfigPeriodV2WithMeta(market, start, end);
  return result.data;
}

export async function fetchCompoundMarketConfigPeriodV2WithMeta(
  market: string,
  start: string,
  end: string,
): Promise<DataWithMeta<CompoundV2MarketConfigPeriodResponse>> {
  const key = `${market.trim().toLowerCase()}|${start}|${end}`;
  const cached = compoundV2ConfigPeriodCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundV2ConfigPeriodInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = fetchFirstCompoundV2ConfigCandidate<CompoundV2MarketConfigPeriodResponse>(
    market,
    (candidate) =>
      `/compound/market/config/period?version=v2&market=${encodeURIComponent(candidate)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  )
    .then((data) => {
      const resolved = data ?? EMPTY_V2_MARKET_CONFIG_PERIOD_RESPONSE;
      compoundV2ConfigPeriodCache.set(key, { fetchedAt: Date.now(), data: resolved });
      return resolved;
    })
    .finally(() => {
      compoundV2ConfigPeriodInflight.delete(key);
    });

  compoundV2ConfigPeriodInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export interface CompoundPositionReplayPoint {
  tx_hash: string;
  block_number: number;
  timestamp: string;
  market: string;
  symbol: string;
  eth_price_usd: string;
  total_collateral_usd: string;
  total_debt_usd: string;
  discounted_collateral_usd: string;
  liquidation_buffer_usd: string;
  health_factor: string;
  is_liquidatable: boolean;
  eth_down_liq_price_usd: string;
  eth_up_liq_price_usd: string;
  eth_liq_mode: string;
  dominant_risk: string;
  brief: string;
  assets: CompoundUserAsset[];
}

export interface CompoundPositionReplayResponse {
  address: string;
  version: string;
  from_time: string;
  to_time: string;
  data_source: string;
  points: CompoundPositionReplayPoint[];
  total_points: number;
  total_tx_count: number;
  cache_hit_rate: string;
}

export async function fetchCompoundPositionReplay(
  address: string,
  start: string,
  end: string,
  version: string,
): Promise<CompoundPositionReplayResponse> {
  const result = await fetchCompoundPositionReplayWithMeta(address, start, end, version);
  return result.data;
}

export async function fetchCompoundPositionReplayWithMeta(
  address: string,
  start: string,
  end: string,
  version: string,
): Promise<DataWithMeta<CompoundPositionReplayResponse>> {
  const data = await apiFetch<CompoundPositionReplayResponse>(
    `/compound/position/replay?address=${address}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&version=${version}`,
  );
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchCompoundLiquidationPeriod(
  version: 'v2' | 'v3',
  market: string,
  start: number,
  end: number,
  interval: number = 1,
): Promise<CompoundLiquidationPeriodItem[]> {
  const result = await fetchCompoundLiquidationPeriodWithMeta(
    version,
    market,
    start,
    end,
    interval,
  );
  return result.data;
}

export async function fetchCompoundLiquidationPeriodWithMeta(
  version: 'v2' | 'v3',
  market: string,
  start: number,
  end: number,
  interval: number = 1,
): Promise<DataWithMeta<CompoundLiquidationPeriodItem[]>> {
  const key = `${version}|${market}|${Math.round(start)}|${Math.round(end)}|${interval}`;
  const cached = compoundLiquidationPeriodCache.get(key);

  if (cached && Date.now() - cached.fetchedAt < COMPOUND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = compoundLiquidationPeriodInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({
    version,
    market,
    start: String(start),
    end: String(end),
    interval: String(interval),
  });

  const request = apiFetch<CompoundLiquidationPeriodItem[]>(
    `/compound/liquidate/period?${params.toString()}`,
  )
    .then((data) => {
      compoundLiquidationPeriodCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      compoundLiquidationPeriodInflight.delete(key);
    });

  compoundLiquidationPeriodInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export interface CompoundLiquidationPeriodItem {
  simulated_eth_price: string;
  positions_cnt: string;
  total_eth_sensitive_collateral_usd: string;
  total_liquidation_usd: string;
}

const compoundLiquidationPeriodCache = new Map<
  string,
  { fetchedAt: number; data: CompoundLiquidationPeriodItem[] }
>();
const compoundLiquidationPeriodInflight = new Map<
  string,
  Promise<CompoundLiquidationPeriodItem[]>
>();
