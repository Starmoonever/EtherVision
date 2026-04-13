import { useEffect, useState } from 'react';
import { fetchMorphoPosition } from '../../api/morpho';
import type { MorphoPositionResponse } from '../../api/morpho';
import type { ProtocolRootProps } from '../../shared/types/app';
import { MorphoMarketPage } from './pages/MorphoMarketPage';
import { MorphoPersonalPage } from './pages/MorphoPersonalPage';

interface MorphoState {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

type MorphoCacheEntry = { kind: 'data'; data: MorphoPositionResponse } | { kind: 'not_found' };

const emptyMorphoState = (): MorphoState => ({
  data: null,
  loading: false,
  notFound: false,
});

const morphoPositionCache = new Map<string, MorphoCacheEntry>();

const morphoCacheKey = (address: string, marketId: string, protocol: string) =>
  `${protocol}:${marketId.toLowerCase()}:${address.toLowerCase()}`;

function isBytes32Hex(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

export function MorphoProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [morphoAddress, setMorphoAddress] = useState('');
  const [morphoMarketInput, setMorphoMarketInput] = useState('');
  const [morphoQueriedMarketId, setMorphoQueriedMarketId] = useState('');
  const [morphoState, setMorphoState] = useState<MorphoState>(emptyMorphoState());

  useEffect(() => {
    setMorphoState(emptyMorphoState());
  }, [morphoAddress, morphoQueriedMarketId]);

  useEffect(() => {
    if (!morphoAddress || !morphoQueriedMarketId || activeTab !== 'personal') return;

    let cancelled = false;

    const loadMorpho = async (force = false) => {
      if (!force) {
        setError('');
      }

      const cacheKey = morphoCacheKey(morphoAddress, morphoQueriedMarketId, 'blue');
      const cached = morphoPositionCache.get(cacheKey);
      if (!force && cached) {
        if (cached.kind === 'not_found') {
          if (!cancelled) {
            setMorphoState({ data: null, loading: false, notFound: true });
          }
          return;
        }

        if (!cancelled) {
          setMorphoState({ data: cached.data, loading: false, notFound: false });
        }
        return;
      }

      if (!force) {
        setMorphoState((prev) => ({ ...prev, loading: true, notFound: false }));
      }

      try {
        const data = await fetchMorphoPosition(morphoAddress, morphoQueriedMarketId, 'blue', {
          force,
        });
        morphoPositionCache.set(cacheKey, { kind: 'data', data });
        if (!cancelled) {
          setMorphoState({ data, loading: false, notFound: false });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
          morphoPositionCache.set(cacheKey, { kind: 'not_found' });
          if (!cancelled) {
            setMorphoState({ data: null, loading: false, notFound: true });
          }
          return;
        }

        console.error(loadError);
        if (!cancelled) {
          setMorphoState((prev) => ({ ...prev, loading: false }));
          setError('无法加载 Morpho 仓位数据');
        }
      }
    };

    void loadMorpho(false);

    return () => {
      cancelled = true;
    };
  }, [activeTab, morphoAddress, morphoQueriedMarketId]);

  if (!active) return null;

  return activeTab === 'personal' ? (
    <MorphoPersonalPage
      error={error}
      morphoAddress={morphoAddress}
      morphoMarketInput={morphoMarketInput}
      morphoQueriedMarketId={morphoQueriedMarketId}
      morphoState={morphoState}
      onAddressChange={(value) => {
        setMorphoAddress(value);
        setError('');
      }}
      onMarketInputChange={(value) => {
        setMorphoMarketInput(value);
        setError('');
      }}
      onSearch={(address, marketId) => {
        const trimmedMarketId = marketId.trim();
        setError('');

        if (!trimmedMarketId) {
          setError('请输入 Morpho market id');
          return;
        }

        if (!isBytes32Hex(trimmedMarketId)) {
          setError('Morpho market id 必须是 0x 开头的 32 字节十六进制字符串');
          return;
        }

        setMorphoAddress(address);
        setMorphoMarketInput(trimmedMarketId);
        setMorphoQueriedMarketId(trimmedMarketId);
      }}
    />
  ) : (
    <MorphoMarketPage />
  );
}
