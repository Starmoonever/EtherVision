import { apiFetch, apiFetchRaw } from './client';

// ---------- 类型定义 ----------

export interface LiqPeriodItem {
  simulated_eth_price: string;
  positions_cnt: string;
  total_liquidation_usd: string;
  total_weth_debt_amount?: string;
  total_weth_debt_usd?: string;
}

export interface LiquidationPosition {
  address: string;
  liq_price: string;
  liq_price_rise?: string;
  eth_collateral_amount?: string;
  eth_collateral_usd?: string;
  total_debt_usd?: string;
  weth_debt_amount?: string;
  weth_debt_usd?: string;
  total_collateral_usd?: string;
}

export interface LiquidationDetailResponse {
  simulated_eth_price: string;
  positions: LiquidationPosition[];
  positions_cnt: string;
  total_liquidation_usd: string;
  total_weth_debt_amount?: string;
  total_weth_debt_usd?: string;
}

export interface LiquidationDetailParams {
  limit?: number;
  offset?: number;
  orderby?: string;
  order?: 'asc' | 'desc';
}

export interface HistoricalLiquidationPoint {
  snapshot_date: string;
  liquidation_cnt: string;
  total_eth_collateral_amount: string;
  total_eth_collateral_usd: string;
  total_weth_debt_amount: string;
  total_weth_debt_usd: string;
  eth_price: string;
  sim_eth_price: string;
}

export interface HistoricalLiquidationDetailResponse extends LiquidationDetailResponse {
  snapshot_date: string;
  total_eth_collateral_amount?: string;
  total_eth_collateral_usd?: string;
  note: string;
}

export interface WaterfallTurn {
  eth_sold_amount: string;
  eth_sold_value: string;
  liquidation_accounts: string;
  liquidation_volume_usd: string;
  eth_price: string;
  eth_price_decline: string;
}

export interface WaterfallResponse {
  total_liquidation_usd: string;
  total_eth_sold_amount: string;
  total_eth_sold_value: string;
  initial_decline: string;
  cascade_decline: string;
  total_decline: string;
  total_liquidation_accounts: string;
  max_hf: string;
  liquidation_turns_cnt: string;
  liquidation_turns: WaterfallTurn[];
  note: string;
}

// ---------- API 函数 ----------

// 模块级内存缓存，页面刷新后自动清空
const _periodCache = new Map<string, { fetchedAt: number; data: LiqPeriodItem[] }>();
const _detailCache = new Map<
  string,
  { fetchedAt: number; data: LiquidationDetailResponse | null }
>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 分钟

/**
 * 获取某价格区间内各价格点的清算汇总数据。
 */
export async function fetchLiquidationPeriod(
  side: 'collateral' | 'borrow',
  version: string,
  start: number,
  end: number,
  interval: number = 1,
): Promise<LiqPeriodItem[]> {
  const key = `${side}|${version}|${Math.round(start)}|${Math.round(end)}`;
  const cached = _periodCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return cached.data;
  }

  const path =
    side === 'borrow'
      ? `/aave/borrow/liquidate/period?start=${start}&end=${end}&interval=${interval}&eth_ratio=0.4&version=${version}`
      : `/aave/liquidate/period?start=${start}&end=${end}&interval=${interval}&eth_ratio=0.4&version=${version}`;
  const data = await apiFetch<LiqPeriodItem[]>(path);
  _periodCache.set(key, { fetchedAt: Date.now(), data });
  return data;
}

/**
 * 获取某 ETH 价格点（±1%区间）的清算明细。
 * 当该价格点无数据时（HTTP 422）返回 null，而不是抛出错误。
 */
export async function fetchLiquidationDetail(
  side: 'collateral' | 'borrow',
  version: string,
  ethPrice: number,
  params: LiquidationDetailParams = {},
): Promise<LiquidationDetailResponse | null> {
  const {
    limit = 20,
    offset = 0,
    orderby = side === 'borrow' ? 'liq_price_rise' : 'liq_price',
    order = side === 'borrow' ? 'asc' : 'desc',
  } = params;
  const key = `${side}|${version}|${ethPrice.toFixed(2)}|${limit}|${offset}|${orderby}|${order}`;
  const cached = _detailCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return cached.data;
  }

  const cap = ethPrice * 0.01;
  const path =
    side === 'borrow'
      ? `/aave/borrow/liquidate?eth_price=${ethPrice - cap}&limit=${limit}&offset=${offset}&orderby=${orderby}&order=${order}&cap=${ethPrice + cap}&version=${version}`
      : `/aave/liquidate?eth_price=${ethPrice - cap}&limit=${limit}&offset=${offset}&orderby=${orderby}&order=${order}&cap=${ethPrice + cap}&version=${version}`;

  const response = await apiFetchRaw(path);
  if (response.status === 422) {
    _detailCache.set(key, { fetchedAt: Date.now(), data: null });
    return null;
  }
  if (!response.ok) throw new Error(`API error ${response.status}: ${path}`);
  const data = (await response.json()) as LiquidationDetailResponse;
  _detailCache.set(key, { fetchedAt: Date.now(), data });
  return data;
}

export async function fetchHistoricalLiquidation(
  start: string,
  end: string,
  version: string,
  simEthPriceDistance: number,
): Promise<HistoricalLiquidationPoint[]> {
  const path = `/aave/positions/period?start=${start}&end=${end}&version=${version}&interval=1&sim_eth_price_distance=${simEthPriceDistance}`;
  return apiFetch<HistoricalLiquidationPoint[]>(path);
}

export async function fetchHistoricalLiquidationDetail(
  date: string,
  version: string,
  side: 'collateral' | 'borrow',
  simEthPriceDistance: number,
  params: LiquidationDetailParams = {},
): Promise<HistoricalLiquidationDetailResponse> {
  const {
    limit = 20,
    offset = 0,
    orderby = side === 'borrow' ? 'liq_price_rise' : 'liq_price',
    order = side === 'borrow' ? 'asc' : 'desc',
  } = params;
  const path =
    `/aave/positions/period/detail?date=${date}` +
    `&version=${version}&side=${side}&sim_eth_price_distance=${simEthPriceDistance}` +
    `&limit=${limit}&offset=${offset}&orderby=${orderby}&order=${order}`;
  return apiFetch<HistoricalLiquidationDetailResponse>(path);
}

export async function fetchWaterfallLiquidation(
  version: string,
  initialPriceShockEth: number,
  date: string,
  impactK: number,
  sellPartitionEth: number,
): Promise<WaterfallResponse> {
  const path = `/aave/liquidate/waterfall?version=${version}&initial_price_shock_eth=${initialPriceShockEth}&date=${date}&impact_k=${impactK}&sell_partition_eth=${sellPartitionEth}`;
  return apiFetch<WaterfallResponse>(path);
}
