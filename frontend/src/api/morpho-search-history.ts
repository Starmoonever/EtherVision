/**
 * Morpho 搜索历史管理
 * 支持多维查询: 一个 address 对应多个 marketId，或一个 marketId 对应多个 address
 */

export interface MorphoSearchRecord {
  protocol: 'blue';
  address: string;
  marketId: string;
  timestamp: number; // 搜索时间戳
  label?: string; // 可选标签（例如："主钱包"、"风险市场"）
}

export interface SearchHistoryIndex {
  // 按 address 分组的市场列表
  addressToMarkets: Map<string, Set<string>>;
  // 按 marketId 分组的地址列表
  marketToAddresses: Map<string, Set<string>>;
  // 完整的搜索记录存储
  records: MorphoSearchRecord[];
  // 最大记录数限制
  maxRecords: number;
}

const SEARCH_HISTORY_STORAGE_KEY = 'morpho_search_history';
const LEGACY_SEARCH_HISTORY_STORAGE_KEY = 'search_history_morpho_personal_pairs';
const DEFAULT_MAX_RECORDS = 50;

type StoredSearchRecord = Partial<MorphoSearchRecord> & {
  ts?: number;
};

/**
 * 初始化搜索历史索引
 */
export function initSearchHistory(maxRecords: number = DEFAULT_MAX_RECORDS): SearchHistoryIndex {
  return {
    addressToMarkets: new Map(),
    marketToAddresses: new Map(),
    records: [],
    maxRecords,
  };
}

/**
 * 从 localStorage 加载搜索历史
 */
export function loadSearchHistory(maxRecords: number = DEFAULT_MAX_RECORDS): SearchHistoryIndex {
  try {
    const stored = localStorage.getItem(SEARCH_HISTORY_STORAGE_KEY);
    if (!stored) {
      const migrated = loadLegacySearchHistory(maxRecords);
      if (migrated.records.length > 0) {
        saveSearchHistory(migrated);
        localStorage.removeItem(LEGACY_SEARCH_HISTORY_STORAGE_KEY);
      }
      return migrated;
    }

    const records = JSON.parse(stored) as StoredSearchRecord[];
    return buildIndex(records, maxRecords);
  } catch {
    return initSearchHistory(maxRecords);
  }
}

function loadLegacySearchHistory(maxRecords: number): SearchHistoryIndex {
  try {
    const stored = localStorage.getItem(LEGACY_SEARCH_HISTORY_STORAGE_KEY);
    if (!stored) return initSearchHistory(maxRecords);

    const records = JSON.parse(stored) as StoredSearchRecord[];
    return buildIndex(records, maxRecords);
  } catch {
    return initSearchHistory(maxRecords);
  }
}

/**
 * 从记录列表构建索引
 */
function buildIndex(records: StoredSearchRecord[], maxRecords: number): SearchHistoryIndex {
  const index = initSearchHistory(maxRecords);
  index.records = normalizeRecords(records, maxRecords);

  for (const record of index.records) {
    const addr = record.address.toLowerCase();
    const market = record.marketId.toLowerCase();

    // 建立 address → markets 映射
    if (!index.addressToMarkets.has(addr)) {
      index.addressToMarkets.set(addr, new Set());
    }
    index.addressToMarkets.get(addr)!.add(market);

    // 建立 market → addresses 映射
    if (!index.marketToAddresses.has(market)) {
      index.marketToAddresses.set(market, new Set());
    }
    index.marketToAddresses.get(market)!.add(addr);
  }

  return index;
}

function normalizeRecords(records: StoredSearchRecord[], maxRecords: number): MorphoSearchRecord[] {
  const latestByPair = new Map<string, MorphoSearchRecord>();

  for (const record of records) {
    if (record.protocol && record.protocol !== 'blue') continue;
    if (typeof record.address !== 'string' || typeof record.marketId !== 'string') continue;

    const address = record.address.trim().toLowerCase();
    const marketId = record.marketId.trim().toLowerCase();
    if (!address || !marketId) continue;

    const timestamp =
      typeof record.timestamp === 'number'
        ? record.timestamp
        : typeof record.ts === 'number'
          ? record.ts
          : Date.now();
    const key = `${address}:${marketId}`;
    const existing = latestByPair.get(key);

    if (!existing || timestamp >= existing.timestamp) {
      latestByPair.set(key, {
        protocol: 'blue',
        address,
        marketId,
        timestamp,
        label: typeof record.label === 'string' ? record.label : undefined,
      });
    }
  }

  return Array.from(latestByPair.values())
    .sort((a, b) => a.timestamp - b.timestamp)
    .slice(-maxRecords);
}

