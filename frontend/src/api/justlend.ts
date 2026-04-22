import { apiFetch } from './client';
import type { DataWithMeta } from './requestMeta';

const JUSTLEND_CACHE_TTL_MS = 5 * 60 * 1000;

export interface JustLendPositionAsset {
  asset_address: string;
  symbol: string | null;
  position_type: string;
  is_collateral: boolean;
  amount: string;
  price_usd: string;
  value_usd: string;
}

export interface JustLendPositionResponse {
  protocol: string;
  chain: string;
  address: string;
  snapshot_at: string;
  block_timestamp: string;
  total_deposit_usd: string;
  total_collateral_usd: string;
  total_debt_usd: string;
  available_borrow_usd: string;
  health_factor: string;
  ltv: string;
  liquidation_threshold: string;
  data_source: string;
  assets: JustLendPositionAsset[];
}

export interface JustLendPositionReplayAsset {
  asset_address: string;
  symbol: string | null;
  position_type: string;
  is_collateral: boolean;
  amount: string;
  price_usd: string;
  value_usd: string;
}

export interface JustLendPositionReplayPoint {
  tx_hash: string;
  timestamp: string;
  block_number: number;
  market: string;
  symbol: string;
  operation_type: string;
  total_collateral_usd: string;
  total_debt_usd: string;
  available_borrow_usd: string;
  discounted_collateral_usd: string;
  liquidation_buffer_usd: string;
  health_factor: string;
  ltv: string;
  liquidation_threshold: string;
  brief: string;
  assets: JustLendPositionReplayAsset[];
}

export interface JustLendPositionReplayResponse {
  address: string;
  protocol: string;
  from_time: string;
  to_time: string;
  data_source: string;
  points: JustLendPositionReplayPoint[];
  total_points: number;
  total_tx_count: number;
  cache_hit_rate: string;
}

export interface JustLendStatusResponse {
  module: string;
  status: string;
  chain: string;
  supported_protocols: string[];
  message: string;
}

export interface JustLendMarketItem {
  market: string;
  symbol: string;
  underlying_address: string;
  underlying_symbol: string;
  updated_at: string;
}

export interface JustLendMarketsResponse {
  chain: string;
  markets: JustLendMarketItem[];
}

export interface JustLendMarketStateResponse {
  chain: string;
  protocol: string;
  market: string;
  market_type: string;
  symbol: string;
  underlying_address: string;
  underlying_symbol: string;
  underlying_decimals: number;
  jtoken_decimals: number;
  comptroller_address: string;
  oracle_address: string;
  is_listed: boolean;
  is_entered_supported: boolean;
  collateral_factor: string;
  reserve_factor: string;
  borrow_cap: string;
  supply_cap: string;
  exchange_rate: string;
  cash: string;
  total_borrows: string;
  total_reserves: string;
  total_supply: string;
  utilization: string;
  borrow_rate: string;
  supply_rate: string;
  underlying_price_in_trx: string;
  price_usd: string;
  timestamp: string;
  block_timestamp: string;
  block_number: number;
  extra: Record<string, unknown>;
}

export interface JustLendMarketStatePeriodResponse {
  points: JustLendMarketStateResponse[];
}

export interface JustLendPositionAnalysisAsset {
  asset_address: string;
  symbol: string;
  side: string;
  amount: string;
  price_usd: string;
  value_usd: string;
}

export interface JustLendPositionAnalysisItem {
  protocol: string;
  chain: string;
  address: string;
  snapshot_at: string;
  block_timestamp: string;
  total_supply_usd: string;
  total_collateral_usd?: string;
  total_borrow_usd: string;
  health_factor: string;
  ltv: string;
  liquidation_threshold: string;
  matched_asset_value_usd: string;
  assets: JustLendPositionAnalysisAsset[];
}

export interface JustLendPositionAnalysisResponse {
  items: JustLendPositionAnalysisItem[];
  page: number;
  page_size: number;
  total: number;
  sort_by: string;
  order: string;
  side: string;
  asset: string | null;
}

const justLendPositionCache = new Map<
  string,
  { fetchedAt: number; data: JustLendPositionResponse }
