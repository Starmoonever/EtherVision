import { useState, useEffect } from 'react';
import { getAddress } from 'viem';
import { AddressInput } from './components/AddressInput';
import { SummaryCard } from './components/SummaryCard';
import { PositionTable } from './components/PositionTable';
import { PositionReplayChart } from './components/PositionReplayChart';
import { MarketAssessment } from './components/MarketAssessment';
import { CompoundMarketAssessment } from './components/CompoundMarketAssessment';
import { fetchUserPosition } from './api';
import { fetchCompoundUserPosition } from './api/compound';
import type { UserPosition, BorrowPosition } from './api';
import type { CompoundUserPositionItem } from './api/compound';
import { CompoundSummaryCard } from './components/CompoundSummaryCard';
import { CompoundEthSensitiveTable } from './components/CompoundEthSensitiveTable';
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

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });
const emptyCompoundState = (): CompoundVersionState => ({
  data: null,
  loading: false,
  notFound: false,
});

export default function App() {
  const [protocol, setProtocol] = useState<'aave' | 'compound'>('aave');
  const [queriedAddress, setQueriedAddress] = useState('');
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3' | 'all'>('all'); // 宏观市场版本
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3'); // 个人账户分析版本
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  // Compound 个人账户分析状态
  const [compoundAsset, setCompoundAsset] = useState<'USDC' | 'USDT' | 'WETH' | 'all'>('USDC'); // 默认 USDC 而不是 all，以符合具体资产查询
  const [compoundAddress, setCompoundAddress] = useState('');
  const [compoundState, setCompoundState] = useState<CompoundVersionState>(emptyCompoundState());

  const handleSearch = (address: string) => {
    // 对原始地址进行标准化 (Keccak-256 哈希 checksum 格式)
    // 强制转换为全小写后再交给 getAddress，避免由于大小写混合导致的 Checksum 校验失败抛出异常
    let safeAddress = address;
    try {
      safeAddress = getAddress(address.toLowerCase());
    } catch (e) {
      console.warn('Address standardization failed, using original input', e);
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
    // 每次地址变化时，清空之前的数据状态
    setV2State(emptyState());
    setV3State(emptyState());
  }, [queriedAddress]);

  useEffect(() => {
    // 每次 Compound 地址或资产变化时，清空状态
    setCompoundState(emptyCompoundState());
  }, [compoundAddress, compoundAsset]);

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

  useEffect(() => {
    if (!compoundAddress) return;

    const loadCompound = async () => {
      setCompoundState((prev) => ({ ...prev, loading: true, notFound: false }));

      // Compound 当前仅支持 v3
      if (personalVersion === 'v2') {
        setError('抱歉，暂无 Compound v2 数据');
        setCompoundState({ data: null, loading: false, notFound: false });
        return;
      }

      try {
        const response = await fetchCompoundUserPosition('v3', compoundAsset, compoundAddress);
        // Assuming API returns a single position item per query based on schema
        if (response.positions && response.positions.length > 0) {
          setCompoundState({ data: response.positions[0], loading: false, notFound: false });
        } else {
          setCompoundState({ data: null, loading: false, notFound: true });
        }
      } catch (err) {
        if (err instanceof Error && err.message.includes('404')) {
          setCompoundState({ data: null, loading: false, notFound: true });
        } else {
          setCompoundState({ data: null, loading: false, notFound: false });
          console.error(err);
        }
      }
    };

    loadCompound();
  }, [compoundAddress, compoundAsset, personalVersion]);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo" style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <span className="logo-icon">⚡</span>
              <span className="logo-text"> ETH 市场清算风险监测</span>
            </div>

            {/* Protocol Switch */}
            <div
              style={{
                display: 'flex',
                background: '#1e293b',
                borderRadius: '8px',
                padding: '2px',
              }}
            >
              <button
                onClick={() => setProtocol('aave')}
                style={{
                  background: protocol === 'aave' ? '#3b82f6' : 'transparent',
                  color: protocol === 'aave' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s',
                }}
              >
                Aave
              </button>
              <button
                onClick={() => setProtocol('compound')}
                style={{
                  background: protocol === 'compound' ? '#3b82f6' : 'transparent',
                  color: protocol === 'compound' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s',
                }}
              >
                Compound
              </button>
            </div>
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
        </div>
      </header>

      <main className="app-main">
        {activeTab === 'personal' ? (
          protocol === 'aave' ? (
            <>
              <div className="hero">
                <h1 className="hero-title">个人账户分析</h1>
                <p className="hero-sub">不同借贷市场下账户头寸和 ETH 相关清算风险预测</p>
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
                <p className="hero-sub">不同借贷市场下账户头寸和 ETH 相关清算风险预测</p>
              </div>

              <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '2rem' }}>
                <div
                  style={{
                    display: 'flex',
                    background: '#1e293b',
                    borderRadius: '8px',
                    padding: '4px',
                    gap: '4px',
                  }}
                >
                  {(['USDC', 'USDT', 'WETH', 'all'] as const).map((a) => (
                    <button
                      key={a}
                      onClick={() => setCompoundAsset(a)}
                      style={{
                        background: compoundAsset === a ? '#3b82f6' : 'transparent',
                        color: compoundAsset === a ? '#fff' : '#94a3b8',
                        border: 'none',
                        padding: '6px 24px',
                        borderRadius: '6px',
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        fontWeight: 600,
                        transition: 'all 0.2s',
                        textTransform: a === 'all' ? 'uppercase' : 'none',
                      }}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>

              <AddressInput onSearch={handleSearch} loading={false} />

              {error && (
                <div className="error-block">
                  <span className="error-icon">⚠️</span>
                  <p>{error}</p>
                </div>
              )}

              {compoundAddress && (
                <div className="results-container" style={{ marginTop: '2rem' }}>
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
                    <CompoundSummaryCard
                      address={compoundAddress}
                      version={personalVersion}
                      market={compoundAsset}
                      {...compoundState}
                    />

                    <CompoundEthSensitiveTable {...compoundState} />
                  </div>
                </div>
              )}
            </>
          )
        ) : protocol === 'aave' ? (
          <>
            <div className="hero">
              <h1 className="hero-title">宏观市场评估</h1>
              <p className="hero-sub">ETH 实时价格与清算模拟</p>
            </div>
            <MarketAssessment marketVersion={marketVersion} />
          </>
        ) : (
          <>
            <div className="hero">
              <h1 className="hero-title">宏观借贷市场评估</h1>
              <p className="hero-sub">Compound 借贷市场状态分析</p>
            </div>
            <CompoundMarketAssessment marketVersion={marketVersion} />
          </>
        )}
      </main>

      <footer className="app-footer">数据来源：内网 API | Ethereum Mainnet</footer>
    </div>
  );
}
