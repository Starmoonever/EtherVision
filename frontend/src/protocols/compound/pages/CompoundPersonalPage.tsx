import { AddressInput } from '../../../components/AddressInput';
import { CompoundPersonalRiskDashboard } from '../../../components/CompoundPersonalRiskDashboard';
import type { CompoundMarket, CompoundUserPositionItem } from '../../../api/compound';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';

interface CompoundVersionState {
  data: CompoundUserPositionItem[] | null;
  loading: boolean;
  notFound: boolean;
}

interface CompoundPersonalPageProps {
  personalVersion: 'v2' | 'v3';
  visibleMarkets: CompoundMarket[];
  selectedMarketSymbol: string;
  compoundMarket: string;
  compoundAddress: string;
  compoundState: CompoundVersionState;
  error: string;
  onSearch: (address: string) => void;
  onVersionChange: (version: 'v2' | 'v3') => void;
  onMarketChange: (market: string) => void;
}

export function CompoundPersonalPage({
  personalVersion,
  visibleMarkets,
  selectedMarketSymbol,
  compoundMarket,
  compoundAddress,
  compoundState,
  error,
  onSearch,
  onVersionChange,
  onMarketChange,
}: CompoundPersonalPageProps) {
  return (
    <>
      <PageHero
        title="Compound 个人账户分析"
        subtitle="账户头寸与清算预测"
        controls={
          <>
            <SegmentedControl
              ariaLabel="Compound personal version"
              value={personalVersion}
              onChange={onVersionChange}
              options={[
                {
                  value: 'v2',
                  label: 'V2',
                  activeClassName: 'active-purple',
                },
                {
                  value: 'v3',
                  label: 'V3',
                  activeClassName: 'active-purple',
                },
              ]}
            />
            <SegmentedControl
              ariaLabel="Compound personal market"
              value={compoundMarket}
              onChange={onMarketChange}
              options={[
                ...visibleMarkets.map((item) => ({
                  value: item.address,
                  label: item.symbol,
                })),
                {
                  value: 'all',
                  label: 'ALL',
                },
              ]}
            />
          </>
        }
      />

      <AddressInput
        onSearch={onSearch}
        loading={false}
        historyKey={`search_history_compound_${personalVersion}`}
        placeholder="输入 Compound 钱包地址 (0x...)"
      />
      <ErrorNotice message={error} />

      {compoundAddress ? (
        <div className="results-container">
          <ResultPanel>
            <CompoundPersonalRiskDashboard
              address={compoundAddress}
              version={personalVersion}
              market={selectedMarketSymbol}
              markets={visibleMarkets}
              {...compoundState}
            />
          </ResultPanel>
        </div>
      ) : null}
    </>
  );
}
