import { useState, useEffect, useRef } from 'react';
import { fetchEthPrice } from '../api';
import { LiquidationChart } from './LiquidationChart';
import { EthPriceTrend } from './EthPriceTrend';
import { MarketHistoryChart } from './MarketHistoryChart';
import { HistoricalLiquidationChart } from './HistoricalLiquidationChart';
import { WaterfallLiquidationChart } from './WaterfallLiquidationChart';

export interface MarketAssessmentProps {
  marketVersion: 'v2' | 'v3' | 'all';
}

export function MarketAssessment({ marketVersion }: MarketAssessmentProps) {
  const [marketSide, setMarketSide] = useState<'collateral' | 'borrow'>('collateral');
  const [ethPrice, setEthPrice] = useState<number | null>(null);
  // priceChange: 滑块当前显示值（立即更新，驱动界面显示）
  const [priceChange, setPriceChange] = useState<number>(-10);
  // committedPriceChange: 防抖后的值（停留 1s 才更新，传给图表触发请求）
  const [committedPriceChange, setCommittedPriceChange] = useState<number>(-10);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mode, setMode] = useState<'realtime' | 'history'>('realtime');
  const [startDate, setStartDate] = useState('2026-02-10');
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));

  // 切换 side / mode 时立即重置两个状态，并取消未触发的防抖
  useEffect(() => {
    const next = mode === 'history' ? 0 : marketSide === 'collateral' ? -10 : 10;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setPriceChange(next);
    setCommittedPriceChange(next);
  }, [marketSide, mode]);

  // 滑块拖动：立即更新显示值，1s 无操作后才提交给图表
  const handlePriceChange = (val: number) => {
    setPriceChange(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setCommittedPriceChange(val);
    }, 1000);
  };

  // 组件卸载时清理未触发的防抖
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

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

  const sliderMin = marketSide === 'collateral' ? -100 : 0;
  const sliderMax = marketSide === 'collateral' ? 0 : mode === 'history' ? 200 : 100;
  const sliderTicks = Array.from(
    { length: Math.floor((sliderMax - sliderMin) / 10) + 1 },
    (_, index) => sliderMin + index * 10,
  );
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
                      onClick={() => setMarketSide(s)}
                      style={{
                        background: marketSide === s ? '#3b82f6' : 'transparent',
                        color: marketSide === s ? '#fff' : '#94a3b8',
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
            <div style={{ position: 'relative', paddingBottom: '0.6rem' }}>
              <input
                type="range"
                min={sliderMin}
                max={sliderMax}
                value={priceChange}
                onChange={(e) => handlePriceChange(Number(e.target.value))}
                style={{ width: '100%', accentColor: priceChange < 0 ? '#f87171' : '#4ade80' }}
              />
              {sliderTicks.map((tick) => {
                const left = ((tick - sliderMin) / (sliderMax - sliderMin)) * 100;
                return (
                  <div
                    key={tick}
                    style={{
                      position: 'absolute',
                      top: '15px',
                      left: `${left}%`,
                      width: '1px',
                      height: '6px',
                      background: '#475569',
                      transform: 'translateX(-0.5px)',
                      pointerEvents: 'none',
                    }}
                  />
                );
              })}
            </div>
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
                priceChange={committedPriceChange}
                version={marketVersion}
                side={marketSide}
                onPriceChange={(val) => {
                  setPriceChange(val);
                  setCommittedPriceChange(val);
                }}
              />
            ) : (
              <HistoricalLiquidationChart
                version={marketVersion}
                side={marketSide}
                startDate={startDate}
                endDate={endDate}
                priceChange={committedPriceChange}
              />
            )}
          </div>

          {/* 清算瀑布图 */}
          <WaterfallLiquidationChart version={marketVersion} />

          <MarketHistoryChart version={marketVersion} />
        </div>
      </div>
    </div>
  );
}
