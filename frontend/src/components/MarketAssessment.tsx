import { useState, useEffect } from 'react';
import { LiquidationChart } from './LiquidationChart';

interface MarketAssessmentProps {
  version: 'v2' | 'v3';
}

export function MarketAssessment({ version }: MarketAssessmentProps) {
  const [ethPrice, setEthPrice] = useState<number | null>(null); // 初始化为 null，表示尚未获取到价格
  const [priceChange, setPriceChange] = useState<number>(0); // Percentage change
  
  // Fetch real-time price from API
  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const response = await fetch(`${baseUrl}/price?asset=eth&time=now`);
        if (!response.ok) {
          throw new Error('无法获取 ETH 价格');
        }
        const data = await response.json();
        // API 返回格式: { asset, price_usd, token_address, timestamp, source }
        const price = parseFloat(data.price_usd);
        if (!isNaN(price)) {
          setEthPrice(price);
        }
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
      <div className="summary-grid">
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

        {/* Module 2: Price Volatility Simulation */}
        <div className="card" style={{ gridColumn: 'span 2' }}>
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
                max="0" 
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
                ETH价格下跌 {Math.abs(priceChange)}% 
              </span>
            </div>
          </div>
        </div>
      </div>
      
      {/* Module 3: Liquidation Chart */}
      <div style={{ marginTop: '1.5rem' }}>
        <LiquidationChart currentEthPrice={ethPrice} priceChange={priceChange} version={version} />
      </div>
    </div>
  );
}
