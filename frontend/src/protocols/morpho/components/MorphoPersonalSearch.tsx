import { useEffect, useMemo, useRef, useState } from 'react';
import { isAddress } from 'viem';
import { useMorphoSearchHistory } from '../../../hooks/useMorphoSearchHistory';
import type { MorphoSearchRecord } from '../../../api/morpho-search-history';

const MAX_HISTORY = 50;

function isBytes32Hex(value: string): boolean {
  return /^0x[a-fA-F0-9]{64}$/.test(value.trim());
}

function normalizeEvmAddress(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return '';
  return trimmed.startsWith('0x') || trimmed.startsWith('0X') ? trimmed : `0x${trimmed}`;
}

function dedupeByMostRecent(
  records: MorphoSearchRecord[],
  key: 'address' | 'marketId',
): MorphoSearchRecord[] {
  const seen = new Set<string>();
  const result: MorphoSearchRecord[] = [];
  for (const r of records) {
    const k = (r[key] ?? '').trim().toLowerCase();
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
  const history = useMorphoSearchHistory(MAX_HISTORY);
  const [showAddressHistory, setShowAddressHistory] = useState(false);
  const [showMarketHistory, setShowMarketHistory] = useState(false);
  const [pendingHistorySide, setPendingHistorySide] = useState<'address' | 'market' | null>(null);
  const [localError, setLocalError] = useState('');

  const wrapperRef = useRef<HTMLDivElement>(null);

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

  const recentHistory = history.getRecent(MAX_HISTORY);
  const addressHistory = useMemo(() => {
    const marketId = valueMarketId.trim();
    const records = isBytes32Hex(marketId) ? history.getAddressesByMarket(marketId) : recentHistory;
    return dedupeByMostRecent(records, 'address');
  }, [history, recentHistory, valueMarketId]);

  const marketHistory = useMemo(() => {
    const address = normalizeEvmAddress(valueAddress);
    const records = isAddress(address, { strict: false })
      ? history.getMarketsByAddress(address)
      : recentHistory;
    return dedupeByMostRecent(records, 'marketId');
  }, [history, recentHistory, valueAddress]);

  const savePair = (address: string, marketId: string) => {
    const a = address.trim();
    const m = marketId.trim();
    if (!a || !m) return;
    history.addRecord({ protocol: 'blue', address: a, marketId: m });
  };

  const clearHistory = () => {
    history.clearAll();
  };

  const runSearch = async (address: string, marketId: string) => {
    setLocalError('');
    setShowAddressHistory(false);
    setShowMarketHistory(false);
    setPendingHistorySide(null);
    savePair(address, marketId);
    await onSearch(address, marketId);
  };

  const handleMarketHistoryClick = async (record: MorphoSearchRecord) => {
    const address = normalizeEvmAddress(valueAddress);
    onChangeMarketId(record.marketId);
    setLocalError('');

    if (pendingHistorySide === 'address' && isAddress(address, { strict: false })) {
      await runSearch(address, record.marketId);
      return;
    }

    setPendingHistorySide('market');
    setShowMarketHistory(false);
    setShowAddressHistory(true);
  };

  const handleAddressHistoryClick = async (record: MorphoSearchRecord) => {
    const marketId = valueMarketId.trim();
    onChangeAddress(record.address);
    setLocalError('');

    if (pendingHistorySide === 'market' && isBytes32Hex(marketId)) {
      await runSearch(record.address, marketId);
      return;
    }

    setPendingHistorySide('address');
    setShowAddressHistory(false);
    setShowMarketHistory(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const address = normalizeEvmAddress(valueAddress);
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
    setPendingHistorySide(null);
    onChangeAddress(address);
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
              setPendingHistorySide(null);
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
                    key={`${r.marketId}:${r.address}:${r.timestamp}`}
                    className="history-item"
                    onClick={() => handleMarketHistoryClick(r)}
                    title={r.address}
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
              setPendingHistorySide(null);
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
                    key={`${r.address}:${r.marketId}:${r.timestamp}`}
                    className="history-item"
                    onClick={() => handleAddressHistoryClick(r)}
                    title={r.marketId}
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
