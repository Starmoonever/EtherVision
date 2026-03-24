import { lazy, Suspense, useEffect, useState } from 'react';
import { AddressInput } from './components/AddressInput';
import { CompoundPersonalRiskDashboard } from './components/CompoundPersonalRiskDashboard';
import { PositionTable } from './components/PositionTable';
import { SummaryCard } from './components/SummaryCard';
import { fetchUserPosition } from './api';
import type { BorrowPosition, UserPosition } from './api';
import { fetchCompoundMarkets, fetchCompoundUserPosition } from './api/compound';
import type { CompoundMarket, CompoundUserPositionItem } from './api/compound';
import './App.css';

const MarketAssessment = lazy(() =>
  import('./components/MarketAssessment').then((module) => ({
    default: module.MarketAssessment,
  })),
);
const CompoundMarketAssessment = lazy(() =>
  import('./components/CompoundMarketAssessment').then((module) => ({
    default: module.CompoundMarketAssessment,
  })),
);
const PositionReplayChart = lazy(() =>
  import('./components/PositionReplayChart').then((module) => ({
    default: module.PositionReplayChart,
  })),
);

interface VersionState {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
}

interface CompoundVersionState {
  data: CompoundUserPositionItem | null;
  loading: boolean;
  notFound: boolean;
}

type AaveCacheEntry = { kind: 'data'; data: UserPosition | BorrowPosition } | { kind: 'not_found' };
type CompoundCacheEntry = { kind: 'data'; data: CompoundUserPositionItem } | { kind: 'not_found' };

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });
const emptyCompoundState = (): CompoundVersionState => ({
  data: null,
  loading: false,
  notFound: false,
});
const aavePositionCache = new Map<string, AaveCacheEntry>();
const compoundPositionCache = new Map<string, CompoundCacheEntry>();
const compoundCacheKey = (address: string, market: string) =>
  `v3:${address.toLowerCase()}:${market.toLowerCase()}`;

const resultPanelStyle = {
  border: '1px solid #334155',
  borderRadius: '14px',
  padding: '1.25rem',
  background: '#0d1117',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: '1rem',
};

function ChartFallback({ minHeight = '240px' }: { minHeight?: string }) {
  return (
    <div
      className="card"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight,
      }}
    >
      <div className="spinner"></div>
    </div>
  );
}

