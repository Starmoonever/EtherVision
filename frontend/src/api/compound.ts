import { apiFetch, apiFetchRaw } from './client';

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

const EMPTY_V2_MARKET_CONFIG_RESPONSE = {
  version: 'v2',
  market_config: null,
  protocol_config: null,
};

const EMPTY_V2_MARKET_CONFIG_PERIOD_RESPONSE = {
  points: [],
};

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
  const data = await apiFetch<CompoundMarketsResponse>(`/compound/markets?version=${version}`);
  if (!data.markets || !Array.isArray(data.markets)) {
    throw new Error('Invalid Compound markets response format');
  }
  return data.markets;
}

export async function fetchCompoundMarketHistory(
  version: string,
  market: string,
  start: string,
  end: string,
  options: FetchCompoundMarketHistoryOptions = {},
): Promise<CompoundMarketPoint[]> {
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

  const data = await apiFetch<CompoundMarketHistoryResponse>(
    `/compound/market/state/period?${params.toString()}`,
  );
  if (!data.points || !Array.isArray(data.points)) {
    throw new Error('Invalid Compound market history response format');
  }
  return data.points;
}

export async function fetchCompoundUserPosition(
  version: string,
  market: string,
  address: string,
): Promise<CompoundUserPositionResponse> {
  return apiFetch<CompoundUserPositionResponse>(
    `/compound/position?version=${version}&market=${market}&address=${address}`,
  );
}

export async function fetchCompoundMarketGovernanceV3(market: string, date: string): Promise<any> {
  return apiFetch<any>(
    `/compound/market/config?version=v3&market=${market}&date=${encodeURIComponent(date)}&detail=true`,
  );
}

export async function fetchCompoundMarketConfigV2(market: string, date: string): Promise<any> {
  const data = await fetchFirstCompoundV2ConfigCandidate<any>(
    market,
    (candidate) =>
      `/compound/market/config?version=v2&market=${encodeURIComponent(candidate)}&date=${encodeURIComponent(date)}`,
  );
  return data ?? EMPTY_V2_MARKET_CONFIG_RESPONSE;
}

export async function fetchCompoundMarketConfigPeriodV2(
  market: string,
  start: string,
  end: string,
): Promise<any> {
  const data = await fetchFirstCompoundV2ConfigCandidate<any>(
    market,
    (candidate) =>
      `/compound/market/config/period?version=v2&market=${encodeURIComponent(candidate)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
  );
  return data ?? EMPTY_V2_MARKET_CONFIG_PERIOD_RESPONSE;
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
  return apiFetch<CompoundPositionReplayResponse>(
    `/compound/position/replay?address=${address}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&version=${version}`,
  );
}
