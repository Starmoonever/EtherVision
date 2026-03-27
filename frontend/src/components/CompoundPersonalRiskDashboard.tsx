import { useState } from 'react';
import type { CompoundUserAsset, CompoundUserPositionItem } from '../api/compound';

interface CompoundPersonalRiskDashboardProps {
  address: string;
  version: string;
  market: string;
  data: CompoundUserPositionItem | null;
  loading: boolean;
  notFound: boolean;
}

interface RiskAssetRow extends CompoundUserAsset {
  risk_contribution_usd: number;
  risk_direction: 'down' | 'up' | 'basis' | 'neutral';
}

const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

const toNum = (value: string | number | null | undefined) => {
  if (value === null || value === undefined) return 0;
  const num = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(num) ? num : 0;
};

const formatFixed2 = (value: string | number) => toNum(value).toFixed(2);

const formatUsd2 = (value: string | number) =>
  `$${toNum(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const formatPrice = (value: string | number) =>
  `$${toNum(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function parseHealthFactor(value: string | number): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : Number.POSITIVE_INFINITY;
  }
  const normalized = String(value).trim().toLowerCase();
  if (normalized === 'inf' || normalized === 'infinity') {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = parseFloat(normalized);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function formatHealthFactor(value: string | number): string {
  const hf = parseHealthFactor(value);
  if (!Number.isFinite(hf) || hf >= 1e12) return '∞';
  return hf.toFixed(2);
}

function calcRiskScore(data: CompoundUserPositionItem): number {
  const healthFactor = parseHealthFactor(data.health_factor);
  const liquidationBuffer = toNum(data.liquidation_buffer_usd);
  const discountedCollateral = Math.max(toNum(data.discounted_collateral_usd), 1);
  const netEthExposure = Math.abs(toNum(data.net_eth_exposure_usd));
  const basisRiskCollateral = Math.max(toNum(data.basis_risk_collateral_usd), 0);
  const ethSensitiveTotal =
    Math.max(toNum(data.eth_sensitive_collateral_usd), 0) +
    Math.max(toNum(data.eth_sensitive_debt_usd), 0);

  const hfRisk = Number.isFinite(healthFactor) ? clamp(((3 - healthFactor) / 3) * 40, 0, 40) : 0;
  const bufferRatio = liquidationBuffer / discountedCollateral;
  const bufferRisk = liquidationBuffer <= 0 ? 35 : clamp((1 - bufferRatio) * 30, 0, 30);
  const ethExposureRisk = clamp((netEthExposure / Math.max(ethSensitiveTotal, 1)) * 20, 0, 20);
  const basisRisk = clamp(
    (basisRiskCollateral / Math.max(toNum(data.total_collateral_usd), 1)) * 10,
    0,
    10,
  );

  return clamp(hfRisk + bufferRisk + ethExposureRisk + basisRisk, 0, 100);
}

function toRiskAssets(assets: CompoundUserAsset[]): RiskAssetRow[] {
  return assets
    .map((asset) => {
      const discounted = Math.max(toNum(asset.discounted_value_usd), 0);
      const beta = Math.abs(toNum(asset.beta_to_eth));
      const contribution = discounted * beta;

      let direction: RiskAssetRow['risk_direction'] = 'neutral';
      if (asset.is_basis_risk_asset) {
        direction = 'basis';
      } else if (toNum(asset.beta_to_eth) > 0 && asset.side === 'base_borrow') {
        direction = 'up';
      } else if (
        toNum(asset.beta_to_eth) > 0 &&
        (asset.side === 'collateral' || asset.side === 'base_supply')
      ) {
        direction = 'down';
      }

      return {
        ...asset,
        risk_contribution_usd: contribution,
        risk_direction: direction,
      };
    })
    .sort((a, b) => b.risk_contribution_usd - a.risk_contribution_usd);
}

function riskDirectionLabel(direction: RiskAssetRow['risk_direction']) {
  if (direction === 'down') return 'eth价格下跌';
  if (direction === 'up') return 'eth价格上涨';
  if (direction === 'basis') return '脱锚风险（eth流动性代币相对原生 eth 贬值）';
  return '无风险';
}

function riskDirectionColor(direction: RiskAssetRow['risk_direction']) {
  if (direction === 'down') return '#fb7185';
  if (direction === 'up') return '#c084fc';
  if (direction === 'basis') return '#fbbf24';
  return '#94a3b8';
}

function distanceToLiqPercent(currentEthPrice: number, liqPrice: number, direction: 'up' | 'down') {
  if (
    !Number.isFinite(currentEthPrice) ||
    currentEthPrice <= 0 ||
    !Number.isFinite(liqPrice) ||
    liqPrice <= 0
  ) {
    return '--';
  }

  if (direction === 'down') {
    if (liqPrice >= currentEthPrice) return '已触达/无效';
    return `${(((currentEthPrice - liqPrice) / currentEthPrice) * 100).toFixed(2)}%`;
  }

  if (liqPrice <= currentEthPrice) return '已触达/无效';
  return `${(((liqPrice - currentEthPrice) / currentEthPrice) * 100).toFixed(2)}%`;
}

export function CompoundPersonalRiskDashboard({
  address,
  version,
  market,
  data,
  loading,
  notFound,
}: CompoundPersonalRiskDashboardProps) {
  const [showHelp, setShowHelp] = useState(false);
  const [showTableHelp, setShowTableHelp] = useState(false);
  const [valueMode, setValueMode] = useState<'absolute' | 'ratio'>('absolute');

  if (loading) {
    return (
      <div className="card" style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  if (notFound || (data && !data.has_open_position)) {
    return (
      <div className="card" style={{ textAlign: 'center', padding: '2rem', color: '#94a3b8' }}>
        <p>
          该地址 ({address}) 在 Compound {version.toUpperCase()} {market} 市场不存在非空仓位。
        </p>
      </div>
    );
  }

  if (!data) return null;

  const riskScore = calcRiskScore(data);
  const riskScoreColor = riskScore >= 75 ? '#ef4444' : riskScore >= 45 ? '#f59e0b' : '#10b981';

  const ethPrice = toNum(data.eth_price_usd);
  const ethUpLiq = toNum(data.eth_up_liq_price_usd);
  const ethDownLiq = toNum(data.eth_down_liq_price_usd);
  const assets = toRiskAssets(data.assets || []);
  const totalContribution = assets.reduce((sum, item) => sum + item.risk_contribution_usd, 0);

  const totalExposure =
    Math.max(toNum(data.eth_sensitive_collateral_usd), 0) +
    Math.max(toNum(data.eth_sensitive_debt_usd), 0);
  const collateralRatio =
    totalExposure > 0
      ? (Math.max(toNum(data.eth_sensitive_collateral_usd), 0) / totalExposure) * 100
      : 0;
  const debtRatio =
    totalExposure > 0 ? (Math.max(toNum(data.eth_sensitive_debt_usd), 0) / totalExposure) * 100 : 0;
  const discountedCollateral = Math.max(toNum(data.discounted_collateral_usd), 1);

  const formatValueByMode = (
    value: string | number,
    denominator: number = discountedCollateral,
  ) => {
    if (valueMode === 'absolute') return formatUsd2(value);
    return `${((toNum(value) / Math.max(denominator, 1)) * 100).toFixed(2)}%`;
  };

  const riskLevel = riskScore >= 75 ? '高风险' : riskScore >= 45 ? '中风险' : '低风险';
  const helpRows = [
    {
      k: 'ETH敏感风险评分',
      v: '基于健康因子、清算缓冲、净ETH敞口、Basis敞口的综合评分（0-100），分数越高风险越大',
    },
    {
      k: '主导风险',
      v: '主要清算风险来源：eth价格下跌 / eth价格上涨 / 脱锚风险（eth流动性代币相对原生 eth 贬值） / 多市场综合性风险 / 无风险。',
    },
    {
      k: 'ETH上涨 / 下跌清算价格',
      v: '达到该价格时，账户进入清算触发区间',
    },
    { k: 'ETH敏感抵押/债务', v: '对ETH价格变化敏感的抵押与负债规模，单位USD。' },
    { k: '净ETH敞口', v: 'ETH敏感抵押减去ETH敏感债务，正值偏多，负值偏空。' },
    {
      k: '基差风险抵押资产规模',
      v: 'ETH 衍生资产，价格与原生 ETH 价格相关但存在价差风险的抵押资产（如wstETH）。',
    },
    {
      k: '清算风险贡献度',
      v: ' ETH 价格波动，各抵押资产对账户清算风险贡献度 （按 |discounted_collateral_usd * beta_to_eth| 估算排序）',
    },
  ];

  const getDominantRiskLabel = (risk: string) => {
    switch (risk) {
      case 'eth_down':
        return 'eth价格下跌';
      case 'eth_up':
        return 'eth价格上涨';
      case 'basis':
        return '脱锚风险（eth流动性代币相对原生 eth 贬值）';
      case 'mixed':
        return '多市场综合性风险';
      case 'neutral':
      default:
        return '无风险';
    }
  };

  const tableHelpRows = [
    { k: '折扣后价值 (USD)', v: '该资产按清算折扣系数折算后的可用抵押价值' },
    {
      k: 'ETH Beta',
      v: 'ETH 价格变动导致的该资产价格变动比例（衡量该资产价格受 ETH 价格影响程度）',
    },
    { k: '风险贡献度', v: '该资产对账户清算风险的贡献度，按 折扣后价值 * ETH Beta 衡量' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <h2 className="card-title">ETH 敏感风险总览</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div className="badge" style={{ background: '#1e3a8a', color: '#bfdbfe' }}>
              Compound {version.toUpperCase()} - {market}
            </div>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => setShowHelp((v) => !v)}
                onMouseEnter={() => setShowHelp(true)}
                onMouseLeave={() => setShowHelp(false)}
                style={{
                  width: '26px',
                  height: '26px',
                  borderRadius: '999px',
                  border: '1px solid #334155',
                  background: showHelp ? '#334155' : '#0f172a',
                  color: '#cbd5e1',
                  fontWeight: 700,
                  cursor: 'pointer',
                  padding: 0,
                }}
                title="字段说明"
              >
                ?
              </button>
              {showHelp && (
                <div
                  onMouseEnter={() => setShowHelp(true)}
                  onMouseLeave={() => setShowHelp(false)}
                  style={{
                    position: 'absolute',
                    top: '32px',
                    right: 0,
                    width: 'min(520px, 80vw)',
                    zIndex: 20,
                    background: '#0b1220',
                    border: '1px solid #334155',
                    borderRadius: '10px',
                    padding: '0.85rem 1rem',
                    boxShadow: '0 12px 24px rgba(2,6,23,0.55)',
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                    gap: '0.65rem',
                  }}
                >
                  {helpRows.map((item) => (
                    <div key={item.k} style={{ fontSize: '0.8rem', lineHeight: 1.4 }}>
                      <div style={{ color: '#e2e8f0', fontWeight: 700 }}>{item.k}</div>
                      <div style={{ color: '#94a3b8' }}>{item.v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="summary-grid compound-overview-grid">
          <div className="metric-box">
            <span className="metric-label">ETH 敏感风险评分 (0-100)</span>
            <span className="metric-value" style={{ color: riskScoreColor }}>
              {riskScore.toFixed(2)}
            </span>
            <div
              style={{
                width: '100%',
                height: '8px',
                background:
                  'linear-gradient(90deg, rgba(16,185,129,0.35) 0%, rgba(16,185,129,0.35) 40%, rgba(245,158,11,0.35) 40%, rgba(245,158,11,0.35) 75%, rgba(239,68,68,0.35) 75%, rgba(239,68,68,0.35) 100%)',
                borderRadius: '999px',
                marginTop: '0.35rem',
                overflow: 'hidden',
                border: '1px solid #334155',
              }}
            >
              <div
                style={{
                  width: `${riskScore}%`,
                  height: '100%',
                  background:
                    riskScore >= 75
                      ? 'linear-gradient(90deg, #dc2626, #ef4444)'
                      : riskScore >= 45
                        ? 'linear-gradient(90deg, #d97706, #f59e0b)'
                        : 'linear-gradient(90deg, #059669, #10b981)',
                }}
              />
            </div>
            <span style={{ color: '#94a3b8', fontSize: '0.75rem' }}>{riskLevel}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">主导风险</span>
            <span className="metric-value">{getDominantRiskLabel(data.dominant_risk)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">健康因子</span>
            <span className="metric-value">{formatHealthFactor(data.health_factor)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">清算缓冲 (USD)</span>
            <span className="metric-value">{formatUsd2(data.liquidation_buffer_usd)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">是否可清算</span>
            <span
              className="metric-value"
              style={{ color: data.is_liquidatable ? '#ef4444' : '#10b981' }}
            >
              {data.is_liquidatable ? '是' : '否'}
            </span>
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
          gap: '1rem',
        }}
      >
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">ETH 下跌情景</span>
            <span className="badge" style={{ background: '#3f1d27', color: '#fb7185' }}>
              Downside
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
            <div className="metric-box">
              <span className="metric-label">ETH 下跌清算价</span>
              <span className="metric-value">
                {ethDownLiq > 0 ? formatPrice(ethDownLiq) : '--'}
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">距下跌清算价</span>
              <span className="metric-value">
                {distanceToLiqPercent(ethPrice, ethDownLiq, 'down')}
              </span>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">ETH 上涨情景</span>
            <span className="badge" style={{ background: '#3b1f45', color: '#c084fc' }}>
              Upside
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.7rem' }}>
            <div className="metric-box">
              <span className="metric-label">ETH 上涨清算价</span>
              <span className="metric-value">{ethUpLiq > 0 ? formatPrice(ethUpLiq) : '--'}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">距上涨清算价</span>
              <span className="metric-value">{distanceToLiqPercent(ethPrice, ethUpLiq, 'up')}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">ETH 敞口分解</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="badge" style={{ background: '#1e293b', color: '#93c5fd' }}>
              Current ETH {formatPrice(ethPrice)}
            </span>
            <div
              style={{
                display: 'inline-flex',
                border: '1px solid #334155',
                borderRadius: '8px',
                overflow: 'hidden',
              }}
            >
              <button
                type="button"
                onClick={() => setValueMode('absolute')}
                style={{
                  border: 'none',
                  background: valueMode === 'absolute' ? '#3b82f6' : '#111827',
                  color: '#e5e7eb',
                  fontSize: '0.72rem',
                  padding: '0.25rem 0.55rem',
                  cursor: 'pointer',
                }}
              >
                绝对值
              </button>
              <button
                type="button"
                onClick={() => setValueMode('ratio')}
                style={{
                  border: 'none',
                  background: valueMode === 'ratio' ? '#3b82f6' : '#111827',
                  color: '#e5e7eb',
                  fontSize: '0.72rem',
                  padding: '0.25rem 0.55rem',
                  cursor: 'pointer',
                }}
              >
                占比
              </button>
            </div>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: '0.8rem',
          }}
        >
          <div className="metric-box">
            <span className="metric-label">ETH 敏感抵押 (USD)</span>
            <span className="metric-value">
              {formatValueByMode(data.eth_sensitive_collateral_usd, totalExposure)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">ETH 敏感债务 (USD)</span>
            <span className="metric-value">
              {formatValueByMode(data.eth_sensitive_debt_usd, totalExposure)}
            </span>
          </div>
          <div className="metric-box">
            <span className="metric-label">净 ETH 敞口 (USD)</span>
            <span className="metric-value">{formatValueByMode(data.net_eth_exposure_usd)}</span>
          </div>
          <div className="metric-box">
            <span className="metric-label">Basis Risk 抵押 (USD)</span>
            <span className="metric-value">
              {formatValueByMode(data.basis_risk_collateral_usd)}
            </span>
          </div>
        </div>

        <div
          style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.45rem' }}
        >
          <div style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
            ETH 敏感抵押/债务占比: {collateralRatio.toFixed(2)}% / {debtRatio.toFixed(2)}%
          </div>
          <div
            style={{
              width: '100%',
              height: '12px',
              background: '#0f172a',
              borderRadius: '999px',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                width: `${collateralRatio}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #38bdf8, #60a5fa)',
                float: 'left',
              }}
            />
            <div
              style={{
                width: `${debtRatio}%`,
                height: '100%',
                background: 'linear-gradient(90deg, #f97316, #ef4444)',
                float: 'left',
              }}
            />
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">各抵押资产清算风险贡献度</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span className="badge" style={{ background: '#1e293b', color: '#94a3b8' }}>
              按贡献度降序
            </span>
            <div style={{ position: 'relative' }}>
              <button
                type="button"
                onClick={() => setShowTableHelp((v) => !v)}
                onMouseEnter={() => setShowTableHelp(true)}
                onMouseLeave={() => setShowTableHelp(false)}
                style={{
                  width: '26px',
                  height: '26px',
                  borderRadius: '999px',
                  border: '1px solid #334155',
                  background: showTableHelp ? '#334155' : '#0f172a',
                  color: '#cbd5e1',
                  fontWeight: 700,
                  cursor: 'pointer',
                  padding: 0,
                }}
                title="字段说明"
              >
                ?
              </button>
              {showTableHelp && (
                <div
                  onMouseEnter={() => setShowTableHelp(true)}
                  onMouseLeave={() => setShowTableHelp(false)}
                  style={{
                    position: 'absolute',
                    top: '32px',
                    right: 0,
                    width: 'min(400px, 80vw)',
                    zIndex: 20,
                    background: '#0b1220',
                    border: '1px solid #334155',
                    borderRadius: '10px',
                    padding: '0.85rem 1rem',
                    boxShadow: '0 12px 24px rgba(2,6,23,0.55)',
                    display: 'grid',
                    gridTemplateColumns: '1fr',
                    gap: '0.65rem',
                  }}
                >
                  {tableHelpRows.map((item) => (
                    <div key={item.k} style={{ fontSize: '0.8rem', lineHeight: 1.4 }}>
                      <div style={{ color: '#e2e8f0', fontWeight: 700 }}>{item.k}</div>
                      <div style={{ color: '#94a3b8' }}>{item.v}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="table-wrap">
          <table className="pos-table">
            <thead>
              <tr>
                <th>资产</th>
                <th>仓位角色</th>
                <th className="right">数量</th>
                <th className="right">折扣后价值 (USD)</th>
                <th className="right"> ETH Beta</th>
                <th className="right">风险贡献度</th>
                <th className="right">贡献占比</th>
                <th className="right">风险诱因</th>
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => (
                <tr key={`${asset.asset}-${asset.side}`}>
                  <td>
                    <span className="token-symbol">{asset.symbol}</span>
                  </td>
                  <td>{asset.side}</td>
                  <td className="right mono">{formatFixed2(asset.amount)}</td>
                  <td className="right mono">{formatUsd2(asset.discounted_value_usd)}</td>
                  <td className="right mono">{formatFixed2(asset.beta_to_eth)}</td>
                  <td className="right mono">{formatUsd2(asset.risk_contribution_usd)}</td>
                  <td className="right">
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        minWidth: '120px',
                        justifyContent: 'flex-end',
                      }}
                    >
                      <div
                        style={{
                          width: '56px',
                          height: '6px',
                          background: '#0f172a',
                          borderRadius: '999px',
                          overflow: 'hidden',
                        }}
                      >
                        <div
                          style={{
                            width: `${totalContribution > 0 ? (asset.risk_contribution_usd / totalContribution) * 100 : 0}%`,
                            height: '100%',
                            background: '#60a5fa',
                          }}
                        />
                      </div>
                      <span className="mono" style={{ fontSize: '0.78rem', color: '#93c5fd' }}>
                        {totalContribution > 0
                          ? `${((asset.risk_contribution_usd / totalContribution) * 100).toFixed(2)}%`
                          : '0.00%'}
                      </span>
                    </div>
                  </td>
                  <td className="right">
                    <span
                      className="badge"
                      style={{
                        background: '#0f172a',
                        color: riskDirectionColor(asset.risk_direction),
                        border: `1px solid ${riskDirectionColor(asset.risk_direction)}`,
                      }}
                    >
                      {riskDirectionLabel(asset.risk_direction)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
