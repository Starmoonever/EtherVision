import { apiFetch } from './client';
import type { DataWithMeta } from './requestMeta';

const JUSTLEND_CACHE_TTL_MS = 5 * 60 * 1000;

export interface JustLendPositionAsset {
  asset_address: string;
  symbol: string | null;
  side: string;
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
  total_collateral_usd: string;
  total_debt_usd: string;
  available_borrow_usd: string;
  health_factor: string;
  ltv: string;
  liquidation_threshold: string;
  data_source: string;
  assets: JustLendPositionAsset[];
}

const justLendPositionCache = new Map<
  string,
  { fetchedAt: number; data: JustLendPositionResponse }
>();
const justLendPositionInflight = new Map<string, Promise<JustLendPositionResponse>>();

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
