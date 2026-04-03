import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { fetchAssetPricePeriodWithMeta } from '../api/price';
import {
  fetchCompoundMarketConfigPeriodV2WithMeta,
  fetchCompoundMarketConfigV2WithMeta,
  getCompoundV2BaseAssetSymbol,
} from '../api/compound';
import type { PricePeriodItem } from '../api';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';

interface PricePoint {
  time: string;
  price: number; // For v3: asset price. For v2: cToken price
  exchange_rate?: number; // Only used in v2
}

// 模块级内存缓存：key = asset + 时间段，value = { fetchedAt, points }
// 页面刷新后自动清空，无持久化坏数据风险
const _cache = new Map<string, { fetchedAt: number; points: PricePoint[] }>();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5 分钟

interface CompoundPriceTrendProps {
  asset: string;
  version?: 'v2' | 'v3';
  scenarioLabel?: string;
}

const explainItems: ExplainItem[] = [
  {
    term: '市场资产价格',
    formula: 'v3: 资产现价；v2: 底层资产价格 × exchange rate',
    meaning: 'v2 里展示的是 cToken 价格路径，v3 展示的是市场基础资产价格路径。',
    riskHint: '若价格本身波动很大，再叠加高利用率或高杠杆，清算风险会被放大。',
  },
  {
    term: 'exchange rate (v2)',
    formula: 'cToken 可兑换底层资产的比率',
    meaning: '随着利息累积，兑换率通常会缓慢上升，因此 cToken 价格不等于底层资产价格。',
    riskHint: '看 v2 图时要区分“底层价格波动”和“利息累积导致的兑换率抬升”。',
  },
];

export function CompoundPriceTrend({
  asset,
  version = 'v3',
  scenarioLabel,
}: CompoundPriceTrendProps) {
  const [timeRange, setTimeRange] = useState<'24h' | '7D' | '3M'>('24h');
  const [data, setData] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

  useEffect(() => {
    const fetchData = async () => {
      const cacheKey = `${asset}_${timeRange}_${version}`;
      // 命中内存缓存且未过期则直接使用，跳过网络请求
      const cached = _cache.get(cacheKey);
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
            interval = 60; // 1 hour in minutes
            break;
          case '3M':
            startTime.setMonth(now.getMonth() - 3);
            interval = 360; // 6 hours in minutes
            break;
        }

        const formatDate = (date: Date) => date.toISOString().slice(0, 19).replace('T', ' ');

        const startStr = formatDate(startTime);
        const endStr = formatDate(now);

        let finalData: PricePoint[] = [];

        if (version === 'v2') {
          const baseSymbol = getCompoundV2BaseAssetSymbol(asset);
          const baselineConfigDate = startStr.slice(0, 10) + ' 00:00:00';
          const [priceItems, configRes, baselineConfig] = await Promise.all([
            fetchAssetPricePeriodWithMeta(baseSymbol, startStr, endStr, interval),
            fetchCompoundMarketConfigPeriodV2WithMeta(
              asset,
              baselineConfigDate,
              endStr.slice(0, 10) + ' 00:00:00',
            ),
            fetchCompoundMarketConfigV2WithMeta(asset, baselineConfigDate),
          ]);
          setMeta(mergeRequestMetas([priceItems.meta, configRes.meta, baselineConfig.meta]));

          // Create a map of timestamp -> exchange_rate
          const rateMap = new Map<string, number>();
          if (configRes.data && Array.isArray(configRes.data.points)) {
            configRes.data.points.forEach((pt: any) => {
              if (pt.market_config && pt.market_config.exchange_rate) {
                // Keep only the date part YYYY-MM-DD to match closest price point
                const dateKey = pt.market_config.effective_timestamp.split('T')[0];
                rateMap.set(dateKey, parseFloat(pt.market_config.exchange_rate));
              }
            });
          }

          let lastKnownRate = parseFloat(baselineConfig.data?.market_config?.exchange_rate || '1');

          finalData = priceItems.data.map((item: PricePeriodItem) => {
            const dateKey = item.timestamp.split('T')[0];
            const rate = rateMap.get(dateKey) || lastKnownRate;
            if (rateMap.has(dateKey)) {
              lastKnownRate = rate;
            }

            return {
              time: new Date(item.timestamp).toLocaleString(undefined, {
                month: 'numeric',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
              }),
              price: parseFloat(item.price_usd) * rate,
              exchange_rate: rate,
            };
          });
        } else {
          const result = await fetchAssetPricePeriodWithMeta(asset, startStr, endStr, interval);
          setMeta(mergeRequestMetas([result.meta]));
          finalData = result.data.map((item: PricePeriodItem) => ({
            time: new Date(item.timestamp).toLocaleString(undefined, {
              month: 'numeric',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            }),
            price: parseFloat(item.price_usd),
          }));
        }

        setData(finalData);
        // 写入内存缓存（仅当有数据时）
        if (finalData.length > 0) {
          _cache.set(cacheKey, { fetchedAt: Date.now(), points: finalData });
        }
      } catch (err) {
        console.error(`Fetch ${asset} price trend error:`, err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [timeRange, asset, version]);

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
          <ChartInfoButton title="Compound 价格趋势说明" items={explainItems} />
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
                yAxisId="left"
                stroke="#64748b"
                domain={['auto', 'auto']}
                tickFormatter={(val) => `$${val}`}
                width={65}
              />
              {version === 'v2' && (
                <YAxis
                  yAxisId="right"
                  orientation="right"
                  stroke="#10b981"
                  domain={['auto', 'auto']}
                  tickFormatter={(val) => val.toFixed(4)}
                  width={60}
                />
              )}
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  borderColor: '#1e293b',
                  color: '#e2e8f0',
                }}
                itemStyle={{ color: '#3b82f6' }}
                formatter={(value: any, name: any) => {
                  if (name === 'price') {
                    const label = version === 'v2' ? `${asset} 价格` : '价格';
                    return [
                      `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                      label,
                    ];
                  }
                  if (name === 'exchange_rate') {
                    return [
                      Number(value).toLocaleString(undefined, {
                        minimumFractionDigits: 4,
                        maximumFractionDigits: 6,
                      }),
                      `${asset} 兑换率`,
                    ];
                  }
                  return [value, name] as any;
                }}
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="price"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
              />
              {version === 'v2' && (
                <Line
                  yAxisId="right"
                  type="monotone"
                  dataKey="exchange_rate"
                  stroke="#10b981"
                  strokeWidth={2}
                  dot={false}
                  strokeDasharray="5 5"
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </>
  );
}
