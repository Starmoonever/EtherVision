import { useEffect, useState } from 'react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { apiFetch } from '../api/client';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import type { AggregatedRequestMeta } from '../api/requestMeta';

interface MarketHistoryChartProps {
  version: 'v2' | 'v3' | 'all';
  riskReferencePrice?: number;
  riskDirection?: 'up' | 'down';
  scenarioLabel?: string;
}

interface MarketReplayPoint {
  block_timestamp: string;
  eth_price_usd: string;
  eth_total_debt_usd: string;
  eth_available_liquidity_usd: string;
  eth_supply_apy: string;
  eth_variable_borrow_apy: string;
  eth_utilization_rate: string;
}

interface MarketReplayResponse {
  points: MarketReplayPoint[];
}

interface MarketPoint {
  timestamp: string;
  eth_price_usd: number;
  total_debt_usd: number;
  available_liquidity_usd: number;
  variable_borrow_apy: number;
  supply_apy: number;
  utilization_rate: number;
}

type TimeRangePreset = '3M' | '6M' | '1Y';

type ChartTooltipValue = string | number | ReadonlyArray<string | number>;

const HISTORY_CACHE_TTL_MS = 5 * 60 * 1000;
const historyCache = new Map<string, { fetchedAt: number; data: MarketPoint[] }>();

const explainItems: ExplainItem[] = [
  {
    term: '市场规模',
    formula: '借出 ETH 总值 + 剩余可借 ETH 总值',
    meaning: '反映协议内 ETH 借贷盘子的大小和剩余流动性缓冲。',
    riskHint: '借出规模大、剩余流动性小，代表系统在冲击下更容易出现资金紧张。',
  },
  {
    term: '资金利用率',
    formula: 'utilization = borrowed / available liquidity',
    meaning: '利用率越高，说明池子里的资金越被借走，利率和脆弱性通常也越高。',
    riskHint: '高利用率叠加价格快速下跌时，清算与利率上升往往会同时出现。',
  },
  {
    term: '联动风险阈值',
    formula: '来自清算模拟当前选中的 ETH 价格',
    meaning: '把压力测试中的价格阈值，映射到真实历史价格曲线上做对照。',
    riskHint: '如果历史价格反复接近这条线，说明该风险情景并非极端小概率事件。',
  },
];

function formatDateInput(date: Date) {
  return date.toISOString().split('T')[0];
}

function getPresetRange(preset: TimeRangePreset) {
  const endDate = new Date();
  const startDate = new Date(endDate);

  if (preset === '3M') startDate.setMonth(endDate.getMonth() - 3);
  else if (preset === '6M') startDate.setMonth(endDate.getMonth() - 6);
  else startDate.setFullYear(endDate.getFullYear() - 1);

  return {
    start: formatDateInput(startDate),
    end: formatDateInput(endDate),
  };
}

function formatUsdTick(value: number) {
  return `$${(value / 1e6).toFixed(0)}M`;
}

function formatPriceTick(value: number) {
  return `$${value.toFixed(0)}`;
}

function formatTooltipValue(
  value: ChartTooltipValue | undefined,
  name: string | number | undefined,
) {
  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
  const label = String(name ?? '');
  if (label === 'ETH 历史价格') {
    return [`$${numericValue.toLocaleString()}`, label] as [string, string];
  }
  return [`$${numericValue.toLocaleString()}`, label] as [string, string];
}

function formatRateTooltipValue(
  value: ChartTooltipValue | undefined,
  name: string | number | undefined,
) {
  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
  const label = String(name ?? '');
  if (label === 'ETH 历史价格') {
    return [`$${numericValue.toLocaleString()}`, label] as [string, string];
  }
  return [`${numericValue.toFixed(2)}%`, label] as [string, string];
}

