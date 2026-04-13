import { Suspense } from 'react';
import { AddressInput } from '../../../components/AddressInput';
import { PositionReplayChart } from '../../../components/PositionReplayChart';
import { PositionTable } from '../../../components/PositionTable';
import { SummaryCard } from '../../../components/SummaryCard';
import { ChartFallback } from '../../../shared/components/ChartFallback';
import { ErrorNotice } from '../../../shared/components/ErrorNotice';
import { PageHero } from '../../../shared/components/PageHero';
import { ResultPanel } from '../../../shared/components/ResultPanel';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';
import type { BorrowPosition, UserPosition } from '../../../api';

interface VersionState {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
}

interface AavePersonalPageProps {
  queriedAddress: string;
  personalVersion: 'v2' | 'v3';
  error: string;
  v2State: VersionState;
  v3State: VersionState;
  onSearch: (address: string) => void;
  onVersionChange: (version: 'v2' | 'v3') => void;
}

export function AavePersonalPage({
  queriedAddress,
  personalVersion,
  error,
  v2State,
  v3State,
  onSearch,
  onVersionChange,
}: AavePersonalPageProps) {
  const currentState = personalVersion === 'v2' ? v2State : v3State;

  return (
    <>
      <PageHero
        title="Aave 个人账户分析"
        subtitle="账户头寸与清算预测"
        controls={
          <SegmentedControl
            ariaLabel="Aave personal version"
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
        }
      />

      <AddressInput
        onSearch={onSearch}
        loading={false}
        historyKey="search_history_aave"
        placeholder="输入 Aave 钱包地址 (0x...)"
      />
      <ErrorNotice message={error} />

      {queriedAddress ? (
        <div className="results-container">
          <ResultPanel>
            <SummaryCard address={queriedAddress} version={personalVersion} {...currentState} />
            <PositionTable version={personalVersion} {...currentState} />
          </ResultPanel>

          <div className="results-section">
            <Suspense fallback={<ChartFallback minHeight="320px" />}>
              <PositionReplayChart address={queriedAddress} version={personalVersion} />
            </Suspense>
          </div>
        </div>
      ) : null}
    </>
  );
}
