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

export interface MakerDaoPositionParams {
  address: string;
  vaultId?: number | null;
  ilk?: string | null;
  includeEmpty?: boolean;
}

const makerDaoPositionCache = new Map<
  string,
  { fetchedAt: number; data: MakerDaoPositionResponse }
>();
const makerDaoPositionInflight = new Map<string, Promise<MakerDaoPositionResponse>>();

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
