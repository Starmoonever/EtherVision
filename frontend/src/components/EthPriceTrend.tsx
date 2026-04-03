import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceArea,
  ReferenceLine,
} from 'recharts';
import { fetchEthPricePeriodWithMeta } from '../api/price';
import type { PricePeriodItem } from '../api';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';

interface PricePoint {
  time: string;
  price: number;
}

type ChartTooltipValue = string | number | ReadonlyArray<string | number>;

// 模块级内存缓存：key = 时间段，value = { fetchedAt, points }
// 页面刷新后自动清空，无持久化坏数据风险
const _cache = new Map<string, { fetchedAt: number; points: PricePoint[] }>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 分钟

const explainItems: ExplainItem[] = [
  {
    term: 'ETH 历史价格',
    formula: 'price = oracle / market feed',
    meaning: '展示 ETH 在不同时间点的美元价格，是所有清算风险分析的基础锚点。',
    riskHint: '当价格快速接近清算模拟选中的阈值时，协议中的 ETH 敏感仓位会明显增多。',
  },
  {
    term: '联动风险区间',
    formula: '下跌风险: ETH <= 模拟阈值；上涨风险: ETH >= 模拟阈值',
    meaning: '这是和清算模拟图共用的风险情景，帮助把“假设价格”映射到真实历史走势中。',
    riskHint: '如果历史价格经常进入这个区间，说明该风险情景不是极端尾部，而是曾真实发生过。',
  },
];

interface EthPriceTrendProps {
  riskReferencePrice?: number;
  riskDirection?: 'up' | 'down';
  scenarioLabel?: string;
}

export function EthPriceTrend({
  riskReferencePrice,
  riskDirection = 'down',
  scenarioLabel,
}: EthPriceTrendProps) {
  const [timeRange, setTimeRange] = useState<'24h' | '7D' | '3M'>('24h');
  const [data, setData] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    const fetchData = async () => {
      // 命中内存缓存且未过期则直接使用，跳过网络请求
      const cached = _cache.get(timeRange);
      if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
        setData(cached.points);
        setMeta({
          lastUpdatedAt: cached.fetchedAt,
          cacheStatus: 'hit',
        });
        return;
      }

      setLoading(true);
      try {
        const now = new Date();
        const startTime = new Date();
        let interval = 15; // default 15 minutes for 24h

        switch (timeRange) {
          case '24h':
            startTime.setDate(now.getDate() - 1);
            interval = 15;
            break;
          case '7D':
            startTime.setDate(now.getDate() - 7);
            interval = 180; // 3 hours in minutes
            break;
          case '3M':
            startTime.setMonth(now.getMonth() - 3);
            interval = 1440; // 1 day in minutes
            break;
        }

        const formatDate = (date: Date) => date.toISOString().slice(0, 19).replace('T', ' ');

        const startStr = formatDate(startTime);
        const endStr = formatDate(now);

        const result = await fetchEthPricePeriodWithMeta(startStr, endStr, interval);
        const items = result.data;

        const formattedData = items.map((item: PricePeriodItem) => ({
          time: new Date(item.timestamp).toLocaleString(undefined, {
            month: 'numeric',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          }),
          price: parseFloat(item.price_usd),
        }));

        setData(formattedData);
        // 写入内存缓存（仅当有数据时）
        if (formattedData.length > 0) {
          _cache.set(timeRange, { fetchedAt: Date.now(), points: formattedData });
        }
        setMeta(mergeRequestMetas([result.meta]));
      } catch (err) {
        console.error('Fetch price trend error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [timeRange]);

  return (
    <>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span className="card-title">历史趋势</span>
          <ChartInfoButton title="ETH 历史趋势说明" items={explainItems} />
        </div>
        <ChartDataStatus meta={meta} scenarioLabel={scenarioLabel} />
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '0.75rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            gap: '0.5rem',
            background: '#1e293b',
            padding: '0.2rem',
            borderRadius: '0.5rem',
          }}
        >
          {(['24h', '7D', '3M'] as const).map((range) => (
            <button
              key={range}
              onClick={() => setTimeRange(range)}
              style={{
                background: timeRange === range ? '#3b82f6' : 'transparent',
                color: timeRange === range ? '#ffffff' : '#94a3b8',
                border: 'none',
                padding: '0.25rem 0.85rem',
                borderRadius: '0.3rem',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: 500,
                transition: 'all 0.2s',
              }}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      <div style={{ minWidth: 0 }}>
        {loading ? (
          <div
            style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <div className="spinner"></div>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 11 }} minTickGap={40} />
              <YAxis
                stroke="#64748b"
                domain={['auto', 'auto']}
                tickFormatter={(val) => `$${val}`}
                width={65}
              />
              {riskReferencePrice ? (
                <>
                  <ReferenceLine
                    y={riskReferencePrice}
                    stroke={riskDirection === 'down' ? '#fb7185' : '#c084fc'}
                    strokeDasharray="6 4"
                    label={{
                      value: `风险阈值 $${riskReferencePrice.toFixed(0)}`,
                      position: 'insideTopRight',
                      fill: riskDirection === 'down' ? '#fb7185' : '#c084fc',
                      fontSize: 11,
                    }}
                  />
                  <ReferenceArea
                    y1={0}
                    y2={riskReferencePrice}
                    ifOverflow="extendDomain"
                    fill="#7f1d1d"
                    fillOpacity={0.08}
                  />
                </>
              ) : riskReferencePrice ? (
                <ReferenceLine
                  y={riskReferencePrice}
                  stroke="#c084fc"
                  strokeDasharray="6 4"
                  label={{
                    value: `风险阈值 $${riskReferencePrice.toFixed(0)}`,
                    position: 'insideTopRight',
                    fill: '#c084fc',
                    fontSize: 11,
                  }}
                />
              ) : null}
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#1e293b',
                  color: '#e2e8f0',
                }}
                itemStyle={{ color: '#3b82f6' }}
                formatter={(value: ChartTooltipValue | undefined) => {
                  const numericValue = Number(Array.isArray(value) ? value[0] : (value ?? 0));
                  return [
                    `$${numericValue.toLocaleString(undefined, { minimumFractionDigits: 2 })}`,
                    'Price',
                  ];
                }}
              />
              <Line
                type="monotone"
                dataKey="price"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </>
  );
}
