import type { AccountSummary } from '../lib/aave';

interface Props {
  summary: AccountSummary;
  address: string;
}

function healthColor(hfStr: string): string {
  if (hfStr === '∞') return '#22c55e';
  const hf = parseFloat(hfStr);
  if (hf >= 2) return '#22c55e';
  if (hf >= 1.2) return '#f59e0b';
  return '#ef4444';
}

export function SummaryCard({ summary, address }: Props) {
  const hfColor = healthColor(summary.healthFactor);

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
          <span className="metric-label">总抵押品 (USD)</span>
          <span className="metric-value green">
            ${parseFloat(summary.totalCollateralUSD).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">总债务 (USD)</span>
          <span className="metric-value red">
            ${parseFloat(summary.totalDebtUSD).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">可借额度 (USD)</span>
          <span className="metric-value blue">
            ${parseFloat(summary.availableBorrowsUSD).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">健康因子</span>
          <span className="metric-value" style={{ color: hfColor, fontSize: '1.6rem' }}>
            {summary.healthFactor}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">当前 LTV</span>
          <span className="metric-value">{summary.ltv}%</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">清算阈值</span>
          <span className="metric-value">{summary.currentLiquidationThreshold}%</span>
        </div>
      </div>
    </div>
  );
}
