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
import { fetchCompoundPositionReplay, CompoundPositionReplayPoint } from '../api/compound';
import { ChartDataStatus, ChartInfoButton, type ExplainItem } from './ChartAssist';
import type { AggregatedRequestMeta } from '../api/requestMeta';

interface CompoundPositionReplayProps {
  address: string;
  version: 'v2' | 'v3';
  marketFilter?: string;
  marketLabel?: string;
}

interface ReplayPointExt extends CompoundPositionReplayPoint {
  operation_type: string;
  liq_price: number;
}

const replayCache = new Map<string, ReplayPointExt[]>();
const replayMetaCache = new Map<string, number>();
const REPLAY_CACHE_TTL_MS = 5 * 60 * 1000;

const explainItems: ExplainItem[] = [
  {
    term: '有效抵押总值',
    formula: 'discounted collateral usd',
    meaning: '已经乘上协议折扣/抵押参数后，真正能用来支撑借款安全垫的抵押价值。',
    riskHint: '这条线如果持续靠近债务总值，账户的缓冲会越来越薄。',
  },
  {
    term: 'ETH 清算价格',
    formula: 'eth_down_liq_price_usd 或 eth_up_liq_price_usd',
    meaning: '反映账户在 ETH 下跌或上涨场景下触发清算的关键价格阈值。',
    riskHint: '清算价越接近当前 ETH 价格，说明仓位越脆弱。',
  },
];

interface ReplayTooltipPayloadEntry {
  payload: ReplayPointExt;
}

interface ReplayTooltipProps {
  active?: boolean;
  payload?: ReplayTooltipPayloadEntry[];
  label?: string;
}

const safeParse = (val: unknown) => {
  const num = parseFloat(String(val));
  return Number.isNaN(num) ? 0 : num;
};

