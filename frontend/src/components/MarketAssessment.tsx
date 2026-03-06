import { useState, useEffect } from 'react';
import { fetchEthPrice } from '../api';
import { LiquidationChart } from './LiquidationChart';
import { EthPriceTrend } from './EthPriceTrend';
import { MarketHistoryChart } from './MarketHistoryChart';

export function MarketAssessment() {
  const [ethPrice, setEthPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState<number>(-10);
  const [version, setVersion] = useState<'v2' | 'v3' | 'all'>('all');
  const [side, setSide] = useState<'collateral' | 'borrow'>('collateral');

  // Reset priceChange to sensible default when side switches
  useEffect(() => {
    setPriceChange(side === 'collateral' ? -10 : 10);
  }, [side]);

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
              <span className="card-title">价格波动下清算模拟</span>
              {/* side / version 切换器 */}
              <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                <div
                  style={{
                    display: 'flex',
                    background: '#0f172a',
                    borderRadius: '6px',
                    padding: '2px',
                  }}
                >
                  {(['collateral', 'borrow'] as const).map((s) => (
                    <button
                      key={s}
                      onClick={() => setSide(s)}
                      style={{
                        background: side === s ? '#3b82f6' : 'transparent',
                        color: side === s ? '#fff' : '#94a3b8',
                        border: 'none',
                        padding: '3px 10px',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        transition: 'all 0.2s',
                      }}
                    >
                      {s === 'collateral' ? '抵押端' : '借贷端'}
                    </button>
                  ))}
                </div>
                <div
                  style={{
                    display: 'flex',
                    background: '#0f172a',
                    borderRadius: '6px',
                    padding: '2px',
                  }}
                >
                  {(['v2', 'v3', 'all'] as const).map((v) => (
                    <button
                      key={v}
                      onClick={() => setVersion(v)}
                      style={{
                        background: version === v ? '#7c3aed' : 'transparent',
                        color: version === v ? '#fff' : '#94a3b8',
                        border: 'none',
                        padding: '3px 10px',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        transition: 'all 0.2s',
                      }}
                    >
                      {v.toUpperCase()}
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
              min={side === 'collateral' ? -100 : 0}
              max={side === 'collateral' ? 0 : 100}
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
            <LiquidationChart
              currentEthPrice={ethPrice}
              priceChange={priceChange}
              version={version}
              side={side}
              onPriceChange={setPriceChange}
            />
          </div>

          <MarketHistoryChart version={version} />
        </div>
      </div>
    </div>
  );
}
