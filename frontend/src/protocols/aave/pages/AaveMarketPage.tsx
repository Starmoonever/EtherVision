import { Suspense } from 'react';
import { MarketAssessment } from '../../../components/MarketAssessment';
import { ChartFallback } from '../../../shared/components/ChartFallback';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';

interface AaveMarketPageProps {
  marketVersion: 'v2' | 'v3';
  onVersionChange: (version: 'v2' | 'v3') => void;
}

export function AaveMarketPage({ marketVersion, onVersionChange }: AaveMarketPageProps) {
  return (
    <>
      <PageHero
        title="Aave 宏观市场评估"
        subtitle="ETH 实时价格与清算模拟"
        controls={
          <SegmentedControl
            ariaLabel="Aave market version"
            value={marketVersion}
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

      <Suspense fallback={<ChartFallback minHeight="420px" />}>
        <MarketAssessment marketVersion={marketVersion} />
      </Suspense>
    </>
  );
}
