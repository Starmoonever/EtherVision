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

          {/* 导航 Tab */}
          <div style={{ display: 'flex', justifyContent: 'center', background: '#1e293b', borderRadius: '8px', padding: '2px' }}>
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

          <span className="network-badge">数据库版</span>
        </div>
      </header>

      <main className="app-main">
        {activeTab === 'personal' ? (
          <>
            <div className="hero">
              <h1 className="hero-title">个人账户分析</h1>
              <p className="hero-sub">账户头寸与清算</p>
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
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                  {/* V2 版块 */}
                  <div style={{ border: '1px solid #334155', borderRadius: '14px', padding: '1.25rem', background: '#0d1117', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    <SummaryCard address={queriedAddress} version="v2" />
                    <PositionTable address={queriedAddress} version="v2" />
                  </div>
                  {/* V3 版块 */}
                  <div style={{ border: '1px solid #334155', borderRadius: '14px', padding: '1.25rem', background: '#0d1117', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    <SummaryCard address={queriedAddress} version="v3" />
                    <PositionTable address={queriedAddress} version="v3" />
                  </div>
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

      <footer className="app-footer">
        数据来源：内网 API | Ethereum Mainnet
      </footer>
    </div>
  );
}
