import type { CompoundUserPositionItem } from '../api/compound';

interface CompoundSummaryCardProps {
  address: string;
  version: string;
  market: string;
  data: CompoundUserPositionItem | null;
  loading: boolean;
  notFound: boolean;
}

export function CompoundSummaryCard({
  address,
  version,
  market,
  data,
  loading,
  notFound,
}: CompoundSummaryCardProps) {
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

  const discountedCollateral = parseFloat(data.discounted_collateral_usd || '0');
  const totalDebt = parseFloat(data.total_debt_usd || '0');
  const healthFactor = parseFloat(data.health_factor || '0');

  // Format health factor
  const hfDisplay = healthFactor.toFixed(2);
  let hfColor = '#10b981'; // Green
  if (healthFactor < 1.0)
    hfColor = '#ef4444'; // Red
  else if (healthFactor < 1.5) hfColor = '#f59e0b'; // Yellow

  return (
    <div className="card">
      <div className="card-header" style={{ marginBottom: '1.5rem' }}>
        <h2 className="card-title">账户概览</h2>
        <div className="badge blue-badge">
          Compound {version.toUpperCase()} - {market} Market
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
        {/* Row 1: Collateral and Debt */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '1rem',
          }}
        >
          <div style={{ background: '#1e293b', padding: '1.25rem', borderRadius: '8px' }}>
            <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
              折算后可用抵押价值 (USD)
            </div>
            <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#3b82f6' }}>
              $
              {discountedCollateral.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>

            {/* Break down assets */}
            {data.assets && data.assets.length > 0 && (
              <div
                style={{
                  marginTop: '1rem',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.5rem',
                }}
              >
                {data.assets
                  .filter(
                    (a) =>
                      a.symbol.toUpperCase() !== market.toUpperCase() &&
                      (a.side === 'collateral' || parseFloat(a.amount) > 0) &&
                      parseFloat(a.discounted_value_usd || '0') >= 0.004,
                  )
                  .map((asset, idx) => (
                    <div
                      key={idx}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontSize: '0.85rem',
                        padding: '0.25rem 0',
                        borderBottom: '1px solid #334155',
                      }}
                    >
                      <span style={{ color: '#cbd5e1' }}>{asset.symbol}</span>
                      <span style={{ color: '#10b981' }}>
                        $
                        {parseFloat(asset.discounted_value_usd || '0').toLocaleString(undefined, {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </div>

          <div
            style={{
              background: '#1e293b',
              padding: '1.25rem',
              borderRadius: '8px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
            }}
          >
            <div>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                总债务价值 (USD)
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#ef4444' }}>
                $
                {totalDebt.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}
              </div>
            </div>

            <div style={{ marginTop: '1rem', paddingTop: '1rem', borderTop: '1px dashed #334155' }}>
              <div style={{ color: '#94a3b8', fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                健康因子
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: hfColor }}>
                {hfDisplay}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