export function MarketHistoryChart({
  version,
  riskReferencePrice,
  riskDirection = 'down',
  scenarioLabel,
}: MarketHistoryChartProps) {
  const [data, setData] = useState<MarketPoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const [timeRange, setTimeRange] = useState<TimeRangePreset | null>('3M');
  const [dateRange, setDateRange] = useState(() => getPresetRange('3M'));
  const today = formatDateInput(new Date());

  useEffect(() => {
    const fetchData = async () => {
      if (version === 'all') {
        setData([]);
        setError('');
        setLoading(false);
        return;
      }

      setLoading(true);
      setError('');
      try {
        const key = `${version}|${dateRange.start}|${dateRange.end}`;
        const cached = historyCache.get(key);

        let finalData: MarketPoint[];
        if (cached && Date.now() - cached.fetchedAt < HISTORY_CACHE_TTL_MS) {
          finalData = cached.data;
          setMeta({
            lastUpdatedAt: cached.fetchedAt,
            cacheStatus: 'hit',
          });
        } else {
          const json = await apiFetch<MarketReplayResponse>(
            `/aave/positions/replay?start=${dateRange.start}&end=${dateRange.end}&version=${version}&interval=24`,
          );

          if (!json.points || !Array.isArray(json.points)) {
            throw new Error('Invalid data format');
          }

          finalData = json.points
            .map((pt) => ({
              timestamp: pt.block_timestamp.split('T')[0],
              eth_price_usd: parseFloat(pt.eth_price_usd || '0'),
              total_debt_usd: parseFloat(pt.eth_total_debt_usd || '0'),
              available_liquidity_usd: parseFloat(pt.eth_available_liquidity_usd || '0'),
              variable_borrow_apy: parseFloat(pt.eth_variable_borrow_apy || '0') * 100,
              supply_apy: parseFloat(pt.eth_supply_apy || '0') * 100,
              utilization_rate: parseFloat(pt.eth_utilization_rate || '0') * 100,
            }))
            .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
          historyCache.set(key, { fetchedAt: Date.now(), data: finalData });
          setMeta({
            lastUpdatedAt: Date.now(),
            cacheStatus: 'miss',
          });
        }

        setData(finalData);
      } catch (err) {
        console.error(err);
        setError('无法加载市场历史数据');
      } finally {
        setLoading(false);
      }
    };

    if (!dateRange.start || !dateRange.end) {
      setData([]);
      setError('请选择完整时间区间');
      return;
    }

    if (dateRange.start > dateRange.end) {
      setData([]);
      setError('开始日期不能晚于结束日期');
      return;
    }

    void fetchData();
  }, [dateRange.end, dateRange.start, version]);

  if (version === 'all') {
    return;
  }

  const handlePresetClick = (preset: TimeRangePreset) => {
    setTimeRange(preset);
    setDateRange(getPresetRange(preset));
  };

  const handleDateChange = (field: 'start' | 'end', value: string) => {
    setTimeRange(null);
    setDateRange((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const renderStatusCard = (message: string, color: string, height = 400, showSpinner = false) => (
    <div
      className="card"
      style={{
        height,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color,
      }}
    >
      {showSpinner ? <div className="spinner"></div> : message}
    </div>
  );

  return (
    <div style={{ marginTop: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '1.2rem', fontWeight: 'bold', color: '#fff' }}>
            历史数据回顾
          </span>
          <ChartInfoButton title="Aave 市场历史图说明" items={explainItems} />
        </div>
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <ChartDataStatus meta={meta} scenarioLabel={scenarioLabel} />
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            {(['3M', '6M', '1Y'] as const).map((preset) => (
              <button
                key={preset}
                onClick={() => handlePresetClick(preset)}
                style={{
                  background: timeRange === preset ? '#3b82f6' : 'transparent',
                  color: timeRange === preset ? '#fff' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '0.75rem',
                }}
              >
                {preset}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <input
              type="date"
              value={dateRange.start}
              max={dateRange.end || today}
              onChange={(e) => handleDateChange('start', e.target.value)}
              style={{
                background: '#0f172a',
                border: '1px solid #334155',
                color: '#cbd5e1',
                borderRadius: '4px',
                padding: '2px 6px',
                fontSize: '0.8rem',
              }}
            />
            <span style={{ color: '#64748b' }}>-</span>
            <input
              type="date"
              value={dateRange.end}
              min={dateRange.start}
              max={today}
              onChange={(e) => handleDateChange('end', e.target.value)}
              style={{
                background: '#0f172a',
                border: '1px solid #334155',
                color: '#cbd5e1',
                borderRadius: '4px',
                padding: '2px 6px',
                fontSize: '0.8rem',
              }}
            />
          </div>
        </div>
      </div>

      {loading ? (
        renderStatusCard('', '#94a3b8', 400, true)
      ) : error ? (
        renderStatusCard(error, '#f87171', 100)
      ) : !data.length ? (
        renderStatusCard('暂无数据', '#94a3b8')
      ) : (
        <>
          <div className="card">
            <div
              className="card-header"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span className="card-title">市场规模（ETH 市场 + ETH 价格）</span>
            </div>
            <div style={{ height: 400 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="timestamp"
                    stroke="#64748b"
                    tick={{ fontSize: 12 }}
                    minTickGap={30}
                  />
                  <YAxis yAxisId="size" stroke="#64748b" tickFormatter={formatUsdTick} width={60} />
                  <YAxis
                    yAxisId="price"
                    orientation="right"
                    stroke="#f59e0b"
                    tickFormatter={formatPriceTick}
                    width={60}
                  />
                  {riskReferencePrice ? (
                    <>
                      <ReferenceLine
                        yAxisId="price"
                        y={riskReferencePrice}
                        stroke={riskDirection === 'down' ? '#fb7185' : '#c084fc'}
                        strokeDasharray="6 4"
                      />
                      {riskDirection === 'down' && (
                        <ReferenceArea
                          yAxisId="price"
                          y1={0}
                          y2={riskReferencePrice}
                          ifOverflow="extendDomain"
                          fill="#7f1d1d"
                          fillOpacity={0.08}
                        />
                      )}
                    </>
                  ) : null}
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={formatTooltipValue}
                  />
                  <Legend />
                  <Line
                    yAxisId="size"
                    type="monotone"
                    dataKey="total_debt_usd"
                    name="借出 ETH 总值"
                    stroke="#ef4444"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="size"
                    type="monotone"
                    dataKey="available_liquidity_usd"
                    name="剩余可借 ETH 总值"
                    stroke="#10b981"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="eth_price_usd"
                    name="ETH 历史价格"
                    stroke="#f59e0b"
                    dot={false}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card">
            <div
              className="card-header"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span className="card-title">抵押借贷利率、资金利用率与 ETH 价格</span>
            </div>
            <div style={{ height: 400 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis
                    dataKey="timestamp"
                    stroke="#64748b"
                    tick={{ fontSize: 12 }}
                    minTickGap={30}
                  />
                  <YAxis
                    yAxisId="utilization"
                    stroke="#3b82f6"
                    tickFormatter={(val) => `${Number(val).toFixed(0)}%`}
                    width={48}
                  />
                  <YAxis
                    yAxisId="apy"
                    orientation="right"
                    stroke="#ef4444"
                    tickFormatter={(val) => `${Number(val).toFixed(2)}%`}
                    width={56}
                  />
                  <YAxis
                    yAxisId="price"
                    hide
                    orientation="right"
                    stroke="#f59e0b"
                    tickFormatter={formatPriceTick}
                    width={60}
                  />
                  {riskReferencePrice ? (
                    <ReferenceLine
                      yAxisId="price"
                      y={riskReferencePrice}
                      stroke={riskDirection === 'down' ? '#fb7185' : '#c084fc'}
                      strokeDasharray="6 4"
                    />
                  ) : null}
                  <Tooltip
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b' }}
                    formatter={formatRateTooltipValue}
                  />
                  <Legend />
                  <Line
                    yAxisId="apy"
                    type="monotone"
                    dataKey="variable_borrow_apy"
                    name="借款实际年化利息率"
                    stroke="#ef4444"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="apy"
                    type="monotone"
                    dataKey="supply_apy"
                    name="存款年化收益率"
                    stroke="#10b981"
                    dot={false}
                    strokeWidth={2}
                  />
                  <Line
                    yAxisId="utilization"
                    type="monotone"
                    dataKey="utilization_rate"
                    name="资金利用率"
                    stroke="#3b82f6"
                    dot={false}
                    strokeWidth={2}
                    strokeDasharray="5 5"
                  />
                  <Line
                    yAxisId="price"
                    type="monotone"
                    dataKey="eth_price_usd"
                    name="ETH 历史价格"
                    stroke="#f59e0b"
                    dot={false}
                    strokeWidth={2}
                    strokeDasharray="6 4"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
