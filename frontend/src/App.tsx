import { useState } from 'react';
import { AddressInput } from './components/AddressInput';
import { SummaryCard } from './components/SummaryCard';
import { PositionTable } from './components/PositionTable';
import { MarketAssessment } from './components/MarketAssessment';
import './App.css';

export default function App() {
  const [queriedAddress, setQueriedAddress] = useState('');
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<'personal' | 'market'>('personal');
  const [version, setVersion] = useState<'v2' | 'v3' | 'all'>('all'); // 默认为 all
  const [side, setSide] = useState<'collateral' | 'borrow'>('collateral'); // 默认为抵押端

  const handleSearch = (address: string) => {
    if (!address.startsWith('0x') || address.length !== 42) {
      setError('请输入有效的 42 位以太坊地址');
      setQueriedAddress('');
      return;
    }
    setError('');
    setQueriedAddress(address);
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <span className="logo-text">Aave ETH 市场清算风险监测</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div className="side-switch" style={{ display: 'flex', background: '#1e293b', borderRadius: '8px', padding: '2px' }}>
              <button
                onClick={() => setSide('collateral')}
                style={{
                  background: side === 'collateral' ? '#3b82f6' : 'transparent',
                  color: side === 'collateral' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                抵押端
              </button>
              <button
                onClick={() => setSide('borrow')}
                style={{
                  background: side === 'borrow' ? '#3b82f6' : 'transparent',
                  color: side === 'borrow' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                借贷端
              </button>
            </div>
            <div className="version-switch" style={{ display: 'flex', background: '#1e293b', borderRadius: '8px', padding: '2px' }}>
              <button
                onClick={() => setVersion('v2')}
                style={{
                  background: version === 'v2' ? '#7c3aed' : 'transparent',
                  color: version === 'v2' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                V2
              </button>
              <button
                onClick={() => setVersion('v3')}
                style={{
                  background: version === 'v3' ? '#7c3aed' : 'transparent',
                  color: version === 'v3' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                V3
              </button>
              <button
                onClick={() => setVersion('all')}
                style={{
                  background: version === 'all' ? '#7c3aed' : 'transparent',
                  color: version === 'all' ? '#fff' : '#94a3b8',
                  border: 'none',
                  padding: '4px 12px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                  transition: 'all 0.2s'
                }}
              >
                ALL
              </button>
            </div>
            <span className="network-badge">数据库版</span>
          </div>
        </div>
      </header>

      <main className="app-main">
        <div className="tabs-container">
          <button
            className={`tab-btn ${activeTab === 'personal' ? 'active' : ''}`}
            onClick={() => setActiveTab('personal')}
          >
            个人账户分析
          </button>
          <button
            className={`tab-btn ${activeTab === 'market' ? 'active' : ''}`}
            onClick={() => setActiveTab('market')}
          >
            宏观市场评估
          </button>
        </div>

        {activeTab === 'personal' ? (
          <>
            <div className="hero">
              <h1 className="hero-title">个人账户分析</h1>
              <p className="hero-sub">账户头寸与清算</p>
            </div>

            {/* 搜索组件 */}
            <AddressInput onSearch={handleSearch} loading={false} />

            {error && (
              <div className="error-block">
                <span className="error-icon">⚠️</span>
                <p>{error}</p>
              </div>
            )}

            {/* 当有地址时，显示数据看板 */}
            {queriedAddress && (
              <div className="results-container" style={{ marginTop: '2rem' }}>
                {/* 传递地址给子组件，子组件内部去 fetch */}
                <SummaryCard address={queriedAddress} version={version} side={side} />

                <div style={{ marginTop: '2rem' }}>
                  <h3 className="section-title">资产负债情况</h3>
                  <PositionTable address={queriedAddress} />
                </div>
              </div>
            )}
          </>
        ) : (
          <>
            <div className="hero">
              <h1 className="hero-title">宏观市场评估</h1>
              <p className="hero-sub">ETH实时价格与清算模拟</p>
            </div>
            <MarketAssessment version={version} side={side} />
          </>
        )}
      </main>

      <footer className="app-footer">
        数据来源：内网 API | Ethereum Mainnet
      </footer>
    </div>
  );
}
