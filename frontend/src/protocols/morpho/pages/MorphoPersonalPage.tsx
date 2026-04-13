import { AddressInput } from '../../../components/AddressInput';
import { MorphoPersonalDashboard } from '../../../components/MorphoPersonalDashboard';
import type { MorphoPositionResponse } from '../../../api/morpho';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';

interface MorphoState {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

interface MorphoPersonalPageProps {
  error: string;
  morphoAddress: string;
  morphoMarketInput: string;
  morphoQueriedMarketId: string;
  morphoState: MorphoState;
  onMarketInputChange: (value: string) => void;
  onSearch: (address: string) => void;
}

export function MorphoPersonalPage({
  error,
  morphoAddress,
  morphoMarketInput,
  morphoQueriedMarketId,
  morphoState,
  onMarketInputChange,
  onSearch,
}: MorphoPersonalPageProps) {
  return (
    <>
      <PageHero
        title="Morpho 个人账户分析"
        subtitle="Morpho Blue 单市场仓位、借款边际与抵押结构分析"
      />

      <div className="input-form input-form-compact">
        <div className="input-row">
          <input
            type="text"
            value={morphoMarketInput}
            onChange={(event) => onMarketInputChange(event.target.value)}
            placeholder="输入 Morpho market id (0x... bytes32)"
            className="address-input"
            spellCheck={false}
          />
        </div>
      </div>

      <AddressInput
        onSearch={onSearch}
        loading={morphoState.loading}
        historyKey="search_history_morpho"
        placeholder="输入 Morpho 钱包地址 (0x...)"
      />
      <ErrorNotice message={error} />

      {morphoAddress && morphoQueriedMarketId ? (
        <div className="results-container">
          <ResultPanel>
            <MorphoPersonalDashboard
              address={morphoAddress}
              marketId={morphoQueriedMarketId}
              protocol="blue"
              {...morphoState}
            />
          </ResultPanel>
        </div>
      ) : null}
    </>
  );
}
