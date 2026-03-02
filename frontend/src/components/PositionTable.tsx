import { useState, useEffect } from 'react';
import { fetchUserPosition } from '../api';
import type { UserPosition as PositionData } from '../api';

// 定义用于渲染表格行的接口
interface PositionRow {
  tokenAddress: string;
  symbol: string;
  priceUSD: number;
  balance: string;
  valueUSD: number;
}

// 定义 Props 接口，要求传入 address
interface PositionTableProps {
  address: string;
}

// 2. 在函数组件定义中接收 address
export function PositionTable({ address }: PositionTableProps) {
  const [position, setPosition] = useState<PositionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 如果地址为空，不执行请求
    if (!address) return;

    const loadPositions = async () => {
      try {
        setLoading(true);
        setError(null); // 清空之前的错误
        // 从环境变量读取基础路径
        const data = await fetchUserPosition(address);
        setPosition(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : '连接后端失败');
      } finally {
        setLoading(false);
      }
    };

    loadPositions();
  }, [address]);

  // 3. 逻辑处理：将扁平对象转换为表格所需的数组格式

  if (loading) return <div className="loading">正在查询数据库...</div>;
  if (error) return <div className="error-text">错误: {error}</div>;
  if (!position) return <div className="empty-text">无数据</div>;

  // 解析数值
  const ethAmount = parseFloat(position.eth_collateral_amount || '0');
  const ethValue = parseFloat(position.eth_collateral_usd || '0');
  const debtValue = parseFloat(position.total_debt_usd || '0');

  // 构建供给列表 (仅 ETH)
  const supplies: PositionRow[] = [];
  if (ethAmount > 0) {
    supplies.push({
      tokenAddress: 'ETH',
      symbol: 'ETH',
      priceUSD: ethAmount > 0 ? ethValue / ethAmount : 0,
      balance: position.eth_collateral_amount,
      valueUSD: ethValue
    });
  }

  // 构建借贷列表 (仅显示总债务)
  const borrows: PositionRow[] = [];
  if (debtValue > 0) {
    borrows.push({
      tokenAddress: 'TOTAL_DEBT',
      symbol: 'Total Debt',
      priceUSD: 1, // 债务以 USD 计价，单价视为 1
      balance: position.total_debt_usd,
      valueUSD: debtValue
    });
  }

  return (
    <div className="positions-wrap">
      {/* ── 供给仓位 (数据来自数据库) ── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">资产 (Supplied)</span>
          <span className="badge green-badge">{supplies.length} 项</span>
        </div>

        {supplies.length === 0 ? (
          <p className="empty-text">该地址还没有抵押资产记录</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">单价 (USD)</th>
                  <th className="right">余额</th>
                  <th className="right">估值 (USD)</th>
                  <th className="center">用作抵押品</th>
                </tr>
              </thead>
              <tbody>
                {supplies.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td><span className="token-symbol">{r.symbol}</span></td>
                    <td className="right mono">${r.priceUSD.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                    <td className="right mono">{parseFloat(r.balance).toLocaleString(undefined, {minimumFractionDigits: 4, maximumFractionDigits: 4})}</td>
                    <td className="right mono bold">${r.valueUSD.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                    <td className="center">
                      <span className="pill green-pill">是</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── 借贷仓位 (数据来自数据库) ── */}
      <div className="card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span className="card-title">负债 (Borrowed)</span>
            {Number(position.available_borrows_usd) > 0 && (
              <span className="badge" style={{ backgroundColor: '#1e293b', color: '#94a3b8', fontSize: '0.75rem', fontWeight: 'normal', border: '1px solid #334155' }}>
                可借额度: ${parseFloat(position.available_borrows_usd).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
              </span>
            )}
          </div>
          <span className="badge red-badge">{borrows.length} 项</span>
        </div>

        {borrows.length === 0 ? (
          <p className="empty-text">该地址还没有负债记录</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">单价 (USD)</th>
                  <th className="right">合计借贷 (USD)</th>
                  <th className="right">估值 (USD)</th>
                </tr>
              </thead>
              <tbody>
                {borrows.map((r) => (
                  <tr key={r.tokenAddress}>
                    <td><span className="token-symbol">{r.symbol}</span></td>
                    <td className="right mono">-</td>
                    <td className="right mono bold">{parseFloat(r.balance).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                    <td className="right mono bold red-text">${r.valueUSD.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
