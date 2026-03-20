import { useState, useEffect } from 'react';
import { fetchAssetPrice } from '../api';
import { CompoundPriceTrend } from './CompoundPriceTrend';
import { CompoundMarketHistoryChart } from './CompoundMarketHistoryChart';
import { CompoundCollateralHistoryChart } from './CompoundCollateralHistoryChart';

export interface CompoundMarketAssessmentProps {
  marketVersion: 'v2' | 'v3' | 'all';
}

export function CompoundMarketAssessment({ marketVersion }: CompoundMarketAssessmentProps) {
  const [asset, setAsset] = useState<'USDC' | 'USDT' | 'WETH'>('USDC');
  const [assetPrice, setAssetPrice] = useState<number | null>(null);

  // Fetch real-time price from API
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const price = await fetchAssetPrice(asset);
        setAssetPrice(price);
      } catch (err) {
        console.error(`Fetch ${asset} price error:`, err);
      }
    };

    fetchPrice(); // Initial fetch
    const interval = setInterval(fetchPrice, 600000); // Poll every 10 minutes
    return () => clearInterval(interval);
  }, [asset]);

  return (
    <div className="market-assessment">
      {/* Asset Toggle */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '2rem' }}>
        <div
          style={{
            display: 'flex',
            background: '#1e293b',
            borderRadius: '8px',
            padding: '4px',
            gap: '4px',
          }}
        >
          {(['USDC', 'USDT', 'WETH'] as const).map((a) => (
            <button
              key={a}
              onClick={() => setAsset(a)}
              style={{
                background: asset === a ? '#3b82f6' : 'transparent',
                color: asset === a ? '#fff' : '#94a3b8',
                border: 'none',
                padding: '6px 24px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: 600,
                transition: 'all 0.2s',
              }}
            >
              {a}
            </button>
          ))}
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 3fr',
          gap: '1.5rem',
          alignItems: 'start',
        }}
      >
        {/* Left: Price Panel */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* Real-time price */}
          <div style={{ textAlign: 'center' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.5rem',
                marginBottom: '0.75rem',
              }}
            >
              <span className="card-title">{asset} 实时价格</span>
              <span className="badge green-badge">Live</span>
            </div>
            <div className="metric-value" style={{ fontSize: '2.2rem' }}>
              {assetPrice !== null ? (
                `$${assetPrice.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 4,
                })}`
              ) : (
                <span style={{ fontSize: '1rem', color: '#64748b' }}>加载中...</span>
              )}
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid #1e293b', margin: 0 }} />

          {/* Historical trend */}
          <CompoundPriceTrend asset={asset} />
        </div>

        {/* Right: Historical Data Panel */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
          <CompoundMarketHistoryChart version={marketVersion} asset={asset} />
          
          <div style={{ marginTop: '2rem' }}>
            <CompoundCollateralHistoryChart version={marketVersion} asset={asset} />
          </div>
        </div>
      </div>
    </div>
  );
}
