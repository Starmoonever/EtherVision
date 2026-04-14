import type { MorphoPositionResponse } from '../../../api/morpho';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';
import { MorphoPersonalSearch } from '../components/MorphoPersonalSearch';
import { MorphoPersonalDashboard } from '../components/MorphoPersonalDashboard';

interface MorphoState {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

interface MorphoPersonalPageProps {
  error: string;
  morphoAddress: string;
  morphoQueriedAddress: string;
  morphoMarketInput: string;
  morphoQueriedMarketId: string;
  morphoState: MorphoState;
  onMarketInputChange: (value: string) => void;
  onAddressChange: (value: string) => void;
  onSearch: (address: string, marketId: string) => void | Promise<void>;
}

export function MorphoPersonalPage({
  error,
  morphoAddress,
  morphoQueriedAddress,
  morphoMarketInput,
  morphoQueriedMarketId,
  morphoState,
  onMarketInputChange,
  onAddressChange,
  onSearch,
}: MorphoPersonalPageProps) {
  return (
    <>
      <PageHero
        title="Morpho 个人账户分析"
        subtitle="Morpho Blue 单市场仓位、借款边际与抵押结构分析"
      />

      <MorphoPersonalSearch
        loading={morphoState.loading}
        valueAddress={morphoAddress}
        valueMarketId={morphoMarketInput}
        onChangeAddress={onAddressChange}
        onChangeMarketId={onMarketInputChange}
        onSearch={onSearch}
      />
      <ErrorNotice message={error} />

      {morphoQueriedAddress && morphoQueriedMarketId ? (
        <div className="results-container">
          <ResultPanel>
            <MorphoPersonalDashboard
              address={morphoQueriedAddress}
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
