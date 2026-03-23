import { useEffect, useState } from 'react';
import { getAddress } from 'viem';
import { AddressInput } from './components/AddressInput';
import { CompoundEthSensitiveTable } from './components/CompoundEthSensitiveTable';
import { CompoundMarketAssessment } from './components/CompoundMarketAssessment';
import { CompoundSummaryCard } from './components/CompoundSummaryCard';
import { MarketAssessment } from './components/MarketAssessment';
import { PositionReplayChart } from './components/PositionReplayChart';
import { PositionTable } from './components/PositionTable';
import { SummaryCard } from './components/SummaryCard';
import { fetchUserPosition } from './api';
import type { BorrowPosition, UserPosition } from './api';
import { fetchCompoundUserPosition } from './api/compound';
import type { CompoundUserPositionItem } from './api/compound';
import './App.css';

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

type CompoundAsset = 'USDC' | 'USDT' | 'WETH' | 'all';

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });
const emptyCompoundState = (): CompoundVersionState => ({
  data: null,
  loading: false,
  notFound: false,
});

const resultPanelStyle = {
  border: '1px solid #334155',
  borderRadius: '14px',
  padding: '1.25rem',
  background: '#0d1117',
  display: 'flex',
  flexDirection: 'column' as const,
  gap: '1rem',
};

export default function App() {
  const [protocol, setProtocol] = useState<'aave' | 'compound'>('aave');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [error, setError] = useState('');

  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3' | 'all'>('all');
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3');

  const [queriedAddress, setQueriedAddress] = useState('');
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  const [compoundAsset, setCompoundAsset] = useState<CompoundAsset>('USDC');
  const [compoundAddress, setCompoundAddress] = useState('');
  const [compoundState, setCompoundState] = useState<CompoundVersionState>(emptyCompoundState());

  const handleSearch = (address: string) => {
    let safeAddress = address;

    try {
      safeAddress = getAddress(address.toLowerCase());
    } catch (searchError) {
      console.warn('Address standardization failed, using original input', searchError);
      setError('抵押ETH的钱包地址格式无效');

      if (protocol === 'aave') {
        setQueriedAddress('');
      } else {
        setCompoundAddress('');
      }
      return;
    }

    setError('');

    if (protocol === 'aave') {
      setQueriedAddress(safeAddress);
    } else {
      setCompoundAddress(safeAddress);
    }
  };

  useEffect(() => {
    setV2State(emptyState());
    setV3State(emptyState());
  }, [queriedAddress]);

  useEffect(() => {
    setCompoundState(emptyCompoundState());
  }, [compoundAddress, compoundAsset]);

  useEffect(() => {
    if (!queriedAddress || protocol !== 'aave' || activeTab !== 'personal') return;

    const load = async (version: 'v2' | 'v3', setState: typeof setV2State) => {
      setState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        const data = await fetchUserPosition(queriedAddress, version);
        setState({ data, loading: false, notFound: false });
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
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
      setCompoundState((prev) => ({ ...prev, loading: true, notFound: false }));

      if (personalVersion === 'v2') {
        setError('抱歉，暂无 Compound v2 数据');
        setCompoundState({ data: null, loading: false, notFound: false });
        return;
      }

      try {
        setError('');
        const response = await fetchCompoundUserPosition('v3', compoundAsset, compoundAddress);
        if (response.positions && response.positions.length > 0) {
          setCompoundState({ data: response.positions[0], loading: false, notFound: false });
        } else {
          setCompoundState({ data: null, loading: false, notFound: true });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          setCompoundState({ data: null, loading: false, notFound: true });
        } else {
          setCompoundState({ data: null, loading: false, notFound: false });
          console.error(loadError);
        }
      }
    };

    loadCompound();
  }, [activeTab, compoundAddress, compoundAsset, personalVersion, protocol]);

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
        <button
          onClick={() => setMarketVersion('all')}
          className={`switch-btn ${marketVersion === 'all' ? 'active active-purple' : ''}`}
          type="button"
        >
          ALL
        </button>
      </div>
    </div>
  );

  const renderCompoundAssetSwitch = () => (
    <div className="hero-switch">
      <div className="switch-group">
        {(['USDC', 'USDT', 'WETH', 'all'] as const).map((asset) => (
          <button
            key={asset}
            onClick={() => setCompoundAsset(asset)}
            className={`switch-btn ${compoundAsset === asset ? 'active' : ''}`}
            type="button"
          >
            {asset}
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

      <AddressInput onSearch={handleSearch} loading={false} />
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
            <PositionReplayChart address={queriedAddress} version={personalVersion} />
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

      <AddressInput onSearch={handleSearch} loading={false} />
      {renderError()}

      {compoundAddress && personalVersion === 'v3' && (
        <div className="results-container" style={{ marginTop: '2rem' }}>
          <div style={resultPanelStyle}>
            <CompoundSummaryCard
              address={compoundAddress}
              version="v3"
              market={compoundAsset}
              {...compoundState}
            />
            <CompoundEthSensitiveTable {...compoundState} />
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
      <MarketAssessment marketVersion={marketVersion} />
    </>
  );

  const renderCompoundMarket = () => (
    <>
      <div className="hero">
        <h1 className="hero-title">Compound 宏观借贷市场评估</h1>
        <p className="hero-sub">Compound 借贷市场状态分析</p>
        {renderMarketVersionSwitch()}
      </div>
      <CompoundMarketAssessment marketVersion={marketVersion} />
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
