import { apiFetch } from './client';

// ---------- 类型定义 ----------

/** 用户在 Aave 上的仓位概览，对应 /position 接口返回结构。 */
export interface UserPosition {
  address: string;
  eth_collateral_amount: string;
  eth_collateral_usd: string;
  total_collateral_usd: string;
  available_borrows_usd: string;
  total_debt_usd: string;
  health_factor: string;
  ltv: string;
  liq_threshold: string;
  liq_price: string;
  weth_debt_amount: string;
  weth_debt_usd: string;
  liq_price_rise: string;
  reserves: {
    symbol: string;
    token_address: string;
    price_usd: string;
    supply_amount: string;
    supply_usd: string;
    stable_debt_amount: string;
    variable_debt_amount: string;
    total_debt_amount: string;
    total_debt_usd: string;
    use_as_collateral: boolean;
  }[];
}

export type BorrowPosition = UserPosition; // 统一使用 UserPosition

// ---------- API 函数 ----------

/**
 * 获取指定地址在 Aave 上的仓位概览。
 * @param address  以太坊地址
 * @param version  协议版本（v2 / v3），不传则由后端使用默认值
 */
export async function fetchUserPosition(address: string, version?: string): Promise<UserPosition> {
  const query = version ? `address=${address}&version=${version}` : `address=${address}`;
  return apiFetch<UserPosition>(`/aave/position?${query}`);
}

/**
 * 获取指定地址在 Aave 上的借贷仓位详情。
 * @deprecated 请使用 fetchUserPosition，后端接口已合并
 */
export async function fetchUserBorrowPosition(
  address: string,
  version: string,
): Promise<UserPosition> {
  // 为了兼容旧代码调用，暂时保留函数签名，但内部逻辑可能需要调整或直接废弃
  // 根据用户需求，现在统一调用 /position 接口
  return fetchUserPosition(address, version);
}