const CustomTooltip = ({ active, payload, label }: ReplayTooltipProps) => {
  if (active && payload && payload.length) {
    const point = payload[0].payload as ReplayPointExt;
    return (
      <div
        className="custom-tooltip"
        style={{
          backgroundColor: '#0f172a',
          borderColor: '#1e293b',
          border: '1px solid',
          padding: '10px',
          borderRadius: '4px',
          color: '#e2e8f0',
          fontSize: '0.9rem',
          lineHeight: '1.5',
        }}
      >
        <p className="label" style={{ color: '#94a3b8', margin: '0 0 5px 0' }}>
          {label}
        </p>
        <p style={{ margin: '0 0 5px 0', color: '#fff' }}>{point.brief}</p>
        <p style={{ margin: '0 0 5px 0', color: '#fbbf24' }}>交易类型: {point.operation_type}</p>
        <p style={{ margin: '0' }}>
          有效抵押总值: $
          {safeParse(point.discounted_collateral_usd).toLocaleString(undefined, {
            maximumFractionDigits: 2,
          })}
        </p>
        <p style={{ margin: '0' }}>
          债务总值: $
          {safeParse(point.total_debt_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </p>
        <p style={{ margin: '0' }}>健康因子: {safeParse(point.health_factor).toFixed(2)}</p>
        <p style={{ margin: '0' }}>
          ETH 清算价格: $
          {safeParse(point.liq_price).toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </p>
        <p style={{ margin: '0' }}>
          ETH 价格: $
          {safeParse(point.eth_price_usd).toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </p>
      </div>
    );
  }
  return null;
};

export function CompoundPositionReplayChart({
  address,
  version,
  marketFilter,
  marketLabel,
}: CompoundPositionReplayProps) {
  const [fullData, setFullData] = useState<ReplayPointExt[]>([]);
  const [data, setData] = useState<ReplayPointExt[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });

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

  useEffect(() => {
    const fetchFullHistory = async () => {
      if (!address) return;
      setLoading(true);
      setError('');
      try {
        const cacheKey = `${version}:${address.toLowerCase()}`;
        const cached = replayCache.get(cacheKey);
        const cachedAt = replayMetaCache.get(cacheKey);
        if (cached && cachedAt && Date.now() - cachedAt < REPLAY_CACHE_TTL_MS) {
          setFullData(cached);
          setData(cached);
          setMeta({
            lastUpdatedAt: cachedAt,
            cacheStatus: 'hit',
          });
          return;
        }

        const defaultStart = '2020-12-01 00:00:00';
        const now = new Date();
        const year = now.getUTCFullYear();
        const month = String(now.getUTCMonth() + 1).padStart(2, '0');
        const day = String(now.getUTCDate()).padStart(2, '0');
        const hours = String(now.getUTCHours()).padStart(2, '0');
        const minutes = String(now.getUTCMinutes()).padStart(2, '0');
        const seconds = String(now.getUTCSeconds()).padStart(2, '0');
        const defaultEnd = `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;

        const result = await fetchCompoundPositionReplay(
          address,
          defaultStart,
          defaultEnd,
          version,
        );

        if (!result.points || !Array.isArray(result.points)) {
          throw new Error('Invalid data format');
        }

        const formattedData = result.points
          .map((pt) => {
            const d = new Date(pt.timestamp);
            const pad = (n: number) => n.toString().padStart(2, '0');
            const timeStr = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;

            // Parse operation_type robustly by searching for keywords in the brief
            let operation_type = '未知';
            const originalBrief = pt.brief ? pt.brief.trim() : '';
            const typeKeywords = ['存入', '赎回', '借入', '还款', '代还', '清算'];
            for (const kw of typeKeywords) {
              if (originalBrief.startsWith(kw)) {
                operation_type = kw;
                break;
              }
            }

            // Rewrite brief: "存入... WETH @WETH" -> "在WETH市场存入...WETH"
            let formattedBrief = originalBrief;
            const atMatch = originalBrief.match(/^(.*?)\s*@\s*([^ ]+)$/);
            if (atMatch) {
              formattedBrief = `在${atMatch[2]}市场${atMatch[1]}`;
            }

            const downLiq = parseFloat(pt.eth_down_liq_price_usd || '0');
            const upLiq = parseFloat(pt.eth_up_liq_price_usd || '0');
            const liq_price = downLiq !== 0 ? downLiq : upLiq;

            return {
              ...pt,
              brief: formattedBrief,
              timestamp: timeStr,
              operation_type,
              liq_price,
            };
          })
          .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

        replayCache.set(cacheKey, formattedData);
        replayMetaCache.set(cacheKey, Date.now());
        setFullData(formattedData);
        setData(formattedData);
        setMeta({
          lastUpdatedAt: Date.now(),
          cacheStatus: 'miss',
        });
      } catch (err) {
        console.error(err);
        setError('无法加载历史回放数据');
      } finally {
        setLoading(false);
      }
    };

    fetchFullHistory();
  }, [address, version]);

  const [appliedRange, setAppliedRange] = useState({ start: '2020-12-01 00:00:00', end: endTime });

  useEffect(() => {
    if (!fullData.length) return;
    const startTs = new Date(appliedRange.start).getTime();
    const endTs = new Date(appliedRange.end).getTime();

    let filtered = fullData.filter((pt) => {
      const ptTs = new Date(pt.timestamp).getTime();
      return ptTs >= startTs && ptTs <= endTs;
    });

    if (marketFilter) {
      const normalizedMarket = marketFilter.toLowerCase();
      filtered = filtered.filter((pt) => pt.market.toLowerCase() === normalizedMarket);
    }

    if (selectedType !== 'all') {
      filtered = filtered.filter((pt) => pt.operation_type === selectedType);
    }

    setData(filtered);
  }, [appliedRange, fullData, marketFilter, selectedType]);

  const handleSearch = () => {
    setAppliedRange({ start: startTime, end: endTime });
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

  return (
    <div className="card" style={{ marginTop: '1.5rem' }}>
      <div
        className="card-header"
        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
      >
        <span className="card-title">
          {marketLabel ? `${marketLabel} 历史交易与头寸变化记录` : '历史交易与头寸变化记录'}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <ChartInfoButton title="Compound 账户回放图说明" items={explainItems} />
          <ChartDataStatus meta={meta} />
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
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: '#64748b', fontWeight: 600 }}>交易类型:</span>
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
            }}
          >
            All
          </button>
          {['存入', '赎回', '借入', '还款', '代还', '清算'].map((type) => (
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
            <LineChart data={data} margin={{ top: 10, right: 30, left: 10, bottom: 5 }}>
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

              <Tooltip content={<CustomTooltip />} />
              <Legend />

              <Line
                yAxisId="left"
                type="monotone"
                dataKey="discounted_collateral_usd"
                stroke="#10b981"
                strokeWidth={2}
                dot={false}
                name="有效抵押总值"
              />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="total_debt_usd"
                stroke="#f59e0b"
                strokeWidth={2}
                dot={false}
                name="债务总值"
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="liq_price"
                stroke="#ef4444"
                strokeWidth={2}
                strokeDasharray="5 5"
                dot={false}
                name="ETH 清算价格"
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
