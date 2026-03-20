import { apiFetch } from './client';

export interface CompoundReserve {
  reserve: string;
  symbol: string;
  decimals: number;
  total_supply: string;
  total_borrow: string;
  utilization: string;
  borrow_rate: string;
  supply_rate: string;
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
  borrow_rate: string;
  supply_rate: string;
  price_usd?: string;
  supply_usd: string;
  borrow_usd: string;
  reserves: CompoundReserve[];
}

export interface CompoundMarketHistoryResponse {
  points: CompoundMarketPoint[];
}

export async function fetchCompoundMarketHistory(
  version: string,
  market: string,
  start: string,
  end: string,
): Promise<CompoundMarketPoint[]> {
  const data = await apiFetch<CompoundMarketHistoryResponse>(
    `/compound/market/state/period?version=${version}&market=${market}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&detail=true`
  );
  if (!data.points || !Array.isArray(data.points)) {
    throw new Error('Invalid Compound market history response format');
  }
  return data.points;
}
