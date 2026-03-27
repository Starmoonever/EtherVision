import { useState, useEffect } from 'react';
import { fetchAssetPrice } from '../api';
import type { CompoundMarket } from '../api/compound';
import { fetchCompoundMarketConfigV2 } from '../api/compound';
import { CompoundPriceTrend } from './CompoundPriceTrend';
import { CompoundMarketHistoryChart } from './CompoundMarketHistoryChart';
import { CompoundCollateralHistoryChart } from './CompoundCollateralHistoryChart';

export interface CompoundMarketAssessmentProps {
  marketVersion: 'v2' | 'v3';
  markets: CompoundMarket[];
  selectedMarket: string;
  onMarketChange: (market: string) => void;
}

export function CompoundMarketAssessment({
  marketVersion,
  markets,
  selectedMarket,
  onMarketChange,
}: CompoundMarketAssessmentProps) {
  const [assetPrice, setAssetPrice] = useState<number | null>(null);
  const activeMarket = markets.find((item) => item.address === selectedMarket) ?? markets[0];
  const activeMarketAddress = activeMarket?.address ?? '';
  const activeMarketSymbol = activeMarket?.symbol ?? '';

  useEffect(() => {
    if (!activeMarketAddress) return;
    if (selectedMarket !== activeMarketAddress) {
      onMarketChange(activeMarketAddress);
    }
  }, [activeMarketAddress, onMarketChange, selectedMarket]);

  // Fetch real-time price from API
  useEffect(() => {
    if (!activeMarketSymbol) return;

    const fetchPrice = async () => {
      try {
        if (marketVersion === 'v2') {
          // For Compound v2 cTokens, we need to fetch the underlying token price and multiply by exchange_rate
          const baseSymbol = activeMarketSymbol.replace(/^c/i, '');
          const basePrice = await fetchAssetPrice(baseSymbol);
          
          const today = new Date().toISOString().slice(0, 10) + ' 00:00:00';
          const configRes = await fetchCompoundMarketConfigV2(activeMarketSymbol, today);
          
          if (configRes && configRes.market_config && configRes.market_config.exchange_rate) {
            const exchangeRate = parseFloat(configRes.market_config.exchange_rate);
            setAssetPrice(basePrice * exchangeRate);
          } else {
            setAssetPrice(basePrice); // fallback if exchange rate fails
          }
        } else {
          // Compound v3 handles regular tokens
          const price = await fetchAssetPrice(activeMarketSymbol);
          setAssetPrice(price);
        }
      } catch (err) {
        setAssetPrice(null);
        console.error(`Fetch ${activeMarketSymbol} price error:`, err);
      }
    };

    fetchPrice(); // Initial fetch
    const interval = setInterval(fetchPrice, 600000); // Poll every 10 minutes
    return () => clearInterval(interval);
  }, [activeMarketSymbol, activeMarketAddress, marketVersion]);

  if (!activeMarketAddress) {
    return (
      <div className="card" style={{ textAlign: 'center', color: '#94a3b8' }}>
        暂无 Compound 市场配置
      </div>
    );
  }

  return (
    <div className="market-assessment">
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
              <span className="card-title">{activeMarketSymbol} 实时价格</span>
              <span className="badge green-badge">Live</span>
            </div>
            <div className="metric-value" style={{ fontSize: '2.2rem' }}>
              {assetPrice !== null ? (
                `$${assetPrice.toLocaleString(undefined, {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                })}`
              ) : (
                <span style={{ fontSize: '1rem', color: '#64748b' }}>加载中...</span>
              )}
            </div>
          </div>

          <hr style={{ border: 'none', borderTop: '1px solid #1e293b', margin: 0 }} />

          {/* Historical trend */}
          <CompoundPriceTrend asset={activeMarketSymbol} version={marketVersion} />
        </div>

        {/* Right: Historical Data Panel */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
          <CompoundMarketHistoryChart
            version={marketVersion}
            market={activeMarketAddress}
            marketSymbol={activeMarketSymbol}
          />

          <div style={{ marginTop: '2rem' }}>
            <CompoundCollateralHistoryChart
              version={marketVersion}
              market={activeMarketAddress}
              marketSymbol={activeMarketSymbol}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
