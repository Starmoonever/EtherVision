import { apiFetch } from './client';
import type { DataWithMeta } from './requestMeta';

const MAKERDAO_CACHE_TTL_MS = 5 * 60 * 1000;

export interface MakerDaoPositionAsset {
  role: string;
  token_address: string;
  symbol: string;
  amount: string;
  value_usd: string;
}

export interface MakerDaoVaultPosition {
  vault_uid: string;
  vault_id: number;
  vault_type: string;
  ilk: string;
  urn_address: string;
  owner_address: string;
  proxy_address: string;
  block_number: number;
  block_timestamp: string;
  snapshot_at: string;
  collateral_symbol: string;
  collateral_token_address: string;
  collateral_amount: string;
  collateral_value_usd: string;
  debt_symbol: string;
  debt_token_address: string;
  debt_amount: string;
  debt_value_usd: string;
  liquidation_ratio: string;
  liquidation_price_usd: string;
  health_factor: string;
  is_healthy: boolean;
  data_source: string;
  assets: MakerDaoPositionAsset[];
}

export interface MakerDaoPositionResponse {
  chain: string;
  protocol: string;
  address: string;
  total_positions: number;
  positions: MakerDaoVaultPosition[];
}

export interface MakerDaoSystemPositionResponse {
  chain: string;
  protocol: string;
  position_type: string;
  position_uid: string;
  ilk: string;
  urn_address: string;
  block_number: number;
  block_timestamp: string;
  snapshot_at: string;
  collateral_symbol: string;
  collateral_token_address: string;
  collateral_amount: string;
  collateral_value_usd: string;
  debt_symbol: string;
  debt_token_address: string;
  debt_amount: string;
  debt_value_usd: string;
  liquidation_ratio: string;
  liquidation_price_usd: string;
  health_factor: string;
  is_healthy: boolean;
  data_source: string;
}

export interface MakerDaoSystemPositionsResponse {
  chain: string;
  protocol: string;
  urn_address: string;
  total_positions: number;
  ilks: string[];
  positions: MakerDaoSystemPositionResponse[];
}

export interface MakerDaoIlkItem {
  ilk: string;
  vault_type: string;
  gem_symbol: string | null;
  gem_address: string | null;
  debt_ceiling?: string | null;
  liquidation_ratio?: string | null;
  liquidation_penalty?: string | null;
  stability_fee?: string | null;
  dust?: string | null;
  updated_at: string;
}

export interface MakerDaoIlkListResponse {
  chain: string;
  protocol: string;
  ilks: MakerDaoIlkItem[];
}

export interface MakerDaoPositionListItem {
  position_uid: string;
  position_scope: string;
  vault_id: number | null;
  vault_type: string;
  ilk: string;
  urn_address: string;
  owner_address: string | null;
  proxy_address: string | null;
  block_number: number | null;
  block_timestamp: string;
  snapshot_at: string;
  collateral_symbol: string | null;
  collateral_token_address: string | null;
  collateral_amount: string;
  collateral_value_usd: string | null;
  debt_symbol: string;
  debt_token_address: string | null;
  debt_amount: string;
  debt_value_usd: string | null;
  liquidation_ratio: string | null;
  liquidation_price_usd: string | null;
  health_factor: string | null;
  is_healthy: boolean;
  data_source: string;
}

export interface MakerDaoPositionsAggregates {
  total_positions: number;
  user_positions: number;
  system_positions: number;
  unhealthy_positions: number;
  total_collateral_value_usd: string;
  total_debt_value_usd: string;
  min_health_factor: string | null;
  max_health_factor: string | null;
}

export interface MakerDaoPositionsResponse {
  chain: string;
  protocol: string;
  items: MakerDaoPositionListItem[];
  page: number;
  page_size: number;
  total: number;
  sort_by: string;
  order: string;
  position_scope: string;
  include_empty: boolean;
  aggregates: MakerDaoPositionsAggregates;
}

