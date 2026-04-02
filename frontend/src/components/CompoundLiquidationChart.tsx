import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { fetchEthPrice } from '../api';
import {
  fetchCompoundLiquidationPeriod,
  type CompoundLiquidationPeriodItem,
} from '../api/compound';

interface CompoundLiquidationChartProps {
  version: 'v2' | 'v3';
  market: string;
  marketSymbol: string;
}

interface ChartDataPoint {
  price: number;
  priceLabel: string;
  totalLiquidationUsd: number;
  positionsCnt: number;
  totalSensitiveCollateralUsd: number;
  isCurrent: boolean;
}

type ChartTooltipValue = string | number | ReadonlyArray<string | number>;

export function CompoundLiquidationChart({
  version,
  market,
  marketSymbol,
}: CompoundLiquidationChartProps) {
  const [ethPrice, setEthPrice] = useState<number | null>(null);
  const [priceChange, setPriceChange] = useState(-10);
  const [committedPriceChange, setCommittedPriceChange] = useState(-10);
  const [chartData, setChartData] = useState<ChartDataPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setPriceChange(-10);
    setCommittedPriceChange(-10);
    setError('');
  }, [market, version]);

  useEffect(() => {
    const loadEthPrice = async () => {
      try {
        const price = await fetchEthPrice();
        setEthPrice(price);
      } catch (err) {
        console.error('Fetch ETH price error:', err);
      }
    };

    loadEthPrice();
    const intervalId = window.setInterval(loadEthPrice, 600000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current);
      }
    };
  }, []);

  const handlePriceChange = (value: number) => {
    setPriceChange(value);
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }
    debounceRef.current = setTimeout(() => {
      setCommittedPriceChange(value);
    }, 300);
  };

  useEffect(() => {
    const loadChartData = async () => {
      if (!ethPrice || ethPrice <= 0 || !market) return;

      setLoading(true);
      setError('');

      try {
        const points = await fetchCompoundLiquidationPeriod(version, market, 0.01, ethPrice, 5);

        const rangeSteps = Array.from({ length: 101 }, (_, index) => -100 + index);
        const mappedData = rangeSteps.map((step) => mapPeriodPointToChart(step, ethPrice, points));

        setChartData(mappedData);
      } catch (err) {
        console.error('Fetch Compound liquidation range data error:', err);
        setChartData([]);
        setError(err instanceof Error ? err.message : '加载清算模拟失败');
      } finally {
        setLoading(false);
      }
    };

    loadChartData();
  }, [ethPrice, market, version]);

  const selectedPrice = ethPrice ? ethPrice * (1 + committedPriceChange / 100) : 0;
  const displayedPrice = ethPrice ? ethPrice * (1 + priceChange / 100) : 0;

  const highlightedData = useMemo(
    () =>
      chartData.map((item) => ({
        ...item,
        isCurrent: ethPrice
          ? Math.abs(item.price - selectedPrice) < Math.max(1, ethPrice * 0.005)
          : false,
      })),
    [chartData, ethPrice, selectedPrice],
  );

  if (ethPrice === null) {
    return (
      <div style={{ height: 380, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner"></div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card-header" style={{ marginBottom: 0 }}>
        <span className="card-title">实时价格波动下清算模拟</span>
        <span className="badge green-badge">{marketSymbol || 'Market'}</span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: '0.75rem',
        }}
      >
        <MetricCard
          label="当前 ETH 价格"
          value={`$${ethPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          hint="Ethereum Mainnet Oracle"
        />
        <MetricCard
          label="模拟 ETH 价格"
          value={`$${displayedPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          hint={`${priceChange > 0 ? '+' : ''}${priceChange}%`}
          accent={priceChange < 0 ? '#f87171' : '#4ade80'}
        />
      </div>

      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'baseline',
            marginBottom: '0.5rem',
          }}
        >
          <span className="check-label">拖动滑块查看不同 ETH 价格下的清算规模</span>
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
            min={-100}
            max={0}
            value={priceChange}
            onChange={(event) => handlePriceChange(Number(event.target.value))}
            style={{ width: '100%', accentColor: '#f87171' }}
          />
          {Array.from({ length: 11 }, (_, index) => -100 + index * 10).map((tick) => {
            const left = tick + 100;
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

      <div
        style={{
          background: '#0a0f1a',
          borderRadius: '10px',
          padding: '1rem',
          border: '1px solid #1e293b',
          minHeight: '340px',
        }}
      >
        {loading && chartData.length === 0 ? (
          <div
            style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <div className="spinner"></div>
          </div>
        ) : error ? (
          <div
            style={{
              height: 300,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#94a3b8',
              textAlign: 'center',
              padding: '0 1.5rem',
            }}
          >
            {error}
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart
              data={highlightedData}
              margin={{ top: 20, right: 30, left: 10, bottom: 5 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="priceLabel"
                stroke="#64748b"
                tick={{ fontSize: 11 }}
                minTickGap={24}
                label={{
                  value: 'ETH 价格下降幅度',
                  position: 'insideBottom',
                  offset: -5,
                  fill: '#64748b',
                  fontSize: 12,
                }}
              />
              <YAxis
                yAxisId="left"
                stroke="#64748b"
                tickFormatter={(value) => `$${(Number(value) / 1000000).toFixed(1)}M`}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                stroke="#38bdf8"
                allowDecimals={false}
                tickFormatter={(value) => `${value}`}
              />
              <Tooltip
                cursor={{ fill: '#1e293b', opacity: 0.4 }}
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#1e293b',
                  color: '#e2e8f0',
                }}
                formatter={(
                  value: ChartTooltipValue | undefined,
                  name: string | number | undefined,
                ) => {
                  const normalizedValue = Array.isArray(value) ? value[0] : value;
                  const label = String(name ?? '');

                  if (label === 'positionsCnt') {
                    return [Number(normalizedValue ?? 0).toLocaleString(), '清算仓位数'];
                  }

                  if (label === 'totalSensitiveCollateralUsd') {
                    return [
                      `$${Number(normalizedValue ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                      'ETH 敏感抵押',
                    ];
                  }

                  return [
                    `$${Number(normalizedValue ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
                    '预计清算规模',
                  ];
                }}
                labelFormatter={(label, payload) => {
                  if (payload && payload.length > 0) {
                    const point = payload[0].payload as ChartDataPoint;
                    return `ETH 价格: $${point.price.toLocaleString(undefined, { maximumFractionDigits: 2 })} (${point.priceLabel})`;
                  }
                  return label;
                }}
              />
              <Bar
                yAxisId="left"
                dataKey="totalLiquidationUsd"
                fill="#e43f36"
                radius={[4, 4, 0, 0]}
                activeBar={{ fill: '#4a6080' }}
                onClick={(barData) => {
                  const clickedPrice = (barData as { payload?: ChartDataPoint }).payload?.price;
                  if (!clickedPrice) return;
                  const rawPct = Math.round((clickedPrice / ethPrice - 1) * 100);
                  handlePriceChange(Math.max(-100, Math.min(0, rawPct)));
                  setCommittedPriceChange(Math.max(-100, Math.min(0, rawPct)));
                }}
                shape={(props: {
                  x?: number;
                  y?: number;
                  width?: number;
                  height?: number;
                  index?: number;
                }) => {
                  const { x = 0, y = 0, width = 0, height = 0, index = 0 } = props;
                  const entry = highlightedData[index];
                  const color = entry?.isCurrent ? '#ef4444' : '#334155';
                  return (
                    <rect x={x} y={y} width={width} height={height} fill={color} rx={4} ry={4} />
                  );
                }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="positionsCnt"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="totalSensitiveCollateralUsd"
                stroke="#f59e0b"
                strokeWidth={1.5}
                strokeDasharray="6 4"
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function mapPeriodPointToChart(
  step: number,
  currentEthPrice: number,
  points: CompoundLiquidationPeriodItem[],
): ChartDataPoint {
  const simulatedPrice = currentEthPrice * (1 + step / 100);

  let closest: CompoundLiquidationPeriodItem | null = null;
  let minDiff = Infinity;

  for (const item of points) {
    const pointPrice = parseFloat(item.simulated_eth_price);
    const diff = Math.abs(pointPrice - simulatedPrice);
    if (diff < minDiff) {
      minDiff = diff;
      closest = item;
    }
  }

  if (!closest || minDiff > 100) {
    return {
      price: simulatedPrice,
      priceLabel: `${step}%`,
      totalLiquidationUsd: 0,
      positionsCnt: 0,
      totalSensitiveCollateralUsd: 0,
      isCurrent: false,
    };
  }

  return {
    price: simulatedPrice,
    priceLabel: `${step}%`,
    totalLiquidationUsd: parseFloat(closest.total_liquidation_usd),
    positionsCnt: parseInt(closest.positions_cnt, 10) || 0,
    totalSensitiveCollateralUsd: parseFloat(closest.total_eth_sensitive_collateral_usd),
    isCurrent: false,
  };
}

interface MetricCardProps {
  label: string;
  value: string;
  hint: string;
  accent?: string;
}

function MetricCard({ label, value, hint, accent = '#e2e8f0' }: MetricCardProps) {
  return (
    <div
      style={{
        background: '#0f172a',
        border: '1px solid #1e293b',
        borderRadius: '10px',
        padding: '0.9rem 1rem',
      }}
    >
      <div style={{ color: '#94a3b8', fontSize: '0.82rem', marginBottom: '0.35rem' }}>{label}</div>
      <div style={{ color: accent, fontSize: '1.4rem', fontWeight: 700, lineHeight: 1.2 }}>
        {value}
      </div>
      <div style={{ color: '#64748b', fontSize: '0.78rem', marginTop: '0.3rem' }}>{hint}</div>
    </div>
  );
}
