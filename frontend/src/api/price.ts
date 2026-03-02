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
 * 获取 ETH 当前价格（USD）。
 */
export async function fetchEthPrice(): Promise<number> {
  const data = await apiFetch<PriceResponse>('/price?asset=eth&time=now');
  const price = parseFloat(data.price_usd);
  if (isNaN(price)) throw new Error('Invalid ETH price response');
  return price;
}

/**
 * 获取 ETH 历史价格序列。
 * @param start    起始时间字符串，格式 "YYYY-MM-DD HH:MM:SS"
 * @param end      结束时间字符串
 * @param interval 间隔（分钟）
 */
export async function fetchEthPricePeriod(
  start: string,
  end: string,
  interval: number,
): Promise<PricePeriodItem[]> {
  const data = await apiFetch<PricePeriodResponse>(
    `/price/period?asset=eth&start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&interval=${interval}`,
  );
  if (!data.prices || !Array.isArray(data.prices)) {
    throw new Error('Invalid price period response format');
  }
  return data.prices;
}