export interface MakerDaoPositionParams {
  address: string;
  vaultId?: number | null;
  ilk?: string | null;
  includeEmpty?: boolean;
}

export interface MakerDaoPositionsParams {
  page?: number;
  pageSize?: number;
  sortBy?: string;
  order?: 'asc' | 'desc';
  positionScope?: 'all' | 'user' | 'system';
  ilk?: string | null;
  isHealthy?: boolean | null;
  includeEmpty?: boolean;
}

export interface MakerDaoSystemPositionParams {
  urn: string;
  ilk?: string | null;
}

const MAKERDAO_ILKS_CACHE_KEY = 'makerdao_ilks';

const makerDaoPositionCache = new Map<
  string,
  { fetchedAt: number; data: MakerDaoPositionResponse }
>();
const makerDaoPositionInflight = new Map<string, Promise<MakerDaoPositionResponse>>();
const makerDaoSystemPositionCache = new Map<
  string,
  { fetchedAt: number; data: MakerDaoSystemPositionResponse }
>();
const makerDaoSystemPositionInflight = new Map<string, Promise<MakerDaoSystemPositionResponse>>();
const makerDaoIlksCache = new Map<string, { fetchedAt: number; data: MakerDaoIlkListResponse }>();
const makerDaoIlksInflight = new Map<string, Promise<MakerDaoIlkListResponse>>();
const makerDaoPositionsCache = new Map<
  string,
  { fetchedAt: number; data: MakerDaoPositionsResponse }
>();
const makerDaoPositionsInflight = new Map<string, Promise<MakerDaoPositionsResponse>>();

function normalizeMakerDaoSystemPositionResponse(
  data: MakerDaoSystemPositionResponse | MakerDaoSystemPositionsResponse,
): MakerDaoSystemPositionResponse {
  if ('positions' in data) {
    const firstPosition = data.positions[0];
    if (!firstPosition) {
      throw new Error('MakerDAO 系统仓位未返回 positions 数据');
    }
    return firstPosition;
  }

  return data;
}

function buildMakerDaoPositionKey({
  address,
  vaultId = null,
  ilk = null,
  includeEmpty = false,
}: MakerDaoPositionParams): string {
  return JSON.stringify({
    address: address.toLowerCase(),
    vaultId,
    ilk: ilk?.trim().toLowerCase() || null,
    includeEmpty,
  });
}

function buildMakerDaoSystemPositionKey({ urn, ilk = null }: MakerDaoSystemPositionParams): string {
  return JSON.stringify({
    urn: urn.trim().toLowerCase(),
    ilk: ilk?.trim().toUpperCase() || null,
  });
}

function buildMakerDaoPositionsKey({
  page = 1,
  pageSize = 50,
  sortBy = 'health_factor',
  order = 'asc',
  positionScope = 'all',
  ilk = null,
  isHealthy = null,
  includeEmpty = false,
}: MakerDaoPositionsParams): string {
  return JSON.stringify({
    page,
    pageSize,
    sortBy,
    order,
    positionScope,
    ilk: ilk?.trim().toUpperCase() || null,
    isHealthy,
    includeEmpty,
  });
}

export async function fetchMakerDaoPosition(
  params: MakerDaoPositionParams,
): Promise<MakerDaoPositionResponse> {
  const result = await fetchMakerDaoPositionWithMeta(params);
  return result.data;
}

export async function fetchMakerDaoPositionWithMeta(
  params: MakerDaoPositionParams,
): Promise<DataWithMeta<MakerDaoPositionResponse>> {
  const key = buildMakerDaoPositionKey(params);
  const cached = makerDaoPositionCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < MAKERDAO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = makerDaoPositionInflight.get(key);
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
    address: params.address,
    include_empty: String(params.includeEmpty ?? false),
  });
  if (params.vaultId !== null && params.vaultId !== undefined) {
    searchParams.set('vault_id', String(params.vaultId));
  }
  if (params.ilk?.trim()) {
    searchParams.set('ilk', params.ilk.trim());
  }

  const request = apiFetch<MakerDaoPositionResponse>(
    `/makerdao/position?${searchParams.toString()}`,
  )
    .then((data) => {
      makerDaoPositionCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      makerDaoPositionInflight.delete(key);
    });

  makerDaoPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMakerDaoSystemPosition(
  params: MakerDaoSystemPositionParams,
): Promise<MakerDaoSystemPositionResponse> {
  const result = await fetchMakerDaoSystemPositionWithMeta(params);
  return result.data;
}