export default function App() {
  const [protocol, setProtocol] = useState<'aave' | 'compound'>('aave');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [error, setError] = useState('');

  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3'>('v3');
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3');

  const [queriedAddress, setQueriedAddress] = useState('');
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  const [compoundMarkets, setCompoundMarkets] = useState<CompoundMarket[]>([]);
  const [compoundMarket, setCompoundMarket] = useState<string>('all');
  const [compoundAddress, setCompoundAddress] = useState('');
  const [compoundState, setCompoundState] = useState<CompoundVersionState>(emptyCompoundState());

  const selectedCompoundMarketSymbol =
    compoundMarket === 'all'
      ? 'all'
      : (compoundMarkets.find((item) => item.address === compoundMarket)?.symbol ?? compoundMarket);

  const handleSearch = (address: string) => {
    setError('');

    if (protocol === 'aave') {
      setQueriedAddress(address);
    } else {
      setCompoundAddress(address);
    }
  };

  useEffect(() => {
    setV2State(emptyState());
    setV3State(emptyState());
  }, [queriedAddress]);

  useEffect(() => {
    setCompoundState(emptyCompoundState());
  }, [compoundAddress, compoundMarket]);

  useEffect(() => {
    const loadCompoundMarkets = async () => {
      try {
        const markets = await fetchCompoundMarkets('v3');
        setCompoundMarkets(markets);
      } catch (loadError) {
        console.error(loadError);
        setError('无法加载 Compound 市场列表');
      }
    };

    loadCompoundMarkets();
  }, []);

  useEffect(() => {
    if (!queriedAddress || protocol !== 'aave' || activeTab !== 'personal') return;

    const load = async (version: 'v2' | 'v3', setState: typeof setV2State) => {
      const cacheKey = `${version}:${queriedAddress.toLowerCase()}`;
      const cached = aavePositionCache.get(cacheKey);
      if (cached) {
        if (cached.kind === 'not_found') {
          setState({ data: null, loading: false, notFound: true });
          return;
        }
        setState({ data: cached.data, loading: false, notFound: false });
        return;
      }

      setState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        const data = await fetchUserPosition(queriedAddress, version);
        aavePositionCache.set(cacheKey, { kind: 'data', data });
        setState({ data, loading: false, notFound: false });
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          aavePositionCache.set(cacheKey, { kind: 'not_found' });
          setState({ data: null, loading: false, notFound: true });
        } else {
          setState({ data: null, loading: false, notFound: false });
          console.error(loadError);
        }
      }
    };

    setError('');
    if (personalVersion === 'v2') {
      load('v2', setV2State);
    } else {
      load('v3', setV3State);
    }
  }, [activeTab, personalVersion, protocol, queriedAddress]);

  useEffect(() => {
    if (!compoundAddress || protocol !== 'compound' || activeTab !== 'personal') return;

    const loadCompound = async () => {
      if (personalVersion === 'v2') {
        setError('抱歉，暂无 Compound v2 数据');
        setCompoundState({ data: null, loading: false, notFound: false });
        return;
      }
      setError('');

      const cacheKey = compoundCacheKey(compoundAddress, compoundMarket);
      const cached = compoundPositionCache.get(cacheKey);
      if (cached) {
        if (cached.kind === 'not_found') {
          setCompoundState({ data: null, loading: false, notFound: true });
          return;
        }
        setCompoundState({ data: cached.data, loading: false, notFound: false });
        return;
      }

      setCompoundState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        setError('');
        const response = await fetchCompoundUserPosition('v3', compoundMarket, compoundAddress);
        if (response.positions && response.positions.length > 0) {
          const position = response.positions[0];

          if (compoundMarket === 'all') {
            const foundMarkets = new Set<string>();
            for (const item of response.positions) {
              compoundPositionCache.set(compoundCacheKey(compoundAddress, item.market), {
                kind: 'data',
                data: item,
              });
              foundMarkets.add(item.market.toLowerCase());
            }
            for (const item of compoundMarkets) {
              if (!foundMarkets.has(item.address.toLowerCase())) {
                compoundPositionCache.set(compoundCacheKey(compoundAddress, item.address), {
                  kind: 'not_found',
                });
              }
            }
          }

          compoundPositionCache.set(cacheKey, { kind: 'data', data: position });
          setCompoundState({ data: position, loading: false, notFound: false });
        } else {
          compoundPositionCache.set(cacheKey, { kind: 'not_found' });
          setCompoundState({ data: null, loading: false, notFound: true });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          compoundPositionCache.set(cacheKey, { kind: 'not_found' });
          setCompoundState({ data: null, loading: false, notFound: true });
        } else {
          setCompoundState({ data: null, loading: false, notFound: false });
          console.error(loadError);
        }
      }
    };

    loadCompound();
  }, [activeTab, compoundAddress, compoundMarket, compoundMarkets, personalVersion, protocol]);

  const renderProtocolSwitch = () => (
    <div className="switch-group">
      <button
        onClick={() => setProtocol('aave')}
        className={`switch-btn ${protocol === 'aave' ? 'active' : ''}`}
        type="button"
      >
        Aave
      </button>
      <button
        onClick={() => setProtocol('compound')}
        className={`switch-btn ${protocol === 'compound' ? 'active' : ''}`}
        type="button"
      >
        Compound
      </button>
    </div>
  );

  const renderPageTabs = () => (
    <div className="switch-group">
      <button
        onClick={() => setActiveTab('personal')}
        className={`switch-btn switch-btn-wide ${activeTab === 'personal' ? 'active active-purple' : ''}`}
        type="button"
      >
        个人账户分析
      </button>
      <button
        onClick={() => setActiveTab('market')}
        className={`switch-btn switch-btn-wide ${activeTab === 'market' ? 'active active-purple' : ''}`}
        type="button"
      >
        宏观市场评估
      </button>
    </div>
  );

  const renderPersonalVersionSwitch = () => (
    <div className="hero-switch">
      <div className="switch-group">
        <button
          onClick={() => setPersonalVersion('v2')}
          className={`switch-btn ${personalVersion === 'v2' ? 'active active-purple' : ''}`}
          type="button"
        >
          V2
        </button>
        <button
          onClick={() => setPersonalVersion('v3')}
          className={`switch-btn ${personalVersion === 'v3' ? 'active active-purple' : ''}`}
          type="button"
        >
          V3
        </button>
      </div>
    </div>
  );

  const renderMarketVersionSwitch = () => (
    <div className="hero-switch">
      <div className="switch-group">
        <button
          onClick={() => setMarketVersion('v2')}
          className={`switch-btn ${marketVersion === 'v2' ? 'active active-purple' : ''}`}
          type="button"
        >
          V2
        </button>
        <button
          onClick={() => setMarketVersion('v3')}
          className={`switch-btn ${marketVersion === 'v3' ? 'active active-purple' : ''}`}
          type="button"
        >
          V3
        </button>
      </div>
    </div>
  );

  const renderCompoundAssetSwitch = () => (
    <div className="hero-switch">
      <div className="switch-group">
        {compoundMarkets.map((item) => (
          <button
            key={item.address}
            onClick={() => setCompoundMarket(item.address)}
            className={`switch-btn ${compoundMarket === item.address ? 'active' : ''}`}
            type="button"
          >
            {item.symbol}
          </button>
        ))}
        <button
          onClick={() => setCompoundMarket('all')}
          className={`switch-btn ${compoundMarket === 'all' ? 'active' : ''}`}
          type="button"
        >
          ALL
        </button>
      </div>
    </div>
  );

  const renderCompoundMarketSwitch = () => (
    <div className="hero-switch">
      <div className="switch-group">
        {compoundMarkets.map((item) => (
          <button
            key={item.address}
            onClick={() => setCompoundMarket(item.address)}
            className={`switch-btn ${compoundMarket === item.address ? 'active' : ''}`}
            type="button"
          >
            {item.symbol}
          </button>
        ))}
      </div>
    </div>
  );

  const renderError = () =>
    error ? (
      <div className="error-block">
        <span className="error-icon">⚠️</span>
        <p>{error}</p>
      </div>
    ) : null;

  const renderAavePersonal = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Aave 个人账户分析</h1>
        <p className="hero-sub">账户头寸与清算预测</p>
        {renderPersonalVersionSwitch()}
      </div>

      <AddressInput
        onSearch={handleSearch}
        loading={false}
        historyKey="search_history_aave"
        placeholder="输入 Aave 钱包地址 (0x...)"
      />
      {renderError()}

      {queriedAddress && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          {personalVersion === 'v2' ? (
            <div style={resultPanelStyle}>
              <SummaryCard address={queriedAddress} version="v2" {...v2State} />
              <PositionTable version="v2" {...v2State} />
            </div>
          ) : (
            <div style={resultPanelStyle}>
              <SummaryCard address={queriedAddress} version="v3" {...v3State} />
              <PositionTable version="v3" {...v3State} />
            </div>
          )}

          <div style={{ marginTop: '2rem' }}>
            <Suspense fallback={<ChartFallback minHeight="320px" />}>
              <PositionReplayChart address={queriedAddress} version={personalVersion} />
            </Suspense>
          </div>
        </div>
      )}
    </>
  );

  const renderCompoundPersonal = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Compound 个人账户分析</h1>
        <p className="hero-sub">账户头寸与清算预测</p>
        {renderPersonalVersionSwitch()}
        {renderCompoundAssetSwitch()}
      </div>

      <AddressInput
        onSearch={handleSearch}
        loading={false}
        historyKey="search_history_compound"
        placeholder="输入 Compound 钱包地址 (0x...)"
      />
      {renderError()}

      {compoundAddress && personalVersion === 'v3' && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          <div style={resultPanelStyle}>
            <CompoundPersonalRiskDashboard
              address={compoundAddress}
              version="v3"
              market={selectedCompoundMarketSymbol}
              {...compoundState}
            />
          </div>
        </div>
      )}
    </>
  );

  const renderAaveMarket = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Aave 宏观市场评估</h1>
        <p className="hero-sub">ETH 实时价格与清算模拟</p>
        {renderMarketVersionSwitch()}
      </div>
      <Suspense fallback={<ChartFallback minHeight="420px" />}>
        <MarketAssessment marketVersion={marketVersion} />
      </Suspense>
    </>
  );

  const renderCompoundMarket = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Compound 宏观借贷市场评估</h1>
        <p className="hero-sub">Compound 借贷市场状态分析</p>
        {renderMarketVersionSwitch()}
        {renderCompoundMarketSwitch()}
      </div>
      <Suspense fallback={<ChartFallback minHeight="420px" />}>
        <CompoundMarketAssessment
          marketVersion={marketVersion}
          markets={compoundMarkets}
          selectedMarket={compoundMarket}
          onMarketChange={setCompoundMarket}
        />
      </Suspense>
    </>
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <div className="logo">
              <span className="logo-icon">⚡</span>
              <span className="logo-text"> ETH 市场清算风险监测</span>
            </div>
          </div>

          <div className="header-nav">{renderPageTabs()}</div>
          <div className="header-protocol">{renderProtocolSwitch()}</div>
        </div>
      </header>

      <main className="app-main">
        {activeTab === 'personal'
          ? protocol === 'aave'
            ? renderAavePersonal()
            : renderCompoundPersonal()
          : protocol === 'aave'
            ? renderAaveMarket()
            : renderCompoundMarket()}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet</footer>
    </div>
  );
}
