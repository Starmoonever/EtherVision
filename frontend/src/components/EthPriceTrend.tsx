import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer
} from 'recharts';

interface PricePoint {
  time: string;
  price: number;
}

interface PriceApiItem {
  timestamp: string;
  price_usd: string;
}

export function EthPriceTrend() {
  const [timeRange, setTimeRange] = useState<'24h' | '7D' | '3M'>('24h');
  const [data, setData] = useState<PricePoint[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      // 1. Try to load from localStorage first
      const cacheKey = `eth_price_trend_${timeRange}`;
      const cachedData = localStorage.getItem(cacheKey);

      if (cachedData) {
        try {
          const { timestamp, points } = JSON.parse(cachedData);
          // Check if cache is valid (e.g., less than 5 minutes old)
          const now = Date.now();
          if (now - timestamp < 5 * 60 * 1000) {
            setData(points);
            return;
          }
        } catch (e) {
          console.warn('Invalid cache data', e);
          localStorage.removeItem(cacheKey);
        }
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

        // Format dates as YYYY-MM-DD HH:MM:SS (UTC)
        // Adjusting to API requirement if needed, assuming API handles standard ISO or specific format
        // Based on user prompt: "2024-01-01"

        const formatDate = (date: Date) => {
             return date.toISOString().slice(0, 19).replace('T', ' ');
        };

        const startStr = formatDate(startTime);
        const endStr = formatDate(now);

        const baseUrl = import.meta.env.VITE_API_BASE_URL;
        const response = await fetch(`${baseUrl}/price/period?asset=eth&start=${encodeURIComponent(startStr)}&end=${encodeURIComponent(endStr)}&interval=${interval}`);

        if (!response.ok) throw new Error('Failed to fetch price trend');

        const result = await response.json();

        if (!result.prices || !Array.isArray(result.prices)) {
          throw new Error('Invalid data format');
        }

        const formattedData = result.prices.map((item: PriceApiItem) => ({
          time: new Date(item.timestamp).toLocaleString(undefined, {
              month: 'numeric',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit'
          }),
          price: parseFloat(item.price_usd)
        }));

        setData(formattedData);

        // 2. Save to localStorage
        localStorage.setItem(cacheKey, JSON.stringify({
          timestamp: Date.now(),
          points: formattedData
        }));
      } catch (err) {
        console.error('Fetch price trend error:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [timeRange]);

  return (
    <div className="card" style={{ gridColumn: 'span 2', marginTop: '1.5rem' }}>
      <div className="card-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="card-title">历史趋势</span>
        <div style={{ display: 'flex', gap: '0.5rem', background: '#1e293b', padding: '0.2rem', borderRadius: '0.5rem' }}>
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
                transition: 'all 0.2s'
              }}
            >
              {range}
            </button>
          ))}
        </div>
      </div>

      <div style={{ height: 300, marginTop: '1rem' }}>
        {loading ? (
           <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
             <div className="spinner"></div>
           </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="time"
                stroke="#64748b"
                tick={{ fontSize: 12 }}
                minTickGap={30}
              />
              <YAxis
                stroke="#64748b"
                domain={['auto', 'auto']}
                tickFormatter={(val) => `$${val}`}
                width={60}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#e2e8f0' }}
                itemStyle={{ color: '#3b82f6' }}
                formatter={(value: number | string | undefined) => [`$${Number(value).toLocaleString(undefined, {minimumFractionDigits: 2})}`, 'Price']}
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
    </div>
  );
}
