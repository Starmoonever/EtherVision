import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface PositionReplayProps {
  address: string;
  version: 'v2' | 'v3';
}

interface ReplayPoint {
  timestamp: string;
  eth_price_usd: number;
  eth_collateral_usd: number;
  weth_debt_usd: number;
  liq_price: number;
  brief: string;
  total_collateral_usd: number;
  total_debt_usd: number;
  available_borrows_usd: number;
  health_factor: number;
  operation_type: string;
  original_operation_type: string;
}

const CustomTooltip = ({ active, payload, label, onDetailsClick, primaryMetric }: any) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload;
    return (
      <div
        className="custom-tooltip"
        style={{
          backgroundColor: '#0f172a',
          borderColor: '#1e293b',
          border: '1px solid',
          padding: '10px',
          borderRadius: '4px',
        }}
      >
        <p className="label" style={{ color: '#94a3b8', marginBottom: '5px' }}>
          {point.brief ? `${label} - ${point.brief}` : label}
        </p>
        <p style={{ color: '#fbbf24', fontSize: '0.8rem', marginBottom: '5px' }}>
          类型: {point.operation_type}
          {point.original_operation_type &&
            point.original_operation_type !== point.operation_type &&
            point.original_operation_type !== 'unknown' && (
              <span style={{ color: '#94a3b8', marginLeft: '4px' }}>
                ({point.original_operation_type})
              </span>
            )}
        </p>
        {primaryMetric === 'eth_collateral_usd' ? (
            <p style={{ color: '#e2e8f0', margin: 0, fontSize: '0.9rem' }}>
                总抵押资产价值: {point.total_collateral_usd}
            </p>
        ) : (
            <p style={{ color: '#e2e8f0', margin: 0, fontSize: '0.9rem' }}>
                总贷出债务价值: {point.total_debt_usd}
            </p>
        )}
        {payload.map((entry: any, index: number) => (
          <p key={index} style={{ color: entry.color, margin: 0, fontSize: '0.9rem' }}>
            {entry.name}: {entry.value}
          </p>
        ))}
        <button
          onClick={() => onDetailsClick(point)}
          style={{
            marginTop: '8px',
            background: '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: '4px',
            padding: '4px 8px',
            cursor: 'pointer',
            fontSize: '0.8rem',
          }}
        >
          账户头寸明细
        </button>
      </div>
    );
  }
  return null;
};

