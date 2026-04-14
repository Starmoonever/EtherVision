import { useEffect, useState } from 'react';
import type { MorphoPositionAsset, MorphoPositionResponse } from '../../../api/morpho';
import { fetchAssetPrice } from '../../../api';

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
function renderRows(
  rows: MorphoPositionAsset[],
  priceQuote?: string,
  maxBorrowable?: string,
  loanTokenPrice?: number,
  collateralTokenPrice?: number,
) {
  return rows.map((asset) => {
    let oracleValue: number | undefined;
    let borrowValue: number | undefined;
    let collateralUsdValue: number | undefined;
    let maxBorrowValue: number | undefined;

    if (asset.role === 'loan') {
      // 借款价值 = 借款数量 × 借款 token USD 单价
      if (loanTokenPrice) {
        borrowValue = toNum(asset.amount) * loanTokenPrice;
      }
      // 最大借款价值 = 市场最大可借数量（统一值）
      if (maxBorrowable) {
        maxBorrowValue = toNum(maxBorrowable);
      }
    } else if (asset.role === 'collateral') {
      // 抵押价值（USD） = 抵押数量 × 抵押 token USD 单价
      if (collateralTokenPrice) {
        collateralUsdValue = toNum(asset.amount) * collateralTokenPrice;
      }
      // 折算借款资产价值 = 抵押数量 × Oracle price_quote
      if (priceQuote) {
        oracleValue = toNum(asset.amount) * toNum(priceQuote);
      }
    }

    return (
      <tr key={`${asset.role}:${asset.token_address}`}>
        <td>
          <span className="token-symbol">{asset.symbol}</span>
        </td>
        <td className="right mono bold">{formatAmount(asset.amount)}</td>

        {/* 单价列 */}
        {asset.role === 'loan' && (
          <td className="right mono">
            {loanTokenPrice !== undefined ? `$${formatAmount(loanTokenPrice, 2)}` : '-'}
          </td>
        )}
        {asset.role === 'collateral' && (
          <td className="right mono">
            {collateralTokenPrice !== undefined ? `$${formatAmount(collateralTokenPrice, 2)}` : '-'}
          </td>
        )}

        {/* 价值列 */}
        {asset.role === 'loan' && (
          <td className="right mono">
            {borrowValue !== undefined ? `$${formatAmount(borrowValue, 2)}` : '-'}
          </td>
        )}
        {asset.role === 'loan' && (
          <td className="right mono">
            {maxBorrowValue !== undefined ? formatAmount(maxBorrowValue) : '-'}
          </td>
        )}

        {asset.role === 'collateral' && (
          <td className="right mono">
            {collateralUsdValue !== undefined ? `$${formatAmount(collateralUsdValue, 2)}` : '-'}
          </td>
        )}
        {asset.role === 'collateral' && (
          <td className="right mono">
            {oracleValue !== undefined ? formatAmount(oracleValue) : '-'}
          </td>
        )}

        {/* 合约地址列 */}
        <td className="right mono" title={asset.token_address}>
          {asset.token_address.slice(0, 8)}…{asset.token_address.slice(-6)}
        </td>
      </tr>
    );
  });
}

export function MorphoPositionTable({
  data,
  loading,
  notFound,
  protocol = 'blue',
}: MorphoPositionTableProps) {
  const [loanTokenPrice, setLoanTokenPrice] = useState<number | undefined>(undefined);
  const [collateralTokenPrice, setCollateralTokenPrice] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (!data?.loan_token) {
      console.log('⚠️ loan_token is empty');
      return;
    }
    console.log(`🔍 Fetching loan token price for: ${data.loan_token}`);

    // Prefer address lookup to avoid symbol ambiguity for long-tail assets.
    fetchAssetPrice(data.loan_token)
      .then((price) => {
        console.log(`✅ Loan price fetched: ${data.loan_token} = $${price}`);
        setLoanTokenPrice(price);
      })
      .catch((err) => {
        console.error(`❌ Failed to fetch loan price for ${data.loan_token}:`, err);
        setLoanTokenPrice(undefined);
      });
  }, [data?.loan_token]);

  useEffect(() => {
    if (!data?.collateral_token) {
      console.log('⚠️ collateral_token is empty');
      return;
    }
    console.log(`🔍 Fetching collateral token price for: ${data.collateral_token}`);

    fetchAssetPrice(data.collateral_token)
      .then((price) => {
        console.log(`✅ Collateral price fetched: ${data.collateral_token} = $${price}`);
        setCollateralTokenPrice(price);
      })
      .catch((err) => {
        console.error(`❌ Failed to fetch collateral price for ${data.collateral_token}:`, err);
        setCollateralTokenPrice(undefined);
      });
  }, [data?.collateral_token]);

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

        <div className="protocol-banner protocol-banner-soft" style={{ marginBottom: '0.9rem' }}>
          <div className="protocol-banner-copy">
            当前借款主资产为 <strong>{data.loan_token_symbol}</strong>，总借款数量为{' '}
            <strong>{formatAmount(data.borrow_assets)}</strong>。
          </div>
        </div>

        {loanAssets.length === 0 ? (
          <p className="empty-text">当前市场没有贷款侧余额</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table morpho-table">
              <colgroup>
                <col style={{ width: '20%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '20%' }} />
              </colgroup>
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">数量</th>
                  <th className="right">单价</th>
                  <th className="right">借款价值</th>
                  <th className="right">最大借款价值</th>
                  <th className="right">合约</th>
                </tr>
              </thead>
              <tbody>
                {renderRows(
                  loanAssets,
                  data.price_quote,
                  data.max_borrowable_in_loan_asset,
                  loanTokenPrice,
                  collateralTokenPrice,
                )}
              </tbody>
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

        <div className="protocol-banner protocol-banner-soft" style={{ marginBottom: '0.9rem' }}>
          <div className="protocol-banner-copy">
            当前抵押主资产为 <strong>{data.collateral_token_symbol}</strong>，总抵押数量为{' '}
            <strong>{formatAmount(data.collateral_assets)}</strong>
            {collateralTokenPrice !== undefined && (
              <>
                ，抵押价值约为{' '}
                <strong>
                  ${formatAmount(toNum(data.collateral_assets) * collateralTokenPrice)}
                </strong>{' '}
                USD
              </>
            )}
            {data.price_quote && (
              <>
                ，折算借款资产价值约为{' '}
                <strong>
                  {formatAmount(toNum(data.collateral_assets) * toNum(data.price_quote))}
                </strong>{' '}
                {data.loan_token_symbol}
              </>
            )}
            。
          </div>
        </div>

        {collateralAssets.length === 0 ? (
          <p className="empty-text">当前市场没有抵押侧余额</p>
        ) : (
          <div className="table-wrap">
            <table className="pos-table morpho-table">
              <colgroup>
                <col style={{ width: '20%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '15%' }} />
                <col style={{ width: '20%' }} />
              </colgroup>
              <thead>
                <tr>
                  <th>资产</th>
                  <th className="right">数量</th>
                  <th className="right">单价</th>
                  <th className="right">抵押价值</th>
                  <th className="right">折算借款资产价值</th>
                  <th className="right">合约</th>
                </tr>
              </thead>
              <tbody>
                {renderRows(
                  collateralAssets,
                  data.price_quote,
                  undefined,
                  undefined,
                  collateralTokenPrice,
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
