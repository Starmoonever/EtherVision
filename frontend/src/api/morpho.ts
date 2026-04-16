import { apiFetch } from './client';
import type { DataWithMeta } from './requestMeta';

const MORPHO_CACHE_TTL_MS = 5 * 60 * 1000;

export type MorphoProtocol = 'blue';

export interface MorphoPositionAsset {
  role: 'loan' | 'collateral' | string;
  token_address: string;
  symbol: string;
  decimals: number;
  amount: string;
}

export interface MorphoPositionResponse {
  protocol: string;
  market_type: string;
  chain: string;
  morpho_address: string;
  market_id: string;
  address: string;
  block_number: number;
  block_timestamp: string;
  has_position: boolean;
  is_healthy: boolean;
  loan_token: string;
  loan_token_symbol: string;
  loan_token_decimals: number;
  collateral_token: string;
  collateral_token_symbol: string;
  collateral_token_decimals: number;
  oracle: string;
  irm: string;
  lltv: string;
  lltv_ratio: string;
  supply_shares: string;
  borrow_shares: string;
  collateral_assets_raw: string;
  supply_assets: string;
  borrow_assets: string;
  collateral_assets: string;
  collateral_value_in_loan_asset: string;
  max_borrowable_in_loan_asset: string;
  health_factor: string | null;
  price_quote: string;
  data_source: string;
  assets: MorphoPositionAsset[];
}

export interface MorphoPositionReplayPoint {
  tx_hash: string;
  timestamp: string;
  block_number: number;
  operation_type: string | null;
  brief: string;
  has_position: boolean;
  is_healthy: boolean;
  collateral_value_in_loan_asset: string;
  borrow_assets: string;
  health_factor: string | null;
  assets: MorphoPositionAsset[];
}

export interface MorphoPositionReplayResponse {
  protocol: string;
  market_type: string;
  chain: string;
  market_id: string;
  address: string;
  from_time: string;
  to_time: string;
  data_source: string;
  total_points: number;
  total_tx_count: number;
  cache_hit_rate: string;
  points: MorphoPositionReplayPoint[];
}

const morphoPositionCache = new Map<string, { fetchedAt: number; data: MorphoPositionResponse }>();
const morphoPositionInflight = new Map<string, Promise<MorphoPositionResponse>>();
const morphoReplayCache = new Map<
  string,
  { fetchedAt: number; data: MorphoPositionReplayResponse }
>();
const morphoReplayInflight = new Map<string, Promise<MorphoPositionReplayResponse>>();

function buildMorphoPositionCacheKey(
  address: string,
  marketId: string,
  protocol: MorphoProtocol,
): string {
  return `${protocol}:${marketId.toLowerCase()}:${address.toLowerCase()}`;
}

export async function fetchMorphoPosition(
  address: string,
  marketId: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean } = {},
): Promise<MorphoPositionResponse> {
  const result = await fetchMorphoPositionWithMeta(address, marketId, protocol, options);
  return result.data;
}

export async function fetchMorphoPositionWithMeta(
  address: string,
  marketId: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean } = {},
): Promise<DataWithMeta<MorphoPositionResponse>> {
  const key = buildMorphoPositionCacheKey(address, marketId, protocol);
  const cached = morphoPositionCache.get(key);
  const force = options.force === true;

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoPositionInflight.get(key);
  if (!force && inflight) {
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
    market_id: marketId,
    protocol,
  });

  const request = apiFetch<MorphoPositionResponse>(`/morpho/position?${params.toString()}`)
    .then((data) => {
      morphoPositionCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoPositionInflight.delete(key);
    });

  morphoPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

function buildMorphoReplayCacheKey(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol,
  detail: boolean,
): string {
  return [
    protocol,
    marketId.toLowerCase(),
    address.toLowerCase(),
    start,
    end,
    detail ? 'detail' : 'summary',
  ].join(':');
}

export async function fetchMorphoPositionReplay(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean; detail?: boolean; useCache?: boolean } = {},
): Promise<MorphoPositionReplayResponse> {
  const result = await fetchMorphoPositionReplayWithMeta(
    address,
    marketId,
    start,
    end,
    protocol,
    options,
  );
  return result.data;
}

export async function fetchMorphoPositionReplayWithMeta(
  address: string,
  marketId: string,
  start: string,
  end: string,
  protocol: MorphoProtocol = 'blue',
  options: { force?: boolean; detail?: boolean; useCache?: boolean } = {},
): Promise<DataWithMeta<MorphoPositionReplayResponse>> {
  const detail = options.detail === true;
  const useCache = options.useCache !== false;
  const key = buildMorphoReplayCacheKey(address, marketId, start, end, protocol, detail);
  const cached = morphoReplayCache.get(key);
  const force = options.force === true;

  if (!force && cached && Date.now() - cached.fetchedAt < MORPHO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = morphoReplayInflight.get(key);
  if (!force && inflight) {
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
    market_id: marketId,
    start,
    end,
    protocol,
    use_cache: String(useCache),
    detail: String(detail),
  });

  const request = apiFetch<MorphoPositionReplayResponse>(
    `/morpho/position/replay?${params.toString()}`,
  )
    .then((data) => {
      morphoReplayCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      morphoReplayInflight.delete(key);
    });

  morphoReplayInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}