/**
 * 保存搜索历史到 localStorage
 */
export function saveSearchHistory(history: SearchHistoryIndex): void {
  try {
    localStorage.setItem(SEARCH_HISTORY_STORAGE_KEY, JSON.stringify(history.records));
  } catch {
    // 如果 localStorage 满了或被禁用，静默失败
  }
}

/**
 * 添加新的搜索记录
 */
export function addSearchRecord(
  history: SearchHistoryIndex,
  record: MorphoSearchRecord,
): SearchHistoryIndex {
  const addr = record.address.toLowerCase();
  const market = record.marketId.toLowerCase();
  const newRecord = { ...record, address: addr, marketId: market, timestamp: Date.now() };
  const next = buildIndex([...history.records, newRecord], history.maxRecords);

  saveSearchHistory(next);
  return next;
}

/**
 * 查询某个 address 对应的所有 markets
 */
export function getMarketsByAddress(
  history: SearchHistoryIndex,
  address: string,
): MorphoSearchRecord[] {
  const addr = address.toLowerCase();
  const markets = history.addressToMarkets.get(addr);

  if (!markets) return [];

  return history.records
    .filter((r) => r.address.toLowerCase() === addr)
    .sort((a, b) => b.timestamp - a.timestamp); // 按时间倒序
}

/**
 * 查询某个 marketId 对应的所有 addresses
 */
export function getAddressesByMarket(
  history: SearchHistoryIndex,
  marketId: string,
): MorphoSearchRecord[] {
  const market = marketId.toLowerCase();
  const addresses = history.marketToAddresses.get(market);

  if (!addresses) return [];

  return history.records
    .filter((r) => r.marketId.toLowerCase() === market)
    .sort((a, b) => b.timestamp - a.timestamp); // 按时间倒序
}

/**
 * 获取最近的搜索记录（按时间倒序）
 */
export function getRecentSearches(
  history: SearchHistoryIndex,
  limit: number = 10,
): MorphoSearchRecord[] {
  return history.records.slice(-limit).reverse();
}

/**
 * 清除搜索历史
 */
export function clearSearchHistory(history: SearchHistoryIndex): SearchHistoryIndex {
  localStorage.removeItem(SEARCH_HISTORY_STORAGE_KEY);
  return initSearchHistory(history.maxRecords);
}

/**
 * 删除特定记录
 */
export function deleteSearchRecord(
  history: SearchHistoryIndex,
  address: string,
  marketId: string,
): SearchHistoryIndex {
  const addr = address.toLowerCase();
  const market = marketId.toLowerCase();

  const index = history.records.findIndex(
    (r) => r.address.toLowerCase() === addr && r.marketId.toLowerCase() === market,
  );

  if (index !== -1) {
    const next = buildIndex(
      history.records.filter((_, recordIndex) => recordIndex !== index),
      history.maxRecords,
    );
    saveSearchHistory(next);
    return next;
  }

  return history;
}

/**
 * 编辑搜索记录的标签
 */
export function updateSearchRecordLabel(
  history: SearchHistoryIndex,
  address: string,
  marketId: string,
  label: string | undefined,
): SearchHistoryIndex {
  const record = history.records.find(
    (r) =>
      r.address.toLowerCase() === address.toLowerCase() &&
      r.marketId.toLowerCase() === marketId.toLowerCase(),
  );

  if (!record) {
    return history;
  }

  const next = buildIndex(
    history.records.map((r) =>
      r.address.toLowerCase() === address.toLowerCase() &&
      r.marketId.toLowerCase() === marketId.toLowerCase()
        ? { ...r, label }
        : r,
    ),
    history.maxRecords,
  );
  saveSearchHistory(next);
  return next;
}
