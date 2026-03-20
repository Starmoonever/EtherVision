import { apiFetch } from './client';

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

// ---------- API 函数 ----------

/**
 * 获取任意资产当前价格（USD）。
 */
export async function fetchAssetPrice(asset: string): Promise<number> {
  const data = await apiFetch<PriceResponse>(`/price?asset=${asset.toLowerCase()}&time=now`);
  const price = parseFloat(data.price_usd);
  if (isNaN(price)) throw new Error(`Invalid ${asset} price response`);
  return price;
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
  const data = await apiFetch<PricePeriodResponse>(
    `/price/period?asset=${asset.toLowerCase()}&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&interval=${interval}`,
  );
  if (!data.prices || !Array.isArray(data.prices)) {
    throw new Error(`Invalid ${asset} price period response format`);
  }
  return data.prices;
}

export async function fetchEthPrice(): Promise<number> {
  return fetchAssetPrice('eth');
}

export async function fetchEthPricePeriod(
  start: string,
  end: string,
  interval: number,
): Promise<PricePeriodItem[]> {
  return fetchAssetPricePeriod('eth', start, end, interval);
}