>();
const justLendPositionInflight = new Map<string, Promise<JustLendPositionResponse>>();
let justLendStatusCache: { fetchedAt: number; data: JustLendStatusResponse } | null = null;
let justLendStatusInflight: Promise<JustLendStatusResponse> | null = null;
let justLendMarketsCache: { fetchedAt: number; data: JustLendMarketsResponse } | null = null;
let justLendMarketsInflight: Promise<JustLendMarketsResponse> | null = null;
const justLendMarketStateCache = new Map<
  string,
  { fetchedAt: number; data: JustLendMarketStateResponse }
>();
const justLendMarketStateInflight = new Map<string, Promise<JustLendMarketStateResponse>>();
const justLendMarketStatePeriodCache = new Map<
  string,
  { fetchedAt: number; data: JustLendMarketStatePeriodResponse }
>();
const justLendMarketStatePeriodInflight = new Map<
  string,
  Promise<JustLendMarketStatePeriodResponse>
>();
const justLendPositionAnalysisCache = new Map<
  string,
  { fetchedAt: number; data: JustLendPositionAnalysisResponse }
>();
const justLendPositionAnalysisInflight = new Map<
  string,
  Promise<JustLendPositionAnalysisResponse>
>();
const justLendReplayCache = new Map<
  string,
  { fetchedAt: number; data: JustLendPositionReplayResponse }
>();
const justLendReplayInflight = new Map<string, Promise<JustLendPositionReplayResponse>>();

export async function fetchJustLendPosition(
  address: string,
  protocol: string = 'trx',
): Promise<JustLendPositionResponse> {
  const result = await fetchJustLendPositionWithMeta(address, protocol);
  return result.data;
}

