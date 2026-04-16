import { Suspense } from 'react';
import { CompoundMarketAssessment } from '../../../components/CompoundMarketAssessment';
import type { CompoundMarket } from '../../../api/compound';
import { ChartFallback } from '../../../shared/components/ChartFallback';
import { PageHero } from '../../../shared/components/PageHero';
import { SegmentedControl } from '../../../shared/components/SegmentedControl';

interface CompoundMarketPageProps {
  marketVersion: 'v2' | 'v3';
  visibleMarkets: CompoundMarket[];
  compoundMarket: string;
  onVersionChange: (version: 'v2' | 'v3') => void;
  onMarketChange: (market: string) => void;
}

export function CompoundMarketPage({
  marketVersion,
  visibleMarkets,
  compoundMarket,
  onVersionChange,
  onMarketChange,
}: CompoundMarketPageProps) {
  return (
    <>
      <PageHero
        title="Compound 宏观借贷抵押市场评估"
        subtitle="Compound 借贷抵押市场分析"
        controls={
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '0.75rem',
            }}
          >
            <SegmentedControl
              ariaLabel="Compound market version"
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
            <SegmentedControl
              ariaLabel="Compound market selector"
              value={compoundMarket}
              onChange={onMarketChange}
              options={visibleMarkets.map((item) => ({
                value: item.address,
                label: item.symbol,
              }))}
            />
          </div>
        }
      />
      <Suspense fallback={<ChartFallback minHeight="420px" />}>
        <CompoundMarketAssessment
          marketVersion={marketVersion}
          markets={visibleMarkets}
          selectedMarket={compoundMarket}
          onMarketChange={onMarketChange}
        />
      </Suspense>
    </>
  );
}
