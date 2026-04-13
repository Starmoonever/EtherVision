import { lazy, Suspense, useEffect, useState } from 'react';
import { AddressInput } from './components/AddressInput';
import { CompoundPersonalRiskDashboard } from './components/CompoundPersonalRiskDashboard';
import { JustLendMarketDashboard } from './components/JustLendMarketDashboard';
import { JustLendPersonalDashboard } from './components/JustLendPersonalDashboard';
import { MorphoPersonalDashboard } from './components/MorphoPersonalDashboard';
import { PositionTable } from './components/PositionTable';
import { SummaryCard } from './components/SummaryCard';
import { fetchUserPosition } from './api';
import type { BorrowPosition, UserPosition } from './api';
import { fetchCompoundMarkets, fetchCompoundUserPosition } from './api/compound';
import type { CompoundMarket, CompoundUserPositionItem } from './api/compound';
import { fetchMorphoPosition } from './api/morpho';
import type { MorphoPositionResponse } from './api/morpho';
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
  data: CompoundUserPositionItem[] | null;
  loading: boolean;
  notFound: boolean;
}

interface MorphoState {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

type AaveCacheEntry = { kind: 'data'; data: UserPosition | BorrowPosition } | { kind: 'not_found' };
type CompoundCacheEntry =
  | { kind: 'data'; data: CompoundUserPositionItem[] }
  | { kind: 'not_found' };
type MorphoCacheEntry = { kind: 'data'; data: MorphoPositionResponse } | { kind: 'not_found' };

const COMPOUND_V2_PERSONAL_MARKETS = new Set(['ceth', 'cwbtc', 'cusdt', 'cdai']);

function getVisibleCompoundMarkets(
  activeTab: 'personal' | 'market',
  version: 'v2' | 'v3',
  marketsVersion: 'v2' | 'v3' | null,
  markets: CompoundMarket[],
): CompoundMarket[] {
  if (marketsVersion !== version) return [];
  if (activeTab === 'personal' && version === 'v2') {
    return markets.filter((item) => COMPOUND_V2_PERSONAL_MARKETS.has(item.symbol.toLowerCase()));
  }
  return markets;
}

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });
const emptyCompoundState = (): CompoundVersionState => ({
  data: null,
  loading: false,
  notFound: false,
});
const emptyMorphoState = (): MorphoState => ({
  data: null,
  loading: false,
  notFound: false,
});
const aavePositionCache = new Map<string, AaveCacheEntry>();
const compoundPositionCache = new Map<string, CompoundCacheEntry>();
const morphoPositionCache = new Map<string, MorphoCacheEntry>();
const compoundCacheKey = (address: string, market: string, version: string) =>
  `${version}:${address.toLowerCase()}:${market.toLowerCase()}`;
const morphoCacheKey = (address: string, marketId: string, protocol: string) =>
  `${protocol}:${marketId.toLowerCase()}:${address.toLowerCase()}`;

