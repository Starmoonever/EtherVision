/**
 * useMorphoSearchHistory - React Hook for managing Morpho search history
 */

import { useEffect, useState, useCallback } from 'react';
import type { MorphoSearchRecord, SearchHistoryIndex } from '../api/morpho-search-history';
import {
  loadSearchHistory,
  addSearchRecord,
  getMarketsByAddress,
  getAddressesByMarket,
  getRecentSearches,
  clearSearchHistory,
  deleteSearchRecord,
  updateSearchRecordLabel,
} from '../api/morpho-search-history';

export interface UseMorphoSearchHistoryReturn {
  // 状态
  history: SearchHistoryIndex;

  // 查询方法
  getMarketsByAddress: (address: string) => MorphoSearchRecord[];
  getAddressesByMarket: (marketId: string) => MorphoSearchRecord[];
  getRecent: (limit?: number) => MorphoSearchRecord[];

  // 修改方法
  addRecord: (record: Omit<MorphoSearchRecord, 'timestamp'>) => void;
  deleteRecord: (address: string, marketId: string) => void;
  updateLabel: (address: string, marketId: string, label?: string) => void;
  clearAll: () => void;
}

export function useMorphoSearchHistory(maxRecords: number = 50): UseMorphoSearchHistoryReturn {
  const [history, setHistory] = useState<SearchHistoryIndex>(() => loadSearchHistory(maxRecords));

  // 从 localStorage 初始化
  useEffect(() => {
    const loaded = loadSearchHistory(maxRecords);
    setHistory(loaded);
  }, [maxRecords]);

  const addRecord = useCallback((record: Omit<MorphoSearchRecord, 'timestamp'>) => {
    setHistory((prev) => addSearchRecord(prev, { ...record, timestamp: 0 }));
  }, []);

  const deleteRecord = useCallback((address: string, marketId: string) => {
    setHistory((prev) => deleteSearchRecord(prev, address, marketId));
  }, []);

  const updateLabel = useCallback((address: string, marketId: string, label?: string) => {
    setHistory((prev) => updateSearchRecordLabel(prev, address, marketId, label));
  }, []);

  const clearAll = useCallback(() => {
    setHistory((prev) => clearSearchHistory(prev));
  }, []);

  const getRecent = useCallback((limit?: number) => getRecentSearches(history, limit), [history]);

  return {
    history,
    getMarketsByAddress: (addr) => getMarketsByAddress(history, addr),
    getAddressesByMarket: (market) => getAddressesByMarket(history, market),
    getRecent,
    addRecord,
    deleteRecord,
    updateLabel,
    clearAll,
  };
}
