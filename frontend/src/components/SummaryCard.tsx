import type { UserPosition, BorrowPosition } from '../api';

interface Props {
  address: string;
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
  version: 'v2' | 'v3';
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

export function SummaryCard({ address, data: summary, loading, notFound, version }: Props) {
  const versionLabel = version.toUpperCase();

  if (loading)
    return (
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '120px',
        }}
      >
        <div className="spinner"></div>
      </div>
    );

  if (notFound)
    return (
      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', minHeight: '120px', gap: '0.5rem' }}
      >
        <div className="card-header" style={{ width: '100%' }}>
          <span className="card-title">账户概览</span>
          <span
            className="badge"
            style={{ background: '#1e293b', color: '#64748b', border: '1px solid #334155' }}
          >
            {versionLabel}
          </span>
        </div>
        <span style={{ color: '#475569', fontSize: '0.9rem', marginTop: '0.5rem' }}>
          该地址在 Aave {versionLabel} 暂无仓位记录
        </span>
      </div>
    );

  if (!summary) return null;

  const hfColor = healthColor(summary.health_factor);

  return (
    <div className="card summary-card">
      <div className="card-header">
        <span className="card-title">账户概览</span>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <span
            className="badge"
            style={{
              background: '#1e293b',
              color: '#a78bfa',
              border: '1px solid #4c1d95',
              fontWeight: 700,
            }}
          >
            {versionLabel}
          </span>
          <span className="address-badge" title={address}>
            {address.slice(0, 6)}…{address.slice(-4)}
          </span>
        </div>
      </div>

      <div className="summary-grid">
        <div className="metric-box">
          <span className="metric-label">总抵押资产价值 (USD)</span>
          <span className="metric-value green">
            $
            {parseFloat(summary.total_collateral_usd).toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">抵押 ETH 价值 (USD)</span>
          <span className="metric-value green">
            $
            {parseFloat(summary.eth_collateral_usd).toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">总债务价值 (USD)</span>
          <span className="metric-value red">
            $
            {parseFloat(summary.total_debt_usd).toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">可借额度 (USD)</span>
          <span className="metric-value blue">
            $
            {parseFloat(summary.available_borrows_usd).toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">借出 ETH 价值 (USD)</span>
          <span className="metric-value red">
            $
            {parseFloat(summary.weth_debt_usd || '0').toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">健康因子</span>
          <span className="metric-value" style={{ color: hfColor, fontSize: '1.6rem' }}>
            {summary.health_factor}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">清算价格 (USD)</span>
          <span className="metric-value blue">
            $
            {parseFloat(summary.liq_price).toLocaleString('en-US', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            })}
          </span>
        </div>
      </div>
    </div>
  );
}
