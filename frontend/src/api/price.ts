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

export interface PriceQueryOptions {
  chain?: 'ethereum' | 'tron';
}

const PRICE_CACHE_TTL_MS = 5 * 60 * 1000;

const priceCache = new Map<string, { fetchedAt: number; value: number }>();
const priceMissCache = new Map<string, { fetchedAt: number; message: string }>();
const priceInflight = new Map<string, Promise<number>>();
const pricePeriodCache = new Map<string, { fetchedAt: number; value: PricePeriodItem[] }>();
const pricePeriodMissCache = new Map<string, { fetchedAt: number; message: string }>();
const pricePeriodInflight = new Map<string, Promise<PricePeriodItem[]>>();

function isEvmAddress(value: string): boolean {
  return /^0x[a-fA-F0-9]{40}$/.test(value.trim());
}

function isTronAddress(value: string): boolean {
  return /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(value.trim());
}

function buildPriceQueryParam(value: string, options?: PriceQueryOptions): string {
  const normalized = value.trim();
  const chainParam = options?.chain ? `&chain=${encodeURIComponent(options.chain)}` : '';
  if (isEvmAddress(normalized)) {
    return `address=${encodeURIComponent(normalized)}${chainParam}`;
  }
  if (isTronAddress(normalized)) {
    return `address=${encodeURIComponent(normalized)}${chainParam || '&chain=tron'}`;
  }
  return `symbol=${encodeURIComponent(normalized)}${chainParam}`;
}

// ---------- API 函数 ----------

/**
 * 获取任意资产当前价格（USD）。
 */
export async function fetchAssetPrice(asset: string, options?: PriceQueryOptions): Promise<number> {
  const result = await fetchAssetPriceWithMeta(asset, options);
  return result.data;
}

export async function fetchAssetPriceWithMeta(
  asset: string,
  options?: PriceQueryOptions,
): Promise<DataWithMeta<number>> {
  const normalizedAsset = asset.trim();
  const key = `now:${options?.chain || 'default'}:${normalizedAsset.toLowerCase()}`;
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
  const missed = priceMissCache.get(key);
  if (missed) {
    throw new Error(missed.message);
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

  const request = apiFetch<PriceResponse>(
    `/price?${buildPriceQueryParam(normalizedAsset, options)}&time=now`,
  )
    .then((data) => {
      const price = parseFloat(data.price_usd);
      if (isNaN(price)) throw new Error(`Invalid ${asset} price response`);
      priceMissCache.delete(key);
      priceCache.set(key, { fetchedAt: Date.now(), value: price });
      return price;
    })
    .catch((error) => {
      const message = error instanceof Error ? error.message : `无法获取 ${asset} 价格`;
      priceMissCache.set(key, { fetchedAt: Date.now(), message });
      throw error;
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
  options?: PriceQueryOptions,
): Promise<PricePeriodItem[]> {
  const result = await fetchAssetPricePeriodWithMeta(asset, start, end, interval, options);
  return result.data;
}

export async function fetchAssetPricePeriodWithMeta(
  asset: string,
  start: string,
  end: string,
  interval: number,
  options?: PriceQueryOptions,
): Promise<DataWithMeta<PricePeriodItem[]>> {
  const normalizedAsset = asset.trim();
  const key = `${options?.chain || 'default'}|${normalizedAsset.toLowerCase()}|${start}|${end}|${interval}`;
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
  const missed = pricePeriodMissCache.get(key);
  if (missed) {
    throw new Error(missed.message);
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
    `/price/period?${buildPriceQueryParam(normalizedAsset, options)}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&interval=${interval}`,
  )
    .then((data) => {
      if (!data.prices || !Array.isArray(data.prices)) {
        throw new Error(`Invalid ${asset} price period response format`);
      }
      pricePeriodMissCache.delete(key);
      pricePeriodCache.set(key, { fetchedAt: Date.now(), value: data.prices });
      return data.prices;
    })
    .catch((error) => {
      const message = error instanceof Error ? error.message : `无法获取 ${asset} 历史价格`;
      pricePeriodMissCache.set(key, { fetchedAt: Date.now(), message });
      throw error;
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