export async function fetchMakerDaoSystemPositionWithMeta(
  params: MakerDaoSystemPositionParams,
): Promise<DataWithMeta<MakerDaoSystemPositionResponse>> {
  const key = buildMakerDaoSystemPositionKey(params);
  const cached = makerDaoSystemPositionCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < MAKERDAO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = makerDaoSystemPositionInflight.get(key);
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
    urn: params.urn,
  });
  if (params.ilk?.trim()) {
    searchParams.set('ilk', params.ilk.trim());
  }

  const request = apiFetch<MakerDaoSystemPositionResponse | MakerDaoSystemPositionsResponse>(
    `/makerdao/system/position?${searchParams.toString()}`,
  )
    .then((data) => {
      const normalized = normalizeMakerDaoSystemPositionResponse(data);
      makerDaoSystemPositionCache.set(key, { fetchedAt: Date.now(), data: normalized });
      return normalized;
    })
    .finally(() => {
      makerDaoSystemPositionInflight.delete(key);
    });

  makerDaoSystemPositionInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMakerDaoIlks(): Promise<MakerDaoIlkListResponse> {
  const result = await fetchMakerDaoIlksWithMeta();
  return result.data;
}

export async function fetchMakerDaoIlksWithMeta(): Promise<DataWithMeta<MakerDaoIlkListResponse>> {
  const cached = makerDaoIlksCache.get(MAKERDAO_ILKS_CACHE_KEY);
  if (cached && Date.now() - cached.fetchedAt < MAKERDAO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = makerDaoIlksInflight.get(MAKERDAO_ILKS_CACHE_KEY);
  if (inflight) {
    return inflight.then((data) => ({
      data,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<MakerDaoIlkListResponse>('/makerdao/ilks')
    .then((data) => {
      makerDaoIlksCache.set(MAKERDAO_ILKS_CACHE_KEY, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      makerDaoIlksInflight.delete(MAKERDAO_ILKS_CACHE_KEY);
    });

  makerDaoIlksInflight.set(MAKERDAO_ILKS_CACHE_KEY, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchMakerDaoPositions(
  params: MakerDaoPositionsParams = {},
): Promise<MakerDaoPositionsResponse> {
  const result = await fetchMakerDaoPositionsWithMeta(params);
  return result.data;
}

export async function fetchMakerDaoPositionsWithMeta(
  params: MakerDaoPositionsParams = {},
): Promise<DataWithMeta<MakerDaoPositionsResponse>> {
  const key = buildMakerDaoPositionsKey(params);
  const cached = makerDaoPositionsCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < MAKERDAO_CACHE_TTL_MS) {
    return {
      data: cached.data,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = makerDaoPositionsInflight.get(key);
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
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
    sort_by: params.sortBy ?? 'health_factor',
    order: params.order ?? 'asc',
    position_scope: params.positionScope ?? 'all',
    include_empty: String(params.includeEmpty ?? false),
  });
  if (params.ilk?.trim()) {
    searchParams.set('ilk', params.ilk.trim());
  }
  if (params.isHealthy !== null && params.isHealthy !== undefined) {
    searchParams.set('is_healthy', String(params.isHealthy));
  }

  const request = apiFetch<MakerDaoPositionsResponse>(
    `/makerdao/positions?${searchParams.toString()}`,
  )
    .then((data) => {
      makerDaoPositionsCache.set(key, { fetchedAt: Date.now(), data });
      return data;
    })
    .finally(() => {
      makerDaoPositionsInflight.delete(key);
    });

  makerDaoPositionsInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}
