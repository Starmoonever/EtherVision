import { useState, useEffect } from 'react';

// 1. 根据你的数据库/API返回字段定义接口
interface AccountSummary {
    eth_collateral_amount: string,
    eth_collateral_usd: string,
    total_collateral_usd: string,
    available_borrows_usd: string,
    total_debt_usd: string,
    health_factor: string,
    ltv: string,
    liq_threshold: string,
    liq_price: string
}

interface Props {
  address: string; // 只需要传入地址
  version: 'v2' | 'v3' | 'all';
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

export function SummaryCard({ address, version }: Props) {
  const [summary, setSummary] = useState<AccountSummary | null>(null);
  const [loading, setLoading] = useState(false);

  // 2. 当地址改变时，去数据库抓取该地址的概览数据
  useEffect(() => {
    if (!address) return;

    const fetchSummary = async () => {
      setLoading(true);
      try {
        // 这里调用的地址通常是后端查询单个用户的接口
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const response = await fetch(`${baseUrl}/user/position?address=${address}&version=${version}`);
        if (!response.ok) throw new Error('获取账户概览失败');

        const data = await response.json();
        // 假设后端返回的对象里包含这些字段，如果字段名是下划线风格请自行修改
        setSummary(data);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchSummary();
  }, [address, version]);

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
