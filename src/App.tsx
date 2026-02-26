import { useState } from 'react';
import { AddressInput } from './components/AddressInput';
import { SummaryCard } from './components/SummaryCard';
import { PositionTable } from './components/PositionTable';
import { fetchUserPosition, type UserPosition } from './lib/aave';
import './App.css';

export default function App() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [position, setPosition] = useState<UserPosition | null>(null);
  const [queriedAddress, setQueriedAddress] = useState('');

  const handleSearch = async (address: string) => {
    setLoading(true);
    setError('');
    setPosition(null);
    setQueriedAddress(address);

    try {
      const result = await fetchUserPosition(address);
      setPosition(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : '查询失败，请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  const hasPosition =
    position &&
    (parseFloat(position.summary.totalCollateralUSD) > 0 ||
      parseFloat(position.summary.totalDebtUSD) > 0);

  return (
    <div className="app">
      {/* Header */}
      <header className="app-header">
        <div className="header-inner">
          <div className="logo">
            <span className="logo-icon">⚡</span>
            <span className="logo-text">Aave V3 仓位查询</span>
          </div>
          <span className="network-badge">Ethereum Mainnet</span>
        </div>
      </header>

      {/* Main */}
      <main className="app-main">
        <div className="hero">
          <h1 className="hero-title">查询账户仓位</h1>
          <p className="hero-sub">输入以太坊地址，实时获取 Aave V3 供给与借贷数据</p>
        </div>

        <AddressInput onSearch={handleSearch} loading={loading} />

        {/* Loading */}
        {loading && (
          <div className="status-block">
            <div className="spinner" />
            <p>正在查询链上数据…</p>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div className="error-block">
            <span className="error-icon">⚠️</span>
            <div>
              {error.split('\n').map((line, i) => (
                <p key={i} style={{ margin: i === 0 ? 0 : '0.4rem 0 0' }}>
                  {line}
                </p>
              ))}
              {error.includes('VITE_ETH_RPC_URL') && (
                <p className="rpc-hint">
                  参考 <code>.env.example</code>，在项目根目录创建 <code>.env.local</code> 并填入 RPC 地址后重启开发服务器。
                </p>
              )}
            </div>
          </div>
        )}

        {/* No position */}
        {!loading && !error && position && !hasPosition && (
          <div className="status-block">
            <p>该地址在 Aave V3 (Ethereum) 上暂无任何仓位</p>
          </div>
        )}

        {/* Results */}
        {!loading && !error && position && hasPosition && (
          <>
            <SummaryCard summary={position.summary} address={queriedAddress} />
            <PositionTable reserves={position.reserves} />
          </>
        )}
      </main>

      <footer className="app-footer">
        数据来源：Aave V3 Ethereum Mainnet 智能合约
      </footer>
    </div>
  );
}
