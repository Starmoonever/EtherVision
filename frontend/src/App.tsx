import { useState, useEffect } from 'react';
import { AddressInput } from './components/AddressInput';
import { SummaryCard } from './components/SummaryCard';
import { PositionTable } from './components/PositionTable';
import { PositionReplayChart } from './components/PositionReplayChart';
import { MarketAssessment } from './components/MarketAssessment';
import { CompoundMarketAssessment } from './components/CompoundMarketAssessment';
import { fetchUserPosition } from './api';
import type { UserPosition, BorrowPosition } from './api';
import './App.css';

interface VersionState {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
}

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });

export default function App() {
  const [protocol, setProtocol] = useState<'aave' | 'compound'>('aave');
  const [queriedAddress, setQueriedAddress] = useState('');
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3' | 'all'>('all'); // 宏观市场版本
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3'); // 个人账户分析版本
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  const handleSearch = (address: string) => {
    if (!address.startsWith('0x') || address.length !== 42) {
      setError('请输入有效的 42 位以太坊地址');
      setQueriedAddress('');
      return;
    }
    setError('');
    setQueriedAddress(address);
  };

  useEffect(() => {
    // 每次地址变化时，清空之前的数据状态
    setV2State(emptyState());
    setV3State(emptyState());
  }, [queriedAddress]);

  useEffect(() => {
    if (!queriedAddress) return;

    const load = async (version: 'v2' | 'v3', setState: typeof setV2State) => {
      setState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        const data = await fetchUserPosition(queriedAddress, version);
        setState({ data, loading: false, notFound: false });
      } catch (err) {
        if (err instanceof Error && err.message.includes('404')) {
          setState({ data: null, loading: false, notFound: true });
        } else {
          setState({ data: null, loading: false, notFound: false });
          console.error(err);
        }
      }
    };

    // 仅加载当前选中的版本
    if (personalVersion === 'v2') {
      load('v2', setV2State);
    } else {
      load('v3', setV3State);
    }
  }, [queriedAddress, personalVersion]);

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
        {activeTab === 'personal' ? (
          protocol === 'aave' ? (
            <>
              <div className="hero">
                <h1 className="hero-title">Aave 个人账户分析</h1>
                <p className="hero-sub">账户头寸与清算预测</p>
                {renderPersonalVersionSwitch()}
              </div>

              <AddressInput onSearch={handleSearch} loading={false} />

              {error && (
                <div className="error-block">
                  <span className="error-icon">⚠️</span>
                  <p>{error}</p>
                </div>
              )}

              {queriedAddress && (
                <div className="results-container" style={{ marginTop: '2rem' }}>
                  {personalVersion === 'v2' ? (
                    <div
                      style={{
                        border: '1px solid #334155',
                        borderRadius: '14px',
                        padding: '1.25rem',
                        background: '#0d1117',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
                      <SummaryCard address={queriedAddress} version="v2" {...v2State} />
                      <PositionTable version="v2" {...v2State} />
                    </div>
                  ) : (
                    <div
                      style={{
                        border: '1px solid #334155',
                        borderRadius: '14px',
                        padding: '1.25rem',
                        background: '#0d1117',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '1rem',
                      }}
                    >
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
          ) : (
            <>
              <div className="hero">
                <h1 className="hero-title">Compound 个人账户分析</h1>
                <p className="hero-sub">账户头寸与清算预测</p>
                {renderPersonalVersionSwitch()}
              </div>
              <div style={{ textAlign: 'center', color: '#94a3b8', marginTop: '4rem' }}>
                Compound 个人账户分析模块正在开发中...
              </div>
            </>
          )
        ) : protocol === 'aave' ? (
          <>
            <div className="hero">
              <h1 className="hero-title">Aave 宏观市场评估</h1>
              <p className="hero-sub">ETH 实时价格与清算模拟</p>
              {renderMarketVersionSwitch()}
            </div>
            <MarketAssessment marketVersion={marketVersion} />
          </>
        ) : (
          <>
            <div className="hero">
              <h1 className="hero-title">Compound 宏观借贷市场评估</h1>
              <p className="hero-sub">Compound 借贷市场状态分析</p>
              {renderMarketVersionSwitch()}
            </div>
            <CompoundMarketAssessment marketVersion={marketVersion} />
          </>
        )}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet</footer>
    </div>
  );
}
