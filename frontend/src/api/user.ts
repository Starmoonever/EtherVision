import { apiFetch } from './client';

// ---------- 类型定义 ----------

/** 用户在 Aave 上的仓位概览，对应 /user/position 接口返回结构。 */
export interface UserPosition {
  eth_collateral_amount: string;
  eth_collateral_usd: string;
  total_collateral_usd: string;
  available_borrows_usd: string;
  total_debt_usd: string;
  health_factor: string;
  ltv: string;
  liq_threshold: string;
  liq_price: string;
}

// ---------- API 函数 ----------

/**
 * 获取指定地址在 Aave 上的仓位概览。
 * @param address  以太坊地址
 * @param version  协议版本（v2 / v3），不传则由后端使用默认值
 */
export async function fetchUserPosition(
  address: string,
  version?: string,
): Promise<UserPosition> {
  const query = version
    ? `address=${address}&version=${version}`
    : `address=${address}`;
  return apiFetch<UserPosition>(`/user/position?${query}`);
}
