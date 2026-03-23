import type { CompoundUserPositionItem } from '../api/compound';

interface CompoundEthSensitiveTableProps {
  data: CompoundUserPositionItem | null;
  loading: boolean;
  notFound: boolean;
}

export function CompoundEthSensitiveTable({
  data,
  loading,
  notFound,
}: CompoundEthSensitiveTableProps) {
  if (loading || notFound || !data || !data.has_open_position) {
    return null; // Handle loading/notFound state gracefully outside or just return null
  }

  const formatUsd = (val: string | number) => {
    const num = typeof val === 'string' ? parseFloat(val || '0') : val;
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatAmount = (val: string | number) => {
    const num = typeof val === 'string' ? parseFloat(val || '0') : val;
    return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 });
  };

  // Asset filtering: exclude small dust assets (< $0.004)
  const validAssets =
    data.assets?.filter((a) => parseFloat(a.discounted_value_usd || '0') >= 0.004) || [];
  const ethCorrelatedAssets = validAssets.filter(
    (a) => a.is_eth_correlated && !a.is_basis_risk_asset,
  );
  const basisRiskAssets = validAssets.filter((a) => a.is_basis_risk_asset);

  // Calculate strictly native ETH sensitive collateral by subtracting basis risk collateral
  const ethSensitiveCollateralRaw = parseFloat(data.eth_sensitive_collateral_usd || '0');
  const basisRiskCollateralRaw = parseFloat(data.basis_risk_collateral_usd || '0');
  const nativeEthSensitiveCollateral = Math.max(
    0,
    ethSensitiveCollateralRaw - basisRiskCollateralRaw,
  );

  return (
    <div className="card">
      <div className="card-header" style={{ marginBottom: '1.5rem' }}>
        <h2 className="card-title">ETH 价格敏感资产负债表</h2>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        {/* 账户清算价格 板块 */}
        {(data.eth_up_liq_price_usd || data.eth_down_liq_price_usd) && (
          <div>
            <h3
              style={{
                fontSize: '1.1rem',
                color: '#e2e8f0',
                marginBottom: '1rem',
                borderBottom: '1px solid #334155',
                paddingBottom: '0.5rem',
              }}
            >
              账户 ETH 清算价格
            </h3>
            <div style={{ display: 'flex', gap: '1.5rem' }}>
              {data.eth_up_liq_price_usd && (
                <div
                  style={{
                    background: '#1e293b',
                    padding: '1rem',
                    borderRadius: '8px',
                    flex: 1,
                    cursor: 'help',
                  }}
                  title={`ETH 价格上涨至 ${formatUsd(data.eth_up_liq_price_usd)} 时，触发清算`}
                >
                  <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    ETH 上涨清算价格
                  </div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#ef4444' }}>
                    {formatUsd(data.eth_up_liq_price_usd)}
                  </div>
                </div>
              )}
              {data.eth_down_liq_price_usd && (
                <div
                  style={{
                    background: '#1e293b',
                    padding: '1rem',
                    borderRadius: '8px',
                    flex: 1,
                    cursor: 'help',
                  }}
                  title={`ETH 价格下跌至 ${formatUsd(data.eth_down_liq_price_usd)} 时，触发清算`}
                >
                  <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    ETH 下跌清算价格
                  </div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#ef4444' }}>
                    {formatUsd(data.eth_down_liq_price_usd)}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 资产 (assets) 板块 */}
        <div>
          <h3
            style={{
              fontSize: '1.1rem',
              color: '#e2e8f0',
              marginBottom: '1rem',
              borderBottom: '1px solid #334155',
              paddingBottom: '0.5rem',
            }}
          >
            资产 (Assets)
          </h3>

          <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1.5rem' }}>
            <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px', flex: 1 }}>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                抵押资产价值锚定原生 ETH 价格
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#3b82f6' }}>
                {formatUsd(nativeEthSensitiveCollateral)}
              </div>
            </div>
            <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px', flex: 1 }}>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                抵押资产价值锚定 ETH 衍生流动性代币价格
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#3b82f6' }}>
                {formatUsd(data.basis_risk_collateral_usd)}
              </div>
            </div>
          </div>

          {/* 资产价格锚定 ETH 资产 */}
          {ethCorrelatedAssets.length > 0 && (
            <div style={{ marginBottom: '2rem' }}>
              <h4
                style={{
                  fontSize: '1.15rem',
                  fontWeight: 'bold',
                  color: '#cbd5e1',
                  marginBottom: '1rem',
                }}
              >
                资产价值锚定原生 ETH 价格
              </h4>
              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ fontSize: '0.9rem', padding: '0.75rem 1rem' }}>资产</th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        数量{' '}
                      </th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        折扣后抵押价值{' '}
                      </th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        对 ETH 价格敏感度 (Beta)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {ethCorrelatedAssets.map((asset, idx) => (
                      <tr key={`eth-${idx}`}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ fontWeight: 600, color: '#e2e8f0' }}>
                              {asset.symbol}
                            </span>
                          </div>
                        </td>
                        <td style={{ textAlign: 'right' }}>{formatAmount(asset.amount)}</td>
                        <td style={{ textAlign: 'right' }}>
                          {formatUsd(asset.discounted_value_usd)}
                        </td>
                        <td style={{ textAlign: 'right', color: '#10b981' }}>
                          {parseFloat(asset.beta_to_eth || '0').toFixed(4)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 资产价格和 ETH 衍生代币价格相关，与原生 ETH 价格存在价差 */}
          {basisRiskAssets.length > 0 && (
            <div style={{ marginBottom: '1.5rem' }}>
              <h4
                style={{
                  fontSize: '1.15rem',
                  fontWeight: 'bold',
                  color: '#cbd5e1',
                  marginBottom: '1rem',
                }}
              >
                资产价值锚定 ETH 衍生流动性代币价格
              </h4>
              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ fontSize: '0.9rem', padding: '0.75rem 1rem' }}>资产</th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        数量
                      </th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        折扣后抵押价值{' '}
                      </th>
                      <th
                        style={{ textAlign: 'right', fontSize: '0.9rem', padding: '0.75rem 1rem' }}
                      >
                        对 ETH 价格敏感度 (Beta)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {basisRiskAssets.map((asset, idx) => (
                      <tr key={`basis-${idx}`}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ fontWeight: 600, color: '#e2e8f0' }}>
                              {asset.symbol}
                            </span>
                          </div>
                        </td>
                        <td style={{ textAlign: 'right' }}>{formatAmount(asset.amount)}</td>
                        <td style={{ textAlign: 'right' }}>
                          {formatUsd(asset.discounted_value_usd)}
                        </td>
                        <td style={{ textAlign: 'right', color: '#f59e0b' }}>
                          {parseFloat(asset.beta_to_eth || '0').toFixed(4)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* 负债（debts) 板块 */}
        <div>
          <h3
            style={{
              fontSize: '1.1rem',
              color: '#e2e8f0',
              marginBottom: '1rem',
              borderBottom: '1px solid #334155',
              paddingBottom: '0.5rem',
            }}
          >
            负债 (Debts)
          </h3>
          <div style={{ display: 'flex', gap: '1.5rem' }}>
            <div style={{ background: '#1e293b', padding: '1rem', borderRadius: '8px', flex: 1 }}>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                债务价值锚定原生 ETH 价格
              </div>
              <div style={{ fontSize: '1.25rem', fontWeight: 'bold', color: '#ef4444' }}>
                {formatUsd(data.eth_sensitive_debt_usd)}
              </div>
            </div>
            {/* Placeholder to keep layout balanced if needed */}
            <div style={{ flex: 1 }}></div>
          </div>
        </div>
      </div>
    </div>
  );
}
