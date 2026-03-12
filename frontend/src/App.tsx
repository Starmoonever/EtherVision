import { useState, useEffect } from 'react';
import { AddressInput } from './components/AddressInput';
import { SummaryCard } from './components/SummaryCard';
import { PositionTable } from './components/PositionTable';
import { PositionReplayChart } from './components/PositionReplayChart';
import { MarketAssessment } from './components/MarketAssessment';
import { fetchUserPosition, fetchUserBorrowPosition } from './api';
import type { UserPosition, BorrowPosition } from './api';
import './App.css';

interface VersionState {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
}

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });

export default function App() {
  const [queriedAddress, setQueriedAddress] = useState('');
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3' | 'all'>('all'); // 宏观市场版本
  const [marketSide, setMarketSide] = useState<'collateral' | 'borrow'>('collateral'); // 宏观市场方向
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3'); // 个人账户分析版本
  const [positionSide, setPositionSide] = useState<'collateral' | 'borrow'>('collateral'); // 个人账户分析方向
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
        let data;
        if (positionSide === 'collateral') {
          data = await fetchUserPosition(queriedAddress, version);
        } else {
          data = await fetchUserBorrowPosition(queriedAddress, version);
        }
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
  }, [queriedAddress, personalVersion, positionSide]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <span className="logo-text">Aave ETH 市场清算风险监测</span>
          </div>

          {/* 导航 Tab */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              background: '#1e293b',
              borderRadius: '8px',
              padding: '2px',
            }}
          >
            <button
              onClick={() => setActiveTab('personal')}
              style={{
                background: activeTab === 'personal' ? '#7c3aed' : 'transparent',
                color: activeTab === 'personal' ? '#fff' : '#94a3b8',
                border: 'none',
                padding: '6px 18px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: 600,
                transition: 'all 0.2s',
              }}
            >
              个人账户分析
            </button>
            <button
              onClick={() => setActiveTab('market')}
              style={{
                background: activeTab === 'market' ? '#7c3aed' : 'transparent',
                color: activeTab === 'market' ? '#fff' : '#94a3b8',
                border: 'none',
                padding: '6px 18px',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '0.9rem',
                fontWeight: 600,
                transition: 'all 0.2s',
              }}
            >
              宏观市场评估
            </button>
          </div>

          {activeTab === 'personal' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div
                className="version-switch"
                style={{
                  display: 'flex',
                  background: '#1e293b',
                  borderRadius: '8px',
                  padding: '2px',
                }}
              >
                <button
                  onClick={() => setPersonalVersion('v2')}
                  style={{
                    background: personalVersion === 'v2' ? '#7c3aed' : 'transparent',
                    color: personalVersion === 'v2' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  V2
                </button>
                <button
                  onClick={() => setPersonalVersion('v3')}
                  style={{
                    background: personalVersion === 'v3' ? '#7c3aed' : 'transparent',
                    color: personalVersion === 'v3' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  V3
                </button>
              </div>
            </div>
          )}

          {activeTab === 'market' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <div
                className="side-switch"
                style={{
                  display: 'flex',
                  background: '#1e293b',
                  borderRadius: '8px',
                  padding: '2px',
                }}
              >
                <button
                  onClick={() => setMarketSide('collateral')}
                  style={{
                    background: marketSide === 'collateral' ? '#3b82f6' : 'transparent',
                    color: marketSide === 'collateral' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  抵押端
                </button>
                <button
                  onClick={() => setMarketSide('borrow')}
                  style={{
                    background: marketSide === 'borrow' ? '#3b82f6' : 'transparent',
                    color: marketSide === 'borrow' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  借贷端
                </button>
              </div>
              <div
                className="version-switch"
                style={{
                  display: 'flex',
                  background: '#1e293b',
                  borderRadius: '8px',
                  padding: '2px',
                }}
              >
                <button
                  onClick={() => setMarketVersion('v2')}
                  style={{
                    background: marketVersion === 'v2' ? '#7c3aed' : 'transparent',
                    color: marketVersion === 'v2' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  V2
                </button>
                <button
                  onClick={() => setMarketVersion('v3')}
                  style={{
                    background: marketVersion === 'v3' ? '#7c3aed' : 'transparent',
                    color: marketVersion === 'v3' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  V3
                </button>
                <button
                  onClick={() => setMarketVersion('all')}
                  style={{
                    background: marketVersion === 'all' ? '#7c3aed' : 'transparent',
                    color: marketVersion === 'all' ? '#fff' : '#94a3b8',
                    border: 'none',
                    padding: '4px 12px',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    transition: 'all 0.2s',
                  }}
                >
                  ALL
                </button>
              </div>
            </div>
          )}

          <span className="network-badge">数据库版</span>
        </div>
      </header>

      <main className="app-main">
        {activeTab === 'personal' ? (
          <>
            <div className="hero">
              <h1 className="hero-title">个人账户分析</h1>
              <p className="hero-sub">账户头寸与清算预测</p>
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
              <h1 className="hero-title">宏观市场评估</h1>
              <p className="hero-sub">ETH 实时价格与清算模拟</p>
            </div>
            <MarketAssessment />
          </>
        )}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet</footer>
    </div>
  );
}
