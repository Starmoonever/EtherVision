import { useEffect, useState } from 'react';
import { fetchUserPosition } from '../../api';
import type { BorrowPosition, UserPosition } from '../../api';
import type { ProtocolRootProps } from '../../shared/types/app';
import { AaveMarketPage } from './pages/AaveMarketPage';
import { AavePersonalPage } from './pages/AavePersonalPage';

interface VersionState {
  data: UserPosition | BorrowPosition | null;
  loading: boolean;
  notFound: boolean;
}

type AaveCacheEntry = { kind: 'data'; data: UserPosition | BorrowPosition } | { kind: 'not_found' };

const emptyState = (): VersionState => ({ data: null, loading: false, notFound: false });
const aavePositionCache = new Map<string, AaveCacheEntry>();

export function AaveProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [marketVersion, setMarketVersion] = useState<'v2' | 'v3'>('v3');
  const [personalVersion, setPersonalVersion] = useState<'v2' | 'v3'>('v3');
  const [queriedAddress, setQueriedAddress] = useState('');
  const [v2State, setV2State] = useState<VersionState>(emptyState());
  const [v3State, setV3State] = useState<VersionState>(emptyState());

  useEffect(() => {
    setV2State(emptyState());
    setV3State(emptyState());
  }, [queriedAddress]);

  useEffect(() => {
    if (!queriedAddress || activeTab !== 'personal') return;

    const load = async (version: 'v2' | 'v3', setState: typeof setV2State) => {
      const cacheKey = `${version}:${queriedAddress.toLowerCase()}`;
      const cached = aavePositionCache.get(cacheKey);
      if (cached) {
        if (cached.kind === 'not_found') {
          setState({ data: null, loading: false, notFound: true });
          return;
        }
        setState({ data: cached.data, loading: false, notFound: false });
        return;
      }

      setState((prev) => ({ ...prev, loading: true, notFound: false }));
      try {
        const data = await fetchUserPosition(queriedAddress, version);
        aavePositionCache.set(cacheKey, { kind: 'data', data });
        setState({ data, loading: false, notFound: false });
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          aavePositionCache.set(cacheKey, { kind: 'not_found' });
          setState({ data: null, loading: false, notFound: true });
          return;
        }

        setState({ data: null, loading: false, notFound: false });
        console.error(loadError);
      }
    };

    setError('');
    if (personalVersion === 'v2') {
      void load('v2', setV2State);
    } else {
      void load('v3', setV3State);
    }
  }, [activeTab, personalVersion, queriedAddress]);

  if (!active) return null;

  return activeTab === 'personal' ? (
    <AavePersonalPage
      queriedAddress={queriedAddress}
      personalVersion={personalVersion}
      error={error}
      v2State={v2State}
      v3State={v3State}
      onSearch={(address) => {
        setError('');
        setQueriedAddress(address);
      }}
      onVersionChange={setPersonalVersion}
    />
  ) : (
    <AaveMarketPage marketVersion={marketVersion} onVersionChange={setMarketVersion} />
  );
}
