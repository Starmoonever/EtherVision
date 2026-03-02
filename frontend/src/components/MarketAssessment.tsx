import { useState, useEffect } from 'react';
import { fetchEthPrice } from '../api';
import { LiquidationChart } from './LiquidationChart';
import { EthPriceTrend } from './EthPriceTrend';

interface MarketAssessmentProps {
  version: 'v2' | 'v3' | 'all';
  side: 'collateral' | 'borrow';
}

export function MarketAssessment({ version, side }: MarketAssessmentProps) {
  const [ethPrice, setEthPrice] = useState<number | null>(null); // 初始化为 null，表示尚未获取到价格
  const [priceChange, setPriceChange] = useState<number>(-10); // Percentage change default to -10%

  // Fetch real-time price from API
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const price = await fetchEthPrice();
        setEthPrice(price);
      } catch (err) {
        console.error('Fetch price error:', err);
      }
    };

    fetchPrice(); // Initial fetch
    const interval = setInterval(fetchPrice, 600000); // Poll every 10 minutes
    return () => clearInterval(interval);
  }, []);

  if (ethPrice === null) {
    return (
      <div className="market-assessment" style={{ display: 'flex', justifyContent: 'center', padding: '4rem' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  const simulatedPrice = ethPrice * (1 + priceChange / 100);

  return (
    <div className="market-assessment">
      <div className="summary-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        {/* Module 1: ETH Real-time Price */}
        <div className="card" style={{ gridColumn: 'span 1' }}>
          <div className="card-header">
            <span className="card-title">ETH 实时价格</span>
            <span className="badge green-badge">Live</span>
          </div>
          <div className="metric-box" style={{ border: 'none', padding: 0, background: 'transparent' }}>
            <span className="metric-value" style={{ fontSize: '2rem' }}>
              ${ethPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span className="metric-label" style={{ marginTop: '0.5rem' }}>
              Base Mainnet Oracle
            </span>
          </div>
        </div>

        {/* Module 2: ETH Price Trend */}
        <EthPriceTrend />

        {/* Module 3: Price Volatility Simulation */}
        <div className="card" style={{ gridColumn: 'span 3' }}>
          <div className="card-header">
            <span className="card-title">价格波动下清算模拟</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <span className="check-label">价格变动幅度</span>
                <span className={`mono bold ${priceChange < 0 ? 'red-text' : 'green-text'}`}>
                  {priceChange > 0 ? '+' : ''}{priceChange}%
                </span>
              </div>
              <input
                type="range"
                min="-100"
                max="+200"
                value={priceChange}
                onChange={(e) => setPriceChange(Number(e.target.value))}
                style={{ width: '100%', accentColor: priceChange < 0 ? '#f87171' : '#4ade80' }}
              />
            </div>

            <div className="metric-box">
              <span className="metric-label">模拟 ETH 价格</span>
              <span className={`metric-value ${priceChange < 0 ? 'red' : priceChange > 0 ? 'green' : ''}`}>
                ${simulatedPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
              <span className="check-detail" style={{ marginTop: '0.5rem' }}>
                ETH价格{priceChange >= 0 ? '上涨' : '下跌'} {Math.abs(priceChange)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Module 4: Liquidation Chart */}
      <div style={{ marginTop: '1.5rem' }}>
        <LiquidationChart currentEthPrice={ethPrice} priceChange={priceChange} version={version} side={side} />
      </div>
    </div>
  );
}
