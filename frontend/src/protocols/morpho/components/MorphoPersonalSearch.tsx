import { useEffect, useMemo, useRef, useState } from 'react';
import { isAddress } from 'viem';

const STORAGE_KEY = 'search_history_morpho_personal_pairs';
const MAX_HISTORY = 50;

type PairRecord = {
  address: string;
  marketId: string;
  ts: number;
};

function isBytes32Hex(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

function safeParsePairs(raw: string | null): PairRecord[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (item): item is PairRecord =>
          typeof item === 'object' &&
          item !== null &&
          typeof (item as PairRecord).address === 'string' &&
          typeof (item as PairRecord).marketId === 'string' &&
          typeof (item as PairRecord).ts === 'number',
      )
      .slice(0, MAX_HISTORY);
  } catch {
    return [];
  }
}

function dedupeByMostRecent(records: PairRecord[], key: 'address' | 'marketId'): PairRecord[] {
  const seen = new Set<string>();
  const result: PairRecord[] = [];
  for (const r of records) {
    const k = (r[key] ?? '').trim();
    if (!k || seen.has(k)) continue;
    seen.add(k);
    result.push(r);
  }
  return result;
}

interface MorphoPersonalSearchProps {
  loading: boolean;
  valueAddress: string;
  valueMarketId: string;
  onChangeAddress: (value: string) => void;
  onChangeMarketId: (value: string) => void;
  onSearch: (address: string, marketId: string) => void | Promise<void>;
}

export function MorphoPersonalSearch({
  loading,
  valueAddress,
  valueMarketId,
  onChangeAddress,
  onChangeMarketId,
  onSearch,
}: MorphoPersonalSearchProps) {
  const [pairs, setPairs] = useState<PairRecord[]>([]);
  const [showAddressHistory, setShowAddressHistory] = useState(false);
  const [showMarketHistory, setShowMarketHistory] = useState(false);
  const [localError, setLocalError] = useState('');

  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setPairs(safeParsePairs(localStorage.getItem(STORAGE_KEY)));
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setShowAddressHistory(false);
        setShowMarketHistory(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const addressHistory = useMemo(() => dedupeByMostRecent(pairs, 'address'), [pairs]);
  const marketHistory = useMemo(() => dedupeByMostRecent(pairs, 'marketId'), [pairs]);

  const persistPairs = (next: PairRecord[]) => {
    const trimmed = next.slice(0, MAX_HISTORY);
    setPairs(trimmed);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  };

  const savePair = (address: string, marketId: string) => {
    const a = address.trim();
    const m = marketId.trim();
    if (!a || !m) return;
    const next: PairRecord[] = [
      { address: a, marketId: m, ts: Date.now() },
      ...pairs.filter((p) => !(p.address === a && p.marketId === m)),
    ].slice(0, MAX_HISTORY);
    persistPairs(next);
  };

  const clearHistory = () => {
    setPairs([]);
    localStorage.removeItem(STORAGE_KEY);
  };

  const applyPair = async (record: PairRecord) => {
    onChangeAddress(record.address);
    onChangeMarketId(record.marketId);
    setLocalError('');
    setShowAddressHistory(false);
    setShowMarketHistory(false);
    savePair(record.address, record.marketId);
    await onSearch(record.address, record.marketId);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const address = valueAddress.trim();
    const marketId = valueMarketId.trim();

    if (!address) {
      setLocalError('请输入 Morpho 钱包地址');
      return;
    }
    if (!isAddress(address, { strict: false })) {
      setLocalError('Morpho 钱包地址格式无效');
      return;
    }
    if (!marketId) {
      setLocalError('请输入 Morpho market id');
      return;
    }
    if (!isBytes32Hex(marketId)) {
      setLocalError('Morpho market id 必须是 0x 开头的 32 字节十六进制字符串');
      return;
    }

    setLocalError('');
    savePair(address, marketId);
    await onSearch(address, marketId);
    setShowAddressHistory(false);
    setShowMarketHistory(false);
  };

  return (
    <form onSubmit={handleSubmit} className="input-form input-form-compact">
      <div className="input-row" ref={wrapperRef}>
        <div className="input-wrapper">
          <input
            type="text"
            value={valueMarketId}
            onFocus={() => {
              setShowMarketHistory(true);
              setShowAddressHistory(false);
            }}
            onChange={(event) => {
              onChangeMarketId(event.target.value);
              setLocalError('');
            }}
            placeholder="输入 Morpho market id (bytes32)"
            className="address-input"
            spellCheck={false}
            disabled={loading}
          />

          {showMarketHistory && marketHistory.length > 0 && (
            <div className="history-dropdown">
              <div className="history-header">
                <span>市场ID 搜索记录</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    clearHistory();
                  }}
                  className="clear-history-btn"
                >
                  清除记录
                </button>
              </div>
              <ul className="history-list">
                {marketHistory.map((r) => (
                  <li
                    key={`${r.marketId}:${r.address}:${r.ts}`}
                    className="history-item"
                    onClick={() => applyPair(r)}
                  >
                    {r.marketId}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="input-wrapper">
          <input
            type="text"
            value={valueAddress}
            onFocus={() => {
              setShowAddressHistory(true);
              setShowMarketHistory(false);
            }}
            onChange={(event) => {
              onChangeAddress(event.target.value);
              setLocalError('');
            }}
            placeholder="输入 Morpho 钱包地址"
            className="address-input"
            spellCheck={false}
            disabled={loading}
          />

          {showAddressHistory && addressHistory.length > 0 && (
            <div className="history-dropdown">
              <div className="history-header">
                <span>用户ID 搜索记录</span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    clearHistory();
                  }}
                  className="clear-history-btn"
                >
                  清除记录
                </button>
              </div>
              <ul className="history-list">
                {addressHistory.map((r) => (
                  <li
                    key={`${r.address}:${r.marketId}:${r.ts}`}
                    className="history-item"
                    onClick={() => applyPair(r)}
                  >
                    {r.address}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <button type="submit" className="search-btn" disabled={loading}>
          {loading ? '查询中…' : '查询仓位'}
        </button>
      </div>

      {localError && <p className="input-error">{localError}</p>}
    </form>
  );
}
