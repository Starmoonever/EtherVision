import { useState, useEffect } from 'react';
import { fetchEthPrice } from '../api';
import { LiquidationChart } from './LiquidationChart';
import { EthPriceTrend } from './EthPriceTrend';
import { MarketHistoryChart } from './MarketHistoryChart';
import { HistoricalLiquidationChart } from './HistoricalLiquidationChart';

export interface MarketAssessmentProps {
  marketVersion: 'v2' | 'v3' | 'all';
  marketSide: 'collateral' | 'borrow';
}

export function MarketAssessment({ marketVersion, marketSide }: MarketAssessmentProps) {
  const [ethPrice, setEthPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number>(-10);
  const [mode, setMode] = useState<'realtime' | 'history'>('realtime');
  const [startDate, setStartDate] = useState('2026-02-10');
  const [endDate, setEndDate] = useState('2026-02-12');

  // Reset priceChange to sensible default when side/mode switches
  useEffect(() => {
    if (mode === 'history') {
      setPriceChange(0);
    } else {
      setPriceChange(marketSide === 'collateral' ? -10 : 10);
    }
  }, [marketSide, mode]);

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
      <div
        className="market-assessment"
        style={{ display: 'flex', justifyContent: 'center', padding: '4rem' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  const simulatedPrice = ethPrice * (1 + priceChange / 100);

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
        {/* ── 左侧：价格 Panel（1/4 宽） ── */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {/* ETH 实时价格：居中 */}
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
              <span className="card-title">ETH 实时价格</span>
              <span className="badge green-badge">Live</span>
            </div>
            <div className="metric-value" style={{ fontSize: '2.2rem' }}>
              $
              {ethPrice.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </div>
            <div className="metric-label" style={{ marginTop: '0.4rem' }}>
              Ethereum Mainnet Oracle
            </div>
          </div>

          {/* 分割线 */}
          <hr style={{ border: 'none', borderTop: '1px solid #1e293b', margin: 0 }} />

          {/* ETH 历史趋势图 */}
          <EthPriceTrend />
        </div>

        {/* ── 右侧：清算模拟 + 图表 Panel（3/4 宽，合并为一个 board） ── */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
          {/* 标题 + 控制器 + 滑块 */}
          <div style={{ padding: '0 0 1.25rem 0' }}>
            <div className="card-header" style={{ marginBottom: '1rem' }}>
              <span className="card-title">
                {mode === 'realtime' ? '实时价格波动下清算模拟' : '历史价格波动清算模拟'}
              </span>
              {/* side / version 切换器 */}
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                {mode === 'history' && (
                  <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      style={{
                        background: '#0f172a',
                        border: '1px solid #334155',
                        color: '#cbd5e1',
                        borderRadius: '4px',
                        padding: '2px 4px',
                        fontSize: '0.8rem',
                      }}
                    />
                    <span style={{ color: '#64748b' }}>-</span>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      style={{
                        background: '#0f172a',
                        border: '1px solid #334155',
                        color: '#cbd5e1',
                        borderRadius: '4px',
                        padding: '2px 4px',
                        fontSize: '0.8rem',
                      }}
                    />
                  </div>
                )}
                <div
                  style={{
                    display: 'flex',
                    background: '#0f172a',
                    borderRadius: '6px',
                    padding: '2px',
                  }}
                >
                  {(['realtime', 'history'] as const).map((m) => (
                    <button
                      key={m}
                      onClick={() => setMode(m)}
                      style={{
                        background: mode === m ? '#3b82f6' : 'transparent',
                        color: mode === m ? '#fff' : '#94a3b8',
                        border: 'none',
                        padding: '3px 10px',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        transition: 'all 0.2s',
                      }}
                    >
                      {m === 'realtime' ? '实时' : '历史'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: '0.5rem',
              }}
            >
              <span className="check-label">
                模拟ETH价格：
                <span className={`mono bold ${priceChange < 0 ? 'red-text' : 'green-text'}`}>
                  $
                  {simulatedPrice.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </span>
              <span
                className={`mono bold ${priceChange < 0 ? 'red-text' : 'green-text'}`}
                style={{ fontSize: '0.9rem' }}
              >
                {priceChange > 0 ? '+' : ''}
                {priceChange}%
              </span>
            </div>
            <input
              type="range"
              min={marketSide === 'collateral' ? -100 : 0}
              max={marketSide === 'collateral' ? 0 : mode === 'history' ? 200 : 100}
              value={priceChange}
              onChange={(e) => setPriceChange(Number(e.target.value))}
              style={{ width: '100%', accentColor: priceChange < 0 ? '#f87171' : '#4ade80' }}
            />
          </div>

          {/* 图表区：深色背景突出可见性 */}
          <div
            style={{
              background: '#0a0f1a',
              borderRadius: '10px',
              padding: '1rem',
              border: '1px solid #1e293b',
            }}
          >
            {mode === 'realtime' ? (
              <LiquidationChart
                currentEthPrice={ethPrice}
                priceChange={priceChange}
                version={marketVersion}
                side={marketSide}
                onPriceChange={setPriceChange}
              />
            ) : (
              <HistoricalLiquidationChart
                version={marketVersion}
                startDate={startDate}
                endDate={endDate}
                priceChange={priceChange}
              />
            )}
          </div>

          <MarketHistoryChart version={marketVersion} />
        </div>
      </div>
    </div>
  );
}