// Morpho 的 market id 是 bytes32 hex，个人页搜索前先在前端做基础校验。
function isBytes32Hex(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

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
  const [protocol, setProtocol] = useState<'aave' | 'compound' | 'justlend' | 'morpho'>('aave');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [error, setError] = useState('');

  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3'>('v3');
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3');

  const [queriedAddress, setQueriedAddress] = useState('');
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  const [compoundMarkets, setCompoundMarkets] = useState<CompoundMarket[]>([]);
  const [compoundMarketsVersion, setCompoundMarketsVersion] = useState<'v2' | 'v3' | null>(null);
  const [compoundMarket, setCompoundMarket] = useState<string>('all');
  const [compoundAddress, setCompoundAddress] = useState('');
  const [compoundState, setCompoundState] = useState<CompoundVersionState>(emptyCompoundState());
  const [justLendAddress, setJustLendAddress] = useState('');
  const [morphoAddress, setMorphoAddress] = useState('');
  const [morphoMarketInput, setMorphoMarketInput] = useState('');
  const [morphoQueriedMarketId, setMorphoQueriedMarketId] = useState('');
  const [morphoState, setMorphoState] = useState<MorphoState>(emptyMorphoState());
  const activeCompoundMarketsVersion = activeTab === 'personal' ? personalVersion : marketVersion;
  const visibleCompoundMarkets = getVisibleCompoundMarkets(
    activeTab,
    activeCompoundMarketsVersion,
    compoundMarketsVersion,
    compoundMarkets,
  );

  const selectedCompoundMarketSymbol =
    compoundMarket === 'all'
      ? 'all'
      : (visibleCompoundMarkets.find((item) => item.address === compoundMarket)?.symbol ??
        compoundMarket);

  // 统一搜索入口：Morpho 额外依赖 market id，所以在这里做协议分发。
  const handleSearch = (address: string) => {
    setError('');

    if (protocol === 'aave') {
      setQueriedAddress(address);
    } else if (protocol === 'compound') {
      setCompoundAddress(address);
    } else if (protocol === 'morpho') {
      const marketId = morphoMarketInput.trim();
      if (!marketId) {
        setError('请输入 Morpho market id');
        return;
      }
      if (!isBytes32Hex(marketId)) {
        setError('Morpho market id 必须是 0x 开头的 32 字节十六进制字符串');
        return;
      }
      setMorphoAddress(address);
      setMorphoQueriedMarketId(marketId);
    } else {
      setJustLendAddress(address);
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
    setMorphoState(emptyMorphoState());
  }, [morphoAddress, morphoQueriedMarketId]);

  useEffect(() => {
    if (protocol !== 'compound') {
      return;
    }

    let cancelled = false;

    const loadCompoundMarkets = async () => {
      try {
        const version = activeCompoundMarketsVersion;
        setCompoundMarketsVersion(null);
        setCompoundMarkets([]);
        const markets = await fetchCompoundMarkets(version);
        const visibleMarkets = getVisibleCompoundMarkets(activeTab, version, version, markets);
        if (cancelled) return;
        setCompoundMarkets(markets);
        setCompoundMarketsVersion(version);
        // Ensure compoundMarket points to a valid address after version change
        if (visibleMarkets.length > 0) {
          setCompoundMarket((currentMarket) => {
            if (
              currentMarket !== 'all' &&
              !visibleMarkets.find((marketItem) => marketItem.address === currentMarket)
            ) {
              return visibleMarkets[0].address;
            }
            return currentMarket;
          });
        }
      } catch (loadError) {
        console.error(loadError);
        setError('无法加载 Compound 市场列表');
      }
    };

    loadCompoundMarkets();
    return () => {
      cancelled = true;
    };
  }, [activeCompoundMarketsVersion, activeTab, protocol]);

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
      setError('');

      const cacheKey = compoundCacheKey(compoundAddress, compoundMarket, personalVersion);
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
        const response = await fetchCompoundUserPosition(
          personalVersion,
          compoundMarket,
          compoundAddress,
        );
        if (response.positions && response.positions.length > 0) {
          const positions = response.positions;

          if (compoundMarket === 'all') {
            const foundMarkets = new Set<string>();
            for (const item of positions) {
              compoundPositionCache.set(
                compoundCacheKey(compoundAddress, item.market, personalVersion),
                {
                  kind: 'data',
                  data: [item],
                },
              );
              foundMarkets.add(item.market.toLowerCase());
            }
            for (const item of compoundMarkets) {
              if (!foundMarkets.has(item.address.toLowerCase())) {
                compoundPositionCache.set(
                  compoundCacheKey(compoundAddress, item.address, personalVersion),
                  {
                    kind: 'not_found',
                  },
                );
              }
            }
          }

          compoundPositionCache.set(cacheKey, { kind: 'data', data: positions });
          setCompoundState({ data: positions, loading: false, notFound: false });
        } else {
          if (compoundMarket === 'all') {
            compoundPositionCache.set(cacheKey, { kind: 'data', data: [] });
            setCompoundState({ data: [], loading: false, notFound: false });
          } else {
            compoundPositionCache.set(cacheKey, { kind: 'not_found' });
            setCompoundState({ data: null, loading: false, notFound: true });
          }
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          if (compoundMarket === 'all') {
            compoundPositionCache.set(cacheKey, { kind: 'data', data: [] });
            setCompoundState({ data: [], loading: false, notFound: false });
          } else {
            compoundPositionCache.set(cacheKey, { kind: 'not_found' });
            setCompoundState({ data: null, loading: false, notFound: true });
          }
        } else {
          setCompoundState({ data: null, loading: false, notFound: false });
          console.error(loadError);
        }
      }
    };

    loadCompound();
  }, [activeTab, compoundAddress, compoundMarket, compoundMarkets, personalVersion, protocol]);

  // Morpho 当前只接入个人页单市场查询，缓存 key 由 address + market id 组成。
  useEffect(() => {
    if (
      !morphoAddress ||
      !morphoQueriedMarketId ||
      protocol !== 'morpho' ||
      activeTab !== 'personal'
    ) {
      return;
    }

    let cancelled = false;

    const loadMorpho = async (force: boolean = false) => {
      if (!force) {
        setError('');
      }

      const cacheKey = morphoCacheKey(morphoAddress, morphoQueriedMarketId, 'blue');
      const cached = morphoPositionCache.get(cacheKey);
      if (!force && cached) {
        if (cached.kind === 'not_found') {
          if (!cancelled) {
            setMorphoState({ data: null, loading: false, notFound: true });
          }
          return;
        }
        if (!cancelled) {
          setMorphoState({ data: cached.data, loading: false, notFound: false });
        }
        return;
      }

      if (!force) {
        setMorphoState((prev) => ({ ...prev, loading: true, notFound: false }));
      }
      try {
        const data = await fetchMorphoPosition(morphoAddress, morphoQueriedMarketId, 'blue', {
          force,
        });
        morphoPositionCache.set(cacheKey, { kind: 'data', data });
        if (!cancelled) {
          setMorphoState({ data, loading: false, notFound: false });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          morphoPositionCache.set(cacheKey, { kind: 'not_found' });
          if (!cancelled) {
            setMorphoState({ data: null, loading: false, notFound: true });
          }
        } else {
          if (!cancelled) {
            setMorphoState((prev) => ({ ...prev, loading: false }));
          }
          console.error(loadError);
          if (!cancelled) {
            setError('无法加载 Morpho 仓位数据');
          }
        }
      }
    };

    void loadMorpho(false);

    return () => {
      cancelled = true;
    };
  }, [activeTab, morphoAddress, morphoQueriedMarketId, protocol]);

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
      <button
        onClick={() => setProtocol('morpho')}
        className={`switch-btn ${protocol === 'morpho' ? 'active' : ''}`}
        type="button"
      >
        Morpho
      </button>
      <button
        onClick={() => setProtocol('justlend')}
        className={`switch-btn ${protocol === 'justlend' ? 'active' : ''}`}
        type="button"
      >
        JustLend
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
        {visibleCompoundMarkets.map((item) => (
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
        {visibleCompoundMarkets.map((item) => (
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

      {compoundAddress && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          <div style={resultPanelStyle}>
            <CompoundPersonalRiskDashboard
              address={compoundAddress}
              version={personalVersion}
              market={selectedCompoundMarketSymbol}
              markets={visibleCompoundMarkets}
              {...compoundState}
            />
          </div>
        </div>
      )}
    </>
  );

  const renderJustLendPersonal = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">JustLend 个人账户分析</h1>
        <p className="hero-sub">TRON 链当前仓位、风险缓冲与资产结构分析</p>
      </div>

      <AddressInput
        onSearch={handleSearch}
        loading={false}
        historyKey="search_history_justlend"
        placeholder="输入 JustLend / TRON 钱包地址 (T...)"
        addressType="tron"
      />
      {renderError()}

      {justLendAddress && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          <JustLendPersonalDashboard address={justLendAddress} />
        </div>
      )}
    </>
  );

  // Morpho 在通用地址输入框上方单独追加 market id 输入框，避免侵入现有 AddressInput。
  const renderMorphoPersonal = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Morpho 个人账户分析</h1>
        <p className="hero-sub">Morpho Blue 单市场仓位、借款边际与抵押结构分析</p>
      </div>

      <div className="input-form" style={{ marginBottom: '1rem' }}>
        <div className="input-row">
          <input
            type="text"
            value={morphoMarketInput}
            onChange={(e) => {
              setMorphoMarketInput(e.target.value);
              setError('');
            }}
            placeholder="输入 Morpho market id (0x... bytes32)"
            className="address-input"
            spellCheck={false}
          />
        </div>
      </div>

      <AddressInput
        onSearch={handleSearch}
        loading={morphoState.loading}
        historyKey="search_history_morpho"
        placeholder="输入 Morpho 钱包地址 (0x...)"
      />
      {renderError()}

      {morphoAddress && morphoQueriedMarketId && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          <div style={resultPanelStyle}>
            <MorphoPersonalDashboard
              address={morphoAddress}
              marketId={morphoQueriedMarketId}
              protocol="blue"
              {...morphoState}
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
        <h1 className="hero-title">Compound 宏观借贷抵押市场评估</h1>
        <p className="hero-sub">Compound 借贷抵押市场分析</p>
        {renderMarketVersionSwitch()}
        {renderCompoundMarketSwitch()}
      </div>
      <Suspense fallback={<ChartFallback minHeight="420px" />}>
        <CompoundMarketAssessment
          marketVersion={marketVersion}
          markets={visibleCompoundMarkets}
          selectedMarket={compoundMarket}
          onMarketChange={setCompoundMarket}
        />
      </Suspense>
    </>
  );

  const renderJustLendMarket = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">JustLend 宏观市场评估</h1>
        <p className="hero-sub">先搭好分析框架，等待 TRON 市场级接口与历史序列接入</p>
      </div>

      <JustLendMarketDashboard />
    </>
  );

  const renderMorphoMarket = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Morpho 宏观市场评估</h1>
        <p className="hero-sub">市场级接口尚未接入，当前先支持单 market id 的个人仓位查询</p>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">接入状态</span>
          <span className="badge" style={{ background: '#1e293b', color: '#7dd3fc' }}>
            Morpho Blue
          </span>
        </div>
        <p className="empty-text" style={{ margin: 0 }}>
          当前已接入个人页 `address + market id` 查询流程。等你提供 `markets`、`market state`、
          `replay` 或 `liquidation` 接口后，这里可以继续扩成完整市场分析页。
        </p>
      </div>
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
            : protocol === 'compound'
              ? renderCompoundPersonal()
              : protocol === 'morpho'
                ? renderMorphoPersonal()
                : renderJustLendPersonal()
          : protocol === 'aave'
            ? renderAaveMarket()
            : protocol === 'compound'
              ? renderCompoundMarket()
              : protocol === 'morpho'
                ? renderMorphoMarket()
                : renderJustLendMarket()}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet / TRON</footer>
    </div>
  );
}