const DetailsModal = ({ point, onClose }: { point: ReplayPoint; onClose: () => void }) => {
  if (!point) return null;
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: '#1e293b',
          padding: '20px',
          borderRadius: '8px',
          width: '400px',
          maxWidth: '90%',
          border: '1px solid #334155',
        }}
      >
        <h3 style={{ color: '#fff', marginTop: 0, marginBottom: '1rem' }}>账户详情</h3>
        <div style={{ display: 'grid', gap: '10px', color: '#e2e8f0', fontSize: '0.9rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>时间:</span> <span>{point.timestamp}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>总抵押资产价值:</span>{' '}
            <span>
              ${point.total_collateral_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>总贷出债务价值:</span>{' '}
            <span>
              ${point.total_debt_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>可借出总额:</span>{' '}
            <span>
              ${point.available_borrows_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>健康因子:</span>{' '}
            <span>{point.health_factor.toFixed(2)}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>抵押ETH价值:</span>{' '}
            <span>
              ${point.eth_collateral_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: '#94a3b8' }}>贷出ETH价值:</span>{' '}
            <span>
              ${point.weth_debt_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px' }}>
          <button
            onClick={onClose}
            style={{
              padding: '6px 16px',
              background: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
};

export function PositionReplayChart({ address, version }: PositionReplayProps) {
  const [fullData, setFullData] = useState<ReplayPoint[]>([]); // Store full dataset 存储首次请求获取的完整历史数据
  const [data, setData] = useState<ReplayPoint[]>([]); // Store filtered/displayed dataset
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [primaryMetric, setPrimaryMetric] = useState<'eth_collateral_usd' | 'weth_debt_usd'>(
    'eth_collateral_usd',
  );
  const [selectedPoint, setSelectedPoint] = useState<ReplayPoint | null>(null);
  const [activeTooltip, setActiveTooltip] = useState<{
    index: number;
    coordinate: { x: number; y: number };
  } | null>(null);

  const [startTime, setStartTime] = useState('2020-12-01 00:00:00');
  const [endTime, setEndTime] = useState(() => {
    const now = new Date();
    const year = now.getUTCFullYear();
    const month = String(now.getUTCMonth() + 1).padStart(2, '0');
    const day = String(now.getUTCDate()).padStart(2, '0');
    const hours = String(now.getUTCHours()).padStart(2, '0');
    const minutes = String(now.getUTCMinutes()).padStart(2, '0');
    const seconds = String(now.getUTCSeconds()).padStart(2, '0');
    return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
  });

  const [selectedType, setSelectedType] = useState<string>('all');

  // Fetch full history ONCE on mount/address change
  useEffect(() => {
    const fetchFullHistory = async () => {
      setLoading(true);
      setError('');
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL;

        // Always fetch the full range initially
        const defaultStart = '2020-12-01 00:00:00';
        const now = new Date();
        const year = now.getUTCFullYear();
        const month = String(now.getUTCMonth() + 1).padStart(2, '0');
        const day = String(now.getUTCDate()).padStart(2, '0');
        const hours = String(now.getUTCHours()).padStart(2, '0');
        const minutes = String(now.getUTCMinutes()).padStart(2, '0');
        const seconds = String(now.getUTCSeconds()).padStart(2, '0');
        const defaultEnd = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;

        const response = await fetch(
          `${baseUrl}/aave/position/replay?address=${address}&start=${encodeURIComponent(defaultStart)}&end=${encodeURIComponent(defaultEnd)}&version=${version}`,
        );

        if (!response.ok) {
          throw new Error('Failed to fetch replay data');
        }

        const result = await response.json();

        if (!result.points || !Array.isArray(result.points)) {
          throw new Error('Invalid data format');
        }

        const formattedData = result.points
          .map((pt: any) => {
            const d = new Date(pt.timestamp);
            const pad = (n: number) => n.toString().padStart(2, '0');
            const timeStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

            const original_operation_type = pt.operation_type || 'unknown';
            let operation_type = original_operation_type;
            let liq_price = parseFloat(pt.liq_price || '0');
            const eth_price_usd = parseFloat(pt.eth_price_usd || '0');
            const eth_collateral_usd = parseFloat(pt.eth_collateral_usd || '0');
            const total_collateral_usd = parseFloat(pt.total_collateral_usd || '0');
            const weth_debt_usd = parseFloat(pt.weth_debt_usd || '0');
            const total_debt_usd = parseFloat(pt.total_debt_usd || '0');

            // Check for "同类资产借贷" (Same asset borrowing)
            const isSameAsset =
              Math.abs(total_collateral_usd - eth_collateral_usd) < 1 &&
              Math.abs(total_debt_usd - weth_debt_usd) < 1;

            if (isSameAsset) {
              operation_type = '杠杆质押(存入LST，借出WETH)';
              liq_price = 0;
            }

            return {
              timestamp: timeStr,
              eth_price_usd,
              eth_collateral_usd,
              weth_debt_usd,
              liq_price,
              brief: pt.brief || '',
              total_collateral_usd,
              total_debt_usd,
              available_borrows_usd: parseFloat(pt.available_borrows_usd || '0'),
              health_factor: parseFloat(pt.health_factor || '0'),
              operation_type,
              original_operation_type,
            };
          })
          .sort(
            (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime(),
          );

        setFullData(formattedData);
        setData(formattedData); // Initialize display data with full data
      } catch (err) {
        console.error(err);
        setError('无法加载历史回放数据');
      } finally {
        setLoading(false);
      }
    };

    if (address) {
      fetchFullHistory();
    }
  }, [address, version]);

  // Filter data locally when search/filter params change
  useEffect(() => {
    if (!fullData.length) return;

    // Filter by time range
    const startTs = new Date(startTime).getTime();
    const endTs = new Date(endTime).getTime();

    const filtered = fullData.filter((pt) => {
      const ptTs = new Date(pt.timestamp).getTime();
      return ptTs >= startTs && ptTs <= endTs;
    });

    setData(filtered);

    // Reset tooltip on filter change
    setActiveTooltip(null);
    setSelectedPoint(null);
  }, [startTime, endTime, fullData]);

  const [appliedRange, setAppliedRange] = useState({ start: '2020-12-01 00:00:00', end: endTime });

  // Update applied range on mount to match initial default
  useEffect(() => {
    setAppliedRange({ start: '2020-12-01 00:00:00', end: endTime });
  }, []);

  // The actual filtering effect depends on appliedRange
  useEffect(() => {
    if (!fullData.length) return;
    const startTs = new Date(appliedRange.start).getTime();
    const endTs = new Date(appliedRange.end).getTime();

    let filtered = fullData.filter((pt) => {
      const ptTs = new Date(pt.timestamp).getTime();
      return ptTs >= startTs && ptTs <= endTs;
    });

    // If a specific type is selected, filter by that type as well
    if (selectedType !== 'all') {
      filtered = filtered.filter(
        (pt) => pt.operation_type === selectedType || pt.original_operation_type === selectedType,
      );
    }

    setData(filtered);
    setActiveTooltip(null);
    setSelectedPoint(null);
  }, [appliedRange, fullData, selectedType]);

  // Button click handler
  const handleSearch = () => {
    setAppliedRange({ start: startTime, end: endTime });
  };

  const handleChartClick = (e: any) => {
    if (e && e.activeTooltipIndex !== undefined && e.activeCoordinate) {
      if (activeTooltip && activeTooltip.index === e.activeTooltipIndex) {
        setActiveTooltip(null); // Toggle off if clicking the same point
      } else {
        setActiveTooltip({
          index: e.activeTooltipIndex,
          coordinate: e.activeCoordinate,
        });
      }
    } else {
      // Don't close if clicking inside the tooltip (handled by wrapperStyle pointerEvents)
      // But Recharts click handler is on the chart area.
      setActiveTooltip(null);
    }
  };

  if (loading)
    return (
      <div
        className="card"
        style={{ height: 550, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  if (error)
    return (
      <div
        className="card"
        style={{
          height: 100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#f87171',
        }}
      >
        {error}
      </div>
    );
  // if (!data.length) return null; // Previously this would hide the whole chart if no data

  return (
    <div className="card" style={{ marginTop: '1.5rem' }}>
      <div
        className="card-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
      >
        <span className="card-title">历史交易与头寸变化记录</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.2rem' }}>
            <input
              type="text"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              placeholder="起始时间"
              style={{
                background: '#1e293b',
                color: '#e2e8f0',
                border: '1px solid #334155',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
                fontSize: '0.8rem',
                width: '140px',
              }}
            />
            <span style={{ color: '#94a3b8' }}>-</span>
            <input
              type="text"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              placeholder="结束时间"
              style={{
                background: '#1e293b',
                color: '#e2e8f0',
                border: '1px solid #334155',
                padding: '0.2rem 0.5rem',
                borderRadius: '4px',
                fontSize: '0.8rem',
                width: '140px',
              }}
            />
            <button
              onClick={handleSearch}
              style={{
                background: '#3b82f6',
                color: '#fff',
                border: 'none',
                padding: '0.2rem 0.8rem',
                borderRadius: '4px',
                fontSize: '0.8rem',
                cursor: 'pointer',
              }}
            >
              查询
            </button>
          </div>
          <span style={{ fontSize: '0.85rem', color: '#94a3b8', marginLeft: '0.5rem' }}>指标:</span>
          <select
            value={primaryMetric}
            onChange={(e) => setPrimaryMetric(e.target.value as any)}
            style={{
              background: '#1e293b',
              color: '#e2e8f0',
              border: '1px solid #334155',
              padding: '0.2rem 0.5rem',
              borderRadius: '4px',
              fontSize: '0.85rem',
            }}
          >
            <option value="eth_collateral_usd">抵押ETH价值 (USD)</option>
            <option value="weth_debt_usd">贷出ETH价值 (USD)</option>
          </select>
        </div>
      </div>

      <div
        style={{
          padding: '0 1rem 0.5rem 1rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.8rem',
        }}
      >
        {/* Basic Types */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600 }}>
            基本交易类型:
          </span>
          <button
            onClick={() => setSelectedType('all')}
            style={{
              padding: '2px 8px',
              fontSize: '0.75rem',
              borderRadius: '4px',
              border: '1px solid #334155',
              background: selectedType === 'all' ? '#3b82f6' : 'transparent',
              color: selectedType === 'all' ? '#fff' : '#94a3b8',
              cursor: 'pointer',
              textTransform: 'capitalize',
            }}
          >
            All
          </button>
          {['borrow', 'repay', 'deposit', 'withdraw'].map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              style={{
                padding: '2px 8px',
                fontSize: '0.75rem',
                borderRadius: '4px',
                border: '1px solid #334155',
                background: selectedType === type ? '#3b82f6' : 'transparent',
                color: selectedType === type ? '#fff' : '#94a3b8',
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {type}
            </button>
          ))}
        </div>

        {/* Advanced Types */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600 }}>
            混合交易类型:
          </span>
          {['liquidate', 'flash loan', '杠杆质押(存入LST，借出WETH)'].map((type) => (
            <button
              key={type}
              onClick={() => setSelectedType(type)}
              style={{
                padding: '2px 8px',
                fontSize: '0.75rem',
                borderRadius: '4px',
                border: '1px solid #334155',
                background: selectedType === type ? '#3b82f6' : 'transparent',
                color: selectedType === type ? '#fff' : '#94a3b8',
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      <div style={{ height: 550 }}>
        {!data.length ? (
          <div
            style={{
              height: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#94a3b8',
            }}
          >
            暂无该时间段的交易数据
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart
              data={data}
              margin={{ top: 10, right: 30, left: 10, bottom: 5 }}
              onClick={handleChartClick}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="timestamp" stroke="#64748b" tick={{ fontSize: 12 }} minTickGap={50} />

              {/* 左轴：资产/债务价值 */}
              <YAxis
                yAxisId="left"
                stroke="#10b981"
                tickFormatter={(val) => `$${(val / 1000).toFixed(0)}k`}
              />

              {/* 右轴：ETH价格 & 清算价格 */}
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#3b82f6"
                tickFormatter={(val) => `$${val}`}
              />

              <Tooltip
                content={<CustomTooltip onDetailsClick={setSelectedPoint} primaryMetric={primaryMetric} />}
                wrapperStyle={{ pointerEvents: 'auto', zIndex: 1000 }}
                trigger="hover"
                active={activeTooltip !== null ? true : undefined}
                position={activeTooltip ? activeTooltip.coordinate : undefined}
              />
              {/*
              Workaround: Recharts onClick gives us the activeIndex.
              We can conditionally render a custom overlay OR try to force the Tooltip props.
              Actually, Recharts `Tooltip` has a `shared` and `defaultIndex` prop but not "force show at index".

              Better UX plan:
              1. Keep standard hover tooltip.
              2. When clicked, setting activeTooltipIndex.
              3. Pass `active={true}` and `payload={...}` corresponding to that index to Tooltip.

              However, cursor follows mouse. To "freeze" it, we might need to stop the mouse events or provide a fixed coordinate.
              Recharts doesn't make "freezing" easy.

              Alternative: When clicked, we open the "DetailsModal" directly?
              User asked to "fix the tooltip".

              Let's try controlling `active` and `payload`.
              Positioning will still follow mouse if we don't provide `coordinate`.
              But `coordinate` is hard to calculate without internal chart state.

              Actually, `onClick` on Chart gives `activeCoordinate`. We can save that!
            */}
              <Legend />

              <Line
                yAxisId="left"
                type="monotone"
                dataKey={primaryMetric}
                stroke="#10b981"
                strokeWidth={2}
                dot={(props: any) => {
                  const { cx, cy, payload } = props;

                  // If filtering by specific type, show prominent dots
                  return (
                    <circle
                      key={payload.timestamp}
                      cx={cx}
                      cy={cy}
                      r={3}
                      fill="#fff"
                      stroke="none"
                    />
                  );
                }}
                name={primaryMetric === 'eth_collateral_usd' ? '抵押ETH价值' : '贷出ETH价值'}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="eth_price_usd"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                name="ETH 价格"
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="liq_price"
                stroke="#ef4444"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                name="ETH清算价格"
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {selectedPoint && (
        <DetailsModal point={selectedPoint} onClose={() => setSelectedPoint(null)} />
      )}
    </div>
  );
}
