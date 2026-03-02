import { useState, useEffect } from 'react';
import { fetchUserPosition } from '../api';
import type { UserPosition } from '../api';

interface Props {
  address: string; // 只需要传入地址
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
}

// 健康因子颜色逻辑保持不变
function healthColor(hfStr: string): string {
  if (hfStr === '∞' || hfStr === 'Infinity') return '#22c55e';
  const hf = parseFloat(hfStr);
  if (isNaN(hf)) return '#9ca3af';
  if (hf >= 2) return '#22c55e';
  if (hf >= 1.2) return '#f59e0b';
  return '#ef4444';
}

export function SummaryCard({ address, version, side }: Props) {
  const [summary, setSummary] = useState<UserPosition | null>(null);
  const [loading, setLoading] = useState(false);

  // 2. 当地址改变时，去数据库抓取该地址的概览数据
  useEffect(() => {
    if (!address) return;

    const fetchSummary = async () => {
      setLoading(true);
      try {
        // 这里调用的地址是后端查询单个用户的接口
        const data = await fetchUserPosition(address, version);
        setSummary(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchSummary();
  }, [address, version, side]);

  if (loading) return <div className="card shadow-sm p-4">加载账户数据中...</div>;
  if (!summary) return null;

  const hfColor = healthColor(summary.health_factor);

  return (
    <div className="card summary-card">

      <div className="card-header">
        <span className="card-title">账户概览</span>
        <span className="address-badge" title={address}>
          {address.slice(0, 6)}…{address.slice(-4)}
        </span>
      </div>

     <div className="summary-grid">
        <div className="metric-box">
          <span className="metric-label">抵押ETH数量</span>
          <span className="metric-value yellow">
            {parseFloat(summary.eth_collateral_amount).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">抵押ETH价值 (USD)</span>
          <span className="metric-value green">
            ${parseFloat(summary.eth_collateral_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">总抵押 (USD)</span>
          <span className="metric-value green">
            ${parseFloat(summary.total_collateral_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">可借额度 (USD)</span>
          <span className="metric-value blue">
            ${parseFloat(summary.available_borrows_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">总债务 (USD)</span>
          <span className="metric-value red">
            ${parseFloat(summary.total_debt_usd).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">清算价格 (USD)</span>
          <span className="metric-value blue">
            ${parseFloat(summary.liq_price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">健康因子</span>
          <span className="metric-value" style={{ color: hfColor, fontSize: '1.6rem' }}>
            {summary.health_factor}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">当前 LTV</span>
          <span className="metric-value">{summary.ltv}%</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">清算阈值</span>
          <span className="metric-value">{summary.liq_threshold}%</span>
        </div>
      </div>
    </div>
)}
