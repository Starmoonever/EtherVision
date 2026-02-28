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
            <span className="logo-text">Aave V3 抵押ETH清算风险监测</span>
          </div>
          <span className="network-badge">数据库版</span>
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
              <p className="hero-sub">账户头寸与清算线</p>
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
                <SummaryCard address={queriedAddress} />

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
            <MarketAssessment />
          </>
        )}
      </main>

      <footer className="app-footer">
        数据来源：内网 API (10.1.5.183) | Base Mainnet
      </footer>
    </div>
  );
}
