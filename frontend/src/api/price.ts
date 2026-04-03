import { apiFetch } from './client';
import type { DataWithMeta } from './requestMeta';

// ---------- 类型定义 ----------

export interface PriceResponse {
  asset: string;
  price_usd: string;
  token_address: string;
  timestamp: string;
  source: string;
}

export interface PricePeriodItem {
  timestamp: string;
  price_usd: string;
}

interface PricePeriodResponse {
  prices: PricePeriodItem[];
}

const PRICE_CACHE_TTL_MS = 5 * 60 * 1000;

const priceCache = new Map<string, { fetchedAt: number; value: number }>();
const priceInflight = new Map<string, Promise<number>>();
const pricePeriodCache = new Map<string, { fetchedAt: number; value: PricePeriodItem[] }>();
const pricePeriodInflight = new Map<string, Promise<PricePeriodItem[]>>();

// ---------- API 函数 ----------

/**
 * 获取任意资产当前价格（USD）。
 */
export async function fetchAssetPrice(asset: string): Promise<number> {
  const result = await fetchAssetPriceWithMeta(asset);
  return result.data;
}

export async function fetchAssetPriceWithMeta(asset: string): Promise<DataWithMeta<number>> {
  const normalizedAsset = asset.toLowerCase();
  const key = `now:${normalizedAsset}`;
  const cached = priceCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < PRICE_CACHE_TTL_MS) {
    return {
      data: cached.value,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = priceInflight.get(key);
  if (inflight) {
    return inflight.then((value) => ({
      data: value,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<PriceResponse>(`/price?asset=${normalizedAsset}&time=now`)
    .then((data) => {
      const price = parseFloat(data.price_usd);
      if (isNaN(price)) throw new Error(`Invalid ${asset} price response`);
      priceCache.set(key, { fetchedAt: Date.now(), value: price });
      return price;
    })
    .finally(() => {
      priceInflight.delete(key);
    });

  priceInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

/**
 * 获取任意资产历史价格序列。
 */
export async function fetchAssetPricePeriod(
  asset: string,
  start: string,
  end: string,
  interval: number,
): Promise<PricePeriodItem[]> {
  const result = await fetchAssetPricePeriodWithMeta(asset, start, end, interval);
  return result.data;
}

export async function fetchAssetPricePeriodWithMeta(
  asset: string,
  start: string,
  end: string,
  interval: number,
): Promise<DataWithMeta<PricePeriodItem[]>> {
  const normalizedAsset = asset.toLowerCase();
  const key = `${normalizedAsset}|${start}|${end}|${interval}`;
  const cached = pricePeriodCache.get(key);
  if (cached && Date.now() - cached.fetchedAt < PRICE_CACHE_TTL_MS) {
    return {
      data: cached.value,
      meta: {
        fetchedAt: cached.fetchedAt,
        fromCache: true,
      },
    };
  }

  const inflight = pricePeriodInflight.get(key);
  if (inflight) {
    return inflight.then((value) => ({
      data: value,
      meta: {
        fetchedAt: Date.now(),
        fromCache: false,
      },
    }));
  }

  const request = apiFetch<PricePeriodResponse>(
    `/price/period?asset=${normalizedAsset}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&interval=${interval}`,
  )
    .then((data) => {
      if (!data.prices || !Array.isArray(data.prices)) {
        throw new Error(`Invalid ${asset} price period response format`);
      }
      pricePeriodCache.set(key, { fetchedAt: Date.now(), value: data.prices });
      return data.prices;
    })
    .finally(() => {
      pricePeriodInflight.delete(key);
    });

  pricePeriodInflight.set(key, request);
  const data = await request;
  return {
    data,
    meta: {
      fetchedAt: Date.now(),
      fromCache: false,
    },
  };
}

export async function fetchEthPrice(): Promise<number> {
  return fetchAssetPrice('eth');
}

export async function fetchEthPriceWithMeta(): Promise<DataWithMeta<number>> {
  return fetchAssetPriceWithMeta('eth');
}

export async function fetchEthPricePeriod(
  start: string,
  end: string,
  interval: number,
): Promise<PricePeriodItem[]> {
  return fetchAssetPricePeriod('eth', start, end, interval);
}

export async function fetchEthPricePeriodWithMeta(
  start: string,
  end: string,
  interval: number,
): Promise<DataWithMeta<PricePeriodItem[]>> {
  return fetchAssetPricePeriodWithMeta('eth', start, end, interval);
}
