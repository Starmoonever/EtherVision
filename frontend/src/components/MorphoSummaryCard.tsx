import type { MorphoPositionResponse } from '../api/morpho';

interface MorphoSummaryCardProps {
  address: string;
  marketId: string;
  protocol?: 'blue';
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatNumber(value: string | number, digits: number = 2): string {
  return toNum(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatPercentFromRatio(value: string | number, digits: number = 2): string {
  return `${(toNum(value) * 100).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

function formatCompactAddress(value: string): string {
  if (value.length <= 12) return value;
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}

function healthColor(data: MorphoPositionResponse): string {
  if (!data.has_position) return '#94a3b8';
  if (!data.health_factor) return '#22c55e';
  return data.is_healthy ? '#22c55e' : '#ef4444';
}

// Morpho 返回的 health_factor 在无仓位和无借款时都可能为空，这里拆开显示语义。
function getHealthFactorText(data: MorphoPositionResponse): string {
  if (!data.has_position) return '无仓位';
  if (data.health_factor === null) {
    return toNum(data.borrow_assets) > 0 ? '计算中' : '∞';
  }
  return toNum(data.health_factor).toFixed(2);
}

// 概览卡集中展示市场定义、借贷规模、风险阈值和可借上限这些高价值字段。
export function MorphoSummaryCard({
  address,
  marketId,
  protocol = 'blue',
  data,
  loading,
  notFound,
}: MorphoSummaryCardProps) {
  const marketLabel = `${protocol.toUpperCase()} · ${formatCompactAddress(marketId)}`;

  if (loading) {
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
  }

  if (notFound) {
    return (
      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', minHeight: '120px', gap: '0.5rem' }}
      >
        <div className="card-header" style={{ width: '100%' }}>
          <span className="card-title">Morpho 仓位概览</span>
          <span
            className="badge"
            style={{ background: '#1e293b', color: '#64748b', border: '1px solid #334155' }}
          >
            {marketLabel}
          </span>
        </div>
        <span style={{ color: '#475569', fontSize: '0.9rem', marginTop: '0.5rem' }}>
          该地址在 Morpho {protocol.toUpperCase()} 市场暂无可用记录
        </span>
      </div>
    );
  }

  if (!data) return null;

  const hfText = getHealthFactorText(data);
  const quoteLabel = `${data.collateral_token_symbol}/${data.loan_token_symbol} 计价`;

  return (
    <div className="card summary-card morpho-emphasis-card">
      <div className="card-header">
        <div>
          <span className="card-title morpho-section-title">Morpho 仓位概览</span>
          <p className="morpho-section-subtitle">
            集中查看市场定义、借贷规模、风险阈值和可借上限，避免关键信息分散。
          </p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span
            className="badge"
            style={{
              background: '#102a43',
              color: '#7dd3fc',
              border: '1px solid #164e63',
              fontWeight: 700,
            }}
          >
            {marketLabel}
          </span>
          <span className="address-badge" title={address}>
            {formatCompactAddress(address)}
          </span>
        </div>
      </div>

      <div className="summary-grid">
        <div className="metric-box">
          <span className="metric-label">借款资产</span>
          <span className="metric-value blue morpho-metric-strong">{data.loan_token_symbol}</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">抵押资产</span>
          <span className="metric-value green morpho-metric-strong">
            {data.collateral_token_symbol}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">存入数量</span>
          <span className="metric-value green">{formatNumber(data.supply_assets, 6)}</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">借款数量</span>
          <span className="metric-value red">{formatNumber(data.borrow_assets, 6)}</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">抵押数量</span>
          <span className="metric-value blue">{formatNumber(data.collateral_assets, 6)}</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">抵押折算借款资产价值</span>
          <span className="metric-value blue">
            {formatNumber(data.collateral_value_in_loan_asset, 6)}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">最大可借数量</span>
          <span className="metric-value blue">
            {formatNumber(data.max_borrowable_in_loan_asset, 6)}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">健康因子</span>
          <span className="metric-value morpho-metric-hero" style={{ color: healthColor(data) }}>
            {hfText}
          </span>
        </div>

        <div className="metric-box">
          <span className="metric-label">LLTV</span>
          <span className="metric-value blue">{formatPercentFromRatio(data.lltv_ratio, 2)}</span>
        </div>

        <div className="metric-box">
          <span className="metric-label">{quoteLabel}</span>
          <span className="metric-value blue">{formatNumber(data.price_quote, 6)}</span>
        </div>
      </div>
    </div>
  );
}
