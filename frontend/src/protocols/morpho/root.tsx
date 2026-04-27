import { useEffect, useState } from 'react';
import { isAddress } from 'viem';
import { fetchMorphoPosition } from '../../api/morpho';
import type { MorphoPositionResponse } from '../../api/morpho';
import type { ProtocolRootProps } from '../../shared/types/app';
import { MorphoMarketPage } from './pages/MorphoMarketPage';
import { MorphoPersonalPage } from './pages/MorphoPersonalPage';
import './styles.css';

interface MorphoState {
  data: MorphoPositionResponse | null;
  loading: boolean;
  notFound: boolean;
}

const emptyMorphoState = (): MorphoState => ({
  data: null,
  loading: false,
  notFound: false,
});

function isBytes32Hex(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

function normalizeEvmAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return trimmed.startsWith('0x') || trimmed.startsWith('0X') ? trimmed : `0x${trimmed}`;
}

export function MorphoProtocolRoot({ active, activeTab }: ProtocolRootProps) {
  const [error, setError] = useState('');
  const [morphoAddressInput, setMorphoAddressInput] = useState('');
  const [morphoQueriedAddress, setMorphoQueriedAddress] = useState('');
  const [morphoMarketInput, setMorphoMarketInput] = useState('');
  const [morphoQueriedMarketId, setMorphoQueriedMarketId] = useState('');
  const [morphoState, setMorphoState] = useState<MorphoState>(emptyMorphoState());

  useEffect(() => {
    setMorphoState(emptyMorphoState());
  }, [morphoQueriedAddress, morphoQueriedMarketId]);

  useEffect(() => {
    if (!active || !morphoQueriedAddress || !morphoQueriedMarketId || activeTab !== 'personal') {
      return;
    }

    let cancelled = false;

    const loadMorpho = async (force = false) => {
      if (!force) {
        setError('');
      }

      if (!force) {
        setMorphoState((prev) => ({ ...prev, loading: true, notFound: false }));
      }

      try {
        const data = await fetchMorphoPosition(
          morphoQueriedAddress,
          morphoQueriedMarketId,
          'blue',
          {
            force,
          },
        );
        if (!cancelled) {
          setMorphoState({ data, loading: false, notFound: false });
        }
      } catch (loadError) {
        if (loadError instanceof Error && loadError.message.includes('404')) {
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
  }, [active, activeTab, morphoQueriedAddress, morphoQueriedMarketId]);

  if (!active) return null;

  return activeTab === 'personal' ? (
    <MorphoPersonalPage
      error={error}
      morphoAddress={morphoAddressInput}
      morphoQueriedAddress={morphoQueriedAddress}
      morphoMarketInput={morphoMarketInput}
      morphoQueriedMarketId={morphoQueriedMarketId}
      morphoState={morphoState}
      onAddressChange={(value) => {
        setMorphoAddressInput(value);
        setError('');
      }}
      onMarketInputChange={(value) => {
        setMorphoMarketInput(value);
        setError('');
      }}
      onSearch={(address, marketId) => {
        const normalizedAddress = normalizeEvmAddress(address);
        const trimmedMarketId = marketId.trim();
        setError('');

        if (!normalizedAddress) {
          setError('请输入 Morpho 钱包地址');
          return;
        }

        if (!isAddress(normalizedAddress, { strict: false })) {
          setError('Morpho 钱包地址格式无效');
          return;
        }

        if (!trimmedMarketId) {
          setError('请输入 Morpho market id');
          return;
        }

        if (!isBytes32Hex(trimmedMarketId)) {
          setError('Morpho market id 必须是 0x 开头的 32 字节十六进制字符串');
          return;
        }

        setMorphoAddressInput(normalizedAddress);
        setMorphoQueriedAddress(normalizedAddress);
        setMorphoMarketInput(trimmedMarketId);
        setMorphoQueriedMarketId(trimmedMarketId);
      }}
    />
  ) : (
    <MorphoMarketPage />
  );
}
