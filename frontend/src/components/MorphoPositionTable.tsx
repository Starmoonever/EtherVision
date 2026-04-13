import type { MorphoPositionAsset, MorphoPositionResponse } from '../api/morpho';

interface MorphoPositionTableProps {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
  protocol?: 'blue';
}

function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const parsed = typeof value === 'number' ? value : parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatAmount(value: string | number, decimals: number = 6): string {
  return toNum(value).toLocaleString(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  });
}

// 保留 Morpho 原始 role 拆分，便于用户直接区分 loan leg 和 collateral leg。
function renderRows(rows: MorphoPositionAsset[]) {
  return rows.map((asset) => (
    <tr key={`${asset.role}:${asset.token_address}`}>
      <td>
        <span className="token-symbol">{asset.symbol}</span>
      </td>
      <td className="right mono">{asset.decimals}</td>
      <td className="right mono bold">{formatAmount(asset.amount)}</td>
      <td className="right mono" title={asset.token_address}>
        {asset.token_address.slice(0, 8)}…{asset.token_address.slice(-6)}
      </td>
    </tr>
  ));
}

export function MorphoPositionTable({
  data,
  loading,
  notFound,
  protocol = 'blue',
}: MorphoPositionTableProps) {
  const badge = (
    <span
      className="badge"
      style={{
        background: '#102a43',
        color: '#7dd3fc',
        border: '1px solid #164e63',
        fontWeight: 700,
      }}
    >
      {protocol.toUpperCase()}
    </span>
  );

  if (loading) {
    return (
      <div
        className="card"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '120px',
          gap: '0.75rem',
        }}
      >
        <div
          className="spinner"
          style={{ width: '20px', height: '20px', borderWidth: '2px' }}
        ></div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div
        className="card"
        style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', minHeight: '200px' }}
      >
        <div className="card-header">
          <span className="card-title">Morpho 资产结构</span>
          {badge}
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <p className="empty-text" style={{ margin: 0 }}>
            当前没有 Morpho 仓位数据
          </p>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const loanAssets = data.assets.filter((asset) => asset.role === 'loan');
  const collateralAssets = data.assets.filter((asset) => asset.role === 'collateral');

  return (
    <div className="positions-wrap">
      <div className="card morpho-detail-card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div>
              <span className="card-title morpho-section-title">借款资产明细</span>
              <p className="morpho-section-subtitle">核对当前市场实际借入资产、余额与合约地址。</p>
            </div>
            {badge}
          </div>
          <span className="badge red-badge">{loanAssets.length} 项</span>
        </div>

        <div className="justlend-banner justlend-banner-soft" style={{ marginBottom: '0.9rem' }}>
          <div className="justlend-banner-copy">
            当前借款主资产为 <strong>{data.loan_token_symbol}</strong>，总借款数量为{' '}
            <strong>{formatAmount(data.borrow_assets)}</strong>。
          </div>
        </div>

        {loanAssets.length === 0 ? (
          <p className="empty-text">当前市场没有贷款侧余额</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table morpho-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">精度</th>
                  <th className="right">数量</th>
                  <th className="right">合约</th>
                </tr>
              </thead>
              <tbody>{renderRows(loanAssets)}</tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card morpho-detail-card">
        <div className="card-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div>
              <span className="card-title morpho-section-title">抵押资产明细</span>
              <p className="morpho-section-subtitle">核对当前市场实际抵押资产、数量与合约地址。</p>
            </div>
            {badge}
          </div>
          <span className="badge green-badge">{collateralAssets.length} 项</span>
        </div>

        <div className="justlend-banner justlend-banner-soft" style={{ marginBottom: '0.9rem' }}>
          <div className="justlend-banner-copy">
            当前抵押主资产为 <strong>{data.collateral_token_symbol}</strong>，总抵押数量为{' '}
            <strong>{formatAmount(data.collateral_assets)}</strong>。
          </div>
        </div>

        {collateralAssets.length === 0 ? (
          <p className="empty-text">当前市场没有抵押侧余额</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table morpho-table">
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">精度</th>
                  <th className="right">数量</th>
                  <th className="right">合约</th>
                </tr>
              </thead>
              <tbody>{renderRows(collateralAssets)}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
