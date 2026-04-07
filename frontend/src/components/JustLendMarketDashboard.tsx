import { useEffect, useState } from 'react';
import {
  fetchJustLendMarketsWithMeta,
  fetchJustLendStatusWithMeta,
  type JustLendMarketsResponse,
  type JustLendStatusResponse,
} from '../api/justlend';
import { mergeRequestMetas, type AggregatedRequestMeta } from '../api/requestMeta';
import { ChartDataStatus } from './ChartAssist';

interface PlannedChartCard {
  title: string;
  summary: string;
  requiredFields: string;
}

const plannedCharts: PlannedChartCard[] = [
  {
    title: '市场规模排行图',
    summary: '展示各市场的总供应和总借款规模，识别资金最集中的资产。',
    requiredFields: 'total_supply_usd, total_borrow_usd',
  },
  {
    title: '利用率 / 流动性对比图',
    summary: '展示各市场利用率、剩余现金和储备，判断流动性拥挤程度。',
    requiredFields: 'utilization, cash, reserves',
  },
  {
    title: '市场历史趋势图',
    summary: '展示单市场在时间轴上的供应、借款和利用率变化。',
    requiredFields: 'timestamp, supply_usd, borrow_usd, utilization',
  },
  {
    title: '风险分布图',
    summary: '展示协议内账户健康因子或清算阈值分布，识别脆弱区间。',
    requiredFields: 'health_factor_distribution or liquidation_threshold_distribution',
  },
  {
    title: '清算敏感性图',
    summary: '展示价格冲击下潜在风险账户规模和债务暴露变化。',
    requiredFields: 'price_shock, at_risk_accounts, at_risk_debt_usd',
  },
];

const readyModules = [
  '个人地址查询与历史搜索记录',
  'JustLend 当前仓位接口 `/api/justlend/position`',
  '协议状态接口 `/api/justlend/status`',
  '市场列表保留接口 `/api/justlend/markets`',
];

export function JustLendMarketDashboard() {
  const [status, setStatus] = useState<JustLendStatusResponse | null>(null);
  const [markets, setMarkets] = useState<JustLendMarketsResponse | null>(null);
  const [meta, setMeta] = useState<AggregatedRequestMeta>({
    lastUpdatedAt: null,
    cacheStatus: 'none',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError('');

      try {
        const [statusResult, marketsResult] = await Promise.all([
          fetchJustLendStatusWithMeta(),
          fetchJustLendMarketsWithMeta(),
        ]);

        if (cancelled) return;
        setStatus(statusResult.data);
        setMarkets(marketsResult.data);
        setMeta(mergeRequestMetas([statusResult.meta, marketsResult.meta]));
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : '无法加载 JustLend 市场状态');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div
        className="card"
        style={{ minHeight: 360, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      >
        <div className="spinner"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <span className="card-title">JustLend 市场框架</span>
          <span className="badge" style={{ background: '#3f0d0d', color: '#fca5a5' }}>
            Error
          </span>
        </div>
        <div className="justlend-banner justlend-banner-warn">
          <div className="justlend-banner-title">无法读取 JustLend 市场状态</div>
          <div className="justlend-banner-copy">{error}</div>
        </div>
      </div>
    );
  }

  return (
    <div className="justlend-market-board">
      <div className="card justlend-market-hero" style={{ marginBottom: 0 }}>
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
            <span className="card-title">JustLend 宏观市场框架</span>
            <span className="badge green-badge">{status?.chain?.toUpperCase() ?? 'TRON'}</span>
            <span className="badge" style={{ background: '#172554', color: '#bfdbfe' }}>
              {status?.status ?? 'scaffold'}
            </span>
          </div>
          <ChartDataStatus meta={meta} />
        </div>

        <div className="justlend-market-hero-grid">
          <div>
            <div className="justlend-market-kicker">当前阶段</div>
            <h2 className="justlend-market-title">市场页已占位，等待市场级数据接入</h2>
            <p className="justlend-market-copy">
              当前页面明确区分“已经可用的接口能力”和“尚未具备的数据能力”。这样前端入口先稳定下来，
              后续后端补齐市场数据后，可以直接把图表位接上，不需要再返工页面结构。
            </p>
          </div>

          <div className="justlend-market-summary-grid">
            <div className="metric-box">
              <span className="metric-label">模块</span>
              <span className="metric-value blue">{status?.module ?? 'justlend'}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">支持协议</span>
              <span className="metric-value">
                {status?.supported_protocols.length ? status.supported_protocols.join(', ') : '--'}
              </span>
            </div>
            <div className="metric-box">
              <span className="metric-label">市场列表数量</span>
              <span className="metric-value">{markets?.markets.length ?? 0}</span>
            </div>
          </div>
        </div>

        <div className="justlend-banner justlend-banner-soft">
          <div className="justlend-banner-title">后端当前返回的真实状态</div>
          <div className="justlend-banner-copy">
            {status?.message ??
              'JustLend 市场页目前只具备框架能力，尚无可直接用于图表的市场级时序与聚合数据。'}
          </div>
        </div>
      </div>

      <div className="justlend-market-grid">
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">已就绪能力</span>
            <span className="badge green-badge">Ready</span>
          </div>
          <div className="justlend-market-list">
            {readyModules.map((item) => (
              <div key={item} className="justlend-market-list-item">
                <span className="check-dot dot-ok" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="card" style={{ marginBottom: 0 }}>
          <div className="card-header">
            <span className="card-title">市场数据现状</span>
            <span className="badge" style={{ background: '#3f3f1a', color: '#fde68a' }}>
              Pending
            </span>
          </div>
          <div className="justlend-market-list">
            <div className="justlend-market-list-item">
              <span className="check-dot dot-fail" />
              <span>市场列表接口已存在，但当前返回空数组</span>
            </div>
            <div className="justlend-market-list-item">
              <span className="check-dot dot-fail" />
              <span>暂无单市场时间序列，无法展示历史趋势</span>
            </div>
            <div className="justlend-market-list-item">
              <span className="check-dot dot-fail" />
              <span>暂无协议级风险分布聚合，无法展示风险分层</span>
            </div>
            <div className="justlend-market-list-item">
              <span className="check-dot dot-fail" />
              <span>暂无价格冲击模拟结果，无法展示清算敏感性</span>
            </div>
          </div>
        </div>
      </div>

      <div className="justlend-market-placeholder-grid">
        {plannedCharts.map((item) => (
          <div
            key={item.title}
            className="card justlend-placeholder-card"
            style={{ marginBottom: 0 }}
          >
            <div className="card-header">
              <span className="card-title">{item.title}</span>
              <span className="badge" style={{ background: '#1f2937', color: '#cbd5e1' }}>
                Placeholder
              </span>
            </div>
            <p className="justlend-market-copy" style={{ marginTop: 0 }}>
              {item.summary}
            </p>
            <div className="justlend-placeholder-shell">
              <div className="justlend-placeholder-icon">No Data Yet</div>
            </div>
            <div className="justlend-caption">
              需要后端字段：<span className="mono">{item.requiredFields}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