export async function fetchJustLendPositionWithMeta(
  address: string,
  protocol: string = 'trx',
): Promise<DataWithMeta<JustLendPositionResponse>> {
  const key = `${protocol}:${address.toLowerCase()}`;
  const cached = justLendPositionCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = justLendPositionInflight.get(key);
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
    address,
    protocol,
  });

  const request = apiFetch<JustLendPositionResponse>(`/justlend/position?${params.toString()}`)
    .then((data) => {
      justLendPositionCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      justLendPositionInflight.delete(key);
    });

  justLendPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchJustLendStatusWithMeta(): Promise<DataWithMeta<JustLendStatusResponse>> {
  if (justLendStatusCache && Date.now() - justLendStatusCache.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: justLendStatusCache.data,
      meta: {
        fetchedAt: justLendStatusCache.fetchedAt,
        fromCache: true,
      },
    };
  }

  if (justLendStatusInflight) {
    return justLendStatusInflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<JustLendStatusResponse>('/justlend/status')
    .then((data) => {
      justLendStatusCache = { fetchedAt: Date.now(), data };
      return data;
    })
    .finally(() => {
      justLendStatusInflight = null;
    });

  justLendStatusInflight = request;
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchJustLendMarketsWithMeta(): Promise<
  DataWithMeta<JustLendMarketsResponse>
> {
  if (justLendMarketsCache && Date.now() - justLendMarketsCache.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: justLendMarketsCache.data,
      meta: {
        fetchedAt: justLendMarketsCache.fetchedAt,
        fromCache: true,
      },
    };
  }

  if (justLendMarketsInflight) {
    return justLendMarketsInflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<JustLendMarketsResponse>('/justlend/markets')
    .then((data) => {
      justLendMarketsCache = { fetchedAt: Date.now(), data };
      return data;
    })
    .finally(() => {
      justLendMarketsInflight = null;
    });

  justLendMarketsInflight = request;
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchJustLendMarketStateWithMeta(
  market: string,
  date?: string,
): Promise<DataWithMeta<JustLendMarketStateResponse>> {
  const key = `${market.toLowerCase()}:${date ?? 'latest'}`;
  const cached = justLendMarketStateCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = justLendMarketStateInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({ market });
  if (date) {
    params.set('date', date);
  }

  const request = apiFetch<JustLendMarketStateResponse>(
    `/justlend/market/state?${params.toString()}`,
  )
    .then((data) => {
      justLendMarketStateCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      justLendMarketStateInflight.delete(key);
    });

  justLendMarketStateInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

interface JustLendMarketStatePeriodParams {
  market: string;
  start: string;
  end: string;
}

export async function fetchJustLendMarketStatePeriodWithMeta({
  market,
  start,
  end,
}: JustLendMarketStatePeriodParams): Promise<DataWithMeta<JustLendMarketStatePeriodResponse>> {
  const key = `${market.toLowerCase()}:${start}:${end}`;
  const cached = justLendMarketStatePeriodCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = justLendMarketStatePeriodInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({ market, start, end });
  const request = apiFetch<JustLendMarketStatePeriodResponse>(
    `/justlend/market/state/period?${params.toString()}`,
  )
    .then((data) => {
      justLendMarketStatePeriodCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      justLendMarketStatePeriodInflight.delete(key);
    });

  justLendMarketStatePeriodInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export interface JustLendPositionAnalysisParams {
  page?: number;
  pageSize?: number;
  sortBy?:
    | 'health_factor'
    | 'total_supply_usd'
    | 'total_collateral_usd'
    | 'total_borrow_usd'
    | 'asset_value_usd';
  order?: 'asc' | 'desc';
  positionType?: 'all' | 'supply' | 'borrow';
  isCollateral?: boolean | null;
  asset?: string | null;
  detail?: boolean;
  address?: string | null;
  forceRefresh?: boolean;
}

export async function fetchJustLendPositionAnalysisWithMeta({
  page = 1,
  pageSize = 50,
  sortBy = 'health_factor',
  order = 'desc',
  positionType = 'all',
  isCollateral = null,
  asset = null,
  detail = false,
  address = null,
  forceRefresh = false,
}: JustLendPositionAnalysisParams): Promise<DataWithMeta<JustLendPositionAnalysisResponse>> {
  const key = JSON.stringify({
    page,
    pageSize,
    sortBy,
    order,
    positionType,
    isCollateral,
    asset,
    detail,
    address,
  });
  const cached = justLendPositionAnalysisCache.get(key);
  if (!forceRefresh && cached && Date.now() - cached.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = justLendPositionAnalysisInflight.get(key);
  if (!forceRefresh && inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort_by: sortBy,
    order,
    position_type: positionType,
    detail: String(detail),
  });
  if (isCollateral !== null) {
    params.set('is_collateral', String(isCollateral));
  }
  if (asset) {
    params.set('asset', asset);
  }
  if (address) {
    params.set('address', address);
  }

  const request = apiFetch<JustLendPositionAnalysisResponse>(
    `/justlend/positions?${params.toString()}`,
  )
    .then((data) => {
      justLendPositionAnalysisCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      justLendPositionAnalysisInflight.delete(key);
    });

  justLendPositionAnalysisInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

interface JustLendPositionReplayParams {
  address: string;
  start: string;
  end: string;
  protocol?: string;
  useCache?: boolean;
  detail?: boolean;
}

export async function fetchJustLendPositionReplay(
  params: JustLendPositionReplayParams,
): Promise<JustLendPositionReplayResponse> {
  const result = await fetchJustLendPositionReplayWithMeta(params);
  return result.data;
}

export async function fetchJustLendPositionReplayWithMeta(
  params: JustLendPositionReplayParams,
): Promise<DataWithMeta<JustLendPositionReplayResponse>> {
  const { address, start, end, protocol = 'trx', useCache = true, detail = false } = params;

  const key = `${protocol}:${address.toLowerCase()}:${start}:${end}:${useCache ? '1' : '0'}:${detail ? '1' : '0'}`;
  const cached = justLendReplayCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < JUSTLEND_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = justLendReplayInflight.get(key);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const searchParams = new URLSearchParams({
    address,
    start,
    end,
    protocol,
    use_cache: String(useCache),
    detail: String(detail),
  });

  const request = apiFetch<JustLendPositionReplayResponse>(
    `/justlend/position/replay?${searchParams.toString()}`,
  )
    .then((data) => {
      justLendReplayCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      justLendReplayInflight.delete(key);
    });

  justLendReplayInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}
