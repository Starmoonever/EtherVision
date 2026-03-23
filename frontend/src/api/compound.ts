import { apiFetch } from './client';

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

export async function fetchCompoundMarketHistory(
  version: string,
  market: string,
  start: string,
  end: string,
): Promise<CompoundMarketPoint[]> {
  const data = await apiFetch<CompoundMarketHistoryResponse>(
    `/compound/market/state/period?version=${version}&market=${market}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&detail=true`,
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
